"""Hub — single CDK stack for the unified capstone service (moved from
newsroom/infra; architecture unchanged).

CloudFront → (CloudFront origin-facing prefix-list SG + X-Origin-Verify) ALB
→ Fargate (public subnets only, desired_count=1), secrets injected at start.
The container now serves the hub image (built from the repo root:
`docker build -f hub/Dockerfile .`). Scope: `cdk synth` clean pass — no deploy.
"""
from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

CONTAINER_PORT = 8000
REPO_ROOT = Path(__file__).resolve().parents[2]  # claude-lab/ (hub/Dockerfile의 빌드 컨텍스트)

# The AWS-managed "com.amazonaws.global.cloudfront.origin-facing" prefix list
# id is region-specific and normally resolved with a context lookup (needs an
# AWS account). To keep `cdk synth` credential-free, pass it via context:
#   cdk synth -c cloudfront_prefix_list_id=pl-xxxxxxxx
# The default below is the well-known id in ap-northeast-2.
DEFAULT_CLOUDFRONT_PREFIX_LIST_ID = "pl-22a6434a"


class HubStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        prefix_list_id = (
            self.node.try_get_context("cloudfront_prefix_list_id")
            or DEFAULT_CLOUDFRONT_PREFIX_LIST_ID
        )
        # Container image — 두 모드:
        #  (기본) DockerImageAsset: cdk deploy가 리포 루트 컨텍스트에서
        #    hub/Dockerfile을 직접 빌드해 CDK 부트스트랩 자산 ECR로 push.
        #    별도 레지스트리·수동 push 불필요. Docker 데몬 필요.
        #    `-c apps=quake,market`로 프론트 번들 앱 선택(빌드 아그 APPS).
        #  (옵션) `-c image_uri=...`: 미리 빌드해 둔 이미지 사용 —
        #    docker 없는 환경의 synth 검증(infra:synth)도 이 경로를 쓴다.
        image_uri = self.node.try_get_context("image_uri")
        if image_uri:
            container_image = ecs.ContainerImage.from_registry(image_uri)
        else:
            # APPS는 Dockerfile RUN의 셸 변수로 들어가므로 모듈 id 허용 목록으로
            # 검증 (임의 문자열이 빌드 컨테이너에서 명령으로 실행되는 것 차단)
            apps = self.node.try_get_context("apps") or "quake,news,trend,market"
            allowed = {"quake", "news", "trend", "market"}
            parts = [p.strip() for p in apps.split(",") if p.strip()]
            if not parts or not set(parts) <= allowed:
                raise ValueError(
                    f"-c apps must be a comma list of {sorted(allowed)}, got {apps!r}"
                )
            container_image = ecs.ContainerImage.from_asset(
                directory=str(REPO_ROOT),
                file="hub/Dockerfile",
                build_args={"APPS": ",".join(parts)},
                # Fargate 기본 아키텍처는 amd64 — Apple Silicon 로컬 빌드 대비 명시
                platform=ecr_assets.Platform.LINUX_AMD64,
            )

        # --- VPC: 2 AZ, public subnets only (no NAT) ---
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC
                )
            ],
        )

        # --- Secrets ---
        # X-Origin-Verify shared secret: auto-generated; referenced by BOTH the
        # CloudFront origin custom header and the ALB listener rule through
        # CloudFormation dynamic references — no plaintext in code or template.
        origin_verify_secret = secretsmanager.Secret(
            self,
            "OriginVerifySecret",
            description="Shared X-Origin-Verify header value (CloudFront -> ALB)",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True, password_length=48
            ),
        )
        # Bedrock bearer token: the secret VALUE is registered manually before
        # deploy (never in CDK code); injected into the container via ECS secrets.
        bedrock_token_secret = secretsmanager.Secret(
            self,
            "BedrockBearerToken",
            description=(
                "AWS_BEARER_TOKEN_BEDROCK - set the value manually before deploy"
            ),
        )

        # --- ECS Fargate: desired_count=1, public IP, inbound from ALB SG only ---
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)

        alb_sg = ec2.SecurityGroup(
            self,
            "AlbSg",
            vpc=vpc,
            description="ALB - inbound restricted to CloudFront origin-facing prefix list",
            allow_all_outbound=True,
        )
        alb_sg.add_ingress_rule(
            ec2.Peer.prefix_list(prefix_list_id),
            ec2.Port.tcp(80),
            "CloudFront origin-facing ranges only",
        )

        service_sg = ec2.SecurityGroup(
            self,
            "ServiceSg",
            vpc=vpc,
            description="Fargate service - inbound from ALB SG only",
            allow_all_outbound=True,
        )
        service_sg.add_ingress_rule(
            alb_sg, ec2.Port.tcp(CONTAINER_PORT), "ALB to app port"
        )

        task_def = ecs.FargateTaskDefinition(
            self, "TaskDef", cpu=256, memory_limit_mib=512
        )
        task_def.add_container(
            "web",
            image=container_image,
            port_mappings=[ecs.PortMapping(container_port=CONTAINER_PORT)],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="hub", log_retention=logs.RetentionDays.ONE_WEEK
            ),
            environment={"PORT": str(CONTAINER_PORT)},
            secrets={
                "AWS_BEARER_TOKEN_BEDROCK": ecs.Secret.from_secrets_manager(
                    bedrock_token_secret
                ),
            },
        )

        service = ecs.FargateService(
            self,
            "Service",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            min_healthy_percent=100,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            assign_public_ip=True,  # public subnets only, no NAT
            security_groups=[service_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        # --- ALB: default 403; forward only when X-Origin-Verify matches ---
        alb = elbv2.ApplicationLoadBalancer(
            self, "Alb", vpc=vpc, internet_facing=True, security_group=alb_sg
        )
        listener = alb.add_listener(
            "Http",
            port=80,
            open=False,  # keep the prefix-list-only SG, don't add 0.0.0.0/0
            default_action=elbv2.ListenerAction.fixed_response(
                403, content_type="text/plain", message_body="Forbidden"
            ),
        )
        target_group = elbv2.ApplicationTargetGroup(
            self,
            "Tg",
            vpc=vpc,
            port=CONTAINER_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            health_check=elbv2.HealthCheck(
                path="/healthz", healthy_http_codes="200"
            ),
        )
        # 보안 노트: unsafe_unwrap()은 평문이 아니라 CloudFormation 동적 참조로
        # 렌더링된다({{resolve:secretsmanager:...}} — 템플릿·코드에 값 없음).
        # 잔여 노출: elbv2:DescribeRules / cloudfront:GetDistributionConfig 권한이
        # 있는 IAM 주체는 배포 후 헤더 값을 읽을 수 있다 — X-Origin-Verify 패턴의
        # 수용된 특성(오리진 직접 접근 차단용이지 기밀 데이터가 아님).
        # unsafe_unwrap() renders as a CloudFormation dynamic reference
        # ({{resolve:secretsmanager:...}}) in the template — not plaintext.
        listener.add_action(
            "OriginVerify",
            priority=1,
            conditions=[
                elbv2.ListenerCondition.http_header(
                    "X-Origin-Verify",
                    [origin_verify_secret.secret_value.unsafe_unwrap()],
                )
            ],
            action=elbv2.ListenerAction.forward([target_group]),
        )

        # --- CloudFront: HTTP origin (no domain/ACM), custom header injected ---
        distribution = cloudfront.Distribution(
            self,
            "Dist",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.HttpOrigin(
                    alb.load_balancer_dns_name,
                    # 수용된 트레이드오프(스펙: 도메인/ACM 없이 개장): CloudFront→ALB
                    # 구간이 HTTP라 X-Origin-Verify 값이 평문 전송된다. 완화책으로
                    # ALB 인바운드를 CloudFront origin-facing prefix list로 제한.
                    # 강화 경로: ACM 인증서 + HTTPS_ONLY 로 전환.
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    custom_headers={
                        "X-Origin-Verify": (
                            origin_verify_secret.secret_value.unsafe_unwrap()
                        )
                    },
                ),
                viewer_protocol_policy=(
                    cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS
                ),
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,  # POST /api/lens
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=(
                    cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER
                ),
            ),
        )

        cdk.CfnOutput(self, "CloudFrontUrl", value=f"https://{distribution.domain_name}")
        cdk.CfnOutput(self, "AlbDns", value=alb.load_balancer_dns_name)
        cdk.CfnOutput(
            self, "BedrockTokenSecretArn", value=bedrock_token_secret.secret_arn
        )

"""Hub — single CDK stack for the unified capstone service (moved from
newsroom/infra; architecture unchanged).

CloudFront → (CloudFront origin-facing prefix-list SG + X-Origin-Verify) ALB
→ Fargate (public subnets only, desired_count=1), secrets injected at start.
The container now serves the hub image (built from the repo root:
`docker build -f hub/Dockerfile .`). Scope: `cdk synth` clean pass — no deploy.
"""
from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

CONTAINER_PORT = 8000

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
        # Container image URI: the hub image, built separately from the repo
        # root (`docker build -f hub/Dockerfile -t claude-lab-hub .` — the
        # multi-stage build in hub/Dockerfile: node builds the market frontend,
        # python:3.11-slim serves all modules), pushed to a registry, and
        # passed via `-c image_uri=...`. from_asset would require Docker at
        # synth time, which the synth-only scope avoids.
        image_uri = (
            self.node.try_get_context("image_uri")
            or "public.ecr.aws/docker/library/python:3.11-slim"
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
            image=ecs.ContainerImage.from_registry(image_uri),
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

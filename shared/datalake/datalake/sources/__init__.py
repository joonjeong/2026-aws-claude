"""소스 클라이언트 패키지.

각 모듈은 순수 클라이언트(fetch*/normalize, 저장 무지)와
`build() -> Client | None`(None = 키·엑스트라 부재로 비활성)을 노출한다.
소비자는 datalake.cli의 소스별 명령 — 오케스트레이션 레지스트리는 없다
(케이던스·재시도는 Temporal 등 외부 도구 소유).
"""

"""datalake — hub와 완전히 독립적인 원본 데이터 적재 도구.

의존성은 httpx·feedparser·websockets뿐 — hub.* / app.* / labkit import 금지
(tests/test_independence.py가 AST 검사로 강제).
스케줄링은 외부 오케스트레이터(Temporal 예정) 소유 — 여기엔 one-shot
CLI(datalake.cli)와 순수 클라이언트(datalake.sources)만 있다.
"""

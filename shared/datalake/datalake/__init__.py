"""datalake — hub와 완전히 독립적인 원본 데이터레이크 수집 CLI 모음.

원천(source)당 파일 하나가 자기완결이다: fetch → 순수 파싱(map/filter) →
landing(원본 봉투)·bronze(파싱 행) 랜딩까지 그 파일 안에서 끝난다.
파일 간 import 없음 — tests/test_independence.py가 hub/labkit 금지와 함께
패키지 내부 상호 import도 검사한다.

존 의미(메달리온): landing=원본 바이트(진실) · bronze=무가공 파싱 행
(append, 중복 허용). bronze→silver→gold는 정리된 원천 위에서 추후 재설계.
스케줄링·재시도는 외부 스케줄러 소유 — 종료 코드 0 성공 / 1 실패 / 2 비활성.
"""

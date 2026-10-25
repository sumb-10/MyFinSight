# 시나리오 실행 결과 (2026-10-25, LLM api)

| 시나리오 | 상태 | 보충 질문 | 추천 | 선택안 | 통과/주의/미통과 | 근거 수 | 대화 s | 실행 s | run_id |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 국내 반도체와 IT 부품 기업 중 최근 주가 흐름이 강한 종목 위주로 5… | failed | Q1 num_holdings → 종목 수를 11개로 줄이고 종목당 상한을 15%로 올려 전액 투자; Q2 min_cash_ratio → 아이디어대로: 0%; Q3 max_weight_per_sector → 이번 분석에서는 섹터 상한을 풀어 전액 투자 (100%) | 없음 | - | - | - | 74.7 | 504.0 | `run_20261025_211730_9454` |
| 국내 자동차와 부품 기업 중 실적 대비 주가가 싼 종목 위주로 2년 정도… | partial | Q1 num_holdings → 종목 수를 4개로 줄이고 종목당 상한을 22%로 올려 전액 투자; Q2 max_weight_per_sector → 이번 분석에서는 섹터 상한을 풀어 전액 투자 (85%) | equal_weight | equal_weight | 0/11/0 | 22 | 85.1 | 133.5 | `run_20261025_212719_b52b` |

- 국내 반도체와 IT 부품 기업 중 최근 주가 흐름이 강한 종목 위주로 5…: {"code": "REPORT_CHECK_FAILED", "message_ko": "ReportCheckError: 리포트 검증 실패: companies: banned phrase '보장'", "step": "14_report", "actions": ["edit_conditions", "retry", "home"]}
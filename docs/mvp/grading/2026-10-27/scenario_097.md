# S4 · scenario_097 채점 기록 (라운드 5 재실행) — `run_20261025_211730_9454`

시나리오 파일: `/Users/apple/dev/MyFinSight/backend/test_scenarios/scenario_097.json`

> 아이디어: 국내 반도체와 IT 부품 기업 중 최근 주가 흐름이 강한 종목 위주로 5년 정도 투자하고 싶어요. 자산을 불리는 게 목표예요. 적당한 위험은 감수할 수 있어요. 경기에 너무 민감한 에너지 섹터는 빼 주세요. 주류, 도박·카지노 관련 회사는 원하지 않아요. 매달 조금씩 추가로 넣을 예정입니다.

## 1. 자동 지표 (grade.py)

### 조건 반영 (요구 1·2·4)

| 항목 | 요청 | 결과 | 판정 |
| --- | --- | --- | --- |
| 필수 포함 | 없음 | 지금 - · 백테스트 - | – |
| 제외 종목 | 없음 | 새어 들어온 것 없음 | ✅ |
| 제외 테마 | alcohol, gambling | 규칙 생성 alcohol, gambling · 후보에서 걸러진 수 0 | ✅ |
| 유니버스 | KOSPI200 | 선정 시장 KR | ✅ |
| 최소 현금 | 10% | 규칙별 투자 비율 {'equal_weight': 1.0, 'market_cap': 1.0, 'inverse_volatility': 1.0, 'min_variance': 1.0} | ❌ |
| 상한 준수(내부 점검) | 종목 0.15 · 섹터 1.0 | 리밸런싱일 상한 점검 | ✅ |
| 리밸런싱 | 매월 첫 거래일에 목표 비중으로 리밸런싱 | 실제 37회 | – |
| 기준일 | 2026-10-08 | 사용 2026-10-08 | ✅ |
| 백테스트 창 | 기본 3년 | 2023-10-08 ~ 2026-10-08 (775거래일) | – |
| 선정 기준 | momentum | 지표 return_12m_1m | ✅ |
| 종목 수 | 목표 15 (최소 12) | 지금 9 · 백테스트 9 | ❌ |

기준일 계산 안내: 없음

### 보충 질문 (요구 2)

질문 3개 (상한 5), 덮어쓰기 {'horizon.start_date': '2026-10-08', 'constraints.num_holdings': {'target': 11, 'min': 11, 'max': 11}, 'constraints.max_weight_per_stock': 0.15, 'constraints.max_weight_per_sector': 1.0, 'constraints.min_cash_ratio': 0.0}, 보충 답변 []

- Q1 [feasibility] `constraints.num_holdings` — 테마에 맞는 종목이 분석 기준일 기준 11개로, 최소 종목 수 12개(목표 15개)에 못 미칩니다. 어떻게 할까요?  
  보기: ['종목 수를 11개로 줄이고 종목당 상한을 15%로 올려 전액 투자', '테마를 넓혀 다시 해석 (인접 산업 포함)', '그대로 진행 (현금이 남을 수 있음)']  
  답: **종목 수를 11개로 줄이고 종목당 상한을 15%로 올려 전액 투자**
- Q2 [conflict] `constraints.min_cash_ratio` — 아이디어와 프로필의 '최소 현금 비율' 이(가) 다릅니다. 요청에서는 전액 투자를 원하지만, 현재 설정된 최소 현금 비중은 10%입니다. 어느 쪽으로 할까요?  
  보기: ['아이디어대로: 0%', '프로필대로: 10%']  
  답: **아이디어대로: 0%**
- Q3 [conflict] `constraints.max_weight_per_sector` — 이 아이디어의 테마는 '정보기술' 한 섹터에 몰려 있습니다. 지금 섹터당 상한이 70%라 투자금의 30%가 현금으로 남게 됩니다. 어떻게 할까요?  
  보기: ['이번 분석에서는 섹터 상한을 풀어 전액 투자 (100%)', '프로필대로 70% 유지 (나머지 30%는 현금)']  
  답: **이번 분석에서는 섹터 상한을 풀어 전액 투자 (100%)**

해석 요약: 국내 반도체와 IT 부품 기업 중 최근 주가 흐름이 강한 종목 11개를 선정해 5년간 자산 증식을 추구합니다. 현금 비중 없이 투자하고 종목당 상한은 15%, 섹터별 상한은 100%로 설정하며, 에너지 섹터와 주류·도박 관련 기업은 제외합니다.

테마: 반도체(semiconductors) GICS ['453010', '45301010', '45301020'] 키워드 ['semiconductor', 'memory chip', 'dram', 'nand flash', 'hbm', 'foundry', 'wafer', 'chip fabrication']; IT 전자부품(it_components) GICS ['45203015'] 키워드 ['electronic components', 'passive components', 'multilayer ceramic capacitor', 'mlcc', 'printed circuit board', 'pcb', 'camera module', 'optical components']

충돌 기록: 없음

설명 수준 intermediate, 검증에 쓰는 허용 낙폭 0.25

### 선정 (요구 4)

후보 검색 13 → 필터 후 11 (규칙 {'example_match': 4, 'gics_match': 11, 'keyword_match': 12}) → 테마 통과 9 → 지표 있음 9 → 선정 9

| 순위 | 종목 | 이름 | 섹터 | 지표 | 테마 신뢰도 |
| --- | --- | --- | --- | --- | --- |
| 1 | 009150.KS | 삼성전기 | Information Technology | 5.9608 | 0.95 |
| 2 | 000660.KS | SK하이닉스 | Information Technology | 3.6156 | 0.98 |
| 3 | 011070.KS | LG이노텍 | Information Technology | 2.2159 | 0.65 |
| 4 | 005930.KS | 삼성전자 | Information Technology | 2.2023 | 0.78 |
| 5 | 006400.KS | 삼성SDI | Information Technology | 1.7106 | 0.5 |
| 6 | 042700.KS | 한미반도체 | Information Technology | 1.3033 | 0.98 |
| 7 | 000990.KS | DB하이텍 | Information Technology | 0.5401 | 0.95 |
| 8 | 007660.KS | 이수페타시스 | Information Technology | 0.3999 | 0.9 |
| 9 | 034220.KS | LG디스플레이 | Information Technology | -0.2923 | 0.85 |

섹터 분포 {'Information Technology': 9} · 배분 불능 None · 선정 경고 ['only 9 tickers have return_12m_1m; target 11 -> selecting 9', 'below num_holdings.min=11 -> fewer holdings than requested (cash may remain; the report labels this)', 'selected 9 < n=11: not enough passed tickers']

### 구성 (요구 4)

리밸런싱 37회 중 기준 비중 유지(근거 부족) 0회 · 공시 있는 날 37 · 뉴스 있는 날 37 · 뷰 148개 (근거: {'news': 80, 'disclosure': 3, 'mixed': 65}) · 시작일 BL 5개 · 종목당 이동 한도 0.05 · 현재 구성 fallback False 

### 백테스트·검증 (요구 5·6)

창 {'start': '2023-10-08', 'end': '2026-10-08', 'as_of': '2023-10-10', 'trading_days': 775, 'window_days': 774, 'annualized_reliable': True} · 엔진 {'commission_bps': 5, 'n_contributions': 35, 'contribution_usd': 222.74, 'risk_free_rate': 0.04, 'benchmarks': ['069500.KS', 'QQQ']} · 비교지수 {'id': 'benchmark_069500.KS', 'cagr': 0.502565, 'mdd': -0.371568, 'final_value_usd': 278625.57, 'same_contributions': True}

7지표 존재 {'total_return': True, 'cagr': True, 'ann_vol': True, 'sharpe': True, 'max_drawdown': True, 'excess_cagr': True, 'final_value_usd': True, 'irr_annual': True} · **독립 재계산 일치(CAGR·MDD)**: ✅

| 포트폴리오 | CAGR | 재계산 | MDD | 재계산 | Sharpe | 최종 USD |
| --- | --- | --- | --- | --- | --- | --- |
| bl_01 | 0.7877 | 0.7877 ✅ | -0.4776 | -0.4776 ✅ | 1.524378 | 474,833 |
| bl_02 | 0.7493 | 0.7493 ✅ | -0.4648 | -0.4648 ✅ | 1.463026 | 443,961 |
| bl_03 | 0.7384 | 0.7384 ✅ | -0.4630 | -0.4630 ✅ | 1.452434 | 435,863 |
| bl_04 | 0.7554 | 0.7554 ✅ | -0.4687 | -0.4687 ✅ | 1.476831 | 449,010 |
| bl_05 | 0.7511 | 0.7511 ✅ | -0.4687 | -0.4687 ✅ | 1.471928 | 445,816 |
| equal_weight | 0.7027 | 0.7027 ✅ | -0.4862 | -0.4862 ✅ | 1.363447 | 408,566 |
| market_cap | 0.7421 | 0.7421 ✅ | -0.4695 | -0.4695 ✅ | 1.45507 | 438,912 |
| inverse_volatility | 0.6931 | 0.6931 ✅ | -0.4778 | -0.4778 ✅ | 1.370212 | 402,464 |
| min_variance | 0.6395 | 0.6395 ✅ | -0.4773 | -0.4773 ✅ | 1.286294 | 366,897 |
| wf_equal_weight | 0.7027 | 0.7027 ✅ | -0.4862 | -0.4862 ✅ | 1.363447 | 408,566 |
| wf_market_cap | 0.6992 | 0.6992 ✅ | -0.4773 | -0.4773 ✅ | 1.353582 | 406,886 |
| wf_inverse_volatility | 0.6882 | 0.6882 ✅ | -0.4809 | -0.4809 ✅ | 1.367712 | 399,007 |
| wf_min_variance | 0.6414 | 0.6414 ✅ | -0.4885 | -0.4885 ✅ | 1.297818 | 368,772 |
| wf_bl_news | 0.6886 | 0.6886 ✅ | -0.4793 | -0.4793 ✅ | 1.338011 | 398,882 |
| dd_match_market_cap | 0.3758 | 0.3758 ✅ | -0.2499 | -0.2499 ✅ | 1.429877 | 214,367 |
| dd_match_wf_bl_news | 0.3318 | 0.3318 ✅ | -0.2488 | -0.2488 ✅ | 1.321165 | 194,173 |

검증 요약 {'n_pass': 0, 'n_warn': 16, 'n_fail': 0, 'n_flag': 14, 'n_candidates': 16, 'n_matched': 2, 'alternative_note': None} · 추천 bl_01 추천(주의: 허용 낙폭 초과 (22.8%p)): BL 타겟 1: 메모리 회복 기대와 중국 생산 불확실성 · 낙폭 맞춤안 [('dd_match_market_cap', 0.5, -0.249922, 0.25), ('dd_match_wf_bl_news', 0.53, -0.248792, 0.25)] · 선택안 bl_01 · 대안 [] · 기준 {'max_drawdown': 0.25, 'input_max_drawdown': 0.25, 'target_annual_return': 0.12, 'horizon_years': 5.0, 'volatility_preference': 'medium'}

추천 사유: 후보 16개 중 1위. · 목표수익(연 12.0%) 충족 · 069500.KS 대비 초과 CAGR +28.5%p · 최대낙폭 47.8% vs 허용 25.0% (22.8%p 초과) · Sharpe 1.52로 가장 높음 · CAGR 78.8%, 최종 평가금액 474,833 USD.

선택안 판정:
- R1 flag: 최대낙폭 47.8% vs 허용 25.0% (같은 기간 069500.KS 매수보유 (동일 적립) 37.2%) — 허용보다 22.8%p 큼
- R1b info: 비교지수보다 낙폭이 큼 (47.8% vs 37.2%)
- R2 pass: CAGR 78.8% vs 목표 12.0% (백테스트 창이 투자기간 5년보다 짧아 전체 CAGR 로 판정)
- R3 pass: 069500.KS 대비 초과 CAGR +28.5%p
- R7 pass: 연변동성 49.1% vs 비교지수 41.5%의 1.3배(중립 성향) = 54.0%
- R4b info: 리밸런싱 사이에 종목 비중이 상한의 1.25배를 넘은 적 있음 (000660.KS, 006400.KS, 009150.KS) — 리밸런싱 주기를 줄이면 완화됩니다
- R5b info: 리밸런싱 사이 섹터 비중이 상한 안에 머묾
- R9 info: 투자 100%, 현금 0%

자료 품질 {'expected_days': 775, 'usable': 11, 'excluded': {}, 'filled': {}}

### 근거·선견 (요구 3·8·15)

색인 {'news': 3206, 'disclosure': 507, 'financial': 18, 'calc': 126} · 본문 인용 0회/0종 · 색인에 없는 인용 없음 · **기준일 이후 자료 0건** [] · 리밸런싱 창 밖 레코드 0건 (40창) · 가격 마지막 날짜 2026-10-08 ≤ 기준일 ✅ · 문서 근거 0건 · 문서 0KB

기업별 근거: 종목 0개, 최소 문단 0, 모두 인용 –

### 리포트

리포트 없음 (실행 실패)

### 실행 (요구 9·12, C6)

상태 failed · 소요 499초 · LLM 46회 $0.140312 (캐시 0, 잘림 0) · 단계 기록 14/14 · 자료 출처 ['src_prices', 'src_fx', 'src_valuation', 'src_universe', 'src_news', 'src_pipeline', 'src_llm', 'src_disclosures']

단계: 01_request SUCCESS(10.16s), 02_intent SUCCESS(0.0s), 03_candidates SUCCESS(0.14s), 04_tagging SUCCESS(13.3s), 05_selection PARTIAL(0.02s), 06_explain SUCCESS(24.04s), 07_backtest_spec PARTIAL(0.81s), 10f_current SUCCESS(63.5s), 10_targets SUCCESS(65.22s), 10w_paths PARTIAL(269.77s), 11_backtest SUCCESS(10.04s), 12_validation SUCCESS(0.0s), 13_results SUCCESS(0.04s), 14_report FAILED(131.96s)

오류: {'step': '14_report', 'code': 'REPORT_CHECK_FAILED', 'message': "ReportCheckError: 리포트 검증 실패: companies: banned phrase '보장'"}

## 2. 사람 판독 (채점자가 채움)

| # | 항목 | 점수(0~2) | 근거 (파일·필드·인용문) |
| --- | --- | --- | --- |
| 1 | 조건 반영 | 2 | 실행 전 점검 질문이 작동: 후보 11개 < 최소 12 → 첫 보기 '종목 수 11개·상한 15%' 로 조건을 바꿈. 에너지 섹터 제외 규칙, 현금 0%(아이디어대로 질문), 섹터 상한 100%, **3년 창 유지**(전 라운드 1년). 반도체 테마에 삼성전자(005930) 포함 |
| 2 | 보충 질문의 적절성 | 2 | 질문 3개(실행 전 점검 → 현금 비율 충돌 → 섹터 상한) 모두 아이디어·프로필·후보 수가 실제로 어긋난 곳. 보기도 각각 2~3개 |
| 3 | 해석 적합성 | 2 | 반도체(453010)·IT 부품 두 테마, 에너지 제외를 규칙으로 |
| 4 | 선정 타당성 | 1 | 11 후보 → 9 통과 → 9 선정(목표 11). 테마 자체가 좁아 공지만 남음(요구대로) |
| 5 | 구성 | 2 | 14회 리밸런싱 뷰 생성, 낙폭 맞춤안 2개(주식 50%/47%). **달력 버그 수정 뒤 내부 점검 R4 전부 통과**(첫 시도에서는 walk-forward 5개가 실패) |
| 6 | 백테스트·검증 논리 | 2 | 창 3년(2023-10-10~2026-10-08), 추천 bl_01 '추천(주의: 허용 낙폭 초과 22.8%p)' — CAGR 78.8%·낙폭 47.8% 라는 극단값에 라벨이 정직. 맞춤안이 R3(비교지수)에서 뒤져 1위가 못 된 것은 순위 설계(목표수익 → 비교지수 → 낙폭) 그대로 |
| 7 | 근거·선견 | 2 | 13_results 기준 기준일 이후 자료 0, 가격 날짜 ✅ (리포트가 없어 본문 인용 검사는 못 함) |
| 8 | 리포트 서술 품질 | 0 | **리포트 없음** — 14 단계 문장 검증 게이트가 기업별 근거의 '…보장하는 근거는 아닙니다' 를 금지 표현으로 잡아(부정형 '아닙니다' 미인식) 재작성 1회 뒤 실행 실패. 게이트 자체는 설계대로 작동했지만 사용자는 8분 뒤 '실패'를 받았다. 부정 표지 '아닙' 추가로 수정(재실행은 안 함) |
| 9 | 실행 | 0 | 실패. 504초, LLM 46회, $0.140 (월간 리밸런싱 + 리포트 재작성) |
| 10 | 사용자에게 보이는 상태 | 1 | 실행 화면에 실패 단계·사유와 '같은 조건으로 다시 실행 / 조건 고쳐 새 요청' 버튼이 있다(라운드 5 추가). 리포트는 없다 |

**합계: 14/20 → 70/100**

## 3. 읽고 느낀 점

- 두 번 돌렸다. 첫 시도(`run_20261025_205958_a689`, `first_attempt/`)는 리포트까지 나왔지만 walk-forward 리밸런싱 날짜가 백테스트 달력(비교지수 시장 포함)과 어긋나 내부 점검 R4 가 5개 포트폴리오에서 틀리게 실패했다 → 달력을 맞춘 뒤 다시 돌린 두 번째 시도는 내부 점검을 모두 통과했으나 리포트 문장 게이트의 부정형 미인식으로 실패했다.
- 두 결함 모두 이번 라운드에서 고쳤다(달력 정렬, 부정 표지 '아닙'). 사용자 결정에 따라 S4 는 다시 돌리지 않았다.

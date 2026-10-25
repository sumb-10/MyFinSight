# MyFinSight 구현 계획 TODO

작성 2026-10-24, 승인된 계획 기준. 근거: `docs/설계보고서/` 개념·상세설계보고서, `docs/Module1~7.md`, `docs/module_prototype2.md` 부록 E·F, `docs/mvp/README.md`, `docs/데이터_현황.md`. 브랜치 `module_mock_up`.

## 0. 목표와 결정

**최종 목표**: 상세설계보고서 채택안(3안: 단계 고정 파이프라인 + Strategy Spec + 역할 한정 LLM)을 일곱 모듈로 구현하고, 내용과 동작을 정리한 최종 보고서를 쓴다.

**결정 (2026-10-24)**

| # | 항목 | 결정 |
| --- | --- | --- |
| D1 | Front 범위 | 포함. 실제 사용 가능한 수준까지 (fixture 제거, API 연동) |
| D2 | 모듈 패키지 | `backend/analysis/` 신설. `module_mockup/`은 실험 기록으로 동결(복사만) |
| D3 | 한국 종목 | 처음부터 미국 + 한국(KOSPI200). 혼합 시장 1차 규칙: 달력 합집합, 휴장일 직전 종가 유지, 거래일 환율 USD 환산, 한국 거래 가정 미반영은 한계 표시 |
| D4 | 체결 규칙 | t−1까지 정보로 추정, t 종가 체결. 뉴스 창 `[d−14, d)` |
| D5 | 추천 없을 때 | 현금 혼합안을 선택안으로 두고 함의 문구 포함 |
| D6 | 보충 질문 형태 | 구조화 질문(선택지) + 자유 입력, 한 번에 1개, 기본 5회 상한(설정) |
| D7 | 재현성 | LLM 캐시 키 = 전체 대화, 실행은 확정된 intent 재사용, 캐시 적중 기록 |
| K-cash | `min_cash_ratio > 0` | 지원 (`apply_constraints(total=1−ratio)`) |
| K-reb0 | `rebalance.count = 0` | buy-and-hold |
| K-id | run_id | `run_<YYYYMMDD>_<HHMMSS>_<4hex>` |
| K-cap | 상한 용량 부족 | 섹터·종목 상한으로 전액 배분이 불가능하면 나머지를 현금으로 두고 사유 기록 (최적화 실패 시 기준 비중 유지) |

## 1. 현재 상태 (2026-10-25 새벽)

| 영역 | 위치 | 상태 |
| --- | --- | --- |
| 팀 DB·수집기 | `backend/` | 운영 중. Repository 에 분석용 리더 6개 추가 (`backend/db/analysis_readers.py`) |
| 분석 패키지 | `backend/analysis/` | **B0~B9 + 라운드 4 완료**(경고 재설계·공시 근거·병렬·문서 v2, 테스트 78개). 01~14 단계가 Repository 직결로 동작, 대화·큐·워커·API·7섹션 리포트·인용 게이트, 모의투자(m6_tracking), 수정 요청·비교(revision/compare), 평가 도구(eval). 테스트 55개 (`backend/tests/analysis/`). 실제 팀 DB(읽기)·로컬 SQLite(쓰기)로 stub·api 모두 끝까지 확인 |
| 분석 파이프라인(실험) | `module_mockup/` | 동결. 참고용 |
| Front | `Front/` | **F0~F8 + 라운드 4 리포트 화면 v2 완료**(Vitest 25개). API 연동 앱(프로필·홈·보충 질문·조건 확인·진행·리포트) + 모의투자 목록/상세/시작 대화상자 + 수정 요청 패널·수정안 카드·원안 비교 화면. Vitest 9개, 차트 화면 코드 분할. typecheck·test·build 통과 |
| 라이브 검증 | 실제 팀 DB | 종목 사전(719종목) 생성, stub 실행(미국·미국+한국), 실제 LLM 실행(AI 시나리오 1회: 12분, $0.08, 리포트 7섹션·인용 2,209건). 시나리오 7개를 서비스 경로(질문→확정→일꾼)로 일괄 실행 중 → `docs/mvp/scenario_runs/` |

## 2. 아키텍처

```
Front (React :5173) ──/api/v1──▶ backend.analysis.api (FastAPI :8001)
                                     │ store/data/*.json (프로필·요청·runs.json 큐·모의투자·비교)
                                     ▼
                          backend.analysis.worker (단일 프로세스, FIFO)
                                     │ executor.runner → stages 01…14
                                     ▼
                  backend.db Repository → 팀 PostgreSQL (읽기: 시장 자료 / 쓰기: run_step·run_artifact·report)
```

패키지 설명은 `backend/analysis/README.md`, 화면 구조는 `Front/README.md`.

## 3. 작업 단계

상태: `[ ]` 미착수 / `[~]` 진행 / `[x]` 완료

### 백엔드

- [x] **B0 기반**: settings/paths/errors, schemas 분할(+Question), LlmClient(멀티턴·캐시·StubLlm·스마트 stub), JsonStore(+잠금), prompts/stubs/store_schemas, pyproject extra.
- [x] **B1 Module2**: Repository 리더(`get_price_bars`, `get_fx_range`, `get_valuation_asof`, `constituents_at`, `get_news_batch`, `asset_map`, `list_reports`), MarketData/View(통화 분리·합집합 달력·휴장일 직전값·LookaheadError), quality(assess_quality 재사용), descriptor(select_version), metrics(Fact 인용 ID), news 창. 합성 sqlite 픽스처(미국 16 + 한국 4 + ETF 3).
- [x] **B2 파이프라인 포팅**: m3(02~06, GOOG/GOOGL 묶기, 상한 전 정렬), m4(07~10 + construct() 4 호출 위치, 뉴스 뷰만, δ 하한, 상한 용량→현금), m5(11~13), executor/cli, 불변식 테스트.
- [x] **B3 실행기·큐·워커**: stages 레지스트리(5묶음), runner(run_step 상태 전이·단계 경계 취소), queue(runs.json+flock, FIFO, position, recover_stale), worker(job_lock+file lock), persist(run_artifact·report), systemd 유닛.
- [x] **B4 Module1 대화**: assemble/validate(한국어 필드 오류)/derive/conditions(ConditionRow)/history/dialog(DialogService: 턴·질문 필터·답 반영·blocked·confirm 멱등·fingerprint), 02_intent 프롬프트 questions 계약.
- [x] **B5 API**: `/api/v1` health·meta/options·profile·requests(answer/skip/confirm/cancel)·runs(cancel)·reports(results/rerun), 오류 봉투, TestClient 테스트.
- [x] **B6 리포트**: 7섹션, evidence 블록, 14c_market 프롬프트, 인용 규칙(14a/14b), report_check 게이트(인용 실존·보유 종목·기준일·7섹션·금지 표현 = 오류, 숫자 = 경고).
- [x] **B7 Module6 모의투자**: `m6_tracking/paper.py` PaperService(preview→create, 거래일별 평가·적립·리밸런싱(construct mode=paper, 종목 유지)·중지/재개(건너뛴 리밸런싱 기록)·지연 표시·단위가격 수익률), `/paper` API, 일꾼 한가할 때 시간당 갱신. 테스트 9개.
- [x] **B8 수정 요청·비교**: `m1_request/revision.py`(15_revision 프롬프트 → 코드 검증: 바꿀 수 있는 필드만, 평가 조건 고정, HARD 통과), `DialogService.start_revision`(revision 모드 대화, 원안 대비 변경 표시), `m5_backtest_report/compare.py`(조건·종목·비중·규칙·성과, LLM 없음), 일꾼이 수정안 실행 뒤 비교 저장, `/reports/{id}/revisions`·`/comparisons/{id}` API. 테스트 3개.
- [x] **B9 실제 DB 검증**: 종목 사전 719종목(1.7초). 발견·수정: 한글날(10-09) 같은 한 시장 휴장일이 창 첫날이면 "직전 종가" 가 없어 필수 종목 결측 → 패널 앞 2주 선적재 + 기준일을 공통 거래일로 옮김; 허용 낙폭·목표수익·비교지수를 LLM 값 대신 코드가 계산; 실제 LLM 리포트가 "보장하지 않습니다" 같은 부정형에 걸려 실패 → 부정형 허용 + 프롬프트 수정. 가격 선적재 22~33초/실행, 실제 LLM 실행 12분·$0.08. 결과는 로컬 SQLite 에 쓰기로 결정(쓰기 계정 요청 안 함). `valuation_daily` 커버리지(최신일): 미국 PER 482/517, ROE 478, 배당 370; 한국 PER 169/201, ROE 199, 배당 145.

### Front

- [x] **F0 골격**: vite proxy, `.env.example`, `api/types.ts`, 환경 타입.
- [x] **F1~F2** (재작성으로 대체): `app/`(router·providers·App), `api/`(client·service·fixtureService), `state/`, `ui/`, `lib/format.ts`. 예전 fixture 앱 파일 삭제.
- [x] **F3 프로필**: 새 모델 위저드 4단계(진단 → 3단계 성향 매핑, 분수 단위), 서버 저장·버전 이력, 구 localStorage 프로필 이관.
- [x] **F4 분석 흐름**: Home → ClarifyScreen(채팅형 이력, 선택지+자유 입력, 건너뛰기, blocked 안내, HARD 오류 안내) → ConfirmScreen(ConditionRow 표, 변경 표시, 미지원 차단) → RunScreen(폴링, 5묶음 실제 상태, 세부 단계, 취소, 실패 행동).
- [x] **F5 리포트**: 목록, 상세(7섹션 블록 렌더, 인용 `[n]` → 출처 패널, 계산 조건·실행 기록 패널, 재분석), 오프라인 샘플 리포트.
- [x] **F6 모의투자 화면**: PaperScreen(목록·상세: 성과 그래프, 비중, 규칙·이력, 거래·리밸런싱, 일별 기록, 갱신·중지·재개), StartPaperDialog(리포트에서 전략·시작일·자본 선택 → 시작 비중 미리보기 → 등록).
- [x] **F7 수정 패널·비교 화면**: RevisionPanel(리포트 → 말로 수정 요청), RevisionCard(Clarify/Confirm 에 반영한/못한 변경), ComparisonScreen(#/comparisons/:id), 실행 완료·리포트에서 "원안과 비교" 연결.
- [x] **F8 마무리**: Vitest + Testing Library(9개), 차트 화면 `React.lazy` 분할(메인 253KB + 차트 357KB 지연), 오프라인(샘플) 모드 제거, 연습(stub) 모드 경고 띠, 홈 "상세 조건" 대화상자(이번 요청 덮어쓰기), 조건 확인에 계산 조건 안내. 남은 것: `Front/docs/05` 브라우저 인수 점검, docs/02 화면 목록.

### 검증·보고서

- [x] **E1** `backend/analysis/eval/requirements.py` → `docs/mvp/requirements_check.md` (R1~R12·C-04·C-06·C-12 모두 테스트 통과, 리포트 7건 인용 277개 색인 일치, 기준일 이후 뉴스 0, 단정 표현 0).
- [x] **E2** 시나리오 7개를 실제 서비스 경로·실제 DB·실제 LLM 으로 실행 (`docs/mvp/scenario_runs/`, 총 LLM 비용 0.55달러). 에너지는 게이트 수정 후 재실행. `docs/mvp/README.md` 상단에 요약.
- [x] **E3** 최종 보고서 초안 `docs/최종보고서_초안.md` (검토 대기). 실험 표·요구사항 표·비용 채움.
- [~] **E4** README·howtouse·패키지 README 갱신 완료. 남은 것: `docs/old/` 로 구 문서 이동 여부 결정(사용자), `Front/docs/02` 화면 목록에 상세 조건·수정·비교·모의투자 반영, 브라우저 인수 점검(`Front/docs/05`).

## 4. 알려진 한계·메모

- LLM 모드 기본값: OPENAI_API_KEY 가 있으면 api, 없으면 stub (2026-10-24 변경; 사용자가 연습 모드 해석을 가짜 자료로 오해). stub 모드 02_intent 파일 stub 은 질문이 없어 대화가 바로 ready 가 된다(실제 LLM 또는 테스트 주입 stub 에서 질문 발생). 스마트 stub 은 04·06·09·14a/b/c·15_revision 에 있음.
- 실제 LLM 대화는 7개 시나리오 중 3개에서 질문을 1개씩 했다(클라우드 범위, 전력 사업자 범위, 소형 바이오 제외). 질문 상한(5)에 걸린 경우는 없었다.
- `backend/analysis/common/store_schemas/analysis_request.schema.json` 은 v1 필드만 적혀 있고 실제 저장은 Pydantic 모델(`AnalysisRequestDoc`)로 검증한다 → E4 에서 스키마 파일을 모델에 맞춰 다시 생성.
- 백엔드 기존 테스트 3건(`test_repository` 2건 pandas 인덱스 dtype, `test_backfill` 1건)은 이번 변경 전부터 실패.
- ruff 가 venv 에 없어 lint 미실행(pyproject 에 `backend/analysis/**` E501 예외 추가함). `pip install ruff` 후 `ruff check backend/analysis` 필요.
- 한 구성종목 스냅샷(2026-10-04)만 있어 과거 기준일은 생존 편향 경고를 리포트 §6 에 자동 표시.

## 5. 역할 A에 요청할 것

- (보류) `myfinsight_write` 계정: 결과를 팀 DB 에 쓰기로 바꿀 때만 필요. 지금은 로컬 SQLite(`data/analysis_results.db`)에 쓰기로 결정(2026-10-24).
- `backend/scripts/build_descriptor.py --universe ALL` 산출물을 `backend/data/processed/`에 두거나 생성 절차 공유.
- `news` 테이블 `(asset_id, published_at)` 인덱스 존재 확인(있음: `idx_news_asset_published`).

## 6. 2026-10-25 라운드 4 (경고·공시·병렬·리포트 화면) — 상세는 `docs/updates/2026-10-25_round4.md`

- 경고: 구조화 계약(`common/warnings.py`, user/info/debug). 화면·리포트 §6 에는 행동 필요한 것만, 단계 PARTIAL 도 그때만. 172건 → 몇 건.
- 공시: `disclosures` 를 뷰의 주 근거(45일 창, `available_on`, 허용 사건 26종), 뉴스는 보조. 근거 ID `dc*`, 06·14c·13·14 검증까지 연결. 공시만 근거인 뷰는 신뢰도 0.25 상한.
- 병렬(결과 동일): 단계 웨이브(`Stage.deps`), 10w 리밸런싱일 풀, 04 배치 풀, 14a∥14c + 오류 낸 호출만 재시도, 체크포인트 요약 경량화, walk-forward 뷰 진단 날짜별(버그 수정). `ANALYSIS_PARALLEL=0` 으로 끄기.
- 리포트 문서 v2 + 화면: 요약 대시보드, 접이식 7부분·묶음, 근거는 인용된 것만 + `/evidence` 드로어, 타임라인·기업 아코디언·비중 비교 표, 옛 문서 자동 변환, gzip.
- 검증(실제 DB·LLM): AI 3년·분기 633→325초, 미국·한국 반도체 561→264초, 저PER 2010~2016 393초(모두 §8 참고). 공시 인용은 최근 구간 뷰의 약 40%, 2010년대는 3%.
- 남은 것: 브라우저에서 새 리포트 화면 수동 점검(`Front/docs/05` §5~7 리포트 항목), 뷰 프롬프트의 공시 인용 강화(2010년대 구간), 재무제표 추이·뉴스 본문 발췌·회사 소개문 근거(제외 후보), `view_refresh_every`(넣지 않기로 함).

## 7. 2026-10-25 사용자 피드백으로 고친 것 (라운드 3 마무리)

- 서버 기본 LLM 모드: 키가 있으면 api (연습 모드 해석을 가짜 자료로 오해한 사례). 연습 모드면 화면에 경고.
- 프로필의 ETF 는 차단이 아니라 안내. 아이디어의 기간("2005년부터 약 12년간")은 코드가 읽어 반드시 질문(`horizon` 부분 갱신). 재무 지표 템플릿은 자료 시작일(미국 2009-08, 한국 2004-08) 전 구간을 잘라내고 안내.
- 한 섹터 테마 + 섹터 상한 → "풀까요/유지할까요" 질문. 리포트 게이트의 '보장' 은 동사꼴만.
- 남은 제안: 리밸런싱일이 한 시장 휴장일일 때 처리 규칙 문서화, 과거 기준일 분석에서 "현재 구성" 명칭을 "기준일 구성" 으로 표시.

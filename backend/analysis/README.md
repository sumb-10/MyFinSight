# backend/analysis — 분석 패키지 (설계보고서 3안 구현)

`module_mockup/`(실험 기록, 동결) 을 일곱 모듈 패키지로 옮긴 것. 모든 금융 자료는 `backend.db` Repository 로만 읽고(외부 호출 0건), LLM 은 의도 해석·보충 질문·테마 분류·뉴스 뷰·서술만 맡는다. 숫자 계산과 값 반영은 코드가 한다.

```
m1_request/      Module1 프로필·요청 조립·HARD 검증·파생값·보충 질문 대화(DialogService)·이력
m2_data/         Module2 MarketData/MarketDataView(기준일 보호, 혼합 달력, USD 환산), 품질 판정, 디스크립터, 지표(fin:* 인용), 근거 창 = 뉴스 14일(ev*) + 공시 45일(dc*, available_on 기준), 공시 사건 한국어 라벨
m3_selection/    Module3 의도 해석(02) → 후보 검색(03) → 테마 분류(04) → 정량 선정(05) → 기업별 근거(06)
m4_portfolio/    Module4 시장모형·템플릿 4종·공시(주)·뉴스(보조) 근거 뷰·Black-Litterman, 공통 함수 construct() (시작·리밸런싱·현재·모의투자)
m5_backtest_report/ Module5 bt 백테스트·지표·R1~R8 검증·현금 혼합안·결과 통합(13)·리포트 문서 v2(14: 요약 대시보드 summary + 7섹션, 접힘 묶음 group_ko, 인용된 근거만 evidence, 14a∥14c 병렬·오류 낸 호출만 재시도)·인용 검증 게이트·DB 저장·수정안 비교(compare)
m6_tracking/     Module6 모의투자: 미리보기→등록, 거래일마다 평가·적립·리밸런싱(construct mode=paper), 중지·재개, 지연 표시
executor/        M0-05 단계 레지스트리(Stage.deps)·러너(의존이 끝난 단계 묶음을 동시에, run_step)·parallel.py(순서 지키는 병렬 도우미)·FIFO 큐(runs.json)·워커(한가할 때 모의투자 갱신)·개발 CLI
api/             M0-06 FastAPI 서비스 (/api/v1, gzip): 프로필, 요청·질문·확정, 실행 상태, 리포트(+근거 색인 페이지·한 건, 체크포인트 상세, 전체 시계열), 수정 요청·비교, 모의투자
common/          설정 스냅샷, LLM 호출기(캐시·지터 백오프·동시 호출 상한·stub), 경고 카탈로그(warnings: user/info/debug), 인용 정규식(citations), 로컬 JSON 저장소(잠금), 프롬프트, DB 연결(dbconn: 읽기 팀 DB / 쓰기 로컬 SQLite)
eval/            E1·E2 도구: run_scenarios(시나리오를 실제 서비스 경로로 실행·요약표), requirements(요구사항 자동 점검표)
examples/        요청 예시 JSON (미국 AI 반도체, 미국+한국 반도체)
prompts/ stubs/  LLM 프롬프트와 stub 응답 (02_intent 에 questions 계약, 09_views_news, 06_explain, 14a/14b/14c, 15_revision)
```

## 실행

```bash
# .env: 팀 DB 주소(DATABASE_URL 또는 NEWS_DB_HOST/USER/PASSWORD), OPENAI_API_KEY (있으면 실제 LLM 이 기본), MYFINSIGHT_LLM=stub 로 연습 모드
#       결과(run_step·run_artifact·report)는 기본으로 로컬 SQLite data/analysis_results.db 에 쓴다 (ANALYSIS_RESULTS_DB, "main" 이면 팀 DB)
python backend/scripts/build_descriptor.py --universe ALL          # 종목 사전 (backend/data/processed)
uvicorn backend.analysis.api.app:app --port 8001                   # 서비스 API (Front 가 /api 로 프록시)
python -m backend.analysis.executor.worker                          # 분석 워커 (단일 프로세스, FIFO)
python -m backend.analysis.executor.cli run --request module_mockup/input/01_user_request.ai.jsonc --stub   # 개발용 인프로세스 실행
pytest backend/tests/analysis -q                                    # 합성 sqlite + stub LLM 테스트
python -m backend.analysis.eval.run_scenarios --scenarios ai,kr --llm api   # 시나리오를 API→질문→확정→일꾼 경로로 실행, docs/mvp/scenario_runs/ 에 요약
python -m backend.analysis.eval.requirements                        # 요구사항 자동 점검표 → docs/mvp/requirements_check.md
```

환경변수: `ANALYSIS_STORE_DIR`(로컬 JSON 저장소, 기본 data/analysis_store), `ANALYSIS_OUTPUT_DIR`(실행 산출물, 기본 output/), `ANALYSIS_RESULTS_DB`(결과 저장 DB, 기본 로컬 SQLite), `ANALYSIS_DESCRIPTOR_DIR`, `ANALYSIS_MARKETS`(기본 US,KR), `ANALYSIS_MAX_QUESTIONS`(기본 5), `ANALYSIS_CORS_ORIGINS`, `ANALYSIS_LLM_CONCURRENCY`(동시 LLM 호출 상한, 기본 4), `ANALYSIS_PARALLEL=0`(단계·리밸런싱일·분류·리포트 호출을 모두 순차로; 결과값은 같음), `ANALYSIS_MAX_PARALLEL_STAGES`(기본 3).

API 추가 경로: `POST /reports/{id}/revisions {text}`(수정 요청 → revision 대화), `GET /comparisons/{id}`·`GET /reports/{id}/comparison`(원안 대비 비교), `POST /paper/preview`, `POST /paper`, `GET /paper`, `GET /paper/{id}`, `POST /paper/{id}/refresh|stop|resume`. 라운드 4: `GET /reports/{id}/evidence?offset&limit≤200&kind&ticker&q&from&to&ids`(근거 색인 페이지), `GET /reports/{id}/evidence/{eid}`(한 건 + 인용 문장), `GET /reports/{id}/checkpoints/{seq}?portfolio_id`(리밸런싱 시점 상세), `GET /reports/{id}/series?dataset&ids`(전체 해상도 시계열). `GET /reports/{id}` 는 옛 v1 문서를 읽을 때 `present_doc` 으로 정규화한다(저장 문서는 그대로).

## 규칙 (요구사항 번호는 개념설계보고서)

- 선견 금지(15): `MarketDataView(as_of)` 가 `end > as_of` 조회를 `LookaheadError` 로 막는다. 구성일 d 의 추정은 d 이전 자료(t−1), 체결은 d 종가.
- 실제 데이터 근거(3): price_daily·fx_daily·valuation_daily·news·disclosures·index_constituent·assets 만 읽는다. 공시는 `available_on`(투자자가 볼 수 있게 된 날) 기준 `[d−45, d)` 창, 수정 공시 제외, 사건 종류 허용 목록(`DisclosureSettings.event_types`; ELS·대량보유·위임장 등은 제외). 품질 판정은 `backend.pipeline.quality.assess_quality`(커버리지 0.95, 1일 채움, 2일 제외).
- 검증 통과 결과만 제공(5, 8): R1~R8 검증, 리포트 문단의 인용 ID(`[ev123]` 뉴스, `[dc45]` 공시, `[fin:…]`, `[calc:…]`) 실존·보유 종목·기준일 이전(공시는 이용 가능일) 검사, 7섹션·금지 표현 검사 실패 시 리포트를 저장하지 않음. 오류를 낸 LLM 호출(14a/14b/14c)만 피드백으로 1회 다시 부른다.
- 경고(라운드 4): 단계는 `ctx.warn(stage, code)` 로 구조화 경고를 남기고(`common/warnings.py` 카탈로그), level `user`(행동 필요) 가 있을 때만 단계가 PARTIAL. 화면·리포트 §6 에는 user 만, info/debug 는 `13_results.warnings`·`run_meta.json` 에만.
- 병렬(라운드 4, 결과값 동일): 러너가 `Stage.deps` 로 의존이 끝난 단계를 묶어 동시에 돌고(06·07·10f / 10·10w), 10w 리밸런싱일·04 분류 배치·14a∥14c 를 풀로 돈다. 결과는 입력 순서로 조립해 순차 실행과 같다(`test_sequential_run_gives_identical_results`). SQLite 저장소는 접근을 직렬화한다.
- 재현성(14): LLM 캐시 키 = 모델 + 단계 + 전체 대화. 확정된 intent 는 실행 때 재사용. 설정 스냅샷은 `run_artifact.params`.
- 보충 질문(2): 1회 1항목, 최대 N회(설정). HARD 오류는 질문 아닌 즉시 수정. 선택지 답은 코드가 필드에 반영, 자유 입력은 아이디어에 덧붙여 다음 턴에 해석.
- 실행 기록(9): 단계마다 `run_step`(QUEUED/STARTED/SUCCESS/PARTIAL/FAILED/CANCELLED), 큐 상태는 `runs.json`, 취소는 단계 경계.
- 수정 요청(10): LLM 은 바꿀 필드·값·이유만 제안(15_revision). 코드가 바꿀 수 있는 필드만 받고, 기간·자본·적립·비교지수·리밸런싱·종목 범위는 원안 값으로 고정해 공정하게 비교한다. 수정안 실행이 끝나면 `compare()` 가 조건·종목·비중·규칙·성과 비교 문서를 만든다(LLM 없음).
- 모의투자(11): 미리보기에서 확인한 비중이 그대로 등록된다. 단위가격 방식이라 적립금은 수익으로 잡히지 않고, 비교지수에도 같은 자본·적립을 넣는다. 필수 가격이 없으면 가짜 스냅샷 없이 delayed 로 둔다.
- 혼합 시장 기준일: 기준일이 어느 한 시장의 휴장일이면 두 시장이 모두 거래한 가장 가까운 앞날로 옮기고 경고를 남긴다. 가격 패널은 창 시작 앞 2주 자료를 같이 읽어 첫날 휴장일에도 "직전 종가 유지"가 되게 한다.

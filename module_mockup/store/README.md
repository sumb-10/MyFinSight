# store/ — 로컬 JSON 저장소

팀 DB에 없는 저장 객체(프로필, 분석 요청, run 색인, 모의투자 tracking, 수정안 비교)를 로컬 JSON으로 둔다.
결정 K1(2026-10-10): 이 객체들은 DB 테이블로 만들지 않는다. 명세는 `docs/module_prototype.md` 부록 H.

```
store/
  README.md                 이 문서 (git 포함)
  schemas/                  JSON Schema draft 2020-12 (git 포함)
  data/                     실제 사용자 데이터 (git 제외: module_mockup/.gitignore → store/data/*)
    profile.json                          프로필 1개 + 버전 이력            profile.schema.json
    requests/<request_id>.json            분석 요청(질문·답변·확정 요청)    analysis_request.schema.json
    runs.json                             run 색인·작업 큐 상태             run_index.schema.json
    paper/<paper_id>/portfolio.json       모의투자 객체                     paper_portfolio.schema.json
    paper/<paper_id>/snapshots.jsonl      일일 스냅샷 (1줄 = 1거래일)        paper_snapshot.schema.json
    paper/<paper_id>/rebalances.jsonl     리밸런싱 기록 (1줄 = 1회)          rebalance_record.schema.json
    comparisons/<comparison_id>.json      원안·수정안 비교                  revision_comparison.schema.json
```

## 규칙

1. 모든 파일에 `schema_version`(정수)을 두고, 스키마가 바뀌면 올린다. 읽는 쪽은 자기가 아는 버전만 처리한다.
2. 쓰기는 `scripts/store.py`(M0-04)만 한다. 순서: 스키마 검증 → 같은 디렉터리의 임시 파일에 쓰기 → 이름 바꾸기(원자적). 깨진 파일을 남기지 않는다.
3. `.jsonl` 파일은 줄을 추가만 한다. 과거 줄을 고치지 않는다.
4. ID 형식: `request_id` = `req_<YYYYMMDD>_<HHMMSS>_<4hex>`, `run_id` = `run_<YYYYMMDD>_<HHMMSS>`, `paper_id` = `paper_<YYYYMMDD>_<4hex>`, `comparison_id` = `cmp_<base_run_id>__<revised_run_id>`.
5. 날짜 `YYYY-MM-DD`, 시각 ISO 8601(시간대 포함), 금액 USD 실수, 비중은 0~1 소수.
6. `data/`는 백업 대상이고 git·Google Drive에 올리지 않는다. 경로는 `scripts/common.py`의 `STORE_DATA`로만 참조한다.
7. 결과 통합(`13_results.json`)과 리포트(`14_report.json`)는 여기 두지 않는다. DB `run_artifact`·`report`에 저장하고, `runs.json`이 `run_id`로 연결한다.

## 검증

```bash
~/.venvs/myfinsight/bin/pip install jsonschema      # 1회
~/.venvs/myfinsight/bin/python -c "import json,jsonschema,pathlib; [jsonschema.Draft202012Validator.check_schema(json.load(open(p))) for p in pathlib.Path('store/schemas').glob('*.json')]; print('ok')"
```

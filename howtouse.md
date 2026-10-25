# MyFinSight 사용 안내 (처음 켜는 사람용)

이 문서는 "어떻게 켜고, 어떻게 쓰는지"만 다룹니다. 설계 설명은 `docs/` 폴더에 있습니다.

## 1. 이 프로그램이 하는 일

1. 내 투자 조건(돈, 기간, 성향, 제약)을 저장합니다.
2. "미국 반도체에 나눠서 투자하고 싶다" 같은 말을 적습니다.
3. 부족한 것이 있으면 프로그램이 한 번에 하나씩 물어봅니다. 최대 5번입니다.
4. 조건을 확인하고 "분석 시작"을 누릅니다.
5. 프로그램이 종목을 고르고, 비중을 정하고, 과거 데이터로 성과를 계산합니다.
6. 결과를 리포트로 보여 줍니다. 숫자마다 어디서 나온 값인지 눌러서 볼 수 있습니다.

실제 매매는 하지 않습니다. 돈이 오가지 않습니다.

## 2. 세 개의 프로그램

| 이름 | 하는 일 | 켜는 방법 |
| --- | --- | --- |
| 화면 (Front) | 브라우저에서 쓰는 화면 | `pnpm dev` |
| 서버 (API) | 화면의 요청을 받아 저장하고 줄을 세움 | `uvicorn ...` |
| 일꾼 (worker) | 줄에 선 분석을 하나씩 실제로 계산 | `python -m ...worker` |

세 개를 다 켜야 분석이 끝까지 됩니다. 화면만 켜면 "서버 연결 끊김"이라고 나옵니다. 서버만 켜고 일꾼을 안 켜면 분석이 "대기 중"에서 멈춥니다.

## 3. 처음 한 번만 하는 준비

### 3-1. 필요한 것

- 파이썬 3.11 이상 (이 컴퓨터에는 `~/.venvs/myfinsight` 가상환경에 3.13이 있습니다)
- Node.js 22 와 pnpm 10 (화면용)
- 팀 데이터베이스 접속 정보 (가격·뉴스가 들어 있는 곳). 없으면 "연습 모드"로 켤 수 있습니다. 6번을 보세요.

### 3-2. 파이썬 쪽

```bash
cd ~/dev/MyFinSight
source ~/.venvs/myfinsight/bin/activate        # 가상환경 켜기
pip install -e ".[analysis,dev,postgres]"      # 필요한 꾸러미 설치
```

설치하다가 `certificate` 어쩌고 하는 빨간 글씨가 나오면 뒤에 이걸 붙여서 다시 합니다.

```bash
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -e ".[analysis,dev,postgres]"
```

### 3-3. 비밀 정보 파일 `.env`

`.env.example`을 복사해서 `.env`를 만들고 값을 채웁니다. 이미 `.env`가 있으면 아래 줄이 있는지만 확인합니다.

```
NEWS_DB_HOST=...        # 팀 DB 주소 (받은 그대로)
NEWS_DB_USER=reader
NEWS_DB_PASSWORD=...
OPENAI_API_KEY=sk-...   # 실제 LLM 호출에 필요. 키가 있으면 실제 LLM(api)이 기본
# MYFINSIGHT_LLM=stub   # 이 줄을 켜면 연습 모드: LLM을 부르지 않고 미리 만든 답을 씁니다 (해석 결과가 아이디어와 맞지 않음). 화면에 "연습 모드" 표시가 뜹니다
```

`.env`는 비밀번호와 같습니다. 깃허브나 메신저에 올리지 마세요.

### 3-4. 종목 사전 만들기 (팀 DB가 있을 때, 한 번)

프로그램이 "반도체 회사가 어떤 회사들인지"를 찾을 때 쓰는 목록입니다. DB에서 읽어서 파일로 만듭니다.

```bash
python backend/scripts/build_descriptor.py --universe ALL
```

끝나면 `backend/data/processed/` 안에 `all_descriptor_*.json` 파일이 생깁니다.

### 3-5. 화면 쪽

```bash
cd Front
source ~/.nvm/nvm.sh && nvm use
pnpm install --frozen-lockfile
cd ..
```

## 4. 켜기 (매번)

터미널 창을 세 개 엽니다. 모두 `~/dev/MyFinSight` 폴더에서 시작합니다.

**창 1 · 서버**

```bash
source ~/.venvs/myfinsight/bin/activate
uvicorn backend.analysis.api.app:app --port 8001
```

**창 2 · 일꾼**

```bash
source ~/.venvs/myfinsight/bin/activate
python -m backend.analysis.executor.worker
```

**창 3 · 화면**

```bash
cd Front
source ~/.nvm/nvm.sh && nvm use
pnpm dev
```

브라우저에서 http://localhost:5173 을 엽니다.

잘 켜졌는지 보려면 브라우저에서 http://localhost:8001/api/v1/health 를 열어 보세요. `"ok": true` 와 `"worker": {"alive": true` 가 보이면 됩니다.

끌 때는 각 창에서 `Ctrl+C` 를 누릅니다.

## 5. 화면에서 하는 순서

1. **내 투자조건** — 처음에는 자동으로 이 화면이 뜹니다. 네 단계입니다.
   - 기본 조건: 돈, 기간, 목적
   - 투자성향: 질문 3개에 답하면 성향이 나옵니다. 다르게 고를 수도 있습니다.
   - 종목 범위·제약: 미국/한국, 종목 수, 한 종목·한 업종 최대 비중, 빼고 싶은 종목·테마·섹터, 시가총액·거래대금 하한(0이면 제한 없음)
   - 전략 선호: 종목 고르는 기준(모멘텀 등), 비중 방식, 뉴스 반영 여부
   - 저장하면 "버전 1"로 기록됩니다. 나중에 고치면 버전 2가 됩니다. 옛 리포트는 그대로 남습니다.
2. **홈** — 투자 아이디어를 말로 적고 "투자조건 확인하기"를 누릅니다. 옆의 **"상세 조건"** 버튼을 누르면 이번 분석에만 쓸 투자금·적립·기간·백테스트 기간(최근 N년 또는 특정 연도 범위)·위험 성향·비교지수·유니버스·종목 수·상한·선정 기준 등을 한 화면에서 정할 수 있습니다. 프로필은 바뀌지 않고, 바꾼 항목은 파란 칩으로 보입니다. 기간을 말로 적어도("2005년부터 12년간") 프로그램이 읽어서 물어봅니다.
3. **보충 질문** — 프로그램이 모르는 것을 하나씩 묻습니다. 보기를 고르거나 직접 적습니다. "답하지 않음"을 누르면 기본값을 씁니다. 5번 넘게 물어도 안 정해지면 분석을 시작하지 않고 무엇이 모자란지 알려 줍니다. 왼쪽 **"지금 조건"** 에 프로필에서 가져온 값이 다 보이고(바뀐 값은 파란색), **"조건 바꾸기"** 버튼으로 투자금·기간·유니버스·종목 수·상한·제외 테마·시가총액 하한·리밸런싱 등을 폼에서 바로 고칠 수 있습니다. 오른쪽 **"말로 조건 보태기"** 에 "한국 종목은 빼 주세요"처럼 적어 보내도 됩니다. 아이디어가 프로필 값과 다르면(예: "미국 기업만"인데 유니버스에 한국이 있음) 프로그램이 "아이디어대로 / 프로필대로" 중 고르게 묻습니다. 이번 요청에서 직접 정한 값은 다시 묻지 않습니다.
4. **조건 확인** — 최종 조건이 표로 나옵니다. 내 기본 조건과 달라진 줄은 파란색으로 표시됩니다. 여기서 "분석 시작"을 눌러야 비로소 계산이 시작됩니다.
5. **진행** — 다섯 묶음(조건 확인 → 종목 고르기 → 과거 계산 → 조건 검증 → 리포트)이 실제 상태대로 바뀝니다. 가짜 진행률은 없습니다. 서로 기다릴 필요가 없는 단계는 동시에 돌고(예: 기업별 근거·백테스트 사양·현재 구성), 리밸런싱일별 뉴스·공시 뷰도 여러 날짜를 한꺼번에 계산하므로 한 묶음 줄에 "7/13" 같은 진행이 보입니다. 보통 몇십 초에서 몇 분 걸립니다. 브라우저를 닫아도 서버는 계속 계산합니다. "분석 취소"는 지금 단계가 끝난 뒤에 멈춥니다. 단계 옆에 "확인 필요 N건"이 붙으면 조건을 바꾸면 결과가 달라질 수 있는 일(예: 상한 때문에 돈을 다 못 넣음)이라는 뜻이고, 그 목록은 리포트 6부분에서 다시 볼 수 있습니다.
6. **리포트** — 맨 위 **한눈에 보기**에 결론 한 줄(추천 여부), 핵심 숫자(비교지수 값과 나란히), 배분 비중, 누적 수익률 미니 차트, 검증 통과·주의·미통과 수, 다음에 할 수 있는 일이 모여 있습니다. 그 아래가 일곱 부분입니다. 종합 판단 / 산업·시장 / 기업별 근거 / 포트폴리오 구성 / 과거 성과 / 전제와 한계 / 참고자료. 각 부분은 접을 수 있고, 긴 표(요청 조건, 연도별·월별 수익률, 검증 상세, 출처·계산 조건)는 묶음으로 접혀 있다가 누르면 열립니다.
   - 문장 끝의 `[3]` 같은 번호를 누르면 그 말의 근거(뉴스 제목, 공시 사건, 재무 숫자, 계산값)와 "이 근거를 인용한 문장"이 옆에 나옵니다. 공시는 사건 종류(실적 발표, 자사주 취득·처분 결정 등)·양식·접수일·이용 가능일만 있고 본문은 없습니다.
   - "출처 전체" 버튼이나 "출처 보기"를 누르면 근거 색인을 검색·종류·종목으로 걸러 50건씩 봅니다. 수천 건이어도 화면이 느려지지 않습니다.
   - 4부분의 **리밸런싱 타임라인**에서 점을 고르면(←/→ 키도 됩니다) 그날의 평가금액, 뉴스·공시 건수, 적용한 뷰, 보유·거래가 나옵니다. 파란 점은 뉴스·공시 뷰를 적용한 날, 회색 점은 근거가 부족해 기준 비중을 둔 날입니다.
   - 3부분 **기업별 근거**는 왼쪽 종목 목록에서 고르면 그 회사의 설명(2~4문단)이 열립니다. 비중·순위·지표·뉴스/공시 건수가 옆에 있습니다.
   - 왼쪽 "계산 조건", "실행 기록" 버튼(또는 위 "더보기")으로 어떤 가정으로 계산했는지, 각 단계가 무엇을 했는지 볼 수 있습니다. 주소에 `?sec=companies&company=NVDA` 처럼 어디를 보고 있었는지가 남아 새로고침해도 같은 자리로 돌아옵니다.
7. **같은 조건으로 재분석** — 리포트 위 버튼. 조건은 그대로 두고 최신 데이터로 다시 돕니다. 새 리포트가 생기고 옛 리포트는 그대로입니다.

8. **조건 수정 요청** — 리포트 위 "조건 수정 요청" 버튼. "엔비디아는 빼 주세요", "종목 수를 10개로" 처럼 말로 적습니다. 프로그램이 어떤 조건을 바꾸는지 보여 주고(바꿀 수 없는 요청은 이유와 함께), 같은 질문·확인 흐름을 거쳐 수정안을 따로 분석합니다. 끝나면 "원안과 비교" 화면에서 종목·비중·조건 검증·성과를 나란히 봅니다. 기간·투자금·적립·비교지수·리밸런싱은 원안과 같게 고정합니다(공정한 비교).
9. **모의투자 시작** — 리포트 위 버튼. 전략(리포트의 포트폴리오 중 하나), 시작일, 가상 자본, 월 적립을 고르면 시작 비중과 배분 금액을 먼저 보여 줍니다. "이 조건으로 시작"을 누르면 등록되고, 왼쪽 메뉴 "모의투자"에서 시작 이후 성과·비교지수·거래 기록을 봅니다. 서버 일꾼이 한가할 때 한 시간에 한 번 최신 가격으로 갱신하고, "최신 자료로 갱신" 버튼으로 바로 갱신할 수도 있습니다. 중지하면 평가를 멈추고 보유는 그대로 둡니다. 실제 돈은 오가지 않습니다.

## 6. 팀 DB 없이 연습해 보기

**가짜 데이터로 서버까지 다 켜 보기**

가짜 가격·뉴스를 넣은 작은 데이터베이스 파일을 만들어서 서버와 일꾼을 켜는 방법입니다. 실제 종목 20개의 이름만 빌린 만들어진 숫자입니다.

```bash
source ~/.venvs/myfinsight/bin/activate
mkdir -p /tmp/mfs && python - <<'EOF'
import datetime as dt, pathlib
from backend.db import open_repository
from backend.db.readers import descriptor_inputs
from backend.pipeline.descriptor import build_descriptors, write_descriptors
from backend.schemas.market import IndexCode
from backend.tests.analysis.conftest import seed_repository
S = pathlib.Path("/tmp/mfs")
repo = open_repository(f"sqlite:///{S/'demo.db'}", clock=lambda: dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
seed_repository(repo)
with repo.engine.connect() as conn:
    write_descriptors(build_descriptors(descriptor_inputs(conn, list(IndexCode)), "ALL"), S / "desc", "ALL")
print("준비 끝:", S)
EOF
```

그 다음 서버와 일꾼을 켤 때 앞에 환경변수를 붙입니다. (창 1, 창 2 둘 다 같은 줄을 붙입니다.)

```bash
export DATABASE_URL=sqlite:////tmp/mfs/demo.db ANALYSIS_DESCRIPTOR_DIR=/tmp/mfs/desc ANALYSIS_STORE_DIR=/tmp/mfs/store ANALYSIS_OUTPUT_DIR=/tmp/mfs/out MYFINSIGHT_LLM=stub
uvicorn backend.analysis.api.app:app --port 8001          # 창 1
python -m backend.analysis.executor.worker                # 창 2 (같은 export 뒤에)
```

화면은 평소처럼 `pnpm dev`. 가짜 데이터라 "미국·한국 반도체" 같은 아이디어만 결과가 잘 나옵니다.

## 7. 화면 없이 명령어로 한 번 돌려 보기

```bash
source ~/.venvs/myfinsight/bin/activate
python -m backend.analysis.executor.cli run --request module_mockup/input/01_user_request.ai.jsonc --stub
```

끝나면 `output/run_.../` 폴더에 단계별 결과 파일(`01_request.json` … `14_report.json`)이 생깁니다. `--stub`을 빼면 실제 LLM을 부릅니다.

## 8. 자주 생기는 문제

| 증상 | 이유 | 해결 |
| --- | --- | --- |
| 화면 왼쪽 아래 "서버 연결 끊김" | 서버(창 1)가 안 켜졌거나 포트가 다름 | 창 1을 켜고 http://localhost:8001/api/v1/health 확인 |
| 분석이 "대기 중 (순번 1)"에서 안 움직임 | 일꾼(창 2)이 안 켜짐 | 창 2를 켬. health 에서 `worker.alive` 가 true 인지 확인 |
| "프로필을 먼저 등록해 주세요" | 투자조건을 아직 저장 안 함 | 내 투자조건 화면에서 저장 |
| "ALL 사전 버전이 없음" | 종목 사전 파일이 없음 | 3-4번 명령 실행 |
| "비교지수 가격이 없음" 또는 "환율 자료가 없음" | DB에 연결이 안 됐거나 비어 있음 | `.env` 의 DB 주소·비밀번호 확인 |
| 분석이 "실패"로 끝남 | 진행 화면의 빨간 상자에 이유가 있음 | 이유대로 조건을 바꿔 새 요청으로 다시. 실패한 분석은 자동으로 다시 돌지 않음 |
| 리포트를 열면 "아직 만들어지지 않았습니다" | 분석이 끝나지 않았거나 실패 | 진행 화면에서 상태 확인 |
| 리포트 위에 "예전 형식 리포트 (자동 변환)" 배지 | 2026-10-25 이전에 만든 리포트 | 정상입니다. 옛 문서를 읽을 때 새 화면에 맞게 바꿔 보여 줍니다. 요약은 있는 정보로만 채워집니다 |
| 서버 로그에 `429` 가 보이고 느려짐 | 동시에 보내는 LLM 호출이 많음 | `.env` 에 `ANALYSIS_LLM_CONCURRENCY=2` 처럼 낮추거나, 전부 순차로 하려면 `ANALYSIS_PARALLEL=0` |
| `pip install` 이 인증서 오류 | 이 컴퓨터 파이썬의 인증서 설정 문제 | 3-2의 `--trusted-host` 붙인 명령 |
| 다른 일꾼이 이미 돌고 있다는 메시지 | 일꾼은 한 개만 켤 수 있음 | 이미 켜진 창을 쓰거나 그 창을 끄고 다시 |
| 조건 확인에 "기준일을 …로 옮김" 경고 | 고른 날이 한국이나 미국 장이 쉰 날 | 정상입니다. 두 시장이 모두 열린 가장 가까운 앞날을 기준일로 씁니다 |
| 모의투자가 "자료 지연" | 그날 가격이 아직 DB에 없음 | 자료가 들어오면 다음 갱신 때 이어서 기록됩니다. 가짜 평가는 만들지 않습니다 |

## 9. 파일은 어디에 쌓이나

| 무엇 | 어디 |
| --- | --- |
| 내 투자조건, 요청, 질문·답, 실행 목록 | `data/analysis_store/` (JSON 파일, 깃에 안 올라감) |
| 실행별 중간 결과 | `output/run_.../` (깃에 안 올라감) |
| 최종 결과와 리포트 | 로컬 SQLite 파일 `data/analysis_results.db` (`run_step`, `run_artifact`, `report` 표). 팀 DB는 읽기만 합니다. `.env` 에 `ANALYSIS_RESULTS_DB=main` 을 적으면 팀 DB에 씁니다(쓰기 계정 필요) |
| 모의투자, 수정안 비교 | `data/analysis_store/paper/`, `data/analysis_store/comparisons/` |
| 시나리오 일괄 실행 결과 | `docs/mvp/scenario_runs/` (요약표 `summary_latest.md`) |
| LLM 호출 비용 기록 | `output/run_.../llm_usage.jsonl`, 같은 질문은 `output/llm_cache/` 에서 재사용 |

## 10. 테스트 돌리기

```bash
source ~/.venvs/myfinsight/bin/activate
python -m pytest backend/tests/analysis -q       # 분석 쪽 (가짜 DB, LLM 안 부름, 약 15초)
python -m pytest backend/tests -q                # 전체
cd Front && pnpm typecheck && pnpm test && pnpm build   # 화면 쪽 (단위 테스트 포함)
```

시나리오 여러 개를 실제 서비스 경로로 한 번에 돌려 표로 모으려면 (실제 LLM 을 쓰면 비용이 듭니다):

```bash
python -m backend.analysis.eval.run_scenarios --list                 # 시나리오 목록
python -m backend.analysis.eval.run_scenarios --scenarios kr --llm stub   # 연습 (LLM 안 부름)
python -m backend.analysis.eval.requirements                         # 요구사항 자동 점검표 → docs/mvp/requirements_check.md
```

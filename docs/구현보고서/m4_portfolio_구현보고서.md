# m4_portfolio 구현보고서

[전체 안내](README.md)

> 작성 기준: 2026-10-25 작업 공간의 실제 소스. 기존 설계 문서는 배경 참고용이며 아래 동작 설명은 구현을 기준으로 합니다.

대상: Python 파일 7개 · 클래스 1개 · 함수/메서드 32개(중첩 함수와 비공개 보조 함수 포함).

[역할](#role) · [파일 구성](#files) · [처리 흐름](#flow) · [클래스](#classes) · [함수](#functions) · [모듈 연계](#interactions) · [오류·검증](#verification)

<a id="role"></a>
## 1. 모듈의 역할과 용어

`m4_portfolio`는 선정한 종목에 얼마씩 배분할지 계산합니다. 시작일 사양을 확정하고 가격 수익률로 시장모형을 추정한 뒤 동일비중·시총비중·역변동성·최소분산의 네 기본 구성을 만듭니다. 근거가 충분하면 LLM 투자 의견을 Black–Litterman(BL) 모형으로 결합해 비중을 조정합니다.

공분산은 종목 수익이 함께 움직이는 정도, 변동성은 흔들림의 크기, δ는 위험을 얼마나 꺼리는지의 계수입니다. BL의 prior는 기준 비중에서 역산한 내재수익, view는 특정 종목 또는 종목군의 기대수익 가설입니다. 이 가설은 실제 관측 사실이나 수익 보장이 아닙니다.

핵심 진입점 `construct()`는 백테스트 시작·날짜별 리밸런싱·현재 구성·모의투자가 재사용합니다. 이 함수가 종목을 다시 고르지는 않으며 시작일 재선정은 `build_backtest_spec()`가 담당합니다.

<a id="files"></a>
## 2. 파일 구성과 책임

| 파일 | 책임 | 문서 내 해설 |
| --- | --- | --- |
| [m4_portfolio/__init__.py](../../backend/analysis/m4_portfolio/__init__.py) | ConstructResult·construct 공개 재노출 | 정의 없음 |
| [m4_portfolio/black_litterman.py](../../backend/analysis/m4_portfolio/black_litterman.py) | 의견 세트별 BL 비중·예상치·활성 제약 | [클래스 0 · 함수 3](#file-m4_portfolio-black_litterman-py) |
| [m4_portfolio/construct.py](../../backend/analysis/m4_portfolio/construct.py) | 시작·리밸런싱·현재·모의투자 공통 구성 | [클래스 1 · 함수 6](#file-m4_portfolio-construct-py) |
| [m4_portfolio/market_model.py](../../backend/analysis/m4_portfolio/market_model.py) | 시장모형·위험회피·배분 용량·네 기준 비중 | [클래스 0 · 함수 4](#file-m4_portfolio-market_model-py) |
| [m4_portfolio/math.py](../../backend/analysis/m4_portfolio/math.py) | 공분산·제약·비중·BL·효용 최적화의 수학 | [클래스 0 · 함수 14](#file-m4_portfolio-math-py) |
| [m4_portfolio/spec.py](../../backend/analysis/m4_portfolio/spec.py) | 실제 평가 창·과거 시작 재선정·자본 환산 사양 | [클래스 0 · 함수 2](#file-m4_portfolio-spec-py) |
| [m4_portfolio/views.py](../../backend/analysis/m4_portfolio/views.py) | 근거 기반 LLM 의견·범위 제한·불량 의견 제거 | [클래스 0 · 함수 3](#file-m4_portfolio-views-py) |

<a id="flow"></a>
## 3. 처리 흐름과 예시

`build_backtest_spec()`는 현재 선정과 별도로 과거 시작일에 후보·지표를 다시 계산합니다. LLM 테마 분류는 현재 실행에서 만든 통과 집합을 재사용하고, 실행 시작에 고정한 Descriptor를 사용하므로 완전한 과거 정보 재현과는 차이가 있습니다. 현재에도 종목이 부족하거나 사용자가 기간 유지를 골랐으면 시작일 이동을 하지 않습니다.

공통 구성 함수는 다음 순서입니다: 기준일 전 USD 가격 → 로그수익 공분산 추정 → 성향/낙폭 기반 δ → 제약을 적용한 네 기준 비중 → 충분한 뉴스·공시의 의견 → BL 사후 수익·공분산 → 제약 효용 최적화.

| 비중 방식 | 초기 아이디어 | 이후 처리 |
| --- | --- | --- |
| equal_weight | 각 종목 동일 | 최소 비중·종목/섹터 상한 반복 적용 |
| market_cap | 시총 비례 | 누락 0, 전체 누락이면 동일비중 후 제약 |
| inverse_volatility | 변동성의 역수 비례 | 공통 제약 |
| min_variance | 전체 분산 최소 | SLSQP, 실패 시 역분산 근사 |

배분 가능 용량은 섹터별 `min(종목 수×종목 상한, 섹터 상한)`의 합입니다. 예를 들어 모든 종목이 하나의 섹터이고 섹터 상한이 0.8이면 최대 80%만 주식으로 두고 나머지는 현금입니다. 코드가 모든 비중을 다시 100%로 늘려 상한을 깨는 방식으로 처리하지 않습니다.

BL은 기준 비중 w에서 `π=δΣw`를 역산합니다. 의견 행렬 P, 기대수익 Q, 신뢰도에서 불확실성 Ω를 계산해 사후 μ·공분산을 구하고 `wᵀμ-δwᵀΣw/2`를 최대화합니다. 상대 의견의 short는 상대 우위 비교식의 음수 항이고 최종 보유에서 공매도를 허용한다는 뜻은 아닙니다.

예를 들어 입력 허용 낙폭 10%이면 기본 δ 낙폭 배수는 상한 1.5입니다. 별도로 뉴스/공시가 있는 종목이 3개 미만이면 의견 생성 없이 기준 비중을 사용합니다. 공시만 인용한 의견은 신뢰도 최대 0.25, 최적화 실패는 기준 비중 유지·user 경고로 표시됩니다.

mode=start는 과거 시작, rebalance는 같은 과거 종목의 날짜별 조정, current는 현재 선정 종목, paper는 모의투자입니다. 날짜별로 비중은 달라도 종목 재선정 책임은 바깥 호출자에게 있습니다.

### 연관 리소스

| 파일 | 계약·용도 |
| --- | --- |
| [prompts/09_views_news/system_prompt.md](../../backend/analysis/prompts/09_views_news/system_prompt.md) | 고정 시스템 지침(로더는 치환하지 않음); 자리표시자 없음 |
| [prompts/09_views_news/user_prompt.md](../../backend/analysis/prompts/09_views_news/user_prompt.md) | 사용자 입력 템플릿; 자리표시자: `abs_range`, `as_of`, `dc_only_max_conf`, `dc_window_days`, `disclosure_block`, `evidence_block`, `max_conf`, `n_sets`, `news_window_days`, `no_evidence_tickers`, `no_news_tickers`, `rel_range`, `stocks_block`, `summary_ko`, `themes_block`, `views_per_set` |

<a id="classes"></a>
## 4. 클래스 상세

필드 표는 해당 클래스에서 직접 선언한 필드입니다. 상속 필드는 부모 클래스 설명을 함께 읽습니다. `Field(...)`의 범위는 선언된 검증이며, 서비스에서 추가하는 조건은 함수 설명에 구분합니다.

<a id="m4_portfolio-construct-py-ConstructResult-25"></a>
### `ConstructResult`

<!-- source-symbol: m4_portfolio/construct.py:25:ConstructResult -->
[construct.py](../../backend/analysis/m4_portfolio/construct.py#L25)

날짜별 포트폴리오 구성의 공통 반환형입니다. 시장모형·기준안·BL·의견·근거·대체 여부·파라미터·경고를 담고 상위 소비자가 고를 비중을 속성으로 제공합니다.

기반: `명시적 부모 없음` · 선언: `dataclass`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `as_of` | `str` | `필수 입력` | 자료 판단 기준일 |
| `mode` | `Mode` | `필수 입력` | 실행·구성·평가 방식 |
| `market_model` | `dict[str, Any]` | `필수 입력` | — |
| `baselines` | `dict[str, Any]` | `필수 입력` | — |
| `bl_portfolios` | `list[dict[str, Any]]` | `생성 함수: list` | — |
| `view_sets` | `list[dict[str, Any]]` | `생성 함수: list` | 날짜별 의견 세트 수 |
| `evidence` | `EvidenceWindow \| None` | `None` | 문서에 실제 포함할 근거 또는 창 객체 |
| `fallback` | `bool` | `False` | 새 의견 대신 기준/이전 비중을 사용했는지 |
| `fallback_reason_ko` | `str \| None` | `None` | 대체 처리 사유 |
| `params` | `dict[str, Any] \| None` | `None` | — |
| `warnings` | `list[str]` | `생성 함수: list` | 문맥별 전체 경고 또는 문장 검사 메모 |

메서드·속성: [tickers](#m4_portfolio-construct-py-ConstructResult-tickers-39), [baseline](#m4_portfolio-construct-py-ConstructResult-baseline-43), [baseline_weights](#m4_portfolio-construct-py-ConstructResult-baseline_weights-47), [chosen_weights](#m4_portfolio-construct-py-ConstructResult-chosen_weights-51), [evidence_summary](#m4_portfolio-construct-py-ConstructResult-evidence_summary-55).


<a id="functions"></a>
## 5. 함수·메서드 상세

시그니처에 입력 자료형·기본값·반환 자료형을 그대로 기재했습니다. `self`는 소속 클래스의 인스턴스, `cls`는 클래스입니다. 반환 주석이 없는 함수는 본문 해설의 반환 내용을 따릅니다. 속성(`property`)은 호출 괄호 없이 읽고, 중첩 함수는 바깥 함수의 지역 상태를 공유합니다. 연결 목록은 정적으로 확인되는 패키지 내부 직접 호출이며, 주입된 서비스·콜백·Repository 호출은 처리 흐름과 해설에서 설명합니다.


<a id="file-m4_portfolio-black_litterman-py"></a>
### m4_portfolio/black_litterman.py


<a id="m4_portfolio-black_litterman-py-view_summary-16"></a>
#### `view_summary`

<!-- source-symbol: m4_portfolio/black_litterman.py:16:view_summary -->
[black_litterman.py](../../backend/analysis/m4_portfolio/black_litterman.py#L16)

```python
def view_summary(v: dict[str, Any]) -> str: ...
```

절대/상대 의견의 티커·연간 기대수익·신뢰도·이유를 한국어 한 줄로 표현합니다.

호출하는 코드: [build_bl](#m4_portfolio-black_litterman-py-build_bl-22).


<a id="m4_portfolio-black_litterman-py-build_bl-22"></a>
#### `build_bl`

<!-- source-symbol: m4_portfolio/black_litterman.py:22:build_bl -->
[black_litterman.py](../../backend/analysis/m4_portfolio/black_litterman.py#L22)

```python
def build_bl(mm: dict[str, Any], base: dict[str, Any], view_sets: list[dict[str, Any]], req: dict[str, Any], intent: dict[str, Any], desc: Descriptor, settings: AnalysisSettings, *, id_prefix: str='bl', name_prefix: str='BL 타겟') -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]: ...
```

시장모형·기준 비중·의견 세트를 받아 세트별 BL 사후 추정과 효용 최적화를 수행합니다. 티커별 비중·현금·기준 대비 변화·반영 의견·사후 수익·제약 내역을 Portfolio로 검증해 반환합니다. 반환은 포트폴리오 목록·경고 목록·파라미터 사전이며 현재 직접 warnings 목록에 추가하는 코드는 없고 최적화 실패 신호는 active_constraints에 남습니다.

직접 연결: [sector_lists](#m4_portfolio-market_model-py-sector_lists-26), [build_PQ](#m4_portfolio-math-py-build_PQ-148), [black_litterman](#m4_portfolio-math-py-black_litterman-163), [optimize_utility](#m4_portfolio-math-py-optimize_utility-176), [view_summary](#m4_portfolio-black_litterman-py-view_summary-16), [Portfolio](schemas_구현보고서.md#schemas-portfolio-py-Portfolio-42), [ex_ante_stats](#m4_portfolio-math-py-ex_ante_stats-203), [sector_weights](#m4_portfolio-math-py-sector_weights-211), [build_bl.label](#m4_portfolio-black_litterman-py-build_bl-label-48).

호출하는 코드: [construct](#m4_portfolio-construct-py-construct-59).


<a id="m4_portfolio-black_litterman-py-build_bl-label-48"></a>
#### `build_bl.label`

<!-- source-symbol: m4_portfolio/black_litterman.py:48:build_bl.label -->
[black_litterman.py](../../backend/analysis/m4_portfolio/black_litterman.py#L48)

```python
def label(x: str) -> str: ...
```

최적화의 upper/lower 인덱스를 실제 티커의 이동·종목 상한 라벨로 바꾸고 섹터 코드를 표시명으로 변환합니다.

호출하는 코드: [build_bl](#m4_portfolio-black_litterman-py-build_bl-22).


<a id="file-m4_portfolio-construct-py"></a>
### m4_portfolio/construct.py


<a id="m4_portfolio-construct-py-ConstructResult-tickers-39"></a>
#### `ConstructResult.tickers`

<!-- source-symbol: m4_portfolio/construct.py:39:ConstructResult.tickers -->
[construct.py](../../backend/analysis/m4_portfolio/construct.py#L39)

```python
def tickers(self) -> list[str]: ...
```

시장모형에서 실제 사용한 티커 목록을 반환합니다. 이력 부족으로 요청 목록보다 줄어들 수 있습니다.

선언·진입 조건: `property`.


<a id="m4_portfolio-construct-py-ConstructResult-baseline-43"></a>
#### `ConstructResult.baseline`

<!-- source-symbol: m4_portfolio/construct.py:43:ConstructResult.baseline -->
[construct.py](../../backend/analysis/m4_portfolio/construct.py#L43)

```python
def baseline(self) -> dict[str, Any]: ...
```

chosen_baseline ID에 해당하는 기준 포트폴리오 사전을 찾아 반환합니다. 해당 항목이 없으면 next 검색이 실패합니다.

선언·진입 조건: `property`.


<a id="m4_portfolio-construct-py-ConstructResult-baseline_weights-47"></a>
#### `ConstructResult.baseline_weights`

<!-- source-symbol: m4_portfolio/construct.py:47:ConstructResult.baseline_weights -->
[construct.py](../../backend/analysis/m4_portfolio/construct.py#L47)

```python
def baseline_weights(self) -> dict[str, float]: ...
```

기준 포트폴리오의 weights를 복사해 반환합니다.

선언·진입 조건: `property`.


<a id="m4_portfolio-construct-py-ConstructResult-chosen_weights-51"></a>
#### `ConstructResult.chosen_weights`

<!-- source-symbol: m4_portfolio/construct.py:51:ConstructResult.chosen_weights -->
[construct.py](../../backend/analysis/m4_portfolio/construct.py#L51)

```python
def chosen_weights(self) -> dict[str, float]: ...
```

BL 포트폴리오가 있으면 첫 세트의 비중, 없으면 기준 비중을 복사해 반환합니다. 과거 성과 순위를 다시 매기는 함수는 아닙니다.

선언·진입 조건: `property`.


<a id="m4_portfolio-construct-py-ConstructResult-evidence_summary-55"></a>
#### `ConstructResult.evidence_summary`

<!-- source-symbol: m4_portfolio/construct.py:55:ConstructResult.evidence_summary -->
[construct.py](../../backend/analysis/m4_portfolio/construct.py#L55)

```python
def evidence_summary(self) -> dict[str, Any] | None: ...
```

근거 창이 있으면 요약 사전, 없으면 None을 반환합니다.


<a id="m4_portfolio-construct-py-construct-59"></a>
#### `construct`

<!-- source-symbol: m4_portfolio/construct.py:59:construct -->
[construct.py](../../backend/analysis/m4_portfolio/construct.py#L59)

```python
def construct(view: MarketDataView, tickers: list[str], req: dict[str, Any], intent: dict[str, Any], settings: AnalysisSettings, llm: LlmClient, desc: Descriptor, *, mode: Mode, n_view_sets: int | None=None, views_per_set: int | None=None, stage_tag: str | None=None, id_prefix: str='bl', name_prefix: str='BL 타겟') -> ConstructResult: ...
```

날짜 view와 고정 티커·요청·의도·설정으로 시장모형과 네 기준 비중을 만듭니다. mode에 따라 시작/현재는 기본 5세트, 리밸런싱/모의투자는 기본 1세트 의견을 요청합니다. 뉴스 반영 꺼짐·근거 종목 부족·유효 의견 없음이면 이유를 기록해 기준 비중으로 대체합니다. 그 외 검증한 의견을 BL에 반영한 ConstructResult를 반환합니다. 종목 재선정은 이 함수 밖의 책임이며 일반 계산 오류를 전부 fallback으로 흡수하지는 않습니다.

직접 연결: [build_market_model](#m4_portfolio-market_model-py-build_market_model-35), [ConstructResult](#m4_portfolio-construct-py-ConstructResult-25), [generate_views](#m4_portfolio-views-py-generate_views-36), [build_bl](#m4_portfolio-black_litterman-py-build_bl-22).

호출하는 코드: [st_targets](executor_구현보고서.md#executor-stages-py-st_targets-146), [st_walkforward.per_date](executor_구현보고서.md#executor-stages-py-st_walkforward-per_date-193), [st_forward](executor_구현보고서.md#executor-stages-py-st_forward-229), [PaperService._construct_weights](m6_tracking_구현보고서.md#m6_tracking-paper-py-PaperService-_construct_weights-231).


<a id="file-m4_portfolio-market_model-py"></a>
### m4_portfolio/market_model.py


<a id="m4_portfolio-market_model-py-drawdown_delta_multiplier-18"></a>
#### `drawdown_delta_multiplier`

<!-- source-symbol: m4_portfolio/market_model.py:18:drawdown_delta_multiplier -->
[market_model.py](../../backend/analysis/m4_portfolio/market_model.py#L18)

```python
def drawdown_delta_multiplier(dd_tol: float, ps) -> float: ...
```

기준 허용 낙폭/입력 허용 낙폭 비율을 설정 범위로 제한한 위험회피 배수를 반환합니다. 0 이하 또는 비어 있는 입력이면 1이며 기본 예시는 20%=1, 10%=1.5, 40%=0.75입니다.

호출하는 코드: [build_market_model](#m4_portfolio-market_model-py-build_market_model-35).


<a id="m4_portfolio-market_model-py-sector_lists-26"></a>
#### `sector_lists`

<!-- source-symbol: m4_portfolio/market_model.py:26:sector_lists -->
[market_model.py](../../backend/analysis/m4_portfolio/market_model.py#L26)

```python
def sector_lists(desc: Descriptor, tickers: list[str]) -> tuple[list[str], list[str]]: ...
```

티커 순서에 맞춘 섹터 코드 배열과 이름 배열을 반환합니다. 사전이 없으면 unknown/Unknown을 사용합니다.

직접 연결: [gics_model](m2_data_구현보고서.md#m2_data-descriptor-py-gics_model-64).

호출하는 코드: [build_bl](#m4_portfolio-black_litterman-py-build_bl-22), [build_market_model](#m4_portfolio-market_model-py-build_market_model-35).


<a id="m4_portfolio-market_model-py-build_market_model-35"></a>
#### `build_market_model`

<!-- source-symbol: m4_portfolio/market_model.py:35:build_market_model -->
[market_model.py](../../backend/analysis/m4_portfolio/market_model.py#L35)

```python
def build_market_model(view: MarketDataView, tickers: list[str], req: dict[str, Any], desc: Descriptor, settings: AnalysisSettings, *, request_id: str | None=None, benchmark: str | None=None) -> tuple[dict[str, Any], dict[str, Any]]: ...
```

구성일 이전 USD 가격으로 공분산을 추정하고 규모 비중·성향별 위험회피·낙폭 배수를 계산합니다. 상한의 배분 용량이 부족하면 투자 합계를 낮춰 현금을 남기고 네 템플릿을 만듭니다. 사용자가 고른 기준 비중으로 내재수익을 역산한 MarketModel과 BaselinePortfolios 사전을 반환합니다. 추정 실패는 상위로 전달됩니다.

직접 연결: [estimate_market_model](#m4_portfolio-math-py-estimate_market_model-16), [sector_lists](#m4_portfolio-market_model-py-sector_lists-26), [cap_weights](#m4_portfolio-math-py-cap_weights-48), [drawdown_delta_multiplier](#m4_portfolio-market_model-py-drawdown_delta_multiplier-18), [market_implied_delta](#m4_portfolio-math-py-market_implied_delta-58), [weight_capacity](#m4_portfolio-math-py-weight_capacity-114), [template_weights](#m4_portfolio-math-py-template_weights-132), [implied_returns](#m4_portfolio-math-py-implied_returns-54), [ex_ante_stats](#m4_portfolio-math-py-ex_ante_stats-203), [sector_weights](#m4_portfolio-math-py-sector_weights-211), [build_market_model.label](#m4_portfolio-market_model-py-build_market_model-label-89), [MarketModel](schemas_구현보고서.md#schemas-portfolio-py-MarketModel-11), [BaselinePortfolios](schemas_구현보고서.md#schemas-portfolio-py-BaselinePortfolios-71).

호출하는 코드: [construct](#m4_portfolio-construct-py-construct-59).


<a id="m4_portfolio-market_model-py-build_market_model-label-89"></a>
#### `build_market_model.label`

<!-- source-symbol: m4_portfolio/market_model.py:89:build_market_model.label -->
[market_model.py](../../backend/analysis/m4_portfolio/market_model.py#L89)

```python
def label(c: str) -> str: ...
```

수치 배열 위치로 표현된 종목 상한·최소 비중 라벨을 실제 티커로 바꾸고 섹터 코드를 이름으로 변환합니다. 해석 가능한 제약 적용 내역을 만드는 지역 함수입니다.

호출하는 코드: [build_market_model](#m4_portfolio-market_model-py-build_market_model-35).


<a id="file-m4_portfolio-math-py"></a>
### m4_portfolio/math.py


<a id="m4_portfolio-math-py-estimate_market_model-16"></a>
#### `estimate_market_model`

<!-- source-symbol: m4_portfolio/math.py:16:estimate_market_model -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L16)

```python
def estimate_market_model(px: pd.DataFrame, tickers: list[str], *, lookback_days: int, min_history_days: int, shrinkage: str) -> dict[str, Any]: ...
```

최근 lookback_days+1 가격에서 로그수익률을 만들고 최소 관측 이력을 만족하는 종목을 남깁니다. 완전 관측 행으로 Ledoit–Wolf 또는 표본 공분산을 계산해 252배 연율화하고 변동성·상관·추정 창·제외 목록을 반환합니다. 종목 2개 또는 최소 거래일 수를 확보하지 못하면 ValueError입니다.

호출하는 코드: [build_market_model](#m4_portfolio-market_model-py-build_market_model-35).

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m4_portfolio-math-py-cap_weights-48"></a>
#### `cap_weights`

<!-- source-symbol: m4_portfolio/math.py:48:cap_weights -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L48)

```python
def cap_weights(tickers: list[str], market_cap_usd: dict[str, float]) -> np.ndarray: ...
```

종목별 시가총액을 배열로 만들고 합계로 정규화합니다. 누락은 0으로 보며 전체 합계가 0이면 동일비중을 반환합니다.

호출하는 코드: [build_market_model](#m4_portfolio-market_model-py-build_market_model-35).


<a id="m4_portfolio-math-py-implied_returns-54"></a>
#### `implied_returns`

<!-- source-symbol: m4_portfolio/math.py:54:implied_returns -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L54)

```python
def implied_returns(cov: np.ndarray, w: np.ndarray, delta: float) -> np.ndarray: ...
```

공분산 Σ, 기준 비중 w, 위험회피 δ로 π=δΣw를 계산합니다. 기준 비중에 들어 있는 균형 기대수익을 역으로 구하는 과정입니다.

호출하는 코드: [build_market_model](#m4_portfolio-market_model-py-build_market_model-35).


<a id="m4_portfolio-math-py-market_implied_delta-58"></a>
#### `market_implied_delta`

<!-- source-symbol: m4_portfolio/math.py:58:market_implied_delta -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L58)

```python
def market_implied_delta(bench_px: pd.Series, *, lookback_days: int, rf: float) -> tuple[float, dict[str, Any]]: ...
```

기준일 이전 비교지수 로그수익률로 δ=(평균 일수익률-rf/252)/일수익률 분산을 계산하고 관측 창을 반환합니다. 60개 미만 수익률이면 실패하며 계산값 상하한 적용은 상위 build_market_model이 담당합니다.

호출하는 코드: [build_market_model](#m4_portfolio-market_model-py-build_market_model-35).

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m4_portfolio-math-py-apply_constraints-69"></a>
#### `apply_constraints`

<!-- source-symbol: m4_portfolio/math.py:69:apply_constraints -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L69)

```python
def apply_constraints(w, max_stock, max_sector, sectors, total=1.0, *, max_iter=50, min_weight=0.01): ...
```

초기 비중을 목표 투자 합계에 맞추고 종목 하한·상한·섹터 상한을 반복 적용합니다. 남거나 부족한 금액을 여유 종목에 분배하고 비중·적용 제약 라벨을 반환합니다. 최대 반복 또는 가용 공간 소진 시 멈추므로 모든 입력에서 정확한 합계·제약 충족을 보장하는 일반 해법은 아닙니다.

호출하는 코드: [min_variance](#m4_portfolio-math-py-min_variance-120), [template_weights](#m4_portfolio-math-py-template_weights-132).


<a id="m4_portfolio-math-py-_sector_constraints-103"></a>
#### `_sector_constraints`

<!-- source-symbol: m4_portfolio/math.py:103:_sector_constraints -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L103)

```python
def _sector_constraints(sectors, max_sector, total): ...
```

섹터 상한을 SLSQP 부등식 콜백 목록으로 만듭니다. 상한이 전체 투자 비율 이상이면 불필요한 제약을 생략합니다. 각 람다의 m 기본 인자는 해당 섹터 마스크를 고정합니다.

호출하는 코드: [min_variance](#m4_portfolio-math-py-min_variance-120), [optimize_utility](#m4_portfolio-math-py-optimize_utility-176).


<a id="m4_portfolio-math-py-weight_capacity-114"></a>
#### `weight_capacity`

<!-- source-symbol: m4_portfolio/math.py:114:weight_capacity -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L114)

```python
def weight_capacity(sectors, max_stock, max_sector) -> float: ...
```

섹터별 min(포함 종목 수×종목 상한, 섹터 상한)을 더해 수용 가능한 최대 주식 비중을 반환합니다.

호출하는 코드: [build_market_model](#m4_portfolio-market_model-py-build_market_model-35).


<a id="m4_portfolio-math-py-min_variance-120"></a>
#### `min_variance`

<!-- source-symbol: m4_portfolio/math.py:120:min_variance -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L120)

```python
def min_variance(cov, max_stock, max_sector, sectors, total=1.0, *, min_weight=0.01): ...
```

SLSQP로 목표 합계·종목 범위·섹터 상한 아래 분산 wᵀΣw를 최소화합니다. 최적화 실패 시 1/분산 초기 비중에 반복 제약을 적용한 근사안과 fallback 라벨을 반환합니다.

직접 연결: [_sector_constraints](#m4_portfolio-math-py-_sector_constraints-103), [apply_constraints](#m4_portfolio-math-py-apply_constraints-69).

호출하는 코드: [template_weights](#m4_portfolio-math-py-template_weights-132).


<a id="m4_portfolio-math-py-template_weights-132"></a>
#### `template_weights`

<!-- source-symbol: m4_portfolio/math.py:132:template_weights -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L132)

```python
def template_weights(template, cov, ann_vol, capw, max_stock, max_sector, sectors, total=1.0, *, min_weight=0.01, max_iter=50): ...
```

동일비중·시총비중·역변동성의 초기 배열을 만들거나 최소분산 최적화를 호출합니다. 나머지 템플릿은 공통 제약 적용 후 비중·라벨을 반환하고 미지원 이름은 ValueError입니다.

직접 연결: [min_variance](#m4_portfolio-math-py-min_variance-120), [apply_constraints](#m4_portfolio-math-py-apply_constraints-69).

호출하는 코드: [build_market_model](#m4_portfolio-market_model-py-build_market_model-35).

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m4_portfolio-math-py-build_PQ-148"></a>
#### `build_PQ`

<!-- source-symbol: m4_portfolio/math.py:148:build_PQ -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L148)

```python
def build_PQ(views, tickers): ...
```

의견별 long 종목에 +1/long수, short 종목에 -1/short수를 넣어 행렬 P를 만들고 기대수익 Q·신뢰도 C를 반환합니다. short는 상대 비교식의 음수 항이며 실제 공매도 주문 지시가 아닙니다.

호출하는 코드: [build_bl](#m4_portfolio-black_litterman-py-build_bl-22).


<a id="m4_portfolio-math-py-black_litterman-163"></a>
#### `black_litterman`

<!-- source-symbol: m4_portfolio/math.py:163:black_litterman -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L163)

```python
def black_litterman(cov, pi, P, Q, conf, tau): ...
```

사전 수익 π와 의견 P·Q·신뢰도를 결합해 사후 기대수익·공분산을 반환합니다. 신뢰도를 He–Litterman 방식의 불확실성 Ω로 바꾸고 행렬 역산을 사용합니다. 의견이 없으면 원래 π·공분산 복사본이며 특이 행렬 예외를 별도 대체 처리하지 않습니다.

호출하는 코드: [build_bl](#m4_portfolio-black_litterman-py-build_bl-22).


<a id="m4_portfolio-math-py-optimize_utility-176"></a>
#### `optimize_utility`

<!-- source-symbol: m4_portfolio/math.py:176:optimize_utility -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L176)

```python
def optimize_utility(mu, cov, delta, w_base, max_stock, max_sector, sectors, max_tilt, total=1.0, *, min_weight=0.01): ...
```

사후 기대수익과 공분산으로 기대효용 wᵀμ-δwᵀΣw/2를 최대화합니다. 투자 합계·최소 비중·종목/섹터 상한·기준 대비 최대 이동을 제약하고 실패하면 정규화한 기준 비중과 optimizer_failed_no_tilt 라벨을 반환합니다.

직접 연결: [_sector_constraints](#m4_portfolio-math-py-_sector_constraints-103).

호출하는 코드: [build_bl](#m4_portfolio-black_litterman-py-build_bl-22).


<a id="m4_portfolio-math-py-ex_ante_stats-203"></a>
#### `ex_ante_stats`

<!-- source-symbol: m4_portfolio/math.py:203:ex_ante_stats -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L203)

```python
def ex_ante_stats(w, mu, cov) -> dict[str, float]: ...
```

비중과 기대수익·공분산으로 기대수익, 예상 변동성, 기대수익/변동성 비율, 유효 종목 수 1/Σw²를 계산합니다. 이 sharpe는 백테스트의 무위험수익률 차감 Sharpe와 정의가 다릅니다.

호출하는 코드: [build_bl](#m4_portfolio-black_litterman-py-build_bl-22), [build_market_model](#m4_portfolio-market_model-py-build_market_model-35).


<a id="m4_portfolio-math-py-sector_weights-211"></a>
#### `sector_weights`

<!-- source-symbol: m4_portfolio/math.py:211:sector_weights -->
[math.py](../../backend/analysis/m4_portfolio/math.py#L211)

```python
def sector_weights(w, sector_names) -> dict[str, float]: ...
```

종목별 비중을 같은 위치의 섹터 이름으로 묶어 합산한 사전을 반환합니다.

호출하는 코드: [build_bl](#m4_portfolio-black_litterman-py-build_bl-22), [build_market_model](#m4_portfolio-market_model-py-build_market_model-35).


<a id="file-m4_portfolio-spec-py"></a>
### m4_portfolio/spec.py


<a id="m4_portfolio-spec-py-benchmarks_for-29"></a>
#### `benchmarks_for`

<!-- source-symbol: m4_portfolio/spec.py:29:benchmarks_for -->
[spec.py](../../backend/analysis/m4_portfolio/spec.py#L29)

```python
def benchmarks_for(req: dict[str, Any], tickers: list[str], md: MarketData, settings: AnalysisSettings) -> tuple[str, list[str]]: ...
```

요청 비교지수와 설정 보조 지수를 고르고 한국 종목이 있으면 한국 비교지수를 추가합니다. 주 비교지수와 보조 목록을 반환합니다.

호출하는 코드: [build_backtest_spec](#m4_portfolio-spec-py-build_backtest_spec-37).


<a id="m4_portfolio-spec-py-build_backtest_spec-37"></a>
#### `build_backtest_spec`

<!-- source-symbol: m4_portfolio/spec.py:37:build_backtest_spec -->
[spec.py](../../backend/analysis/m4_portfolio/spec.py#L37)

```python
def build_backtest_spec(md: MarketData, req: dict[str, Any], intent: dict[str, Any], tagging: Tagging, selection: Selection, desc: Descriptor, settings: AnalysisSettings, *, bt_req: BacktestRequest | None=None, allow_fewer_at_start: bool=False) -> tuple[dict[str, Any], dict[str, Any]]: ...
```

자료 범위와 실제 거래일 달력으로 백테스트 시작·끝을 정합니다. 기본 경로는 시작일 view로 후보·지표를 다시 계산하되 현재 분류 통과 집합을 재사용합니다. 과거 종목 부족 시 허용 정책에 따라 약 한 달씩 최대 36회 시작을 이동하고 최소 1년·원래 창의 절반을 남깁니다. 시작일이 확정되면 그날 환율로 초기자본·고정 USD 적립을 다시 환산하고 BacktestSpec과 재선정 산출물을 반환합니다. 재선정 비활성 경로는 현재 목록의 생존 종목을 과거에 적용하며 선견 경고를 남깁니다.

직접 연결: [BacktestRequest](schemas_구현보고서.md#schemas-backtest-py-BacktestRequest-49), [retrieve](m3_selection_구현보고서.md#m3_selection-retrieve-py-retrieve-70), [screen](m3_selection_구현보고서.md#m3_selection-screen-py-screen-22), [benchmarks_for](#m4_portfolio-spec-py-benchmarks_for-29), [BacktestSpec](schemas_구현보고서.md#schemas-backtest-py-BacktestSpec-96).

호출하는 코드: [st_backtest_spec](executor_구현보고서.md#executor-stages-py-st_backtest_spec-132).

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="file-m4_portfolio-views-py"></a>
### m4_portfolio/views.py


<a id="m4_portfolio-views-py-trailing_12m_return-22"></a>
#### `trailing_12m_return`

<!-- source-symbol: m4_portfolio/views.py:22:trailing_12m_return -->
[views.py](../../backend/analysis/m4_portfolio/views.py#L22)

```python
def trailing_12m_return(view: MarketDataView, tickers: list[str]) -> dict[str, float]: ...
```

기준일 전 약 380일 가격을 읽고 첫 가용값 대비 마지막 값 수익률을 반환합니다. 고정 252거래일을 정확히 자르는 지표가 아니라 LLM에 전달하는 보조 수익률이며 자료가 비면 빈 사전입니다.

호출하는 코드: [generate_views](#m4_portfolio-views-py-generate_views-36).


<a id="m4_portfolio-views-py-_check-31"></a>
#### `_check`

<!-- source-symbol: m4_portfolio/views.py:31:_check -->
[views.py](../../backend/analysis/m4_portfolio/views.py#L31)

```python
def _check(a: dict[str, Any]) -> None: ...
```

LLM 의견 응답에 비어 있지 않은 sets 목록이 있는지 검사합니다. 개별 의견의 유효성은 generate_views가 검사·정리합니다.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m4_portfolio-views-py-generate_views-36"></a>
#### `generate_views`

<!-- source-symbol: m4_portfolio/views.py:36:generate_views -->
[views.py](../../backend/analysis/m4_portfolio/views.py#L36)

```python
def generate_views(view: MarketDataView, tickers: list[str], mm: dict[str, Any], base_weights: dict[str, float], intent: dict[str, Any], desc: Descriptor, settings: AnalysisSettings, llm: LlmClient, evidence: EvidenceWindow, *, n_sets: int, views_per_set: int, stage_tag: str=STAGE) -> tuple[list[dict[str, Any]], list[str]]: ...
```

종목·시장모형·기준 비중·최근 수익과 뉴스·공시를 프롬프트에 담아 의견을 받습니다. 알 수 없는 종목·잘못된 long/short 구조·중복·근거 없는 의견을 제거하고 신뢰도·수익률 범위를 제한합니다. 인용 ID로 evidence_type을 다시 계산하며 공시만 인용하면 신뢰도 상한 0.25를 적용합니다. 세트당 의견 수를 제한한 세트·경고를 반환합니다. 세트 수 불일치는 경고만 남기고 요청 세트 수로 항상 자르지는 않습니다.

직접 연결: [trailing_12m_return](#m4_portfolio-views-py-trailing_12m_return-22), [gics_model](m2_data_구현보고서.md#m2_data-descriptor-py-gics_model-64), [load_prompts](common_구현보고서.md#common-prompts-py-load_prompts-17), [messages_from_prompts](common_구현보고서.md#common-llm-py-messages_from_prompts-54).

호출하는 코드: [construct](#m4_portfolio-construct-py-construct-59).


<a id="interactions"></a>
## 6. 다른 모듈과의 상호작용

| 호출 위치 | mode·사용 목록 | 주요 소비 |
| --- | --- | --- |
| 실행기 st_targets | start·과거 시작 선정 | 08 모형·기준안, 09 의견, 10 타겟 |
| 실행기 st_walkforward | rebalance·과거 고정 종목 | 10w 날짜별 비중 경로 |
| 실행기 st_forward | current·현재 선정 | 10f 현재 배분 |
| M6 _construct_weights | paper·모의투자 고정 종목 | 신규 시작·정기 리밸런싱 |

입력 view·회사 산업·뉴스/공시는 [M2](m2_data_구현보고서.md), 시작 재선정 로직은 [M3](m3_selection_구현보고서.md)에서 가져옵니다. 출력 모델은 [schemas](schemas_구현보고서.md)이고 [M5](m5_backtest_report_구현보고서.md)가 목표 비중을 bt로 체결합니다. 순수 수학 함수는 numpy/scipy, 공분산 수축은 sklearn LedoitWolf를 사용하며 자체 DB·LLM 접근은 하지 않습니다.

<a id="verification"></a>
## 7. 오류·제약과 검증 근거

시장모형의 최소 종목·이력 조건 실패, 특이 행렬 등은 예외가 될 수 있습니다. 반복 비중 제약·SLSQP 대체안은 모든 입력에서 최적성을 보장하지 않으며 이후 모델·백테스트 검사를 함께 적용합니다. BL 의견이 없거나 유효하지 않으면 기준 비중으로 대체하고 최적화 실패는 별도 라벨·경고를 남깁니다.

가격 추정은 t-1 마감을 지키지만 시작 재선정에 현재 분류 통과 집합과 고정 사전을 사용합니다. `n_sets`와 응답 세트 수가 다를 때 일부 경로는 경고만 남깁니다. 예상 Sharpe와 실현 백테스트 Sharpe는 정의가 다르므로 숫자를 직접 같은 통계처럼 비교하지 않습니다.

### 관련 테스트

아래는 테스트 소스에서 확인한 검증 시나리오입니다. 이번 문서 작성에서는 금융 DB·유료 LLM·시나리오 워커를 실행하지 않았으며, 테스트 통과를 새로 보증하는 기록으로 사용하지 않습니다.

- [test_pipeline_e2e.py](../../backend/tests/analysis/test_pipeline_e2e.py): 비중 합계·상한·최대 이동·근거 부족 대체·현재 구성.
- [test_round5_validation.py](../../backend/tests/analysis/test_round5_validation.py): 허용 낙폭에 따른 위험회피 배수.
- [test_foundations.py](../../backend/tests/analysis/test_foundations.py): 공시 근거 허용과 공시 단독 신뢰도 제한.

### 문서 검증

구문 분석 정의 목록과 대조하여 이 보고서의 클래스 1개와 함수/메서드 32개를 모두 설명했습니다. 상대경로 링크와 내부 앵커를 별도로 확인합니다.

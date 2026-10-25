# m2_data 구현보고서

[전체 안내](README.md)

> 작성 기준: 2026-10-25 작업 공간의 실제 소스. 기존 설계 문서는 배경 참고용이며 아래 동작 설명은 구현을 기준으로 합니다.

대상: Python 파일 7개 · 클래스 5개 · 함수/메서드 73개(중첩 함수와 비공개 보조 함수 포함).

[역할](#role) · [파일 구성](#files) · [처리 흐름](#flow) · [클래스](#classes) · [함수](#functions) · [모듈 연계](#interactions) · [오류·검증](#verification)

<a id="role"></a>
## 1. 모듈의 역할과 용어

`m2_data`는 다른 분석 모듈에 시장 자료와 인용 가능한 근거를 제공합니다. 시장 자료는 팀 DB의 가격·환율·가치평가·종목 마스터·구성종목·뉴스·공시에서 읽고, 종목 검색 사전은 사전에 생성한 버전 JSON에서 읽습니다. 분석 중 외부 금융 서비스나 웹 검색으로 결측을 보충하는 경로는 없습니다.

`as_of`는 이번 판단의 정보 기준일입니다. MarketData는 실행 전체가 공유하는 원본 캐시, MarketDataView는 이를 특정 날짜로 제한한 조회 창구입니다. 추정용 정보는 보통 기준일 전날까지, 체결용 가격은 기준일 종가까지입니다. Descriptor는 회사·산업·키워드를 모은 종목 검색 사전입니다.

가격·성과 계산 통화는 USD입니다. 한국 원화 가격은 해당 날짜 환율로 환산합니다. 지표 Fact와 EvidenceWindow의 ID는 선정 이유와 리포트 출처를 실제 자료에 연결합니다.

<a id="files"></a>
## 2. 파일 구성과 책임

| 파일 | 책임 | 문서 내 해설 |
| --- | --- | --- |
| [m2_data/__init__.py](../../backend/analysis/m2_data/__init__.py) | MarketData·MarketDataView 공개 재노출 | 정의 없음 |
| [m2_data/descriptor.py](../../backend/analysis/m2_data/descriptor.py) | 기준일 사전 선택·산업 트리·GICS 변환 | [클래스 0 · 함수 10](#file-m2_data-descriptor-py) |
| [m2_data/disclosure_labels.py](../../backend/analysis/m2_data/disclosure_labels.py) | 공시 사건 한국어 라벨·출처별 표시 제목 | [클래스 0 · 함수 2](#file-m2_data-disclosure_labels-py) |
| [m2_data/market_data.py](../../backend/analysis/m2_data/market_data.py) | 공유 가격 캐시·날짜 view·USD 환산·조회·품질 패널 | [클래스 3 · 함수 35](#file-m2_data-market_data-py) |
| [m2_data/metrics.py](../../backend/analysis/m2_data/metrics.py) | 정량 선정 지표와 인용 가능한 Fact | [클래스 1 · 함수 8](#file-m2_data-metrics-py) |
| [m2_data/news.py](../../backend/analysis/m2_data/news.py) | 뉴스/공시 창·충분 판정·인용 메타·프롬프트 표현 | [클래스 1 · 함수 16](#file-m2_data-news-py) |
| [m2_data/quality.py](../../backend/analysis/m2_data/quality.py) | 외부 품질 판정의 분석 오류 변환·요약 | [클래스 0 · 함수 2](#file-m2_data-quality-py) |

<a id="flow"></a>
## 3. 처리 흐름과 예시

1. MarketData가 종목 마스터와 시장별 비교지수의 자료 상한을 읽습니다. 요청 조립은 그 이하의 공통 거래일을 다시 선택합니다.
2. 실행기는 사전 전체 종목·비교지수의 가격과 환율을 한 번에 미리 적재합니다. 각 과거 날짜 view는 같은 캐시에서 자기 정보 마감까지 읽습니다.
3. 추정 조회는 기본 t-1 이전 수정종가를 반환하고, 백테스트·모의투자 체결 패널은 t 종가까지 포함합니다.
4. 실제 거래일 합집합에서 한 시장의 휴장일은 그 시장의 직전 종가로 채웁니다. 자기 시장 거래일 누락은 품질 검사에 남깁니다.
5. 품질 통과 가격으로 지표를 만들고 값마다 fin ID를 붙입니다. 뉴스와 공시에는 ev/dc ID를 붙여 구성·설명의 근거로 전달합니다.

예를 들어 한국 종목 가격 130,000원과 해당일 USDKRW 1,300이면 USD 가격은 100입니다. 수익률에는 주가 변화와 환율 변화가 함께 반영됩니다. 초기 투자금 환산은 백테스트 첫 구성일 환율, 현재 배분은 분석 기준일 환율을 사용합니다.

| 기준 | 코드 동작 |
| --- | --- |
| 가격 커버리지 | 값 있는 기대 거래일/전체 기대 거래일 ≥ 기본 0.95 |
| 실제 결측 | 기본 1일만 직전값 채움, 긴 연속 결측·첫값 부재·품질 미달은 제외 |
| 필수 가격 | 비교지수·모의투자 보유 필수 종목 탈락은 DataMissing |
| 가치평가 | 조회 마감일 이하 최신 행, 기본 10달력일 이상 오래되면 제외 |
| 뉴스 의견 창 | 기본 [구성일-14일, 구성일), UTC 발행시각 기준 |
| 공시 의견 창 | 기본 [구성일-45일, 구성일), available_on 기준 |
| 공시 기업 요약 | 호출자가 기본 90일과 정기 보고 허용 종류를 지정 |
| 근거 충분 여부 | 뉴스/설정상 공시가 있는 종목 기본 3개 이상 |

공시에는 본문이 없고 사건 종류·제목·접수일·이용 가능일만 있습니다. 실적 발표 공시가 있다는 사실만으로 좋은 실적이나 상승 원인을 확인한 것은 아닙니다. 뉴스도 헤드라인 메타를 사용합니다.

검색 사전 버전은 실행 시작에 고정합니다. 과거보다 앞선 파일이 없으면 가장 오래된 파일을 경고와 함께 쓰며 완전한 당시 유니버스를 복원하지 못합니다. Repository.constituents_at도 유사한 대체 정책을 갖지만 주 분석 경로는 고정 Descriptor 검색을 사용합니다.


<a id="classes"></a>
## 4. 클래스 상세

필드 표는 해당 클래스에서 직접 선언한 필드입니다. 상속 필드는 부모 클래스 설명을 함께 읽습니다. `Field(...)`의 범위는 선언된 검증이며, 서비스에서 추가하는 조건은 함수 설명에 구분합니다.

<a id="m2_data-market_data-py-_Cache-44"></a>
### `_Cache`

<!-- source-symbol: m2_data/market_data.py:44:_Cache -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L44)

MarketData 내부의 가격·환율·가치평가·뉴스 캐시입니다. 적재 기간과 요청한 티커 집합, 첫 가격일·적재 횟수를 별도로 저장하여 자료 없는 티커의 반복 재조회도 막습니다.

기반: `명시적 부모 없음` · 선언: `dataclass`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `bars` | `pd.DataFrame \| None` | `None` | long 형식 가격 표 |
| `bars_range` | `tuple[dt.date, dt.date] \| None` | `None` | 캐시에 적재한 가격 기간 |
| `tickers_loaded` | `set[str]` | `생성 함수: set` | 조회 요청한 종목; 자료 없는 종목도 포함 |
| `first_date` | `dict[str, dt.date]` | `생성 함수: dict` | 적재 범위 안의 종목별 첫 가격일 |
| `n_loads` | `int` | `0` | 가격 전체 적재 횟수 |
| `fx` | `pd.Series \| None` | `None` | 원본 USDKRW 시계열 |
| `fx_range` | `tuple[dt.date, dt.date] \| None` | `None` | 적재 환율 기간 |
| `valuation` | `dict[tuple[dt.date, frozenset[str]], pd.DataFrame]` | `생성 함수: dict` | 마감일·종목 집합별 가치평가 캐시 |
| `news` | `dict[tuple, EvidenceWindow]` | `생성 함수: dict` | 조건별 뉴스·공시 창 캐시 |


<a id="m2_data-market_data-py-MarketData-56"></a>
### `MarketData`

<!-- source-symbol: m2_data/market_data.py:56:MarketData -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L56)

Repository 위의 시장 자료 조회·캐시 계층입니다. repo·s·assets·_c·_lock·ceiling을 보관하고 여러 기준일 view가 같은 원본 적재를 공유하게 합니다.

기반: `명시적 부모 없음`.

메서드·속성: [__init__](#m2_data-market_data-py-MarketData-__init__-57), [benchmark_of](#m2_data-market_data-py-MarketData-benchmark_of-68), [benchmarks](#m2_data-market_data-py-MarketData-benchmarks-71), [asset_id](#m2_data-market_data-py-MarketData-asset_id-74), [market_of](#m2_data-market_data-py-MarketData-market_of-80), [currency_of](#m2_data-market_data-py-MarketData-currency_of-84), [name_of](#m2_data-market_data-py-MarketData-name_of-88), [latest_trading_day](#m2_data-market_data-py-MarketData-latest_trading_day-92), [common_trading_day_on_or_before](#m2_data-market_data-py-MarketData-common_trading_day_on_or_before-101), [data_range](#m2_data-market_data-py-MarketData-data_range-115), [prefetch](#m2_data-market_data-py-MarketData-prefetch-126), [_prefetch](#m2_data-market_data-py-MarketData-_prefetch-131), [_ensure](#m2_data-market_data-py-MarketData-_ensure-153), [bars](#m2_data-market_data-py-MarketData-bars-166), [fx_series](#m2_data-market_data-py-MarketData-fx_series-174), [view](#m2_data-market_data-py-MarketData-view-187).


<a id="m2_data-market_data-py-MarketDataView-193"></a>
### `MarketDataView`

<!-- source-symbol: m2_data/market_data.py:193:MarketDataView -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L193)

공유 MarketData를 특정 as_of로 자른 조회 객체입니다. 가격·환율·재무·근거 조회가 정보 마감을 넘지 않도록 하며 추정용 전날까지와 체결용 당일 종가를 구분합니다. 금융 데이터의 완전한 과거 재구성을 자동 보증하는 것은 아닙니다.

기반: `명시적 부모 없음`.

메서드·속성: [__init__](#m2_data-market_data-py-MarketDataView-__init__-196), [_check](#m2_data-market_data-py-MarketDataView-_check-202), [_end](#m2_data-market_data-py-MarketDataView-_end-211), [_markets](#m2_data-market_data-py-MarketDataView-_markets-217), [trading_days](#m2_data-market_data-py-MarketDataView-trading_days-222), [adj_close](#m2_data-market_data-py-MarketDataView-adj_close-232), [_to_usd](#m2_data-market_data-py-MarketDataView-_to_usd-262), [close_volume](#m2_data-market_data-py-MarketDataView-close_volume-271), [first_dates](#m2_data-market_data-py-MarketDataView-first_dates-284), [panel](#m2_data-market_data-py-MarketDataView-panel-291), [_carry_market_holidays](#m2_data-market_data-py-MarketDataView-_carry_market_holidays-310), [fx_on_or_before](#m2_data-market_data-py-MarketDataView-fx_on_or_before-328), [fx_series](#m2_data-market_data-py-MarketDataView-fx_series-335), [valuation](#m2_data-market_data-py-MarketDataView-valuation-339), [shares_outstanding](#m2_data-market_data-py-MarketDataView-shares_outstanding-379), [market_cap_usd](#m2_data-market_data-py-MarketDataView-market_cap_usd-383), [news_window](#m2_data-market_data-py-MarketDataView-news_window-388), [constituents](#m2_data-market_data-py-MarketDataView-constituents-410).


<a id="m2_data-metrics-py-Fact-21"></a>
### `Fact`

<!-- source-symbol: m2_data/metrics.py:21:Fact -->
[metrics.py](../../backend/analysis/m2_data/metrics.py#L21)

지표 한 건의 불변 근거입니다. id·ticker·asset_id·metric·value·unit·as_of·source를 보관해 정량 선정 숫자와 리포트 인용을 연결합니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `id` | `str` | `필수 입력` | 현재 객체의 식별자 |
| `ticker` | `str` | `필수 입력` | 가격 조회 표기의 종목 코드 |
| `asset_id` | `str` | `필수 입력` | DB 종목 마스터 ID |
| `metric` | `str` | `필수 입력` | 정량 지표 코드 |
| `value` | `float` | `필수 입력` | 선택·변경·지표의 실제 값 |
| `unit` | `str` | `필수 입력` | 비율 단위 또는 리밸런싱 단위 |
| `as_of` | `str` | `필수 입력` | 자료 판단 기준일 |
| `source` | `str` | `필수 입력` | 자료·설명·선정의 출처 식별 |

메서드·속성: [to_dict](#m2_data-metrics-py-Fact-to_dict-31).


<a id="m2_data-news-py-EvidenceWindow-20"></a>
### `EvidenceWindow`

<!-- source-symbol: m2_data/news.py:20:EvidenceWindow -->
[news.py](../../backend/analysis/m2_data/news.py#L20)

한 구성일의 뉴스·공시 반개구간 창과 티커별 인용 ID를 담습니다. 뉴스/공시 창 시작이 다를 수 있으며 enough는 건수보다 근거가 있는 종목 수로 판단합니다.

기반: `명시적 부모 없음` · 선언: `dataclass`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `as_of` | `dt.date` | `필수 입력` | 자료 판단 기준일 |
| `start` | `dt.date` | `필수 입력` | 구간 시작 |
| `end` | `dt.date` | `필수 입력` | 구간 끝 |
| `tickers` | `list[str]` | `필수 입력` | 관련 종목 티커 목록 |
| `records` | `list[dict[str, Any]]` | `생성 함수: list` | 뉴스 레코드 |
| `by_ticker` | `dict[str, list[str]]` | `생성 함수: dict` | 티커별 뉴스 인용 ID |
| `min_tickers` | `int` | `3` | 의견 생성에 필요한 근거 종목 수 |
| `disclosures` | `list[dict[str, Any]]` | `생성 함수: list` | 공시 사건 레코드 |
| `by_ticker_dc` | `dict[str, list[str]]` | `생성 함수: dict` | 티커별 공시 인용 ID |
| `dc_start` | `dt.date \| None` | `None` | 공시 조회 창 시작일 |
| `count_disclosures` | `bool` | `True` | 공시만 있는 종목을 근거 수에 포함할지 |

메서드·속성: [n_articles](#m2_data-news-py-EvidenceWindow-n_articles-34), [n_disclosures](#m2_data-news-py-EvidenceWindow-n_disclosures-38), [n_tickers_with_news](#m2_data-news-py-EvidenceWindow-n_tickers_with_news-42), [n_tickers_with_disclosures](#m2_data-news-py-EvidenceWindow-n_tickers_with_disclosures-46), [n_tickers_with_evidence](#m2_data-news-py-EvidenceWindow-n_tickers_with_evidence-50), [has_evidence](#m2_data-news-py-EvidenceWindow-has_evidence-53), [enough](#m2_data-news-py-EvidenceWindow-enough-57), [ids](#m2_data-news-py-EvidenceWindow-ids-62), [all_records](#m2_data-news-py-EvidenceWindow-all_records-66), [summary](#m2_data-news-py-EvidenceWindow-summary-69), [prompt_lines](#m2_data-news-py-EvidenceWindow-prompt_lines-85), [disclosure_lines](#m2_data-news-py-EvidenceWindow-disclosure_lines-98), [event_counts](#m2_data-news-py-EvidenceWindow-event_counts-109), [to_dict](#m2_data-news-py-EvidenceWindow-to_dict-118).


<a id="functions"></a>
## 5. 함수·메서드 상세

시그니처에 입력 자료형·기본값·반환 자료형을 그대로 기재했습니다. `self`는 소속 클래스의 인스턴스, `cls`는 클래스입니다. 반환 주석이 없는 함수는 본문 해설의 반환 내용을 따릅니다. 속성(`property`)은 호출 괄호 없이 읽고, 중첩 함수는 바깥 함수의 지역 상태를 공유합니다. 연결 목록은 정적으로 확인되는 패키지 내부 직접 호출이며, 주입된 서비스·콜백·Repository 호출은 처리 흐름과 해설에서 설명합니다.


<a id="file-m2_data-descriptor-py"></a>
### m2_data/descriptor.py


<a id="m2_data-descriptor-py-load_for-24"></a>
#### `load_for`

<!-- source-symbol: m2_data/descriptor.py:24:load_for -->
[descriptor.py](../../backend/analysis/m2_data/descriptor.py#L24)

```python
def load_for(as_of: date, universes: Iterable[str], markets: Iterable[str]=('US', 'KR'), *, processed_dir: Path | str=PROCESSED, universe_file: str='ALL') -> tuple[Descriptor, dict[str, Any], list[str]]: ...
```

기준일 이하 최신 사전 파일을 선택하고 유니버스·시장·섹터 정보가 있는 종목으로 필터링합니다. Descriptor·버전 정보·경고를 반환하며 DRAFT 분류 종목도 경고와 함께 유지합니다. 과거 파일이 없으면 외부 select_version의 가장 오래된 파일 대체 정책을 따릅니다.

호출하는 코드: [st_request](executor_구현보고서.md#executor-stages-py-st_request-46), [DialogService._turn](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-_turn-275), [PaperService._desc](m6_tracking_구현보고서.md#m6_tracking-paper-py-PaperService-_desc-204).


<a id="m2_data-descriptor-py-code_of-59"></a>
#### `code_of`

<!-- source-symbol: m2_data/descriptor.py:59:code_of -->
[descriptor.py](../../backend/analysis/m2_data/descriptor.py#L59)

```python
def code_of(entry: dict[str, Any], level: str) -> str | None: ...
```

사전 항목에서 지정 GICS 계층의 코드를 읽고 없으면 None을 반환합니다.

호출하는 코드: [retrieve](m3_selection_구현보고서.md#m3_selection-retrieve-py-retrieve-70).


<a id="m2_data-descriptor-py-gics_model-64"></a>
#### `gics_model`

<!-- source-symbol: m2_data/descriptor.py:64:gics_model -->
[descriptor.py](../../backend/analysis/m2_data/descriptor.py#L64)

```python
def gics_model(entry: dict[str, Any]) -> Gics: ...
```

사전의 네 산업 계층을 Gics 모델로 변환합니다. 빠진 계층은 섹터 값으로 채우므로 모든 반환 코드 길이가 해당 계층 길이와 같다고 단정할 수 없습니다.

직접 연결: [Gics](schemas_구현보고서.md#schemas-selection-py-Gics-15), [gics_model.lvl](#m2_data-descriptor-py-gics_model-lvl-67).

호출하는 코드: [retrieve](m3_selection_구현보고서.md#m3_selection-retrieve-py-retrieve-70), [screen.sector_of](m3_selection_구현보고서.md#m3_selection-screen-py-screen-sector_of-71), [sector_lists](m4_portfolio_구현보고서.md#m4_portfolio-market_model-py-sector_lists-26), [generate_views](m4_portfolio_구현보고서.md#m4_portfolio-views-py-generate_views-36), [prepare](m5_backtest_report_구현보고서.md#m5_backtest_report-backtest-py-prepare-155), [build_results](m5_backtest_report_구현보고서.md#m5_backtest_report-collect-py-build_results-42).


<a id="m2_data-descriptor-py-gics_model-lvl-67"></a>
#### `gics_model.lvl`

<!-- source-symbol: m2_data/descriptor.py:67:gics_model.lvl -->
[descriptor.py](../../backend/analysis/m2_data/descriptor.py#L67)

```python
def lvl(name: str) -> GicsLevel: ...
```

지정 계층이 있으면 코드·이름을 만들고 없으면 섹터 코드·이름으로 GicsLevel을 반환합니다. 바깥 gics_model의 g 사전을 읽는 중첩 함수입니다.

직접 연결: [GicsLevel](schemas_구현보고서.md#schemas-selection-py-GicsLevel-10).

호출하는 코드: [gics_model](#m2_data-descriptor-py-gics_model-64).


<a id="m2_data-descriptor-py-render_tree-78"></a>
#### `render_tree`

<!-- source-symbol: m2_data/descriptor.py:78:render_tree -->
[descriptor.py](../../backend/analysis/m2_data/descriptor.py#L78)

```python
def render_tree(desc: Descriptor, max_level: str='sub_industry') -> str: ...
```

현재 사전에 남은 종목을 계층별로 집계해 들여쓴 GICS 코드·산업명·종목 수 문자열을 만듭니다. max_level로 출력 깊이를 제한하며 의도 해석 프롬프트가 사용합니다.

호출하는 코드: [build_messages](m3_selection_구현보고서.md#m3_selection-intent-py-build_messages-66).


<a id="m2_data-descriptor-py-sector_name_to_code-108"></a>
#### `sector_name_to_code`

<!-- source-symbol: m2_data/descriptor.py:108:sector_name_to_code -->
[descriptor.py](../../backend/analysis/m2_data/descriptor.py#L108)

```python
def sector_name_to_code(desc: Descriptor) -> dict[str, str]: ...
```

사전에 있는 영문·한국어 섹터 이름을 2자리 코드에 대응시키는 사전을 반환합니다.

호출하는 코드: [DialogService._code_proposals](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-_code_proposals-413), [retrieve](m3_selection_구현보고서.md#m3_selection-retrieve-py-retrieve-70).


<a id="m2_data-descriptor-py-parents_of-119"></a>
#### `parents_of`

<!-- source-symbol: m2_data/descriptor.py:119:parents_of -->
[descriptor.py](../../backend/analysis/m2_data/descriptor.py#L119)

```python
def parents_of(code: str) -> list[str]: ...
```

주어진 GICS 코드보다 짧은 6·4·2자리 접두사를 가까운 상위 계층 순서로 반환합니다.

호출하는 코드: [retrieve](m3_selection_구현보고서.md#m3_selection-retrieve-py-retrieve-70).


<a id="m2_data-descriptor-py-known_codes-124"></a>
#### `known_codes`

<!-- source-symbol: m2_data/descriptor.py:124:known_codes -->
[descriptor.py](../../backend/analysis/m2_data/descriptor.py#L124)

```python
def known_codes(desc: Descriptor) -> set[str]: ...
```

Descriptor의 산업분류 표에 존재하는 코드 집합을 반환합니다. LLM이 제안한 코드 실존 여부를 검사할 때 사용합니다.

호출하는 코드: [interpret](m3_selection_구현보고서.md#m3_selection-intent-py-interpret-104).


<a id="m2_data-descriptor-py-tickers-128"></a>
#### `tickers`

<!-- source-symbol: m2_data/descriptor.py:128:tickers -->
[descriptor.py](../../backend/analysis/m2_data/descriptor.py#L128)

```python
def tickers(desc: Descriptor) -> list[str]: ...
```

사전에 포함된 yfinance_symbol을 정렬한 목록으로 반환합니다. 자료를 외부 yfinance 서비스에서 조회한다는 뜻은 아닙니다.

호출하는 코드: [st_request](executor_구현보고서.md#executor-stages-py-st_request-46), [precheck](m1_request_구현보고서.md#m1_request-precheck-py-precheck-54), [interpret](m3_selection_구현보고서.md#m3_selection-intent-py-interpret-104), [build_results](m5_backtest_report_구현보고서.md#m5_backtest_report-collect-py-build_results-42).


<a id="m2_data-descriptor-py-entry-132"></a>
#### `entry`

<!-- source-symbol: m2_data/descriptor.py:132:entry -->
[descriptor.py](../../backend/analysis/m2_data/descriptor.py#L132)

```python
def entry(desc: Descriptor, ticker: str) -> dict[str, Any] | None: ...
```

Descriptor.by_ticker에 위임해 해당 티커의 사전 항목 또는 None을 반환합니다.


<a id="file-m2_data-disclosure_labels-py"></a>
### m2_data/disclosure_labels.py


<a id="m2_data-disclosure_labels-py-label_ko-33"></a>
#### `label_ko`

<!-- source-symbol: m2_data/disclosure_labels.py:33:label_ko -->
[disclosure_labels.py](../../backend/analysis/m2_data/disclosure_labels.py#L33)

```python
def label_ko(event_type: str | None) -> str: ...
```

공시 event_type을 한국어 사건명으로 바꿉니다. 미등록 종류는 원래 코드, 빈 종류는 '분류 없음'으로 반환합니다.

호출하는 코드: [display_title](#m2_data-disclosure_labels-py-display_title-37), [build_window](#m2_data-news-py-build_window-131).


<a id="m2_data-disclosure_labels-py-display_title-37"></a>
#### `display_title`

<!-- source-symbol: m2_data/disclosure_labels.py:37:display_title -->
[disclosure_labels.py](../../backend/analysis/m2_data/disclosure_labels.py#L37)

```python
def display_title(rec: dict[str, Any]) -> str: ...
```

SEC 출처는 양식·항목 번호와 사건명을 결합하고 DART 등은 보고서 제목을 우선 사용합니다. 없는 정보는 form·라벨 순으로 보완한 표시 제목을 반환합니다.

직접 연결: [label_ko](#m2_data-disclosure_labels-py-label_ko-33).

호출하는 코드: [build_window](#m2_data-news-py-build_window-131).


<a id="file-m2_data-market_data-py"></a>
### m2_data/market_data.py


<a id="m2_data-market_data-py-_d-38"></a>
#### `_d`

<!-- source-symbol: m2_data/market_data.py:38:_d -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L38)

```python
def _d(x: Any) -> dt.date: ...
```

pandas Timestamp·문자열·날짜 입력을 순수 datetime.date로 맞춥니다. 날짜 비교에서 Timestamp와 date의 차이를 없애는 보조 함수입니다.

호출하는 코드: [MarketData.common_trading_day_on_or_before](#m2_data-market_data-py-MarketData-common_trading_day_on_or_before-101), [MarketData._prefetch](#m2_data-market_data-py-MarketData-_prefetch-131).


<a id="m2_data-market_data-py-MarketData-__init__-57"></a>
#### `MarketData.__init__`

<!-- source-symbol: m2_data/market_data.py:57:MarketData.__init__ -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L57)

```python
def __init__(self, repo: Any, settings: AnalysisSettings, *, ceiling: dt.date | None=None) -> None: ...
```

Repository의 종목 마스터를 읽고 캐시·재진입 잠금을 만듭니다. ceiling을 주지 않으면 설정 시장의 최신 자료 날짜 중 가장 이른 날짜를 상한으로 사용합니다. 명시 상한이 실제 최신 자료를 넘으면 DataMissing입니다.

직접 연결: [_Cache](#m2_data-market_data-py-_Cache-44), [MarketData.latest_trading_day](#m2_data-market_data-py-MarketData-latest_trading_day-92), [DataMissing](common_구현보고서.md#errors-py-DataMissing-38).

명시적으로 발생시키는 예외: `DataMissing`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m2_data-market_data-py-MarketData-benchmark_of-68"></a>
#### `MarketData.benchmark_of`

<!-- source-symbol: m2_data/market_data.py:68:MarketData.benchmark_of -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L68)

```python
def benchmark_of(self, market: str) -> str: ...
```

시장 코드 US/KR에 대응하는 설정 비교지수 티커를 반환합니다. 지원하지 않는 시장은 매핑 조회 오류가 발생합니다.

호출하는 코드: [MarketData.benchmarks](#m2_data-market_data-py-MarketData-benchmarks-71).


<a id="m2_data-market_data-py-MarketData-benchmarks-71"></a>
#### `MarketData.benchmarks`

<!-- source-symbol: m2_data/market_data.py:71:MarketData.benchmarks -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L71)

```python
def benchmarks(self, markets: Iterable[str] | None=None) -> list[str]: ...
```

전달 시장 또는 기본 설정 시장의 비교지수 목록을 반환합니다.

직접 연결: [MarketData.benchmark_of](#m2_data-market_data-py-MarketData-benchmark_of-68).

호출하는 코드: [MarketData.latest_trading_day](#m2_data-market_data-py-MarketData-latest_trading_day-92), [MarketData.common_trading_day_on_or_before](#m2_data-market_data-py-MarketData-common_trading_day_on_or_before-101), [MarketData.data_range](#m2_data-market_data-py-MarketData-data_range-115), [MarketData._prefetch](#m2_data-market_data-py-MarketData-_prefetch-131).


<a id="m2_data-market_data-py-MarketData-asset_id-74"></a>
#### `MarketData.asset_id`

<!-- source-symbol: m2_data/market_data.py:74:MarketData.asset_id -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L74)

```python
def asset_id(self, ticker: str) -> str: ...
```

티커를 정규화해 종목 마스터의 asset_id를 반환합니다. 마스터에 없으면 한국 코드의 KR- 접두사 또는 미국의 US- 접두사로 추정합니다.

호출하는 코드: [MarketData.latest_trading_day](#m2_data-market_data-py-MarketData-latest_trading_day-92).


<a id="m2_data-market_data-py-MarketData-market_of-80"></a>
#### `MarketData.market_of`

<!-- source-symbol: m2_data/market_data.py:80:MarketData.market_of -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L80)

```python
def market_of(self, ticker: str) -> str: ...
```

정규화한 티커의 마스터 시장을 반환하고 누락 시 통화 판별로 KR/US를 추정합니다.


<a id="m2_data-market_data-py-MarketData-currency_of-84"></a>
#### `MarketData.currency_of`

<!-- source-symbol: m2_data/market_data.py:84:MarketData.currency_of -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L84)

```python
def currency_of(self, ticker: str) -> str: ...
```

티커의 마스터 통화를 반환하고 누락 시 종목 표기에서 통화를 추정합니다.


<a id="m2_data-market_data-py-MarketData-name_of-88"></a>
#### `MarketData.name_of`

<!-- source-symbol: m2_data/market_data.py:88:MarketData.name_of -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L88)

```python
def name_of(self, ticker: str) -> str: ...
```

마스터 회사명을 반환하고 없으면 입력 티커를 그대로 사용합니다.


<a id="m2_data-market_data-py-MarketData-latest_trading_day-92"></a>
#### `MarketData.latest_trading_day`

<!-- source-symbol: m2_data/market_data.py:92:MarketData.latest_trading_day -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L92)

```python
def latest_trading_day(self, markets: Iterable[str] | None=None) -> dt.date: ...
```

요청 시장 비교지수의 마지막 가격 날짜를 조회해 최솟값을 반환합니다. 비교지수 누락은 DataMissing입니다. 이 값 자체가 양 시장 거래일의 교집합 날짜라는 뜻은 아니며 공통 거래일 보정은 별도 함수가 수행합니다.

직접 연결: [MarketData.benchmarks](#m2_data-market_data-py-MarketData-benchmarks-71), [MarketData.asset_id](#m2_data-market_data-py-MarketData-asset_id-74), [DataMissing](common_구현보고서.md#errors-py-DataMissing-38).

호출하는 코드: [MarketData.__init__](#m2_data-market_data-py-MarketData-__init__-57).

명시적으로 발생시키는 예외: `DataMissing`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m2_data-market_data-py-MarketData-common_trading_day_on_or_before-101"></a>
#### `MarketData.common_trading_day_on_or_before`

<!-- source-symbol: m2_data/market_data.py:101:MarketData.common_trading_day_on_or_before -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L101)

```python
def common_trading_day_on_or_before(self, d: dt.date, markets: Iterable[str] | None=None) -> dt.date: ...
```

지정일 이전 42일의 비교지수 가격 날짜를 시장별로 교집합하여 가장 최근 공통 거래일을 반환합니다. 자료나 교집합이 없으면 DataMissing입니다.

직접 연결: [MarketData.benchmarks](#m2_data-market_data-py-MarketData-benchmarks-71), [MarketData.bars](#m2_data-market_data-py-MarketData-bars-166), [DataMissing](common_구현보고서.md#errors-py-DataMissing-38), [_d](#m2_data-market_data-py-_d-38).

명시적으로 발생시키는 예외: `DataMissing`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m2_data-market_data-py-MarketData-data_range-115"></a>
#### `MarketData.data_range`

<!-- source-symbol: m2_data/market_data.py:115:MarketData.data_range -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L115)

```python
def data_range(self, markets: Iterable[str] | None=None) -> tuple[dt.date, dt.date]: ...
```

시장별 비교지수 자료 시작일의 최댓값과 현재 ceiling을 반환합니다. 비교지수 범위가 없으면 분석 창을 만들 수 없으므로 실패합니다.

직접 연결: [MarketData.benchmarks](#m2_data-market_data-py-MarketData-benchmarks-71), [DataMissing](common_구현보고서.md#errors-py-DataMissing-38).

명시적으로 발생시키는 예외: `DataMissing`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m2_data-market_data-py-MarketData-prefetch-126"></a>
#### `MarketData.prefetch`

<!-- source-symbol: m2_data/market_data.py:126:MarketData.prefetch -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L126)

```python
def prefetch(self, tickers: Iterable[str], start: dt.date, end: dt.date | None=None) -> None: ...
```

재진입 잠금 안에서 가격·비교지수·환율을 사전 적재합니다. 반환값은 없고 공유 캐시를 갱신합니다.

직접 연결: [MarketData._prefetch](#m2_data-market_data-py-MarketData-_prefetch-131).


<a id="m2_data-market_data-py-MarketData-_prefetch-131"></a>
#### `MarketData._prefetch`

<!-- source-symbol: m2_data/market_data.py:131:MarketData._prefetch -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L131)

```python
def _prefetch(self, tickers: Iterable[str], start: dt.date, end: dt.date | None=None) -> None: ...
```

요청 종목·설정 비교지수를 기존 적재 범위와 합쳐 DB에서 읽습니다. 가격이 없는 요청 종목도 loaded로 기억해 재조회 반복을 막습니다. 환율은 시작 전 14일까지 추가 조회하며 없으면 DataMissing입니다. end는 ceiling 이하로 제한합니다.

직접 연결: [MarketData.benchmarks](#m2_data-market_data-py-MarketData-benchmarks-71), [_d](#m2_data-market_data-py-_d-38), [DataMissing](common_구현보고서.md#errors-py-DataMissing-38).

호출하는 코드: [MarketData.prefetch](#m2_data-market_data-py-MarketData-prefetch-126), [MarketData._ensure](#m2_data-market_data-py-MarketData-_ensure-153).

명시적으로 발생시키는 예외: `DataMissing`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m2_data-market_data-py-MarketData-_ensure-153"></a>
#### `MarketData._ensure`

<!-- source-symbol: m2_data/market_data.py:153:MarketData._ensure -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L153)

```python
def _ensure(self, tickers: Iterable[str], start: dt.date, end: dt.date) -> None: ...
```

캐시가 종목·기간을 포함하면 빠르게 반환하고, 아니면 잠금 안에서 포함 범위 전체를 재적재합니다. 자료가 전혀 없는 종목도 요청 이력으로 판단합니다.

직접 연결: [MarketData._prefetch](#m2_data-market_data-py-MarketData-_prefetch-131).

호출하는 코드: [MarketData.bars](#m2_data-market_data-py-MarketData-bars-166), [MarketData.fx_series](#m2_data-market_data-py-MarketData-fx_series-174).


<a id="m2_data-market_data-py-MarketData-bars-166"></a>
#### `MarketData.bars`

<!-- source-symbol: m2_data/market_data.py:166:MarketData.bars -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L166)

```python
def bars(self, tickers: Sequence[str], start: dt.date, end: dt.date) -> pd.DataFrame: ...
```

필요 캐시를 확보하고 날짜 양끝을 포함하는 long 형식 가격 행을 반환합니다. 이 저수준 함수보다 기준일 보호가 필요한 분석은 MarketDataView를 사용합니다.

직접 연결: [MarketData._ensure](#m2_data-market_data-py-MarketData-_ensure-153).

호출하는 코드: [MarketData.common_trading_day_on_or_before](#m2_data-market_data-py-MarketData-common_trading_day_on_or_before-101).


<a id="m2_data-market_data-py-MarketData-fx_series-174"></a>
#### `MarketData.fx_series`

<!-- source-symbol: m2_data/market_data.py:174:MarketData.fx_series -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L174)

```python
def fx_series(self, start: dt.date, end: dt.date) -> pd.Series: ...
```

날짜별 USDKRW 시계열을 만들고 휴일을 직전 환율로 채웁니다. 최초 자료 이전 구간은 첫 환율로 뒤채움하므로 엄격한 시점 검증과 별개의 보정 동작입니다. 유효 구간 내부 결측은 DataMissing입니다.

직접 연결: [MarketData._ensure](#m2_data-market_data-py-MarketData-_ensure-153), [DataMissing](common_구현보고서.md#errors-py-DataMissing-38).

명시적으로 발생시키는 예외: `DataMissing`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m2_data-market_data-py-MarketData-view-187"></a>
#### `MarketData.view`

<!-- source-symbol: m2_data/market_data.py:187:MarketData.view -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L187)

```python
def view(self, as_of: dt.date) -> MarketDataView: ...
```

ceiling 이하 as_of를 가진 MarketDataView를 반환합니다. 상한을 넘는 view 생성은 LookaheadError입니다.

직접 연결: [LookaheadError](common_구현보고서.md#errors-py-LookaheadError-32), [MarketDataView](#m2_data-market_data-py-MarketDataView-193).

명시적으로 발생시키는 예외: `LookaheadError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m2_data-market_data-py-MarketDataView-__init__-196"></a>
#### `MarketDataView.__init__`

<!-- source-symbol: m2_data/market_data.py:196:MarketDataView.__init__ -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L196)

```python
def __init__(self, md: MarketData, as_of: dt.date) -> None: ...
```

공유 MarketData·설정·as_of를 보관합니다. 이 생성자를 직접 쓰면 별도 ceiling 검사는 없으므로 일반 진입점은 MarketData.view입니다.


<a id="m2_data-market_data-py-MarketDataView-_check-202"></a>
#### `MarketDataView._check`

<!-- source-symbol: m2_data/market_data.py:202:MarketDataView._check -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L202)

```python
def _check(self, end: dt.date, *, strict: bool=False) -> dt.date: ...
```

조회 끝 날짜가 as_of 이하인지 검사하고 strict=True면 as_of-1일 이하인지 검사합니다. 위반 시 요청 날짜·기준일 정보를 가진 LookaheadError를 발생시키고 유효하면 end를 반환합니다.

직접 연결: [LookaheadError](common_구현보고서.md#errors-py-LookaheadError-32).

호출하는 코드: [MarketDataView._end](#m2_data-market_data-py-MarketDataView-_end-211), [MarketDataView.trading_days](#m2_data-market_data-py-MarketDataView-trading_days-222), [MarketDataView.panel](#m2_data-market_data-py-MarketDataView-panel-291), [MarketDataView.fx_on_or_before](#m2_data-market_data-py-MarketDataView-fx_on_or_before-328), [MarketDataView.fx_series](#m2_data-market_data-py-MarketDataView-fx_series-335).

명시적으로 발생시키는 예외: `LookaheadError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m2_data-market_data-py-MarketDataView-_end-211"></a>
#### `MarketDataView._end`

<!-- source-symbol: m2_data/market_data.py:211:MarketDataView._end -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L211)

```python
def _end(self, end: dt.date | None, strict_before: bool | None) -> dt.date: ...
```

strict_before 인자 또는 설정으로 추정 정보 마감을 결정합니다. end 미지정 시 기준일 또는 전날을 선택해 _check로 검증합니다.

직접 연결: [MarketDataView._check](#m2_data-market_data-py-MarketDataView-_check-202).

호출하는 코드: [MarketDataView.adj_close](#m2_data-market_data-py-MarketDataView-adj_close-232), [MarketDataView.close_volume](#m2_data-market_data-py-MarketDataView-close_volume-271), [MarketDataView.valuation](#m2_data-market_data-py-MarketDataView-valuation-339).


<a id="m2_data-market_data-py-MarketDataView-_markets-217"></a>
#### `MarketDataView._markets`

<!-- source-symbol: m2_data/market_data.py:217:MarketDataView._markets -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L217)

```python
def _markets(self, tickers: Iterable[str]) -> list[str]: ...
```

종목 목록의 시장을 중복 제거·정렬해 반환합니다. 목록이 비면 설정 시장 전체를 사용합니다.

호출하는 코드: [MarketDataView.adj_close](#m2_data-market_data-py-MarketDataView-adj_close-232), [MarketDataView._carry_market_holidays](#m2_data-market_data-py-MarketDataView-_carry_market_holidays-310).


<a id="m2_data-market_data-py-MarketDataView-trading_days-222"></a>
#### `MarketDataView.trading_days`

<!-- source-symbol: m2_data/market_data.py:222:MarketDataView.trading_days -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L222)

```python
def trading_days(self, start: dt.date, end: dt.date | None=None, *, markets: Iterable[str] | None=None, bench: str | None=None) -> pd.DatetimeIndex: ...
```

비교지수의 실제 가격 날짜를 합쳐 거래일 합집합을 반환합니다. bench가 지정되면 그 종목의 달력을 사용하며 끝 날짜는 as_of를 넘을 수 없습니다.

직접 연결: [MarketDataView._check](#m2_data-market_data-py-MarketDataView-_check-202).

호출하는 코드: [MarketDataView.adj_close](#m2_data-market_data-py-MarketDataView-adj_close-232), [MarketDataView._carry_market_holidays](#m2_data-market_data-py-MarketDataView-_carry_market_holidays-310).


<a id="m2_data-market_data-py-MarketDataView-adj_close-232"></a>
#### `MarketDataView.adj_close`

<!-- source-symbol: m2_data/market_data.py:232:MarketDataView.adj_close -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L232)

```python
def adj_close(self, tickers: Sequence[str], start: dt.date, end: dt.date | None=None, *, strict_before: bool | None=None, usd: bool=True, fill: bool=True) -> pd.DataFrame: ...
```

수정종가를 날짜×티커 표로 피벗하고 시장 거래일 합집합에 맞춥니다. 기본 추정 조회는 기준일 전날까지이며 한국 가격을 날짜별 환율로 USD 환산합니다. fill=True면 시작 전 14일도 읽어 직전값을 이어 붙이고 요청 창으로 자릅니다. 품질 판정 전의 조회이므로 실제 결측을 채울 수도 있습니다.

직접 연결: [MarketDataView._end](#m2_data-market_data-py-MarketDataView-_end-211), [MarketDataView.trading_days](#m2_data-market_data-py-MarketDataView-trading_days-222), [MarketDataView._markets](#m2_data-market_data-py-MarketDataView-_markets-217), [MarketDataView._to_usd](#m2_data-market_data-py-MarketDataView-_to_usd-262).

호출하는 코드: [MarketDataView.panel](#m2_data-market_data-py-MarketDataView-panel-291).


<a id="m2_data-market_data-py-MarketDataView-_to_usd-262"></a>
#### `MarketDataView._to_usd`

<!-- source-symbol: m2_data/market_data.py:262:MarketDataView._to_usd -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L262)

```python
def _to_usd(self, wide: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame: ...
```

표에 있는 KRW 종목 열만 USDKRW로 나눈 복사본을 반환합니다. 한국 종목이나 자료가 없으면 원본 표를 그대로 반환합니다.

호출하는 코드: [MarketDataView.adj_close](#m2_data-market_data-py-MarketDataView-adj_close-232).


<a id="m2_data-market_data-py-MarketDataView-close_volume-271"></a>
#### `MarketDataView.close_volume`

<!-- source-symbol: m2_data/market_data.py:271:MarketDataView.close_volume -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L271)

```python
def close_volume(self, tickers: Sequence[str], start: dt.date, end: dt.date | None=None, *, strict_before: bool | None=None) -> pd.DataFrame: ...
```

원래 종가·거래량에 close_usd와 dollar_volume_usd를 추가한 long 표를 반환합니다. 후보의 유동성·규모 필터가 사용하며 strict 정보 마감을 적용합니다.

직접 연결: [MarketDataView._end](#m2_data-market_data-py-MarketDataView-_end-211).


<a id="m2_data-market_data-py-MarketDataView-first_dates-284"></a>
#### `MarketDataView.first_dates`

<!-- source-symbol: m2_data/market_data.py:284:MarketDataView.first_dates -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L284)

```python
def first_dates(self, tickers: Sequence[str]) -> dict[str, dt.date]: ...
```

공유 캐시 범위 안의 종목별 첫 가격 날짜 중 as_of 이전 항목을 반환합니다. DB 전체 상장일 조회가 아니라 적재된 범위의 첫 날짜라는 점에 유의합니다.


<a id="m2_data-market_data-py-MarketDataView-panel-291"></a>
#### `MarketDataView.panel`

<!-- source-symbol: m2_data/market_data.py:291:MarketDataView.panel -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L291)

```python
def panel(self, tickers: Sequence[str], start: dt.date, end: dt.date | None=None, *, required: Iterable[str]=(), benchmarks: Iterable[str]=()) -> tuple[pd.DataFrame, DataQualityReport]: ...
```

체결·백테스트용 USD 수정종가를 기준일 종가까지 조회하고 시장 휴장일만 먼저 보정합니다. 그 뒤 품질 검사를 적용해 결측 없는 사용 가능 표와 DataQualityReport를 반환합니다. 필수 종목 또는 비교지수의 품질 탈락은 오류입니다.

직접 연결: [MarketDataView._check](#m2_data-market_data-py-MarketDataView-_check-202), [MarketDataView.adj_close](#m2_data-market_data-py-MarketDataView-adj_close-232), [MarketDataView._carry_market_holidays](#m2_data-market_data-py-MarketDataView-_carry_market_holidays-310), [assess](#m2_data-quality-py-assess-21).


<a id="m2_data-market_data-py-MarketDataView-_carry_market_holidays-310"></a>
#### `MarketDataView._carry_market_holidays`

<!-- source-symbol: m2_data/market_data.py:310:MarketDataView._carry_market_holidays -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L310)

```python
def _carry_market_holidays(self, wide: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame: ...
```

합집합 달력에서 해당 시장의 비교지수가 거래하지 않은 날짜만 직전 종가로 채웁니다. 자기 시장 거래일의 실제 누락은 그대로 남겨 품질 판정이 구분하도록 합니다.

직접 연결: [MarketDataView._markets](#m2_data-market_data-py-MarketDataView-_markets-217), [MarketDataView.trading_days](#m2_data-market_data-py-MarketDataView-trading_days-222).

호출하는 코드: [MarketDataView.panel](#m2_data-market_data-py-MarketDataView-panel-291).


<a id="m2_data-market_data-py-MarketDataView-fx_on_or_before-328"></a>
#### `MarketDataView.fx_on_or_before`

<!-- source-symbol: m2_data/market_data.py:328:MarketDataView.fx_on_or_before -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L328)

```python
def fx_on_or_before(self, d: dt.date | None=None) -> FxRate: ...
```

기준일 보호 후 지정일 이하 가장 최근 FxRate를 Repository에서 조회합니다. 환율이 없으면 DataMissing입니다.

직접 연결: [MarketDataView._check](#m2_data-market_data-py-MarketDataView-_check-202), [DataMissing](common_구현보고서.md#errors-py-DataMissing-38).

호출하는 코드: [MarketDataView.valuation](#m2_data-market_data-py-MarketDataView-valuation-339).

명시적으로 발생시키는 예외: `DataMissing`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m2_data-market_data-py-MarketDataView-fx_series-335"></a>
#### `MarketDataView.fx_series`

<!-- source-symbol: m2_data/market_data.py:335:MarketDataView.fx_series -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L335)

```python
def fx_series(self, start: dt.date, end: dt.date | None=None) -> pd.Series: ...
```

끝 날짜를 기준일로 검증한 뒤 MarketData의 환율 보정 시계열을 반환합니다.

직접 연결: [MarketDataView._check](#m2_data-market_data-py-MarketDataView-_check-202).


<a id="m2_data-market_data-py-MarketDataView-valuation-339"></a>
#### `MarketDataView.valuation`

<!-- source-symbol: m2_data/market_data.py:339:MarketDataView.valuation -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L339)

```python
def valuation(self, tickers: Sequence[str], *, strict_before: bool | None=None) -> pd.DataFrame: ...
```

추정 마감일·종목 집합을 키로 가치평가 표를 캐시합니다. 최대 경과일 내 최신 valuation_daily를 읽고 KRW 시가총액을 조회 마감일 환율로 USD 환산하며 요청 순서에 맞춘 ticker 인덱스 표를 반환합니다.

직접 연결: [MarketDataView._end](#m2_data-market_data-py-MarketDataView-_end-211), [MarketDataView.fx_on_or_before](#m2_data-market_data-py-MarketDataView-fx_on_or_before-328).

호출하는 코드: [MarketDataView.shares_outstanding](#m2_data-market_data-py-MarketDataView-shares_outstanding-379), [MarketDataView.market_cap_usd](#m2_data-market_data-py-MarketDataView-market_cap_usd-383).


<a id="m2_data-market_data-py-MarketDataView-shares_outstanding-379"></a>
#### `MarketDataView.shares_outstanding`

<!-- source-symbol: m2_data/market_data.py:379:MarketDataView.shares_outstanding -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L379)

```python
def shares_outstanding(self, tickers: Sequence[str]) -> dict[str, float]: ...
```

가치평가 표에서 결측이 아닌 주식 수만 티커→실수 사전으로 반환합니다.

직접 연결: [MarketDataView.valuation](#m2_data-market_data-py-MarketDataView-valuation-339).


<a id="m2_data-market_data-py-MarketDataView-market_cap_usd-383"></a>
#### `MarketDataView.market_cap_usd`

<!-- source-symbol: m2_data/market_data.py:383:MarketDataView.market_cap_usd -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L383)

```python
def market_cap_usd(self, tickers: Sequence[str]) -> dict[str, float]: ...
```

가치평가 표에서 사용 가능한 USD 시가총액만 반환합니다. 전체 누락과 0 값은 호출하는 구성·후보 코드에서 구분해 처리합니다.

직접 연결: [MarketDataView.valuation](#m2_data-market_data-py-MarketDataView-valuation-339).


<a id="m2_data-market_data-py-MarketDataView-news_window-388"></a>
#### `MarketDataView.news_window`

<!-- source-symbol: m2_data/market_data.py:388:MarketDataView.news_window -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L388)

```python
def news_window(self, tickers: Sequence[str], *, days: int | None=None, per_ticker: int | None=None, languages: Sequence[str] | None=None, dc_days: int | None=None, dc_event_types: Sequence[str] | None=None) -> EvidenceWindow: ...
```

날짜·창 길이·종목·언어·공시 종류별 EvidenceWindow를 캐시해 반환합니다. 뉴스 기본 14일, 공시 기본 45일이며 dc_days=0으로 공시를 끌 수 있습니다. 캐시 키에는 per_ticker가 없어 같은 나머지 조건에서 건수만 바꾼 재호출은 첫 결과를 재사용할 수 있습니다.

직접 연결: [build_window](#m2_data-news-py-build_window-131).


<a id="m2_data-market_data-py-MarketDataView-constituents-410"></a>
#### `MarketDataView.constituents`

<!-- source-symbol: m2_data/market_data.py:410:MarketDataView.constituents -->
[market_data.py](../../backend/analysis/m2_data/market_data.py#L410)

```python
def constituents(self, universe: str) -> tuple[dt.date | None, list[str], list[str]]: ...
```

유니버스를 Repository의 지수 코드로 변환해 기준일 구성종목 스냅샷·티커·경고를 반환합니다. 과거 스냅샷 미확보 시 대체 정책은 Repository에 있습니다. 주 분석 후보 검색은 주로 고정 Descriptor를 사용합니다.


<a id="file-m2_data-metrics-py"></a>
### m2_data/metrics.py


<a id="m2_data-metrics-py-Fact-to_dict-31"></a>
#### `Fact.to_dict`

<!-- source-symbol: m2_data/metrics.py:31:Fact.to_dict -->
[metrics.py](../../backend/analysis/m2_data/metrics.py#L31)

```python
def to_dict(self) -> dict: ...
```

불변 Fact 객체를 사전으로 변환해 통합 결과의 evidence_index에 넣을 수 있게 합니다.


<a id="m2_data-metrics-py-_fact-35"></a>
#### `_fact`

<!-- source-symbol: m2_data/metrics.py:35:_fact -->
[metrics.py](../../backend/analysis/m2_data/metrics.py#L35)

```python
def _fact(view: MarketDataView, ticker: str, metric: str, value: float, unit: str, as_of: dt.date, source: str) -> Fact: ...
```

종목의 asset_id와 지표·날짜를 결합한 fin:<asset_id>:<metric>:<date> ID를 만들고 값·단위·출처를 포함한 Fact를 반환합니다.

직접 연결: [Fact](#m2_data-metrics-py-Fact-21).

호출하는 코드: [return_12m_1m](#m2_data-metrics-py-return_12m_1m-41), [vol_60d](#m2_data-metrics-py-vol_60d-53), [_valuation_metric](#m2_data-metrics-py-_valuation_metric-66).


<a id="m2_data-metrics-py-return_12m_1m-41"></a>
#### `return_12m_1m`

<!-- source-symbol: m2_data/metrics.py:41:return_12m_1m -->
[metrics.py](../../backend/analysis/m2_data/metrics.py#L41)

```python
def return_12m_1m(view: MarketDataView, tickers: Sequence[str]) -> tuple[pd.Series, list[Fact]]: ...
```

기준일 이전 최대 420일의 USD 수정종가에서 최소 253개 관측이 있는 종목의 a[-22]/a[-253]-1을 계산합니다. 최근 약 1개월을 제외한 모멘텀 Series와 Fact 목록을 반환하며 이력이 짧은 종목은 결과에서 빠집니다.

직접 연결: [_fact](#m2_data-metrics-py-_fact-35).


<a id="m2_data-metrics-py-vol_60d-53"></a>
#### `vol_60d`

<!-- source-symbol: m2_data/metrics.py:53:vol_60d -->
[metrics.py](../../backend/analysis/m2_data/metrics.py#L53)

```python
def vol_60d(view: MarketDataView, tickers: Sequence[str]) -> tuple[pd.Series, list[Fact]]: ...
```

기준일 이전 가격의 최근 60개 로그수익률 표본 표준편차에 √252를 곱해 연환산 변동성을 계산합니다. 60개 수익률이 없는 종목은 제외하고 Series·Fact를 반환합니다.

직접 연결: [_fact](#m2_data-metrics-py-_fact-35).


<a id="m2_data-metrics-py-_valuation_metric-66"></a>
#### `_valuation_metric`

<!-- source-symbol: m2_data/metrics.py:66:_valuation_metric -->
[metrics.py](../../backend/analysis/m2_data/metrics.py#L66)

```python
def _valuation_metric(view: MarketDataView, tickers: Sequence[str], column: str, metric: str, *, positive_only: bool) -> tuple[pd.Series, list[Fact]]: ...
```

가치평가 표의 지정 열에서 결측과 선택적 양수 조건을 적용해 지표 Series와 Fact 목록을 만듭니다. 실제 관측 행 날짜를 근거 날짜로 사용합니다.

직접 연결: [_fact](#m2_data-metrics-py-_fact-35).

호출하는 코드: [pe_ttm](#m2_data-metrics-py-pe_ttm-82), [roe_ttm](#m2_data-metrics-py-roe_ttm-87), [dividend_yield_ttm](#m2_data-metrics-py-dividend_yield_ttm-91).


<a id="m2_data-metrics-py-pe_ttm-82"></a>
#### `pe_ttm`

<!-- source-symbol: m2_data/metrics.py:82:pe_ttm -->
[metrics.py](../../backend/analysis/m2_data/metrics.py#L82)

```python
def pe_ttm(view: MarketDataView, tickers: Sequence[str]) -> tuple[pd.Series, list[Fact]]: ...
```

가치평가 per 열에서 양수 값만 채택하여 저PER 선정용 지표와 근거를 반환합니다. 적자·0·누락 값은 제외됩니다.

직접 연결: [_valuation_metric](#m2_data-metrics-py-_valuation_metric-66).


<a id="m2_data-metrics-py-roe_ttm-87"></a>
#### `roe_ttm`

<!-- source-symbol: m2_data/metrics.py:87:roe_ttm -->
[metrics.py](../../backend/analysis/m2_data/metrics.py#L87)

```python
def roe_ttm(view: MarketDataView, tickers: Sequence[str]) -> tuple[pd.Series, list[Fact]]: ...
```

valuation_daily의 ROE 값을 사용해 퀄리티 선정 지표와 근거를 반환합니다. 음수 자체를 금지하지는 않습니다.

직접 연결: [_valuation_metric](#m2_data-metrics-py-_valuation_metric-66).


<a id="m2_data-metrics-py-dividend_yield_ttm-91"></a>
#### `dividend_yield_ttm`

<!-- source-symbol: m2_data/metrics.py:91:dividend_yield_ttm -->
[metrics.py](../../backend/analysis/m2_data/metrics.py#L91)

```python
def dividend_yield_ttm(view: MarketDataView, tickers: Sequence[str]) -> tuple[pd.Series, list[Fact]]: ...
```

가치평가 dividend_yield 열을 고배당 지표와 근거로 반환합니다. 0 배당도 결측이 아니면 허용됩니다.

직접 연결: [_valuation_metric](#m2_data-metrics-py-_valuation_metric-66).


<a id="file-m2_data-news-py"></a>
### m2_data/news.py


<a id="m2_data-news-py-EvidenceWindow-n_articles-34"></a>
#### `EvidenceWindow.n_articles`

<!-- source-symbol: m2_data/news.py:34:EvidenceWindow.n_articles -->
[news.py](../../backend/analysis/m2_data/news.py#L34)

```python
def n_articles(self) -> int: ...
```

records에 적재된 뉴스 건수를 반환하는 속성입니다.

선언·진입 조건: `property`.


<a id="m2_data-news-py-EvidenceWindow-n_disclosures-38"></a>
#### `EvidenceWindow.n_disclosures`

<!-- source-symbol: m2_data/news.py:38:EvidenceWindow.n_disclosures -->
[news.py](../../backend/analysis/m2_data/news.py#L38)

```python
def n_disclosures(self) -> int: ...
```

disclosures에 적재된 공시 건수를 반환합니다.

선언·진입 조건: `property`.


<a id="m2_data-news-py-EvidenceWindow-n_tickers_with_news-42"></a>
#### `EvidenceWindow.n_tickers_with_news`

<!-- source-symbol: m2_data/news.py:42:EvidenceWindow.n_tickers_with_news -->
[news.py](../../backend/analysis/m2_data/news.py#L42)

```python
def n_tickers_with_news(self) -> int: ...
```

요청 티커 중 뉴스 ID 목록이 비어 있지 않은 종목 수를 반환합니다.

선언·진입 조건: `property`.


<a id="m2_data-news-py-EvidenceWindow-n_tickers_with_disclosures-46"></a>
#### `EvidenceWindow.n_tickers_with_disclosures`

<!-- source-symbol: m2_data/news.py:46:EvidenceWindow.n_tickers_with_disclosures -->
[news.py](../../backend/analysis/m2_data/news.py#L46)

```python
def n_tickers_with_disclosures(self) -> int: ...
```

요청 티커 중 공시 ID가 있는 종목 수를 반환합니다.

선언·진입 조건: `property`.


<a id="m2_data-news-py-EvidenceWindow-n_tickers_with_evidence-50"></a>
#### `EvidenceWindow.n_tickers_with_evidence`

<!-- source-symbol: m2_data/news.py:50:EvidenceWindow.n_tickers_with_evidence -->
[news.py](../../backend/analysis/m2_data/news.py#L50)

```python
def n_tickers_with_evidence(self) -> int: ...
```

has_evidence 규칙을 만족하는 종목 수를 셉니다. count_disclosures 설정에 따라 공시만 있는 종목의 포함 여부가 달라집니다.

선언·진입 조건: `property`.

직접 연결: [EvidenceWindow.has_evidence](#m2_data-news-py-EvidenceWindow-has_evidence-53).


<a id="m2_data-news-py-EvidenceWindow-has_evidence-53"></a>
#### `EvidenceWindow.has_evidence`

<!-- source-symbol: m2_data/news.py:53:EvidenceWindow.has_evidence -->
[news.py](../../backend/analysis/m2_data/news.py#L53)

```python
def has_evidence(self, t: str) -> bool: ...
```

티커에 뉴스가 있거나, 공시를 근거 수에 포함하는 설정이고 공시가 있으면 True를 반환합니다.

호출하는 코드: [EvidenceWindow.n_tickers_with_evidence](#m2_data-news-py-EvidenceWindow-n_tickers_with_evidence-50).


<a id="m2_data-news-py-EvidenceWindow-enough-57"></a>
#### `EvidenceWindow.enough`

<!-- source-symbol: m2_data/news.py:57:EvidenceWindow.enough -->
[news.py](../../backend/analysis/m2_data/news.py#L57)

```python
def enough(self) -> bool: ...
```

근거 종목 수가 min_tickers 이상인지 반환합니다. 기사 총량이 아니라 서로 다른 종목의 수를 판단 기준으로 사용합니다.

선언·진입 조건: `property`.


<a id="m2_data-news-py-EvidenceWindow-ids-62"></a>
#### `EvidenceWindow.ids`

<!-- source-symbol: m2_data/news.py:62:EvidenceWindow.ids -->
[news.py](../../backend/analysis/m2_data/news.py#L62)

```python
def ids(self) -> set[str]: ...
```

뉴스·공시 evidence_id를 합친 집합을 반환합니다. LLM 의견의 인용 허용 목록으로 사용됩니다.

선언·진입 조건: `property`.


<a id="m2_data-news-py-EvidenceWindow-all_records-66"></a>
#### `EvidenceWindow.all_records`

<!-- source-symbol: m2_data/news.py:66:EvidenceWindow.all_records -->
[news.py](../../backend/analysis/m2_data/news.py#L66)

```python
def all_records(self) -> list[dict[str, Any]]: ...
```

뉴스 뒤에 공시를 연결한 전체 레코드 목록을 반환합니다. 날짜별 통합 재정렬은 하지 않습니다.

선언·진입 조건: `property`.


<a id="m2_data-news-py-EvidenceWindow-summary-69"></a>
#### `EvidenceWindow.summary`

<!-- source-symbol: m2_data/news.py:69:EvidenceWindow.summary -->
[news.py](../../backend/analysis/m2_data/news.py#L69)

```python
def summary(self) -> dict[str, Any]: ...
```

반개구간 창, 뉴스·공시 건수, 근거 종목 수, 충분 여부와 언어·출처·사건 종류별 수량을 요약한 사전을 반환합니다.

직접 연결: [_count](#m2_data-news-py-_count-123).

호출하는 코드: [EvidenceWindow.to_dict](#m2_data-news-py-EvidenceWindow-to_dict-118).


<a id="m2_data-news-py-EvidenceWindow-prompt_lines-85"></a>
#### `EvidenceWindow.prompt_lines`

<!-- source-symbol: m2_data/news.py:85:EvidenceWindow.prompt_lines -->
[news.py](../../backend/analysis/m2_data/news.py#L85)

```python
def prompt_lines(self, max_per_ticker: int | None=None) -> str: ...
```

티커별 뉴스 ID·날짜·출처·제목 문자열을 만들고 기사가 없는 종목도 표시합니다. max_per_ticker로 전달량을 제한할 수 있습니다.


<a id="m2_data-news-py-EvidenceWindow-disclosure_lines-98"></a>
#### `EvidenceWindow.disclosure_lines`

<!-- source-symbol: m2_data/news.py:98:EvidenceWindow.disclosure_lines -->
[news.py](../../backend/analysis/m2_data/news.py#L98)

```python
def disclosure_lines(self, max_per_ticker: int | None=None) -> list[str]: ...
```

공시를 'ID / 이용 가능일 / 출처 / 양식·항목 / 티커 / 사건명 / 제목' 칸으로 나눈 문자열 목록으로 반환합니다. 티커를 다섯 번째 칸에 두는 규칙은 스마트 stub 파서와 연결됩니다.


<a id="m2_data-news-py-EvidenceWindow-event_counts-109"></a>
#### `EvidenceWindow.event_counts`

<!-- source-symbol: m2_data/news.py:109:EvidenceWindow.event_counts -->
[news.py](../../backend/analysis/m2_data/news.py#L109)

```python
def event_counts(self, t: str) -> dict[str, int]: ...
```

지정 종목의 공시를 한국어 사건명별로 집계합니다. 분석 대상 창·건수 제한을 통과한 자료의 수이며 모든 공시의 총수는 아닙니다.


<a id="m2_data-news-py-EvidenceWindow-to_dict-118"></a>
#### `EvidenceWindow.to_dict`

<!-- source-symbol: m2_data/news.py:118:EvidenceWindow.to_dict -->
[news.py](../../backend/analysis/m2_data/news.py#L118)

```python
def to_dict(self) -> dict[str, Any]: ...
```

요약과 기준일·티커별 ID·뉴스 원문 메타·공시 메타를 결합해 직렬화 가능한 사전을 반환합니다.

직접 연결: [EvidenceWindow.summary](#m2_data-news-py-EvidenceWindow-summary-69).


<a id="m2_data-news-py-_count-123"></a>
#### `_count`

<!-- source-symbol: m2_data/news.py:123:_count -->
[news.py](../../backend/analysis/m2_data/news.py#L123)

```python
def _count(records: list[dict[str, Any]], key: str) -> dict[str, int]: ...
```

레코드 목록에서 지정 키를 문자열로 바꿔 빈도 사전을 만듭니다. 누락 값은 문자열 'None'으로 집계될 수 있습니다.

호출하는 코드: [EvidenceWindow.summary](#m2_data-news-py-EvidenceWindow-summary-69).


<a id="m2_data-news-py-build_window-131"></a>
#### `build_window`

<!-- source-symbol: m2_data/news.py:131:build_window -->
[news.py](../../backend/analysis/m2_data/news.py#L131)

```python
def build_window(md: MarketData, tickers: Sequence[str], as_of: dt.date, *, days: int, per_ticker: int, languages: Sequence[str], min_tickers: int, dc_days: int=0, dc_per_ticker: int=8, dc_event_types: Sequence[str] | None=None, count_disclosures: bool=True, include_amendments: bool=False) -> EvidenceWindow: ...
```

뉴스는 UTC 발행시각 [as_of-days, as_of), 공시는 이용 가능일 [as_of-dc_days, as_of)로 DB 조회합니다. ev/dc ID와 티커 연결·제목·출처를 붙인 EvidenceWindow를 반환합니다. 공시는 허용 종류·수정 공시 제외·종목당 상한을 Repository에 전달하며 해당 읽기 메서드가 없으면 공시 조회를 생략합니다.

직접 연결: [EvidenceWindow](#m2_data-news-py-EvidenceWindow-20), [label_ko](#m2_data-disclosure_labels-py-label_ko-33), [display_title](#m2_data-disclosure_labels-py-display_title-37).

호출하는 코드: [MarketDataView.news_window](#m2_data-market_data-py-MarketDataView-news_window-388).


<a id="file-m2_data-quality-py"></a>
### m2_data/quality.py


<a id="m2_data-quality-py-assess-21"></a>
#### `assess`

<!-- source-symbol: m2_data/quality.py:21:assess -->
[quality.py](../../backend/analysis/m2_data/quality.py#L21)

```python
def assess(prices: pd.DataFrame, required: Iterable[str], expected_calendar: Iterable[date] | pd.DatetimeIndex, settings: MarketSettings) -> tuple[DataQualityReport, pd.DataFrame]: ...
```

가격 표·필수 종목·기대 거래일·품질 설정을 backend.pipeline.quality.assess_quality에 전달합니다. DataQualityError는 분석 패키지의 DataMissing으로 변환하고 품질 보고서와 정제 표를 반환합니다.

직접 연결: [DataMissing](common_구현보고서.md#errors-py-DataMissing-38).

호출하는 코드: [MarketDataView.panel](#m2_data-market_data-py-MarketDataView-panel-291).

명시적으로 발생시키는 예외: `DataMissing`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m2_data-quality-py-report_summary-33"></a>
#### `report_summary`

<!-- source-symbol: m2_data/quality.py:33:report_summary -->
[quality.py](../../backend/analysis/m2_data/quality.py#L33)

```python
def report_summary(report: DataQualityReport) -> dict: ...
```

DataQualityReport를 기준일·거래일 수·사용 가능 수·제외 사유·채움 일수·커버리지·경고 사전으로 축약합니다. 이후 통합 결과와 리포트가 사용합니다.

호출하는 코드: [prepare](m5_backtest_report_구현보고서.md#m5_backtest_report-backtest-py-prepare-155).


<a id="interactions"></a>
## 6. 다른 모듈과의 상호작용

시장 DB의 실제 SQL 읽기는 [AnalysisReadersMixin](../../backend/db/analysis_readers.py)입니다. 가격·환율은 양끝 포함, 뉴스 발행시각·공시 이용 가능일 창은 끝 제외로 전달됩니다. 뉴스 제목 중복 제거, 공시 중요도 우선·수정 제외는 Repository가 수행합니다.

품질 판정은 [pipeline.quality](../../backend/pipeline/quality.py), 사전 버전·검색은 [pipeline.descriptor](../../backend/pipeline/descriptor.py), 티커/통화 정규화는 [normalizer](../../backend/pipeline/normalizer.py)를 재사용합니다. 함수명에 yfinance_symbol이 있어도 표기 규칙을 뜻하며 분석 중 수집 API를 호출하는 것은 아닙니다.

[M1](m1_request_구현보고서.md)은 날짜·환산·점검, [M3](m3_selection_구현보고서.md)은 검색과 지표, [M4](m4_portfolio_구현보고서.md)는 추정·근거, [M5](m5_backtest_report_구현보고서.md)는 체결 패널·인용 색인, [M6](m6_tracking_구현보고서.md)는 필수 가격·새 날짜 근거를 소비합니다.

<a id="verification"></a>
## 7. 오류·제약과 검증 근거

시점 보호는 끝 날짜 검증에 강점이 있지만 입력 자료의 완전한 과거 상태까지 복원하지는 않습니다. 사전 대체 파일·고정 분류·현재 종목 마스터의 생존 편향을 따로 봐야 합니다. 저수준 MarketData.bars보다 분석용 MarketDataView 경로가 정보 마감 보호의 경계입니다.

환율 시계열은 최초 자료 이전 구간에 뒤채움을 적용할 수 있고 뉴스 창 캐시는 per_ticker를 키에 넣지 않습니다. first_dates는 DB 전체 상장일이 아닌 현재 적재 범위의 첫 관측일입니다. 기업 근거용 90일 공시와 의견용 45일 공시는 서로 다른 호출 조건입니다. 재무 가용 시작일 설정은 미국 2010-04-01, 한국 2005-06-01이며 일부 오래된 안내 문구의 날짜와 다릅니다.

### 관련 테스트

아래는 테스트 소스에서 확인한 검증 시나리오입니다. 이번 문서 작성에서는 금융 DB·유료 LLM·시나리오 워커를 실행하지 않았으며, 테스트 통과를 새로 보증하는 기록으로 사용하지 않습니다.

- [test_market_data.py](../../backend/tests/analysis/test_market_data.py): USD 환산·합집합 달력·미래 조회 차단·품질·창 첫날 휴장·공시 필터·캐시 재적재 방지.

### 문서 검증

구문 분석 정의 목록과 대조하여 이 보고서의 클래스 5개와 함수/메서드 73개를 모두 설명했습니다. 상대경로 링크와 내부 앵커를 별도로 확인합니다.

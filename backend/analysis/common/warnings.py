"""실행 경고의 한 가지 계약 (라운드 4).

- 경고 하나 = {stage, code, level, message_ko, count, dates, details}.
- level: user = 사용자가 조건을 바꾸거나 알아야 하는 것(단계가 "경고 있음"이 됨) / info = 참고(파일에만) / debug = 개발자용 원문(파일에만).
- 같은 종류(code + key)는 하나로 합쳐 "… (151회, 2009-12-31~2015-10-01)" 로 보여 준다.
- 모듈들이 내는 영어 문자열은 `from_text()` 가 코드로 바꾼다(모듈 산출물의 warnings 목록은 그대로 두어 파일에는 원문이 남는다).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from backend.analysis.common.labels import sector_ko, usd_ko

Level = Literal["user", "info", "debug"]


@dataclass
class Warning:
    stage: str
    code: str
    level: Level
    message_ko: str
    count: int = 1
    dates: list[str] = field(default_factory=list)
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# code → (level, 한국어 템플릿). {…} 는 make() 의 키워드.
CATALOG: dict[str, tuple[Level, str]] = {
    # 행동 필요
    "must_include_not_in_universe": ("user", "필수 포함 종목 {tickers}은(는) 선택한 유니버스에 없어 반영하지 못했습니다."),
    "exclude_sector_unknown": ("user", "제외 섹터 '{names}'은(는) GICS 섹터 이름과 맞지 않아 적용하지 못했습니다."),
    "too_few_candidates": ("user", "테마 후보가 {n}개로 목표 종목 수 {target}개보다 적습니다. 테마를 넓히거나 목표 종목 수를 줄여 보세요."),
    # '후보 조건' 을 함께 적는다: 시작일 재선정에서는 그날 거래대금·상장일 조건에서 먼저 빠진다 (011: 9개 모두 테마 판정은 통과했는데 거래대금으로 7개가 빠졌다)
    "too_few_with_metric": ("user", "후보 조건(시가총액·거래대금 등)과 테마 판정을 통과하고 선정 지표({metric}) 자료가 있는 종목이 {n}개로 목표 {target}개보다 적어 {selected}개만 선정했습니다. 최소 종목 수에 못 미치면 결론 라벨에 '종목 수 부족' 으로 표시합니다."),
    # 원인·해결을 사실대로 (2026-11 QA 002: 2종목 × 종목당 25% 라 섹터 상한과 무관한데 '섹터 상한을 올리면 해소' 라고 했다).
    # 현금은 최소 현금까지 더한 전체 비율 (F19: 예전에는 상한 때문에 남는 몫만 적어 최소 현금 15% 를 빼고 말했다)
    "weight_capacity": ("user", "{who}로는 투자금의 {cap}까지만 배분할 수 있어 현금이 {cash} 남습니다{mc_note}. {fix}"),
    "must_include_forced": ("user", "필수 포함 종목 {tickers}은(는) 테마 판정 또는 선정 지표 기준에 맞지 않지만 요청에 따라 포함했습니다."),
    "sector_preference_skipped": ("user", "섹터 상한({cap}) 안에서 투자금을 다 배분하려고 한 섹터에서는 {pref}종목까지만 먼저 골라, 선정 지표 순위가 더 높은 {tickers}(섹터별 {sector})은(는) 빼고 다른 섹터 종목{subs}으로 채웠습니다. 섹터 상한을 올리면 순위대로 고를 수 있습니다."),
    # 필수 포함 사유를 사실대로 (2026-11 QA: 지표 자료가 없을 뿐인데 '기준에 맞지 않지만' 이라고 써서 리포트가 '고배당 기준에 못 미친다' 고 오해)
    "must_include_out_of_range": ("user", "필수 포함 종목 {tickers}은(는) 선정 지표가 자격선 밖({detail})이지만 요청에 따라 포함했습니다."),
    "too_few_eligible": ("user", "선정 지표가 자격선 안에 드는 종목이 {n}개라 목표 {target}개를 다 채우지 못했습니다 (자격선 밖 {n_out}개 제외: {examples}). {cash_clause}"),
    "must_include_no_metric": ("user", "필수 포함 종목 {tickers}은(는) 선정 지표 자료가 없어{why} 순위를 매기지 못했지만 요청에 따라 포함했습니다."),
    "must_include_off_theme": ("user", "필수 포함 종목 {tickers}은(는) 테마 판정을 통과하지 못했지만 요청에 따라 포함했습니다."),
    "must_include_excluded_theme": ("user", "필수 포함 종목 {tickers}은(는) 제외 테마({theme})에 해당하지만 요청에 따라 포함했습니다."),
    # 최소 시가총액은 하드 필터 (2026-11 사용자 정책): 확인할 수 없는 종목은 뺀다. 팀 DB 는 XOM·BLK 같은 대형주도 과거 시가총액이 비어 있어 과거 시점에 빠지므로 알린다
    "min_mcap_missing": ("user", "시가총액 자료가 없어 최소 시가총액({min})을 확인할 수 없는 {n}개 종목({tickers})은 후보에서 뺐습니다."),
    "mcap_estimated": ("user", "시가총액 자료가 빈 {n}개 종목({tickers})은 직전에 알려진 주식수(최대 {days} 전)에 그날 종가를 곱해 시가총액을 추정했습니다."),
    "must_include_short_history": ("user", "필수 포함 종목 {tickers}은(는) 기준일 이전 가격 이력이 1년이 안 되지만 요청에 따라 포함했습니다 (이력이 모자라면 비중을 줄 수 없을 수 있습니다)."),
    "backtest_start_shifted": ("user", "{text}"),
    "fewer_holdings_at_start": ("user", "{text}"),
    "backtest_start_clamped": ("user", "{text}"),  # 요청한 백테스트 시작이 재무 지표 자료 시작 전이라 뒤로 옮김 (사용자가 기간을 다시 정할 수 있음)
    "selection_lookahead": ("user", "백테스트 시작일에 종목을 다시 고르지 않고 현재 선정 종목을 그대로 썼습니다 (선정 시점의 선견 편향이 있을 수 있습니다)."),
    "ticker_dropped_history": ("user", "{tickers}은(는) 백테스트 시작일 이전 가격 이력이 부족해 백테스트에서 제외했습니다."),
    "added_tickers_ignored": ("user", "추가 요청 종목 {tickers}은(는) 유니버스에 없어 반영하지 못했습니다."),
    "model_dropped": ("user", "{tickers}은(는) 추정 창 안 수익률 자료가 부족해 시장모형과 비중에서 제외했습니다."),
    "optimizer_failed_no_tilt": ("user", "뉴스 뷰 비중 최적화가 수렴하지 않아 해당 시점에는 뷰를 반영하지 않고 기준 비중을 사용했습니다."),
    "excluded_by_data_quality": ("user", "가격 자료 품질 기준에 미달한 {tickers}을(를) 백테스트에서 제외하고 나머지 비중을 다시 맞췄습니다."),
    "no_portfolio_passed": ("user", "모든 포트폴리오가 필수 검증 규칙을 통과하지 못했습니다. 미통과 규칙: {rules}. 허용 낙폭·목표를 조정하거나 현금 혼합안을 검토해 보세요."),
    "alternative_skipped": ("user", "조건을 통과한 포트폴리오가 없고 현금 혼합안도 만들 수 없었습니다 ({reason})."),
    "matched_floor": ("user", "과거 최대낙폭을 낙폭 맞춤 목표({target}) 안으로 맞추려면 주식 비중을 {floor}보다 더 줄여야 해서 낙폭 맞춤안(주식 + 현금)을 만들지 않았습니다. 주식이 너무 적은 구성은 후보로 두지 않습니다."),
    # 참고 (파일에만)
    "descriptor_version_fallback": ("info", "{text}"),
    "gics_draft": ("info", "{text}"),
    "derived_note": ("info", "{text}"),
    "gics_widened": ("info", "테마에 직접 일치하는 종목이 적어 GICS 분류를 한 단계 넓혀 검색했습니다 (후보 {n}개)."),
    "market_cap_missing": ("info", "시가총액 자료가 없는 종목은 시가총액비중에서 0으로 처리했습니다 ({tickers})."),
    "lookback_short": ("info", "백테스트 시작일 {date} 이전 가격 이력이 공분산 추정 창({days}거래일)보다 짧아 추정 창이 줄어듭니다."),
    "window_clamped": ("info", "{text}"),
    "fx_reconverted": ("info", "백테스트 초기자본은 시작일 환율({date}, 1 USD = {rate} KRW)로 환산한 {usd} USD입니다 (기준일 환율 기준 {usd0} USD)."),
    "news_thin_fallback": ("info", "뉴스·공시가 있는 종목이 최소 {min}개에 못 미쳐 뉴스 뷰 없이 기준 비중을 사용했습니다."),
    "views_none_valid": ("info", "분석 모델이 만든 뷰가 코드 검사를 모두 통과하지 못해 기준 비중을 사용했습니다."),
    "short_window": ("info", "백테스트 창이 {days}거래일로 짧아(1.5년 미만) 연환산 지표는 참고용이고 목표수익(R2)·변동성(R7) 규칙도 참고로만 평가했습니다."),
    "data_quality_note": ("info", "{text}"),
    "data_quality_filled": ("info", "가격 결측을 직전값으로 채운 종목: {tickers}."),
    # 개발자용
    "legacy_note": ("debug", "{text}"),
}

_DATE = r"\d{4}-\d{2}-\d{2}"
# (정규식, code, 그룹 → 키워드)  영어 원문 → 코드. 위에서부터 처음 맞는 것.
_LEGACY: list[tuple[re.Pattern[str], str, tuple[str, ...]]] = [
    (re.compile(r"^must_include ticker (\S+) not in universe"), "must_include_not_in_universe", ("tickers",)),
    (re.compile(r"^exclude_sectors: unknown sector name '?([^']+)'?"), "exclude_sector_unknown", ("names",)),
    (re.compile(r"^only (\d+) candidates for target (\d+)"), "too_few_candidates", ("n", "target")),
    (re.compile(r"^only (\d+) tickers have (\S+); target (\d+) -> selecting (\d+)"), "too_few_with_metric", ("n", "metric", "target", "selected")),
    (re.compile(r"^only (\d+) tickers within eligibility for (\S+); target (\d+) \(excluded (\d+) out of range: (.*?)\)(?: \[capacity ([\d.]+) of ([\d.]+)\])?$"), "too_few_eligible",
     ("n", "metric", "target", "n_out", "examples", "cap", "investable")),
    (re.compile(r"^weight capacity ([\d.]+) < ([\d.]+): .*?\(cap needed ([\d.]+|None)(?:; stock (\d+)%, sector (\d+)%, (\d+) names)?\)"), "weight_capacity",
     ("cap", "investable", "needed", "stock_pct", "sector_pct", "n")),
    (re.compile(r"^caps allow at most (\d+)% invested \(stock (\d+)%, sector (\d+)%, (\d+) names(?:, investable (\d+)%)?\)"), "weight_capacity",
     ("cap_pct", "stock_pct", "sector_pct", "n", "investable_pct")),
    (re.compile(r"^sector count preference \((\d+)/sector, sector cap (\d+%)\) skipped higher-ranked \[([^\]]*)\] \(([^)]*)\)(?: for lower-ranked names in other sectors \[([^\]]*)\])?"), "sector_preference_skipped",
     ("pref", "cap", "tickers", "sector", "subs")),
    (re.compile(r"^must_include (\S+): metric_out_of_range\(([^)]*)\)"), "must_include_out_of_range", ("tickers", "detail")),
    (re.compile(r"^must_include (\S+): metric_missing( \(eps<=0)?"), "must_include_no_metric", ("tickers", "why")),
    (re.compile(r"^must_include (\S+): insufficient price history"), "must_include_short_history", ("tickers",)),
    (re.compile(r"^(\S+): must_include matches excluded theme (.+?) -> "), "must_include_excluded_theme", ("tickers", "theme")),
    (re.compile(r"^must_include (\S+): "), "must_include_forced", ("tickers",)),
    (re.compile(r"^(\S+): must_include but not in theme"), "must_include_off_theme", ("tickers",)),
    (re.compile(r"^original selection used at an earlier date"), "selection_lookahead", ()),
    (re.compile(r"^(\S+) dropped: insufficient history before"), "ticker_dropped_history", ("tickers",)),
    (re.compile(r"^added_tickers not in universe ignored: (.+)"), "added_tickers_ignored", ("tickers",)),
    (re.compile(r"^dropped from model \(insufficient returns in window\): (.+)"), "model_dropped", ("tickers",)),
    (re.compile(r"^excluded by data quality \(weights renormalized\): (.+)"), "excluded_by_data_quality", ("tickers",)),
    (re.compile(r"^no portfolio passed the hard rules \(fail counts by rule: (.+)\)"), "no_portfolio_passed", ("rules",)),
    (re.compile(r"^alternative skipped: (.+)"), "alternative_skipped", ("reason",)),
    (re.compile(r"^matched variant skipped for \S+: stocks below floor (\S+) would be needed to bring max drawdown within (\S+) "), "matched_floor", ("floor", "target")),
    (re.compile(r"^fewer than target after matching; widened GICS codes one level up -> (\d+)"), "gics_widened", ("n",)),
    # 후보 단계 시가총액 하드 필터 (retrieve.mcap_warnings). 아래 시장모형 참고('market cap missing for …: treated as 0')와 앞말이 달라 서로 가리지 않는다
    (re.compile(r"^min market cap ([\d.]+) USD: dropped (\d+) candidates without market cap data \[([^\]]*)\]"), "min_mcap_missing", ("min", "n", "tickers")),
    (re.compile(r"^market cap estimated from last known shares \(within (\d+) days\) for \[([^\]]*)\]"), "mcap_estimated", ("days", "tickers")),
    (re.compile(r"^market cap (?:unavailable|missing for) ?(.*)"), "market_cap_missing", ("tickers",)),
    (re.compile(r"^less than (\d+) trading days of history before (\S+)"), "lookback_short", ("days", "date")),
    (re.compile(r"^backtest (?:start|end)_date .* clamped"), "window_clamped", ()),
    (re.compile(r"^capital re-converted at (\S+) FX ([\d.]+): ([\d,]+) USD vs request-date ([\d,]+) USD"), "fx_reconverted", ("date", "rate", "usd", "usd0")),
    (re.compile(r"^window of (\d+) trading days <"), "short_window", ("days",)),
    (re.compile(r"있는 종목 (\d+)개 < 최소 (\d+)개"), "news_thin_fallback", ("n", "min")),
    (re.compile(r"유효한 뷰가 하나도 남지 않아"), "views_none_valid", ()),
    (re.compile(r"^백테스트 시작일 .* 로 (?:자동으로 )?옮김"), "backtest_start_shifted", ()),  # 동의 이동 · 1종목 이하 자동 이동 (정책 결정 4)
    (re.compile(r"^백테스트 시작일 .* 그 종목으로 시작합니다"), "fewer_holdings_at_start", ()),
    (re.compile(r"^GICS 분류 검수 대기"), "gics_draft", ()),
    (re.compile(r"이전 사전 버전이 없어"), "descriptor_version_fallback", ()),
    (re.compile(r".*(?:재무 지표|시가총액) 자료가 .* 로 옮김"), "backtest_start_clamped", ()),
    (re.compile(r"^(기준일 .* 로 옮김|백테스트 시작일 .* 로 줄임)"), "derived_note", ()),
]
_SCREEN_AT = re.compile(r"^(?:screen|start)@(" + _DATE + r"): (.+)$")  # screen@ = 07 시작일 재선정, start@ = 10 시작일 구성
_DATE_PREFIX = re.compile(r"^(" + _DATE + r"): (.+)$")
RULE_KO = {"R1": "최대낙폭", "R2": "목표수익", "R3": "비교지수 대비", "R4": "종목 상한", "R4b": "종목 상한(드리프트)", "R5": "섹터 상한", "R5b": "섹터 상한(드리프트)", "R6": "종목 수", "R7": "변동성 적합", "R8": "기타"}


def make(stage: str, code: str, *, dates: list[str] | tuple[str, ...] = (), details: dict[str, Any] | None = None, **fmt: Any) -> Warning:
    level, tmpl = CATALOG.get(code, ("debug", "{text}"))
    if code not in CATALOG:
        fmt.setdefault("text", f"{code}")
        code = "legacy_note"
    try:
        msg = tmpl.format(**{k: _fmt_value(v) for k, v in fmt.items()}) if fmt else tmpl
    except (KeyError, IndexError):
        msg = tmpl
    if "{" in msg and "}" in msg:  # 채우지 못한 자리표시자
        msg = fmt.get("text") or re.sub(r"\{[^}]*\}", "…", msg)
    return Warning(stage=stage, code=code, level=level, message_ko=msg, dates=sorted({str(d) for d in dates}), details=details or ({"text": fmt["text"]} if "text" in fmt and code == "legacy_note" else None))


def _fmt_value(v: Any) -> str:
    if isinstance(v, (list, tuple, set)):
        return ", ".join(str(x) for x in v)
    return str(v)


def from_text(stage: str, text: str, *, dates: list[str] | None = None) -> Warning:
    """모듈이 낸 (대개 영어) 경고 문자열을 코드로 바꾼다. 모르는 문자열은 debug 로 보존."""
    text = str(text).strip()
    dates = sorted(set(dates or []))
    m = _SCREEN_AT.match(text)
    if m:  # 07 단계(백테스트 시작일 재선정)의 선정 경고: 기준일 선정과 헷갈리지 않게 시점을 앞에 적는다 (라운드 5)
        w = from_text(stage, m.group(2), dates=[*dates, m.group(1)])
        # 사용자에게 보이는 공지는 모두 시점을 붙인다 (예전에는 too_few_* 만 → 필수 포함 공지가 기준일 선정 얘기로 읽혔다, 098 현대차)
        if w.level == "user" and not w.message_ko.startswith("백테스트 시작일"):
            w.message_ko = f"백테스트 시작일({m.group(1)}) 기준: {w.message_ko}"
        k = (w.details or {}).get("key")
        if w.details is not None and (k is None or str(k).startswith("@now")):  # 같은 날 같은 사실(07 선정·10 구성의 배분 가능 비율)은 하나로 합친다
            w.details["key"] = f"@{m.group(1)}" + (str(k)[len("@now"):] if k else "")
        return w
    m = _DATE_PREFIX.match(text)
    if m and not text.startswith("백테스트 시작일"):
        return from_text(stage, m.group(2), dates=[*dates, m.group(1)])
    for rx, code, keys in _LEGACY:
        m = rx.search(text)
        if not m:
            continue
        kw: dict[str, Any] = {k: m.group(i + 1) for i, k in enumerate(keys) if i + 1 <= rx.groups}
        if code == "weight_capacity":
            kw.update(_capacity_words(kw))
        if code == "too_few_eligible":  # 남는 비중이 정말 있을 때만 '현금' (배분 가능 비율을 모르는 예전 원문은 가능성으로)
            try:
                short = float(kw["cap"]) < float(kw["investable"]) - 1e-9
                kw["cash_clause"] = "남는 비중은 현금으로 둡니다." if short else f"선정한 {kw['n']}종목에 투자금을 나눠 담습니다."
            except (TypeError, ValueError, KeyError):
                kw["cash_clause"] = "종목 수가 적으면 종목·섹터 상한 때문에 현금이 남을 수 있습니다."
        if code == "no_portfolio_passed":
            found = re.findall(r"'(R\d+b?)': (\d+)", kw.get("rules", ""))
            kw["rules"] = ", ".join(f"{RULE_KO.get(r, r)}({r}) {n}개" for r, n in found) or kw.get("rules", "")
        if code == "sector_preference_skipped":  # 시작일 재선정은 20개 넘게 빠지기도 한다 → 앞 5개 + '외 N개'
            names = [x.strip().strip("'\"") for x in kw.get("tickers", "").split(",") if x.strip()]
            kw["tickers"] = ", ".join(names[:5]) + (f" 외 {len(names) - 5}개" if len(names) > 5 else "")
            pairs = [x.rsplit(":", 1) for x in kw.get("sector", "").split(";") if ":" in x]
            if pairs:  # 'Industrials: 2; Utilities: 1' → '산업재 2개, 유틸리티 1개'
                kw["sector"] = ", ".join(f"{sector_ko(a.strip())} {b.strip()}개" for a, b in pairs)
            subs = [x.strip().strip("'\"") for x in (kw.get("subs") or "").split(",") if x.strip()]
            kw["subs"] = f"({', '.join(subs[:5])}" + (f" 외 {len(subs) - 5}개" if len(subs) > 5 else "") + ")" if subs else ""
        if code in ("min_mcap_missing", "mcap_estimated"):  # 과거 시점에는 앞쪽이 빈 종목이 열 개 넘게 빠지기도 한다 → 앞 5개 + '외 N개'
            names = [x.strip().strip("'\"") for x in kw.get("tickers", "").split(",") if x.strip()]
            kw["tickers"] = ", ".join(names[:5]) + (f" 외 {len(names) - 5}개" if len(names) > 5 else "")
            kw["n"] = len(names)
            if code == "min_mcap_missing":
                kw["min"] = usd_ko(float(kw["min"]))
            else:  # 설정(mcap_fallback_max_days)을 바꿔도 문구가 맞게 원문의 일수로: 730 → '2년'
                days = int(kw.get("days") or 0)
                kw["days"] = f"{days // 365}년" if days and days % 365 == 0 else f"{days}일"
        if code == "must_include_no_metric":  # 적자 여부는 PER 에서만 안다 (배당·ROE·모멘텀은 그냥 자료 없음)
            kw["why"] = "(적자이거나 재무 자료 없음)" if kw.get("why") else ""
        if code == "must_include_out_of_range":
            kw["detail"] = _out_of_range_ko(kw.get("detail", ""))
        if code == "too_few_with_metric":
            kw["metric"] = {"return_12m_1m": "모멘텀", "pe_ttm": "PER", "roe_ttm": "ROE", "vol_60d": "변동성", "dividend_yield_ttm": "배당수익률"}.get(kw["metric"], kw["metric"])
        if code in ("backtest_start_shifted", "backtest_start_clamped", "fewer_holdings_at_start", "gics_draft", "descriptor_version_fallback", "derived_note", "window_clamped"):
            kw["text"] = text
        w = make(stage, code, dates=dates, **kw)
        # 기준일 배분 가능 비율은 05 선정·10f 구성이 같은 사실을 따로 낸다 → 하나로 (먼저 나온 05 문장이 해결 방법이 더 구체적)
        w.details = {"text": text, "key": kw.get("tickers") or kw.get("names") or (f"@now:{kw.get('cap')}" if code == "weight_capacity" else None)}
        return w
    return Warning(stage=stage, code="legacy_note", level="debug", message_ko=text, dates=dates, details={"text": text})


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _out_of_range_ko(detail: str) -> str:
    """'roe_ttm=-0.1572, 범위 >0 ≤10' → 'ROE -15.7%, 자격선 0% 초과 1,000% 이하' (리포트 제외 사유와 같은 말, 009: 원문 소수가 공지에 그대로 나왔다).
    못 읽는 원문은 지표 이름만 바꾼다."""
    from backend.analysis.m2_data import metrics as M  # 늦은 import: metrics → market_data 를 경고 모듈이 처음부터 끌어오지 않게

    m = re.match(r"^(\w+)=([-+\d.eE]+)", detail)
    if m and m.group(1) in M.ELIGIBLE_RANGE:
        try:
            met, v = m.group(1), float(m.group(2))
            return f"{M.METRIC_SHORT_KO.get(met, met)} {M.display_metric(met, v)}, 자격선 {M.eligible_range_ko(met)}"
        except ValueError:
            pass
    return re.sub(r"^(\w+)=", lambda mm: {"pe_ttm": "PER ", "roe_ttm": "ROE ", "dividend_yield_ttm": "배당수익률 "}.get(mm.group(1), mm.group(1) + " "), detail)


def _capacity_words(kw: dict[str, Any]) -> dict[str, str]:
    """배분 가능 비율 경고의 숫자 → 문장 조각 (n, stock, sector, cap, cash, mc_note, fix)."""
    try:
        if kw.get("cap_pct") is not None:  # 시장모형(10 단계): 퍼센트 정수
            cap = float(kw["cap_pct"]) / 100
            inv = float(kw["investable_pct"]) / 100 if kw.get("investable_pct") else None
        else:  # 정량 선정(05·07 단계): 소수
            cap, inv = float(kw["cap"]), float(kw["investable"])
    except (TypeError, ValueError, KeyError):
        return {"who": "선정 종목의 섹터 구성", "cap": "일부", "cash": "일부", "mc_note": "", "fix": "상한을 올리거나 테마를 넓히면 해소됩니다."}
    stock = float(kw["stock_pct"]) / 100 if kw.get("stock_pct") else None
    sector = float(kw["sector_pct"]) / 100 if kw.get("sector_pct") else None
    n = int(kw["n"]) if kw.get("n") else None
    needed = kw.get("needed")
    min_cash = max(0.0, 1.0 - inv) if inv is not None else 0.0
    if needed not in (None, "None"):
        fix = f"섹터 상한을 {_pct(float(needed))}로 올리거나 테마를 넓혀 다른 섹터 종목을 늘리면 해소됩니다."
    elif needed == "None" or (n is not None and stock is not None and inv is not None and n * stock < inv - 1e-9):
        fix = "종목 수가 적어 섹터 상한만 올려서는 해소되지 않습니다. 종목당 상한을 올리거나 테마를 넓혀 종목 수를 늘려 보세요."
    else:
        fix = "섹터 상한을 올리거나 테마를 넓혀 다른 섹터 종목을 늘리면 해소됩니다."
    who = (f"선정 종목 {n}개(종목당 상한 {_pct(stock)}, 섹터당 상한 {_pct(sector)})" if n is not None and stock is not None and sector is not None
           else "선정 종목의 섹터 구성")  # 예전 형식 원문(숫자 없음)
    return {"who": who, "cap": _pct(cap), "cash": _pct(1.0 - cap), "mc_note": f" (최소 현금 {_pct(min_cash)} 포함)" if min_cash > 0.004 else "", "fix": fix}  # fmt: skip


def merge(ws: list[Warning]) -> list[Warning]:
    """같은 (code, key) 를 하나로: count 합산, dates 합집합, 종목 목록 합집합. 첫 등장 순서 유지."""
    out: list[Warning] = []
    idx: dict[tuple[str, Any], int] = {}
    for w in ws:
        k2 = (w.details or {}).get("key")
        # 종목 키가 없는 코드(weight_capacity·too_few_*)는 문장까지 같아야 합친다 — 날짜·숫자가 다른 공지를 첫 문장 하나로 덮지 않게.
        # 시작일 재선정 공지('백테스트 시작일(…) 기준:')는 기준일 공지와 따로 둔다.
        key = (w.code, w.message_ko if (w.code == "legacy_note" or k2 is None) else (k2, w.message_ko.startswith("백테스트 시작일")))
        if key in idx:
            g = out[idx[key]]
            if not str(k2 or "").startswith("@"):  # '@날짜' 키 = 다른 단계가 같은 날의 같은 사실을 다시 낸 것 → 횟수로 세지 않는다
                g.count += w.count
            g.dates = sorted(set(g.dates) | set(w.dates))
            continue
        idx[key] = len(out)
        out.append(Warning(**{**w.to_dict(), "dates": list(w.dates), "details": dict(w.details) if w.details else None}))
    return out


def render(w: Warning) -> str:
    if w.count <= 1 and len(w.dates) <= 1:
        return w.message_ko + (f" ({w.dates[0]})" if w.dates and w.level != "user" else "")
    span = f", {w.dates[0]}~{w.dates[-1]}" if w.dates else ""
    return f"{w.message_ko} ({w.count}회{span})"


def by_level(ws: list[Warning], *levels: str) -> list[Warning]:
    return [w for w in ws if w.level in levels]

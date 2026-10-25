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
    "too_few_with_metric": ("user", "선정 지표({metric}) 자료가 있는 종목이 {n}개로 목표 {target}개보다 적어 {selected}개만 선정했습니다. 최소 종목 수에 못 미치면 결론 라벨과 리포트에 그 사실을 표시합니다."),
    "weight_capacity": ("user", "선정 종목의 섹터 구성으로는 종목·섹터 상한 안에서 투자금 전체를 배분할 수 없어 일부({cash})를 현금으로 둡니다. 섹터 상한을 올리거나 테마를 넓히면 해소됩니다."),
    "must_include_forced": ("user", "필수 포함 종목 {tickers}은(는) 테마 판정 또는 선정 지표 기준에 맞지 않지만 요청에 따라 포함했습니다."),
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
    (re.compile(r"^weight capacity ([\d.]+) < ([\d.]+)"), "weight_capacity", ("cap", "investable")),
    (re.compile(r"^caps allow at most (\d+)% invested .*?(\d+)% kept as cash"), "weight_capacity", ("cap_pct", "cash_pct")),
    (re.compile(r"^must_include (\S+): "), "must_include_forced", ("tickers",)),
    (re.compile(r"^(\S+): must_include but not in theme"), "must_include_forced", ("tickers",)),
    (re.compile(r"^original selection used at an earlier date"), "selection_lookahead", ()),
    (re.compile(r"^(\S+) dropped: insufficient history before"), "ticker_dropped_history", ("tickers",)),
    (re.compile(r"^added_tickers not in universe ignored: (.+)"), "added_tickers_ignored", ("tickers",)),
    (re.compile(r"^dropped from model \(insufficient returns in window\): (.+)"), "model_dropped", ("tickers",)),
    (re.compile(r"^excluded by data quality \(weights renormalized\): (.+)"), "excluded_by_data_quality", ("tickers",)),
    (re.compile(r"^no portfolio passed the hard rules \(fail counts by rule: (.+)\)"), "no_portfolio_passed", ("rules",)),
    (re.compile(r"^alternative skipped: (.+)"), "alternative_skipped", ("reason",)),
    (re.compile(r"^fewer than target after matching; widened GICS codes one level up -> (\d+)"), "gics_widened", ("n",)),
    (re.compile(r"^market cap (?:unavailable|missing for) ?(.*)"), "market_cap_missing", ("tickers",)),
    (re.compile(r"^less than (\d+) trading days of history before (\S+)"), "lookback_short", ("days", "date")),
    (re.compile(r"^backtest (?:start|end)_date .* clamped"), "window_clamped", ()),
    (re.compile(r"^capital re-converted at (\S+) FX ([\d.]+): ([\d,]+) USD vs request-date ([\d,]+) USD"), "fx_reconverted", ("date", "rate", "usd", "usd0")),
    (re.compile(r"^window of (\d+) trading days <"), "short_window", ("days",)),
    (re.compile(r"있는 종목 (\d+)개 < 최소 (\d+)개"), "news_thin_fallback", ("n", "min")),
    (re.compile(r"유효한 뷰가 하나도 남지 않아"), "views_none_valid", ()),
    (re.compile(r"^백테스트 시작일 .* 로 옮김"), "backtest_start_shifted", ()),
    (re.compile(r"^백테스트 시작일 .* 그 종목으로 시작합니다"), "fewer_holdings_at_start", ()),
    (re.compile(r"^GICS 분류 검수 대기"), "gics_draft", ()),
    (re.compile(r"이전 사전 버전이 없어"), "descriptor_version_fallback", ()),
    (re.compile(r".*재무 지표 자료가 .* 로 옮김"), "backtest_start_clamped", ()),
    (re.compile(r"^(기준일 .* 로 옮김|백테스트 시작일 .* 로 줄임)"), "derived_note", ()),
]
_SCREEN_AT = re.compile(r"^screen@(" + _DATE + r"): (.+)$")
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
        if w.code in ("too_few_with_metric", "too_few_candidates") and not w.message_ko.startswith("백테스트 시작일"):
            w.message_ko = f"백테스트 시작일({m.group(1)}) 기준: {w.message_ko}"
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
            if "cash_pct" in kw:
                kw["cash"] = f"{kw['cash_pct']}%"
            else:
                try:
                    kw["cash"] = f"{(float(kw['investable']) - float(kw['cap'])) * 100:.0f}%"
                except (ValueError, KeyError):
                    kw["cash"] = "일부"
        if code == "no_portfolio_passed":
            found = re.findall(r"'(R\d+b?)': (\d+)", kw.get("rules", ""))
            kw["rules"] = ", ".join(f"{RULE_KO.get(r, r)}({r}) {n}개" for r, n in found) or kw.get("rules", "")
        if code == "too_few_with_metric":
            kw["metric"] = {"return_12m_1m": "모멘텀", "pe_ttm": "PER", "roe_ttm": "ROE", "vol_60d": "변동성", "dividend_yield_ttm": "배당수익률"}.get(kw["metric"], kw["metric"])
        if code in ("backtest_start_shifted", "backtest_start_clamped", "fewer_holdings_at_start", "gics_draft", "descriptor_version_fallback", "derived_note", "window_clamped"):
            kw["text"] = text
        w = make(stage, code, dates=dates, **kw)
        w.details = {"text": text, "key": kw.get("tickers") or kw.get("names")}
        return w
    return Warning(stage=stage, code="legacy_note", level="debug", message_ko=text, dates=dates, details={"text": text})


def merge(ws: list[Warning]) -> list[Warning]:
    """같은 (code, key) 를 하나로: count 합산, dates 합집합, 종목 목록 합집합. 첫 등장 순서 유지."""
    out: list[Warning] = []
    idx: dict[tuple[str, Any], int] = {}
    for w in ws:
        key = (w.code, (w.details or {}).get("key") if w.code != "legacy_note" else w.message_ko)
        if key in idx:
            g = out[idx[key]]
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

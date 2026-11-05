"""M3-02 후보 검색기 (코드). IntentSpec 의 GICS 코드·키워드·예시 티커로 사전을 검색하고 하드 필터를 적용한다.

규칙: gics_match / keyword_match(서로 다른 키워드 2개 이상) / example_match / must_include.
하드 필터: exclude_tickers·exclude_sectors·exclude_theme_rules·asset_types·시가총액(빈 날은 마지막 주식수로 추정, 그래도 없으면 제외)·거래대금·가격 이력.
같은 회사의 복수 주식 클래스(GOOG·GOOGL)는 유동성이 큰 하나만 남긴다 (MVP 결함 4).
후보 상한(120)은 일치 규칙 수 → 거래대금 순으로 자른다.
"""

from __future__ import annotations

import re

import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

import pandas as pd

from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data import metrics as M
from backend.analysis.m2_data.market_data import MarketDataView
from backend.analysis.schemas.intent import IntentSpec
from backend.analysis.schemas.selection import Candidate, Candidates, FilteredOut
from backend.pipeline.descriptor import Descriptor

MAX_CANDIDATES = 120  # 기본 상한 (settings.selection.max_candidates 로 덮어씀)
BROAD_THEME_MIN_SECTORS = 6  # 테마 GICS 가 이 수 이상의 섹터에 걸치면(또는 GICS 없음) '넓은 테마' → 상한을 선정 지표 순으로 자른다 (라운드 5)
_DEFAULT = object()
MIN_KEYWORD_HITS = 2
MIN_HISTORY_DAYS = 400  # as_of 이전 가격 이력 (달력일): 12개월 지표 계산용
ADV_WINDOW = 60


def _collect(desc: Descriptor, themes: list[dict[str, Any]]) -> dict[str, dict[str, set[str]]]:
    hits: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"matched_by": set(), "matched_themes": set(), "matched_keywords": set()})
    for th in themes:
        for e in desc.filter_by_gics(th.get("gics_codes", [])):
            t = e["yfinance_symbol"]
            hits[t]["matched_by"].add("gics_match")
            hits[t]["matched_themes"].add(th["id"])
        for m in desc.search_keywords(th.get("keywords", []), min_distinct=1):
            t = m.entry["yfinance_symbol"]
            hits[t]["matched_by"].add("keyword_match")
            hits[t]["matched_themes"].add(th["id"])
            hits[t]["matched_keywords"].update(m.matched)
        for t in th.get("example_tickers", []):
            if desc.by_ticker(t):
                sym = desc.by_ticker(t)["yfinance_symbol"]
                hits[sym]["matched_by"].add("example_match")
                hits[sym]["matched_themes"].add(th["id"])
    return hits


_CLASS_RE = re.compile(r"\b(?:class|cl|series)\s+[abc]\b|\b(?:common|ordinary)\s+(?:stock|shares?)\b")
_SUFFIX_RE = re.compile(r"\b(?:inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings?|group)\b")


_NEGATION = re.compile(r"(?:\bnon[- ]?|비|무)$")  # 'non-alcoholic', '비알코올', '무알코올' 의 부정 앞말


def _exclude_keyword_hits(desc: Descriptor, words: list[str]) -> dict[str, set[str]]:
    """제외 테마 키워드가 이름·소개문(GICS 이름 토큰 제외)에서 맞는 종목 → 맞은 키워드 집합. 앞에 부정어가 붙은 것은 세지 않는다."""
    from backend.pipeline.descriptor import _word_pattern

    pats = [(w, _word_pattern(w)) for w in dict.fromkeys(x for x in words if str(x).strip())]
    out: dict[str, set[str]] = {}
    if not pats:
        return out
    for e in desc.stocks:
        text = f"{e.get('name', '')} | {e.get('intro', '')}".lower()
        spans = {w: [(m.start(), m.end()) for m in pat.finditer(text) if not _NEGATION.search(text[max(0, m.start() - 4) : m.start()])] for w, pat in pats}
        # 더 긴 키워드 안에 들어간 일치('tobacco products' 안의 'tobacco')는 따로 세지 않는다 — 한 구절이 2개로 세지면 '2개 이상' 규칙이 무력해진다
        hit = {w for w, sp in spans.items()
               if any(not any(a2 <= a and b <= b2 and (b2 - a2) > (b - a) for w2, sp2 in spans.items() if w2 != w for a2, b2 in sp2) for a, b in sp)}
        if hit:
            out[e["yfinance_symbol"]] = hit
    return out


def _share_class_key(entry: dict[str, Any]) -> str:
    """같은 회사의 주식 클래스를 묶는 키: 회사명에서 괄호·'Class A/C'·'Inc' 등을 뗀 소문자.

    사전의 이름은 "Alphabet Inc. (Class A)" 처럼 괄호 안에 클래스가 있어 예전 문자열 치환(" class a")이 못 잡았다 (GOOG·GOOGL 둘 다 선정되던 원인)."""
    name = str(entry.get("name", "")).lower()
    name = re.sub(r"[().,&'’\-]", " ", name)
    name = _CLASS_RE.sub(" ", name)
    name = _SUFFIX_RE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or entry.get("yfinance_symbol") or entry.get("ticker", "")


def retrieve(
    view: MarketDataView,
    desc: Descriptor,
    intent: IntentSpec | dict[str, Any],
    constraints: dict[str, Any],
    *,
    request_id: str,
    descriptor_version: str | None = None,
    max_candidates: int | None | object = _DEFAULT,
    broad_min_sectors: int = BROAD_THEME_MIN_SECTORS,
    metric_prefilter: bool = True,
    _widen: bool = True,
) -> Candidates:
    """max_candidates=None 이면 상한 없음 (07 재선정·실행 전 점검처럼 뒤에서 교집합을 만드는 호출용).

    GICS 한 단계 넓히기는 시가총액·거래대금 같은 필터를 거친 뒤 후보가 목표보다 적을 때만 한다 (넓혀서 후보가 늘 때만 그 결과를 쓴다).
    예전에는 필터 전 일치 수로 판단해 목표 종목 수가 판단을 바꿨다: 004 에서 목표 25 일 때는 넓혀서 4개, '4개로 줄임' 답 뒤에는
    일치 11개 ≥ 4 라 넓히지 않아 필터 뒤 3개 — 실행 전 점검이 말한 숫자와 실제가 어긋났다 (계획 N-T1-18)."""
    it = intent.model_dump(mode="json") if isinstance(intent, IntentSpec) else intent
    cap = MAX_CANDIDATES if max_candidates is _DEFAULT else max_candidates
    as_of = view.as_of
    cons = constraints
    target = cons["num_holdings"]["target"]
    warnings: list[str] = []
    filtered: list[FilteredOut] = []
    stats: dict[str, Counter] = {"by_rule": Counter(), "by_filter": Counter()}

    themes = it["interpretation"]["themes"]
    hits = _collect(desc, themes)
    for t in cons.get("must_include_tickers", []):
        e = desc.by_ticker(t)
        if e:
            hits[e["yfinance_symbol"]]["matched_by"].add("must_include")
            hits[e["yfinance_symbol"]]["matched_themes"].add("must_include")
        else:
            warnings.append(f"must_include ticker {t} not in universe")
    for h in hits.values():
        for r in h["matched_by"]:
            stats["by_rule"][r] += 1

    sec_code = D.sector_name_to_code(desc)
    excl_sectors = set()
    for s in cons.get("exclude_sectors", []):
        if s in sec_code:
            excl_sectors.add(sec_code[s])
        elif s.isdigit() and len(s) == 2:
            excl_sectors.add(s)
        else:
            warnings.append(f"exclude_sectors: unknown sector name {s!r}")
    excl_by_rule: dict[str, str] = {}
    for r in it.get("exclude_theme_rules", []):
        for e in desc.filter_by_gics(r.get("gics_codes", [])):
            excl_by_rule[e["yfinance_symbol"]] = f"exclude_theme:{r['theme']}(gics)"
        # 키워드 제외는 이름·소개문에서 서로 다른 키워드 2개 이상일 때만 (예전: 1개, GICS 이름 토큰까지 검색 → Caterpillar 를 '화석연료',
        # 콜라 회사를 '주류'('non-alcoholic' 안의 alcoholic)로 뺐다). 1개만 맞는 종목은 04 분류(excluded_theme)가 판단한다.
        fossil = "fossil" in str(r.get("theme", "")).lower()
        for sym, hit in _exclude_keyword_hits(desc, r.get("keywords", [])).items():
            if len(hit) >= MIN_KEYWORD_HITS:
                # 전기·가스 유틸리티는 소개문에 'natural gas'·'coal' 이 있어도 화석연료 회사가 아니다 (04 분류와 같은 규칙, 024)
                e_ = desc.by_ticker(sym) if fossil else None
                g_ = D.gics_model(e_) if e_ else None
                if g_ is not None and g_.sector.code == "55":
                    continue
                excl_by_rule.setdefault(sym, f"exclude_theme:{r['theme']}(keyword)")

    def drop(t: str, reason: str) -> None:
        filtered.append(FilteredOut(ticker=t, reason=reason))
        stats["by_filter"][reason.split("(")[0]] += 1

    excl_tickers = {str(x).upper() for x in cons.get("exclude_tickers", [])}
    # 제외 종목과 같은 회사의 다른 주식 클래스도 뺀다 (063: GOOGL 을 뺐는데 GOOG 가 선정됐다 — F8, 회사 키는 주식 클래스 묶음과 같은 규칙)
    excl_company = {_share_class_key(desc.by_ticker(x)): x for x in excl_tickers if desc.by_ticker(x)}
    # 예시·필수 포함 종목과 같은 세부산업이면 키워드가 하나만 맞아도 04 가 판단한다 (058: 조선 전업 한화오션이 'shipbuilding' 하나라 빠졌는데
    # 예시 종목 셋과 같은 세부산업 20101010 이었다 — 테마의 GICS 코드가 예시 종목의 세부산업을 담지 못한 경우)
    peer_sub: set[str] = set()
    for x in [*(t_ for th in themes for t_ in th.get("example_tickers", []) or []), *(cons.get("must_include_tickers") or [])]:
        e_ = desc.by_ticker(x)
        g_ = D.gics_model(e_) if e_ else None
        if g_ is not None:
            peer_sub.add(g_.sub_industry.code)
    kept: dict[str, dict[str, set[str]]] = {}
    for t, h in hits.items():
        e = desc.by_ticker(t)
        if e is None:
            continue
        forced = "must_include" in h["matched_by"]
        if forced:
            kept[t] = h
            continue
        if h["matched_by"] == {"keyword_match"} and len(h["matched_keywords"]) < MIN_KEYWORD_HITS:
            g_ = D.gics_model(e)
            if not (g_ is not None and g_.sub_industry.code in peer_sub):
                drop(t, f"keyword_weak({','.join(sorted(h['matched_keywords']))})")
                continue
        if t.upper() in excl_tickers or e["ticker"].upper() in excl_tickers:
            drop(t, "exclude_tickers")
            continue
        if _share_class_key(e) in excl_company:
            drop(t, f"exclude_tickers(같은 회사 {excl_company[_share_class_key(e)]})")
            continue
        if D.code_of(e, "sector") in excl_sectors:
            drop(t, "exclude_sectors")
            continue
        if t in excl_by_rule:
            drop(t, excl_by_rule[t])
            continue
        if "stock" not in cons.get("asset_types", ["stock"]):
            drop(t, "asset_types")
            continue
        kept[t] = h

    # 가격 기반 필터 (as_of 이전 자료)
    tickers = sorted(kept)
    cv = view.close_volume(tickers, as_of - dt.timedelta(days=ADV_WINDOW * 2)) if tickers else pd.DataFrame()
    if len(cv):
        adv = cv.sort_values("date").groupby("ticker").tail(ADV_WINDOW).groupby("ticker")["dollar_volume_usd"].mean()
    else:
        adv = pd.Series(dtype=float)
    fd = view.first_dates(tickers) if tickers else {}
    min_mc = float(cons.get("min_market_cap_usd") or 0)
    mcap = view.market_cap_usd(tickers) if tickers else {}
    est = view.market_cap_estimated(tickers) if tickers else {}  # 빈 시가총액을 마지막 주식수 × 그날 종가로 추정한 종목 (값은 mcap 에 이미 들어 있다)

    cands: list[Candidate] = []
    for t, h in kept.items():
        e = desc.by_ticker(t)
        forced = "must_include" in h["matched_by"]
        first = fd.get(t)
        if first is None or (as_of - first).days < MIN_HISTORY_DAYS:
            if not forced:
                drop(t, "insufficient_price_history")
                continue
            warnings.append(f"must_include {t}: insufficient price history, kept anyway")
        a = float(adv.get(t, float("nan")))
        if not forced and (pd.isna(a) or a < cons.get("min_avg_daily_volume_usd", 0)):
            drop(t, "min_avg_daily_volume_usd")
            continue
        mc = mcap.get(t)
        if not forced and min_mc > 0 and mc is None:
            # 최소 시가총액은 하드 필터 (2026-11 사용자 정책): 마지막 주식수로도 추정할 수 없으면 뺀다 (예전에는 남기고 알려 조건을 확인 못 한 VEEV 가 선정됐다, 010).
            # 팀 DB 는 XOM(2026-08~)·BLK(2024-11~) 처럼 앞쪽이 빈 대형주가 과거 시점에 빠진다 → 공지로 알린다 (mcap_warnings)
            drop(t, "market_cap_missing")
            continue
        if not forced and min_mc > 0 and mc < min_mc:
            drop(t, "min_market_cap_usd(estimated)" if t in est else "min_market_cap_usd")  # 추정값으로 뺀 것은 파일에서 구분되게
            continue
        cands.append(Candidate(
            ticker=t, asset_id=e.get("asset_id"), name=e["name"], market=e.get("market", "US"), currency=e.get("currency", "USD"),
            gics=D.gics_model(e), company_summary=e.get("intro", ""), market_cap_usd=mc, adv_usd=None if pd.isna(a) else round(a, 0),
            matched_by=sorted(h["matched_by"]), matched_themes=sorted(h["matched_themes"]),
            matched_keywords=sorted(h["matched_keywords"]), forced=forced,
        ))  # fmt: skip

    # 같은 회사의 복수 주식 클래스 -> 거래대금 큰 하나 (must_include 는 유지)
    by_company: dict[str, list[Candidate]] = defaultdict(list)
    for c in cands:
        by_company[_share_class_key(desc.by_ticker(c.ticker))].append(c)
    deduped: list[Candidate] = []
    for group in by_company.values():
        if len(group) == 1:
            deduped.append(group[0])
            continue
        group.sort(key=lambda c: (not c.forced, -(c.adv_usd or 0)))
        deduped.append(group[0])
        for c in group[1:]:
            if c.forced:
                deduped.append(c)
            else:
                drop(c.ticker, f"share_class_duplicate({group[0].ticker})")
    cands = deduped

    if cap is not None and len(cands) > cap:
        sectors = {str(c)[:2] for th in themes for c in th.get("gics_codes", []) if str(c).strip()}
        broad = metric_prefilter and (len(sectors) >= broad_min_sectors or not sectors)
        if broad:  # 넓은 테마: 거래대금 순이면 선정 지표가 아무것도 거르지 못한다 → 지표 순으로 상한 (결측·동률은 거래대금 순)
            metric, direction = it["screen"]["metric"], it["screen"].get("direction", "desc")
            vals, _facts = M.METRICS[metric](view, [c.ticker for c in cands])
            sign = 1.0 if direction == "desc" else -1.0

            def mkey(c: Candidate):
                v = vals.get(c.ticker)
                ok = v is not None and not pd.isna(v) and M.eligible(metric, v)  # 자격선 밖 값(자료 오류 포함)은 상한 순위에서 결측처럼
                return (c.forced, ok, sign * float(v) if ok else 0.0, c.adv_usd or 0)

            cands.sort(key=mkey, reverse=True)
            reason = "candidate_cap_metric"
            warnings.append(f"candidate cap {cap} applied by selection metric {metric} ({direction}) — broad theme ({len(sectors)} sectors)")
        else:
            cands.sort(key=lambda x: (x.forced, len(x.matched_by), x.adv_usd or 0), reverse=True)
            reason = "candidate_cap"
            warnings.append(f"candidate cap {cap} applied (ranked by matched rules, then liquidity)")
        for x in cands[cap:]:
            drop(x.ticker, reason)
        cands = cands[:cap]
    if _widen and len(cands) < target:  # 필터 뒤에도 모자라면 GICS 를 한 단계 넓혀 다시 (넓혀서 늘 때만 그 결과)
        widened = []
        for th in themes:
            th = dict(th)
            th["gics_codes"] = sorted({p[0] for c in th["gics_codes"] for p in [D.parents_of(c)] if p} | set(th["gics_codes"]))
            widened.append(th)
        if any(set(a["gics_codes"]) != set(b.get("gics_codes", [])) for a, b in zip(widened, themes, strict=True)):
            it2 = {**it, "interpretation": {**it["interpretation"], "themes": widened}}
            alt = retrieve(view, desc, it2, constraints, request_id=request_id, descriptor_version=descriptor_version, max_candidates=max_candidates,
                           broad_min_sectors=broad_min_sectors, metric_prefilter=metric_prefilter, _widen=False)  # fmt: skip
            if len(alt.candidates) > len(cands):
                alt.warnings.insert(0, f"fewer than target after matching; widened GICS codes one level up -> {len(alt.candidates)}")
                return alt
    if len(cands) < target:
        warnings.append(f"only {len(cands)} candidates for target {target}")
    cands.sort(key=lambda x: x.ticker)

    out = Candidates(
        request_id=request_id, as_of=as_of, descriptor_version=descriptor_version, candidates=cands, filtered_out=filtered,
        stats={"n_matched": len(hits), "n_candidates": len(cands), "n_filtered": len(filtered), "by_rule": dict(stats["by_rule"]),
               "by_filter": dict(stats["by_filter"]), "by_theme": dict(Counter(th for x in cands for th in x.matched_themes)),
               "by_market": dict(Counter(x.market for x in cands)),
               "mcap_estimated": {c.ticker: str(est[c.ticker]) for c in cands if c.ticker in est}},  # 추정 시가총액 후보 → 쓴 주식수의 행 날짜
        warnings=warnings,
    )  # fmt: skip
    out.warnings += mcap_warnings(out, cons, view.s.market.mcap_fallback_max_days)
    return out


def mcap_warnings(cand: Candidates, cons: dict[str, Any], max_days: int, *, only: Iterable[str] | None = None) -> list[str]:
    """최소 시가총액 하드 필터의 경고 두 개: 시가총액 자료가 없어 뺀 종목 / 마지막 주식수로 추정해 남긴 종목 (필수 포함은 필터 밖이라 적지 않는다).
    only 를 주면 그 종목만 적고 남는 종목이 없으면 그 경고를 내지 않는다 (07 재선정: 기준일 테마 통과 종목만 — 그날 후보 전체를 적으면 무관한 종목이 공지에 섞인다)."""
    lo = float(cons.get("min_market_cap_usd") or 0)
    if lo <= 0:
        return []
    keep = None if only is None else set(only)
    missing = sorted(f.ticker for f in cand.filtered_out if f.reason == "market_cap_missing" and (keep is None or f.ticker in keep))
    est = cand.stats.get("mcap_estimated") or {}
    estimated = sorted(c.ticker for c in cand.candidates if c.ticker in est and not c.forced and (keep is None or c.ticker in keep))
    out = []
    if missing:
        out.append(f"min market cap {lo:.0f} USD: dropped {len(missing)} candidates without market cap data {missing}")
    if estimated:
        out.append(f"market cap estimated from last known shares (within {max_days} days) for {estimated}")
    return out

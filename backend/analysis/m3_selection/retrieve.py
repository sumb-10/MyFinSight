"""M3-02 후보 검색기 (코드). IntentSpec 의 GICS 코드·키워드·예시 티커로 사전을 검색하고 하드 필터를 적용한다.

규칙: gics_match / keyword_match(서로 다른 키워드 2개 이상) / example_match / must_include.
하드 필터: exclude_tickers·exclude_sectors·exclude_theme_rules·asset_types·시가총액·거래대금·가격 이력.
같은 회사의 복수 주식 클래스(GOOG·GOOGL)는 유동성이 큰 하나만 남긴다 (MVP 결함 4).
후보 상한(120)은 일치 규칙 수 → 거래대금 순으로 자른다.
"""

from __future__ import annotations

import re

import datetime as dt
from collections import Counter, defaultdict
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
) -> Candidates:
    """max_candidates=None 이면 상한 없음 (07 재선정·실행 전 점검처럼 뒤에서 교집합을 만드는 호출용)."""
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
    if len(hits) < target:
        widened = []
        for th in themes:
            th = dict(th)
            th["gics_codes"] = sorted({p[0] for c in th["gics_codes"] for p in [D.parents_of(c)] if p} | set(th["gics_codes"]))
            widened.append(th)
        hits = _collect(desc, widened)
        warnings.append(f"fewer than target after matching; widened GICS codes one level up -> {len(hits)}")
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
        for m in desc.search_keywords(r.get("keywords", []), min_distinct=1):
            excl_by_rule.setdefault(m.entry["yfinance_symbol"], f"exclude_theme:{r['theme']}(keyword)")

    def drop(t: str, reason: str) -> None:
        filtered.append(FilteredOut(ticker=t, reason=reason))
        stats["by_filter"][reason.split("(")[0]] += 1

    excl_tickers = {str(x).upper() for x in cons.get("exclude_tickers", [])}
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
            drop(t, f"keyword_weak({','.join(sorted(h['matched_keywords']))})")
            continue
        if t.upper() in excl_tickers or e["ticker"].upper() in excl_tickers:
            drop(t, "exclude_tickers")
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
    mcap = view.market_cap_usd(tickers) if tickers and cons.get("min_market_cap_usd", 0) > 0 else view.market_cap_usd(tickers) if tickers else {}
    if tickers and not mcap:
        warnings.append("market cap unavailable from valuation_daily for all candidates")

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
        if not forced and cons.get("min_market_cap_usd", 0) > 0 and mc is not None and mc < cons["min_market_cap_usd"]:
            drop(t, "min_market_cap_usd")
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
                ok = v is not None and not pd.isna(v)
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
    if len(cands) < target:
        warnings.append(f"only {len(cands)} candidates for target {target}")
    cands.sort(key=lambda x: x.ticker)

    return Candidates(
        request_id=request_id, as_of=as_of, descriptor_version=descriptor_version, candidates=cands, filtered_out=filtered,
        stats={"n_matched": len(hits), "n_candidates": len(cands), "n_filtered": len(filtered), "by_rule": dict(stats["by_rule"]),
               "by_filter": dict(stats["by_filter"]), "by_theme": dict(Counter(th for x in cands for th in x.matched_themes)),
               "by_market": dict(Counter(x.market for x in cands))},
        warnings=warnings,
    )  # fmt: skip

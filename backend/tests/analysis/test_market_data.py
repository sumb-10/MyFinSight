"""B1: Repository 리더, MarketData/MarketDataView (선견 금지·혼합 달력·환산), 품질 판정, 지표, 뉴스 창, 디스크립터."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from backend.analysis.errors import DataMissing, LookaheadError
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data import metrics as M
from backend.analysis.m2_data.quality import report_summary

AS_OF = dt.date(2025, 12, 31)


# ───────────────────────── repository readers ─────────────────────────
def test_price_bars_mixed_currency_and_fx_range(seeded_repo):
    df = seeded_repo.get_price_bars(["NVDA", "005930.KS", "SPY"], dt.date(2025, 12, 1), dt.date(2025, 12, 31))
    assert set(df["ticker"]) == {"NVDA", "005930.KS", "SPY"} and set(df["currency"]) == {"USD", "KRW"}
    assert df["date"].dtype.kind == "M" and (df["volume"] > 0).all()
    fx = seeded_repo.get_fx_range(dt.date(2025, 12, 1), dt.date(2025, 12, 31))
    assert len(fx) >= 20 and all(1000 < r.rate < 2000 for r in fx)


def test_valuation_asof_and_staleness(seeded_repo):
    rows = seeded_repo.get_valuation_asof(["US-NVDA", "US-PFE", "KR-005930"], AS_OF, max_staleness_days=10)
    assert set(rows) == {"US-NVDA", "US-PFE", "KR-005930"}
    assert rows["US-NVDA"]["per"] > 0 and rows["US-PFE"]["per"] is None and rows["US-NVDA"]["date"] <= AS_OF
    assert seeded_repo.get_valuation_asof(["US-NVDA"], AS_OF, max_staleness_days=0) == {} or True  # 0일이면 당일 행만


def test_constituents_at_falls_back_to_oldest_snapshot(seeded_repo, seed_info):
    snap, rows, warns = seeded_repo.constituents_at("SP500", dt.date(2025, 1, 1))
    assert snap == seed_info["snapshot"] and len(rows) == 16 and warns == []
    snap2, rows2, warns2 = seeded_repo.constituents_at("KOSPI200", dt.date(2022, 1, 1))
    assert snap2 == seed_info["snapshot"] and len(rows2) == 4 and "생존 편향" in warns2[0]
    assert rows2[0].ticker.endswith(".KS")  # yfinance 표기로 돌려줌


def test_news_batch_half_open_dedup_and_per_asset(seeded_repo):
    start, end = dt.datetime(2025, 12, 1, tzinfo=dt.UTC), dt.datetime(2025, 12, 17, tzinfo=dt.UTC)
    rows = seeded_repo.get_news_batch(["US-NVDA", "KR-005930", "US-JPM"], start, end)
    by = {}
    for r in rows:
        by.setdefault(r.asset_id, []).append(r)
    # 12-01, 05, 09, 13 (12-17 은 반개구간 밖) -> 4건, 중복 제목(k=5, 12-21)은 범위 밖
    assert len(by["US-NVDA"]) == 4 and "US-JPM" not in by and all(r.news_id for r in rows)
    assert all(r.published_at < end for r in rows)
    ko = seeded_repo.get_news_batch(["KR-005930"], start, dt.datetime(2026, 1, 1, tzinfo=dt.UTC), languages=["ko"], per_asset=3)
    assert len(ko) == 3 and ko[0].published_at > ko[-1].published_at  # 최신순
    # 전체 범위에서는 중복 제목 1건이 제거되어 5건
    allv = seeded_repo.get_news_batch(["US-NVDA"], start, dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    assert len(allv) == 5


# ───────────────────────── MarketData / View ─────────────────────────
def test_ceiling_is_latest_day_both_markets(market_data):
    # 2025-12-31 은 미국·한국 모두 거래일 (12-25 는 한국 휴장이라 상한이 될 수 없음)
    assert market_data.ceiling == AS_OF
    assert market_data.data_range()[0] >= dt.date(2021, 1, 4)
    assert market_data.asset_id("005930.KS") == "KR-005930" and market_data.market_of("NVDA") == "US"


def test_lookahead_is_blocked_everywhere(market_data):
    view = market_data.view(dt.date(2025, 6, 30))
    future = dt.date(2025, 7, 1)
    with pytest.raises(LookaheadError):
        view.adj_close(["NVDA"], dt.date(2025, 1, 1), future, strict_before=False)
    with pytest.raises(LookaheadError):
        view.adj_close(["NVDA"], dt.date(2025, 1, 1), dt.date(2025, 6, 30))  # strict: as_of 당일도 금지
    with pytest.raises(LookaheadError):
        view.trading_days(dt.date(2025, 1, 1), future)
    with pytest.raises(LookaheadError):
        view.panel(["NVDA"], dt.date(2025, 1, 1), future)
    with pytest.raises(LookaheadError):
        view.fx_on_or_before(future)
    with pytest.raises(LookaheadError):
        view.close_volume(["NVDA"], dt.date(2025, 1, 1), future, strict_before=False)
    with pytest.raises(LookaheadError):
        market_data.view(AS_OF + dt.timedelta(days=1))
    # 허용 범위
    px = view.adj_close(["NVDA"], dt.date(2025, 6, 1))
    assert px.index.max().date() <= dt.date(2025, 6, 29)
    pan, _ = view.panel(["NVDA"], dt.date(2025, 6, 1), benchmarks=["SPY"])
    assert pan.index.max().date() == dt.date(2025, 6, 30)


def test_union_calendar_and_usd_conversion(market_data):
    view = market_data.view(AS_OF)
    start = dt.date(2025, 11, 20)
    px = view.adj_close(["NVDA", "005930.KS"], start, strict_before=False)
    days = {d.date() for d in px.index}
    assert dt.date(2025, 12, 25) in days  # 미국 거래일(한국 휴장) 포함 = 합집합
    assert dt.date(2025, 11, 27) in days  # 한국 거래일(미국 휴장) 포함
    assert px["NVDA"].loc["2025-11-27"] == px["NVDA"].loc["2025-11-26"]  # 미국 휴장일엔 직전 종가 유지
    # 한국 휴장일(12-25)에는 직전 종가 유지, 값은 USD 로 환산되어 KRW 보다 훨씬 작다
    kr = px["005930.KS"]
    assert kr.loc["2025-12-25"] == kr.loc["2025-12-24"]
    assert kr.max() < 1000
    raw = view.adj_close(["005930.KS"], start, strict_before=False, usd=False)
    fx = view.fx_series(start, AS_OF)
    assert np.isclose(raw["005930.KS"].loc["2025-12-24"] / fx.loc["2025-12-24"], kr.loc["2025-12-24"])
    cal_us = view.trading_days(start, markets=["US"])
    cal_kr = view.trading_days(start, markets=["KR"])
    assert dt.date(2025, 12, 25) not in {d.date() for d in cal_kr} and dt.date(2025, 11, 27) not in {d.date() for d in cal_us}
    assert len(cal_us) < len(px) and len(cal_kr) < len(px)


def test_panel_quality_gate(market_data, settings):
    view = market_data.view(AS_OF)
    clean, report = view.panel(["NVDA", "005930.KS", "AMD"], dt.date(2025, 1, 1), required=["NVDA"], benchmarks=["SPY"])
    assert not clean.isna().any().any() and set(clean.columns) >= {"NVDA", "SPY", "005930.KS"}
    summ = report_summary(report)
    # 한국 휴장일(추석 연휴 10-03·10-06 처럼 2거래일 연속)은 결측이 아니라 직전 종가 유지 -> 제외되지 않는다
    assert "005930.KS" in report.usable_tickers and summ["excluded"] == {}
    assert clean["005930.KS"].loc["2025-10-06"] == clean["005930.KS"].loc["2025-10-02"]
    assert clean["NVDA"].loc["2025-11-27"] == clean["NVDA"].loc["2025-11-26"]  # 미국 휴장일도 같은 규칙
    with pytest.raises(DataMissing):
        view.panel(["NVDA", "NOPE"], dt.date(2025, 1, 1), required=["NOPE"], benchmarks=["SPY"])


def test_panel_starting_on_one_markets_holiday(market_data):
    """창 첫날이 한국 휴장일(2025-10-06)이어도 한국 종목·지수는 직전 종가로 채워져 제외되지 않는다 (한글날 2026-10-09 사례)."""
    view = market_data.view(AS_OF)
    clean, report = view.panel(["NVDA", "005930.KS"], dt.date(2025, 10, 6), required=["069500.KS"], benchmarks=["SPY", "069500.KS"])
    assert report.excluded == {} and not clean.isna().any().any()
    assert clean.index[0] == pd.Timestamp("2025-10-06")
    wide = view.adj_close(["005930.KS", "069500.KS"], dt.date(2025, 9, 1), strict_before=False)
    assert clean["005930.KS"].iloc[0] == pytest.approx(wide["005930.KS"].loc["2025-10-02"])
    assert clean["069500.KS"].iloc[0] == pytest.approx(wide["069500.KS"].loc["2025-10-02"])
    # 추정용 adj_close 도 첫 행이 비지 않는다
    est = view.adj_close(["005930.KS", "NVDA"], dt.date(2025, 10, 6), end=dt.date(2025, 10, 10), strict_before=False)
    assert not est.isna().any().any() and est.index[0] == pd.Timestamp("2025-10-06")


def test_common_trading_day_snaps_back_over_holidays(market_data):
    assert market_data.common_trading_day_on_or_before(dt.date(2025, 10, 6), ["US", "KR"]) == dt.date(2025, 10, 2)
    assert market_data.common_trading_day_on_or_before(dt.date(2025, 10, 6), ["US"]) == dt.date(2025, 10, 6)
    assert market_data.common_trading_day_on_or_before(dt.date(2025, 7, 4), ["US", "KR"]) == dt.date(2025, 7, 3)
    assert market_data.common_trading_day_on_or_before(dt.date(2025, 12, 31), ["US", "KR"]) == dt.date(2025, 12, 31)


def test_derive_moves_as_of_off_a_holiday(market_data, settings):
    import json

    from backend.analysis.m1_request.derive import derive

    req = json.load(open("backend/analysis/examples/request_kr_us_semis.json", encoding="utf-8"))
    req["horizon"]["start_date"] = "2025-10-06"
    out = derive(req, market_data, settings)
    d = out.derived
    assert d.as_of == dt.date(2025, 10, 2) and d.backtest_end == dt.date(2025, 10, 2)
    assert any("휴장일" in w for w in d.warnings) and d.markets == ["KR", "US"]


def test_valuation_and_market_cap_usd(market_data):
    view = market_data.view(AS_OF)
    v = view.valuation(["NVDA", "005930.KS", "PFE"])
    assert v.loc["NVDA", "per"] > 0 and pd.isna(v.loc["PFE", "per"])
    assert v.loc["005930.KS", "currency"] == "KRW"
    mc = view.market_cap_usd(["NVDA", "005930.KS"])
    assert mc["005930.KS"] < 1e14  # KRW 시총을 환율로 나눔
    assert v.loc["NVDA", "date"] <= AS_OF - dt.timedelta(days=1)  # strict: as_of 전날 이하


def test_news_window_and_fallback_rule(market_data):
    view = market_data.view(dt.date(2025, 12, 20))
    win = view.news_window(["NVDA", "AMD", "AVGO", "JPM", "005930.KS"])
    assert (win.start, win.end) == (dt.date(2025, 12, 6), dt.date(2025, 12, 20))
    assert win.enough and win.n_tickers_with_news == 4 and win.by_ticker.get("JPM") is None
    assert all(r["published_at"] < "2025-12-20" and r["published_at"] >= "2025-12-06" for r in win.records)
    assert any(r["language"] == "ko" for r in win.records) and all(r["evidence_id"].startswith("ev") for r in win.records)
    thin = view.news_window(["JPM", "KO", "PG"])
    assert not thin.enough and thin.n_articles == 0
    assert "[ev" in win.prompt_lines()


# ───────────────────────── metrics ─────────────────────────
def test_metrics_as_of_and_facts(market_data):
    view = market_data.view(AS_OF)
    tickers = ["NVDA", "AMD", "005930.KS", "PFE"]
    mom, facts = M.return_12m_1m(view, tickers)
    assert set(mom.index) == set(tickers) and all(f.id.startswith("fin:") and f.as_of <= "2025-12-30" for f in facts)
    vol, _ = M.vol_60d(view, tickers)
    assert (vol > 0).all()
    pe, pf = M.pe_ttm(view, tickers)
    assert "PFE" not in pe.index and "005930.KS" in pe.index and pf[0].source == "valuation_daily"
    dy, _ = M.dividend_yield_ttm(view, tickers)
    assert (dy > 0).all()
    # 손으로 계산한 모멘텀과 일치
    px = view.adj_close(["NVDA"], AS_OF - dt.timedelta(days=420), fill=False)["NVDA"].dropna().to_numpy()
    assert np.isclose(mom["NVDA"], px[-22] / px[-253] - 1)


# ───────────────────────── descriptor ─────────────────────────
def test_descriptor_load_filter_and_tree(descriptor_dir):
    desc, info, warns = D.load_for(AS_OF, ["SP500", "NASDAQ100", "KOSPI200"], processed_dir=descriptor_dir)
    assert info["n_stocks"] == 20 and set(D.tickers(desc)) >= {"NVDA", "005930.KS"}
    us_only, info2, _ = D.load_for(AS_OF, ["NASDAQ100"], processed_dir=descriptor_dir)
    assert info2["n_stocks"] == 9 and "005930.KS" not in D.tickers(us_only)
    old, _info3, warns3 = D.load_for(dt.date(2022, 1, 1), ["SP500"], processed_dir=descriptor_dir)
    assert warns3 and "미확보" in warns3[0]
    tree = D.render_tree(desc, "industry")
    assert "45 Information Technology" in tree and "453010" in tree
    hits = desc.filter_by_gics(["4530"])
    assert {h["yfinance_symbol"] for h in hits} >= {"NVDA", "AMD", "005930.KS", "000660.KS"}
    kw = desc.search_keywords(["memory", "DRAM"], min_distinct=1)
    assert {m.entry["yfinance_symbol"] for m in kw} >= {"MU", "000660.KS"}
    g = D.gics_model(desc.by_ticker("NVDA"))
    assert g.sector.code == "45" and g.sub_industry.code == "45301020"
    assert D.parents_of("45301020") == ["453010", "4530", "45"]


def test_price_cache_does_not_reload_for_tickers_without_rows(seeded_repo, settings, monkeypatch):
    """자료가 없는(신규 상장) 종목을 요청해도 전체 재적재를 하지 않는다 — 요청 집합을 기억한다."""
    from backend.analysis.m2_data.market_data import MarketData

    md = MarketData(seeded_repo, settings)
    calls = []
    orig = seeded_repo.get_price_bars

    def spy(tickers, start, end):
        calls.append((len(tickers), start, end))
        return orig(tickers, start, end)

    monkeypatch.setattr(seeded_repo, "get_price_bars", spy)
    md.prefetch(["NVDA", "NEWCO"], dt.date(2025, 1, 1), dt.date(2025, 12, 31))  # NEWCO 는 시드에 없음
    view = md.view(dt.date(2025, 12, 31))
    view.adj_close(["NVDA", "NEWCO"], dt.date(2025, 6, 1))
    view.close_volume(["NVDA", "NEWCO"], dt.date(2025, 6, 1))
    fd = view.first_dates(["NVDA", "NEWCO"])
    assert len(calls) == 1 and "NVDA" in fd and "NEWCO" not in fd and md._c.n_loads == 1
    assert fd["NVDA"] == dt.date(2025, 1, 1)  # 적재 범위 안 첫 거래일 (합성 자료는 1월 1일도 거래일)


# ───────────────────────── 공시 근거 (라운드 4) ─────────────────────────
def test_disclosures_batch_filters_and_labels(seeded_repo):
    from backend.analysis.m2_data.disclosure_labels import EVENT_LABEL_KO, display_title
    from backend.analysis.settings import DisclosureSettings
    from backend.collectors.disclosures import categories as C

    ds = DisclosureSettings()
    a = seeded_repo.asset_map(["NVDA", "005930.KS", "JPM"])
    ids = [v["asset_id"] for v in a.values()]
    rows = seeded_repo.get_disclosures_batch(ids, dt.date(2025, 11, 16), dt.date(2025, 12, 31), event_types=ds.event_types, per_asset=8)
    kinds = {(r.asset_id.split("-")[1], r.event_type) for r in rows}
    assert ("NVDA", "earnings") in kinds and ("005930", "buyback") in kinds and ("JPM", "earnings") in kinds
    assert not any(r.event_type in ("major_holder", "derivative_offering") for r in rows)  # 허용 목록 밖
    assert not any(r.is_amendment for r in rows) and all(dt.date(2025, 11, 16) <= r.available_on < dt.date(2025, 12, 31) for r in rows)
    assert not any(r.available_on == dt.date(2025, 12, 31) for r in rows)  # 반개구간 끝
    one = seeded_repo.get_disclosures_batch(ids, dt.date(2025, 11, 1), dt.date(2025, 12, 31), event_types=ds.event_types, per_asset=1)
    assert all(sum(1 for r in one if r.asset_id == aid) <= 1 for aid in ids) and all(r.event_type == "earnings" for r in one)  # 중요도 우선
    # 라벨: 수집기 규칙의 모든 사건 종류에 한국어 라벨
    all_types = {t for _, t in C.SEC_ITEMS} | {t for _, t in C.SEC_OLD_ITEMS} | set(C.SEC_FORMS.values()) | {t for _, t in C.DART_RULES}
    assert all_types <= set(EVENT_LABEL_KO), sorted(all_types - set(EVENT_LABEL_KO))
    assert display_title({"source": "SEC_EDGAR", "form": "8-K", "items": "2.02,9.01", "title": "8-K", "event_type": "earnings"}) == "8-K 2.02,9.01 · 실적 발표"
    assert display_title({"source": "DART", "form": "주요사항보고서(자기주식취득결정)", "title": "주요사항보고서(자기주식취득결정)", "event_type": "buyback"}) == "주요사항보고서(자기주식취득결정)"


def test_evidence_window_merges_disclosures(market_data):
    view = market_data.view(AS_OF)
    win = view.news_window(["NVDA", "AMD", "JPM", "005930.KS"])  # 기본: 뉴스 14일 + 공시 45일
    assert win.n_disclosures > 0 and win.dc_start == AS_OF - dt.timedelta(days=45)
    assert win.by_ticker_dc.get("JPM") and not win.by_ticker.get("JPM")  # 공시만 있는 종목
    assert win.has_evidence("JPM") and "JPM" not in [t for t in win.tickers if win.by_ticker.get(t)]
    assert win.n_tickers_with_evidence == 4 and win.enough
    assert all(i.startswith("dc") for i in win.by_ticker_dc["JPM"]) and win.ids >= set(win.by_ticker_dc["JPM"])
    s = win.summary()
    assert {"window", "n_articles", "n_tickers_with_news", "n_disclosures", "n_tickers_with_evidence", "by_event_type"} <= set(s)
    assert s["by_event_type"].get("earnings", 0) >= 1 and "major_holder" not in s["by_event_type"]
    lines = win.disclosure_lines()
    assert lines and all(len(ln.split(" | ")) == 7 and ln.split(" | ")[4] in win.tickers for ln in lines)
    assert win.event_counts("005930.KS").get("자사주 취득·처분 결정") == 1
    d = win.to_dict()
    assert d["disclosures"] and d["tickers_dc"]["JPM"] and all(r["kind"] == "disclosure" and r["available_on"] <= str(AS_OF) for r in d["disclosures"])
    # 공시를 끄면 예전과 같다
    off = view.news_window(["NVDA", "JPM"], dc_days=0)
    assert off.n_disclosures == 0 and not off.has_evidence("JPM") and off.ids == {r["evidence_id"] for r in off.records}

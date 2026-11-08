"""새 선정 규칙(유니버스 중앙값 기준선·미국 법인·이익률 유니버스 중앙값)을 저장된 실행의 후보·테마 판정에 적용해 선정 종목이 바뀌는지 본다.
기준일(05)과 백테스트 시작일(07 재선정) 둘 다. LLM 은 쓰지 않는다.  PYTHONPATH=. python dryrun_select.py <final_runs.txt> <out.json>"""
import copy, datetime as dt, json, sys
from pathlib import Path

from backend.analysis.common.dbconn import open_analysis_repository
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m2_data.price_cache import PriceBarCache
from backend.analysis.m3_selection.intent import idea_screen_guards
from backend.analysis.m3_selection.screen import screen
from backend.analysis.m4_portfolio.spec import selectable_at, theme_passed
from backend.analysis.schemas.selection import Tagging
from backend.analysis.settings import AnalysisSettings

s = AnalysisSettings.load(); ms = s.market
repo = open_analysis_repository(None)
prices = PriceBarCache()
out = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    name, rid = line.split()
    o = Path("output") / rid
    req = json.load(open(o / "01_request.json"))
    it = json.load(open(o / "02_intent.json"))
    tag = Tagging.model_validate(json.load(open(o / "04_tagging.json")))
    sel0 = json.load(open(o / "05_selection.json"))
    spec = json.load(open(o / "07_backtest_spec.json"))
    sel_bt0 = json.load(open(o / "07_selection_bt.json")) if (o / "07_selection_bt.json").exists() else None
    it2 = copy.deepcopy(it)
    idea_screen_guards(req, it2["screen"], s)
    d = req["derived"]
    as_of = dt.date.fromisoformat(str(d["as_of"]))
    desc, info, _ = D.load_for(as_of, req["constraints"]["universe"], ms.markets, processed_dir=ms.descriptor_dir or D.PROCESSED, universe_file=ms.descriptor_universe)
    md = MarketData(prices.wrap(repo), s)
    start = dt.date.fromisoformat(str(d["backtest_start"])) - dt.timedelta(days=int(s.portfolio.lookback_days * 1.6) + 60)
    md.prefetch(D.tickers(desc), start, as_of)  # 01 단계와 같은 선적재 (후보 검색이 적재한 가격으로 거래대금·상장일을 본다)
    cons = req["constraints"]
    try:
        sel1, _ = screen(md.view(as_of), desc, tag, it2, cons, request_id=req["request_id"])
        now0 = [x["ticker"] for x in sel0["selected"]]
        now1 = [x.ticker for x in sel1.selected]
        rec = {"now_before": now0, "now_after": now1, "now_changed": sorted(now0) != sorted(now1), "us_hq_only": it2["screen"].get("us_hq_only"),
               "metric": it2["screen"]["metric"], "high_margin": it2["screen"].get("high_margin")}
        if sel_bt0 is not None:
            day0 = dt.date.fromisoformat(str(spec["period"]["start"]))
            bx = {"broad": not getattr(tag, "theme_filter_applied", True), "excluded": [r.ticker for r in tag.excluded_by_theme], "theme_ok": theme_passed(tag)}
            _c, _t, sbt, _f = selectable_at(md, day0, desc, it2, cons, list(tag.passed_tickers), req["request_id"], **bx)
            bt0 = [x["ticker"] for x in sel_bt0["selected"]]
            bt1 = [x.ticker for x in sbt.selected]
            rec.update({"bt_before": bt0, "bt_after": bt1, "bt_changed": sorted(bt0) != sorted(bt1)})
        out[name] = rec
        flag = ("NOW " if rec["now_changed"] else "") + ("BT " if rec.get("bt_changed") else "")
        print(name, flag or "-", rec["metric"], "| now", len(now0), "->", len(now1), "| removed", sorted(set(now0) - set(now1))[:8], flush=True)
    except Exception as e:
        out[name] = {"error": f"{type(e).__name__}: {e}"}
        print(name, "ERROR", type(e).__name__, str(e)[:200], flush=True)
Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1))
ch = [k for k, v in out.items() if v.get("now_changed") or v.get("bt_changed")]
print("changed:", len(ch), ch)

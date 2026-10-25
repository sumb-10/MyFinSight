"""단계 레지스트리 (M0-05). 이름 = run_step.step. 다섯 묶음(bucket)은 화면 진행 표시용 (Module7 §3).

각 단계 함수는 ctx 를 받아 ctx.outputs[이름] 에 JSON 직렬화 가능한 dict 를 넣고, 요약 문자열을 돌려준다.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.analysis.executor.context import RunContext
from backend.analysis.executor.parallel import run_ordered
from backend.analysis.m1_request.derive import derive
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m3_selection.classify import classify
from backend.analysis.m3_selection.explain import explain
from backend.analysis.m3_selection.intent import interpret
from backend.analysis.m3_selection.retrieve import retrieve
from backend.analysis.m3_selection.screen import screen
from backend.analysis.m4_portfolio.construct import construct
from backend.analysis.m4_portfolio.spec import build_backtest_spec
from backend.analysis.m5_backtest_report.backtest import run_backtest
from backend.analysis.m5_backtest_report.backtest_engine import rebalance_dates
from backend.analysis.m5_backtest_report.collect import build_results
from backend.analysis.m5_backtest_report.report import generate_report
from backend.analysis.m5_backtest_report.validate import validate
from backend.analysis.schemas import Candidates, Selection, Tagging
from backend.analysis.schemas.portfolio import Portfolio, TargetPortfolios, Views


@dataclass(frozen=True)
class Stage:
    name: str
    label_ko: str
    bucket: str
    fn: Callable[[RunContext], str]
    when: Callable[[RunContext], bool] = lambda ctx: True
    deps: tuple[str, ...] | None = None  # 선행 단계. None 이면 "목록상 바로 앞 단계" (순차). 러너가 의존이 끝난 단계를 묶어(웨이브) 동시에 돈다


# ───────────────────────── bucket 1: 조건·자료 확인 ─────────────────────────
def st_request(ctx: RunContext) -> str:
    req = ctx.request
    if "derived" not in req:
        req = derive(req, ctx.md, ctx.settings).model_dump(mode="json")
        ctx.request = req
    d = req["derived"]
    ms = ctx.settings.market
    ctx.desc, ctx.desc_info, warns = D.load_for(dt.date.fromisoformat(str(d["as_of"])), req["constraints"]["universe"], ms.markets,
                                                processed_dir=ms.descriptor_dir or D.PROCESSED, universe_file=ms.descriptor_universe)  # fmt: skip
    ctx.desc_info["warnings"] = warns
    ctx.warn_all("01_request", [*warns, *d.get("warnings", [])])
    # 가격·환율 선적재: 유니버스 전체 + 비교지수, 백테스트 시작 − 추정 창 ~ 기준일
    start = dt.date.fromisoformat(str(d["backtest_start"])) - dt.timedelta(days=int(ctx.settings.portfolio.lookback_days * 1.6) + 60)
    ctx.md.prefetch(D.tickers(ctx.desc), start, dt.date.fromisoformat(str(d["as_of"])))
    ctx.outputs["01_request"] = req
    return f"기준일 {d['as_of']}, 유니버스 {ctx.desc_info['n_stocks']}종목, 백테스트 {d['backtest_start']}~{d['backtest_end']}"


TEMPLATE_KO = {"low_per": "저PER", "quality": "퀄리티(ROE)", "momentum": "모멘텀", "low_volatility": "저변동성", "high_dividend": "고배당"}


def st_intent(ctx: RunContext) -> str:
    if ctx.intent is not None:
        ctx.outputs["02_intent"] = ctx.intent
        return "대화에서 확정된 의도 재사용 (LLM 호출 없음)"
    spec, warns, _ = interpret(ctx.request, ctx.desc, ctx.llm, ctx.settings)
    out = spec.model_dump(mode="json")
    out["questions"] = []  # 실행 단계에서는 질문을 쓰지 않음
    ctx.outputs["02_intent"] = out
    ctx.warn_all("02_intent", list(warns))
    return f"테마 {len(spec.interpretation.themes)}개, 선정 기준 {TEMPLATE_KO.get(spec.screen.template, spec.screen.template)}"


# ───────────────────────── bucket 2: 후보 선정·구성 ─────────────────────────
def _as_of(ctx: RunContext) -> dt.date:
    return dt.date.fromisoformat(str(ctx.request["derived"]["as_of"]))


def st_candidates(ctx: RunContext) -> str:
    view = ctx.md.view(_as_of(ctx))
    ss = ctx.settings.selection
    cand = retrieve(view, ctx.desc, ctx.out("02_intent"), ctx.request["constraints"], request_id=ctx.request_id,
                    descriptor_version=ctx.desc_info.get("file"), max_candidates=ss.max_candidates, broad_min_sectors=ss.broad_theme_min_sectors,
                    metric_prefilter=ss.metric_prefilter)  # fmt: skip
    ctx.outputs["03_candidates"] = cand.model_dump(mode="json")
    ctx.warn_all("03_candidates", list(cand.warnings))
    return f"후보 {len(cand.candidates)}개 (제외 {len(cand.filtered_out)})"


def st_tagging(ctx: RunContext) -> str:
    tag = classify(Candidates.model_validate(ctx.out("03_candidates")), ctx.out("02_intent"), ctx.llm,
                   max_workers=ctx.settings.executor.classify_workers or ctx.settings.llm.max_concurrency, cancel_check=ctx.cancel_check)  # fmt: skip
    ctx.outputs["04_tagging"] = tag.model_dump(mode="json")
    ctx.warn_all("04_tagging", list(tag.warnings))
    return f"테마 통과 {len(tag.passed_tickers)}개 / 배치 {tag.batches}"


def st_selection(ctx: RunContext) -> str:
    view = ctx.md.view(_as_of(ctx))
    sel, facts = screen(view, ctx.desc, Tagging.model_validate(ctx.out("04_tagging")), ctx.out("02_intent"), ctx.request["constraints"], request_id=ctx.request_id)
    ctx.outputs["05_selection"] = sel.model_dump(mode="json")
    ctx.facts += facts
    ctx.outputs["_facts_05"] = list(facts)  # 06 이 쓰는 스냅샷 (07 이 같은 웨이브에서 백테스트 시작일 지표를 덧붙이므로)
    ctx.warn_all("05_selection", list(sel.warnings))
    if not sel.selected:
        raise ValueError("no ticker selected: cannot continue")
    return f"선정 {len(sel.selected)}개 ({sel.summary['metric']})"


def st_explain(ctx: RunContext) -> str:
    view = ctx.md.view(_as_of(ctx))
    sel = Selection.model_validate(ctx.out("05_selection"))
    ds = ctx.settings.disclosures
    win = view.news_window([s.ticker for s in sel.selected], dc_days=(ds.summary_days if ds.enabled else 0),
                           dc_event_types=[*ds.event_types, *ds.summary_extra_event_types])  # 기업 근거용: 90일 사건 요약 (정기 보고 포함)
    ctx.add_news_window("06_explain", win.to_dict())
    from backend.analysis.common.warnings import merge as _merge, render as _render

    notes_ko = [_render(w) for w in _merge(ctx.warnings_of("05_selection") + ctx.warnings_of("03_candidates")) if w.level == "user"]
    facts05 = ctx.outputs.get("_facts_05", ctx.facts)
    out = explain(sel, Tagging.model_validate(ctx.out("04_tagging")), ctx.out("02_intent"), ctx.llm,
                  facts=[f for f in facts05 if f["ticker"] in {s.ticker for s in sel.selected}], news=win, warnings_ko=notes_ko)  # fmt: skip
    ctx.outputs["06_selection_explained"] = out
    return f"기업별 근거 {len(out.get('per_ticker', []))}개"


def st_backtest_spec(ctx: RunContext) -> str:
    spec, extras = build_backtest_spec(ctx.md, ctx.request, ctx.out("02_intent"), Tagging.model_validate(ctx.out("04_tagging")),
                                       Selection.model_validate(ctx.out("05_selection")), ctx.desc, ctx.settings, bt_req=ctx.bt_req,
                                       allow_fewer_at_start=ctx.allow_fewer_at_start)  # fmt: skip
    ctx.outputs["07_backtest_spec"] = spec
    for k, v in extras.items():
        if k == "facts_bt":
            ctx.facts += v
        else:
            ctx.outputs[f"07_{k}"] = v
    ctx.warn_all("07_backtest_spec", list(spec["warnings"]))
    return f"창 {spec['period']['start']}~{spec['period']['end']}, 종목 {len(spec['selection']['tickers'])}개, 비교지수 {spec['benchmark']}"


def st_targets(ctx: RunContext) -> str:
    """백테스트 시작일 구성: 시장모형 + 템플릿 4 + 뉴스 뷰 BL (construct mode=start)."""
    spec = ctx.out("07_backtest_spec")
    as_of = dt.date.fromisoformat(str(spec["period"]["as_of"]))
    res = construct(ctx.md.view(as_of), list(spec["selection"]["tickers"]), ctx.request, ctx.out("02_intent"), ctx.settings, ctx.llm, ctx.desc,
                    mode="start", stage_tag=f"09_views_news_{as_of}")  # fmt: skip
    ctx.outputs["08_market_model"] = res.market_model
    ctx.outputs["08_baseline_portfolios"] = res.baselines
    views = Views(request_id=ctx.request_id, as_of=as_of, window=res.evidence.summary() if res.evidence else None,
                  max_view_confidence=ctx.out("02_intent")["news_tilt"]["max_view_confidence"], sets=res.view_sets, fallback=res.fallback,
                  fallback_reason_ko=res.fallback_reason_ko, warnings=res.warnings)  # fmt: skip
    ctx.outputs["09_views"] = views.model_dump(mode="json")
    if res.evidence:
        ctx.add_news_window("10_targets", res.evidence.to_dict())
    notes = ["BL prior = 기준 비중의 역최적화 수익률; 뷰 신뢰도가 0 에 가까우면 기준 비중으로 수렴.",
             "구성일 d 의 추정은 d 이전 자료만 쓰고(정보 마감 t−1), 체결은 d 종가 (D4).",
             (f"종목별 비중 이동 한도 |w − w_baseline| ≤ {res.params['max_tilt_per_stock']}" if res.params else "뉴스 뷰 없음: BL 타겟 없이 템플릿만 백테스트")]  # fmt: skip
    targets = TargetPortfolios(request_id=ctx.request_id, as_of=as_of,
                               backtest_spec={k: spec[k] for k in ["period", "capital", "rebalance_rule", "benchmark", "extra_benchmarks", "selection", "execution_rule"]},
                               parameters=res.params or {}, baseline={"id": res.baselines["chosen_baseline"], "weights": res.baseline_weights},
                               portfolios=[Portfolio(**p) for p in res.bl_portfolios], templates=[Portfolio(**p) for p in res.baselines["portfolios"]],
                               notes_ko=notes, warnings=res.warnings)  # fmt: skip
    ctx.outputs["10_target_portfolios"] = targets.model_dump(mode="json")
    ctx.warn_all("10_targets", list(res.warnings))
    _warn_optimizer(ctx, "10_targets", res.bl_portfolios)
    return f"비중 규칙 {len(res.baselines['portfolios'])}개 + 뉴스 반영 구성 {len(res.bl_portfolios)}개 ({'뉴스 뷰 적용' if not res.fallback else '근거 부족으로 기준 비중 유지'})"


def st_walkforward(ctx: RunContext) -> str:
    """리밸런싱일마다 construct(mode=rebalance): 시장모형·뉴스 뷰·BL 재계산, 종목 고정 (K8)."""
    spec, intent = ctx.out("07_backtest_spec"), ctx.out("02_intent")
    as_of, end = dt.date.fromisoformat(str(spec["period"]["as_of"])), dt.date.fromisoformat(str(spec["period"]["end"]))
    tickers = list(spec["selection"]["tickers"])
    # 백테스트(prepare)와 같은 달력: 종목 시장 ∪ 비교지수 시장의 거래일 합집합. 종목 시장만 쓰면 한국 휴장일에 리밸런싱 날짜가 어긋나
    # 체크포인트의 '리밸런싱 직후 비중'이 드리프트된 값으로 잡혀 내부 점검(R4)이 틀리게 실패한다 (라운드 5 재실행에서 발견)
    benches = [spec["benchmark"], *[b for b in spec.get("extra_benchmarks", []) if b in ctx.md.assets]]
    markets = sorted({ctx.md.market_of(t) for t in tickers} | {ctx.md.market_of(b) for b in benches if b in ctx.md.assets})
    cal = ctx.md.view(end).trading_days(as_of, end, markets=markets)
    dates = [d.date() for d in rebalance_dates(spec["rebalance_rule"], cal, as_of, ctx.settings.backtest)]
    ps = ctx.settings.portfolio
    tmpl = {t: {"id": f"wf_{t}", "kind": "template", "name_ko": f"{ps.template_names_ko[t][0]} (walk-forward)", "rule_ko": ps.template_names_ko[t][1],
                "weights_by_date": {}} for t in ps.templates}  # fmt: skip
    bl: dict[str, Any] = {"id": "wf_bl_news", "kind": "black_litterman", "name_ko": "뉴스 뷰 Black-Litterman (walk-forward)", "title_ko": "뉴스 근거 뷰",
                          "rule_ko": "리밸런싱마다 직전 뉴스 헤드라인으로 뷰를 새로 만들어 기준 비중을 조정", "weights_by_date": {}, "views_by_date": {},
                          "fallback_dates": [], "narrative_by_date": {}}  # fmt: skip
    models, news_summary, warnings = {}, {}, []

    def per_date(d: dt.date):  # 순수 함수: 날짜 하나의 구성 (공유 상태를 건드리지 않음 → 병렬 가능)
        return construct(ctx.md.view(d), tickers, ctx.request, intent, ctx.settings, ctx.llm, ctx.desc, mode="rebalance", stage_tag=f"09_views_news_{d}",
                         id_prefix=f"wf_bl_{d}", name_prefix="뉴스 뷰 BL")  # fmt: skip

    workers = ctx.settings.executor.walkforward_workers or ctx.settings.llm.max_concurrency
    results = run_ordered(ctx, "10w_paths", dates, per_date, max_workers=workers)  # 날짜 순서대로 돌아온다 (라운드 4 S2)
    for d, res in zip(dates, results, strict=True):  # 조립은 날짜순 → 경고·근거 색인 순서가 순차 실행과 같다
        key = str(d)
        models[key] = {k: res.market_model[k] for k in ["delta", "delta_source", "lookback", "implied_returns"]}
        for p in res.baselines["portfolios"]:
            tmpl[p["id"]]["weights_by_date"][key] = p["weights"]
        news_summary[key] = res.evidence_summary() or {"enough": False, "n_articles": 0, "n_tickers_with_news": 0, "n_disclosures": 0}
        if res.evidence:
            ctx.add_news_window("10w_paths", res.evidence.to_dict())
        warnings += [f"{key}: {w}" for w in res.warnings]
        ctx.warn_all("10w_paths", list(res.warnings), dates=[key])
        _warn_optimizer(ctx, "10w_paths", res.bl_portfolios, dates=[key])
        if res.bl_portfolios:
            p0 = res.bl_portfolios[0]
            bl["weights_by_date"][key] = p0["weights"]
            bl["views_by_date"][key] = p0["views_applied"]
            bl["narrative_by_date"][key] = res.view_sets[0].get("narrative_ko", "")
        else:
            bl["weights_by_date"][key] = res.baseline_weights
            bl["views_by_date"][key] = []
            bl["fallback_dates"].append(key)
    out = {"request_id": ctx.request_id, "stage": "10w_target_paths", "dates": [str(d) for d in dates], "tickers": tickers,
           "portfolios": [*tmpl.values(), bl], "market_models_by_date": models, "news_summary": news_summary,
           "parameters": {"view_sets": ctx.settings.news.view_sets_at_rebalance, "views_per_set": ctx.settings.news.views_per_set,
                          "news_window_days": ctx.settings.news.window_days, "min_news_tickers": ctx.settings.news.min_tickers,
                          "disclosure_window_days": (ctx.settings.disclosures.window_days if ctx.settings.disclosures.enabled else 0)},
           "warnings": warnings}  # fmt: skip
    ctx.outputs["10w_target_paths"] = out
    return f"리밸런싱 {len(dates)}회, 뉴스 뷰 적용 {len(dates) - len(bl['fallback_dates'])}회"


def st_forward(ctx: RunContext) -> str:
    """현재 구성: 분석 기준일에 현재 선정 종목으로 construct(mode=current) + USD·KRW 배분."""
    sel = ctx.out("05_selection")
    as_of = _as_of(ctx)
    tickers = [s["ticker"] for s in sel["selected"]]
    res = construct(ctx.md.view(as_of), tickers, ctx.request, ctx.out("02_intent"), ctx.settings, ctx.llm, ctx.desc, mode="current",
                    stage_tag=f"09_views_news_{as_of}_current", id_prefix="fwd_bl", name_prefix="현재 구성 BL")  # fmt: skip
    if res.evidence:
        ctx.add_news_window("10f_current", res.evidence.to_dict())
    init, fx = ctx.request["derived"]["initial_amount_usd"], ctx.request["derived"]["fx_rate"]
    ports = [dict(p) for p in res.bl_portfolios]
    templates = [dict(p) for p in res.baselines["portfolios"]]
    for p in [*templates, *ports]:
        p["allocation"] = [{"ticker": t, "weight": w_, "usd": round(init * w_, 2), "krw": round(init * w_ * fx)}
                           for t, w_ in sorted(p["weights"].items(), key=lambda x: -x[1])]  # fmt: skip
    ev = res.evidence
    out = {"request_id": ctx.request_id, "stage": "10f_forward_portfolios", "as_of": str(as_of), "news_window": ev.summary() if ev else None,
           "evidence": {r["evidence_id"]: r for r in (ev.records if ev else [])},
           "market_model": {k: res.market_model[k] for k in ["as_of", "lookback", "tickers", "ann_vol", "cap_weights", "delta", "delta_source", "tau", "implied_returns"]},
           "baseline": {"id": res.baselines["chosen_baseline"], "weights": res.baseline_weights}, "templates": templates, "views_sets": res.view_sets,
           "portfolios": ports, "chosen_weights": res.chosen_weights, "fallback": res.fallback, "fallback_reason_ko": res.fallback_reason_ko,
           "parameters": res.params, "capital": {"initial_amount_usd": init, "fx_rate": fx, "fx_date": str(ctx.request["derived"]["fx_date"])},
           "warnings": res.warnings}  # fmt: skip
    ctx.outputs["10f_forward_portfolios"] = out
    ctx.warn_all("10f_current", list(res.warnings), dates=[str(as_of)])
    _warn_optimizer(ctx, "10f_current", res.bl_portfolios, dates=[str(as_of)])
    return f"기준일 {as_of} 현재 구성: 템플릿 {len(templates)} + BL {len(ports)}"


# ───────────────────────── bucket 3·4: 백테스트·검증 ─────────────────────────
def st_backtest(ctx: RunContext) -> str:
    bt, bt_ctx, daily = run_backtest(ctx.md, ctx.out("10_target_portfolios"), ctx.request, ctx.out("02_intent"), ctx.out("08_market_model"), ctx.desc,
                                     ctx.settings, walkforward=ctx.outputs.get("10w_target_paths"))  # fmt: skip
    ctx.outputs["11_backtest_results"] = bt
    ctx.outputs["_bt_ctx"] = bt_ctx
    ctx.outputs["_daily_panel"] = daily
    ctx.warn_all("11_backtest", list(bt["warnings"]))
    _warn_data_quality(ctx, bt.get("data_quality") or {})
    return f"포트폴리오 {len(bt['portfolios'])}개 + 비교지수 {len(bt['benchmarks'])}개, {bt['period']['trading_days']}거래일"


def st_validation(ctx: RunContext) -> str:
    bt_ctx = ctx.out("_bt_ctx")
    sectors = bt_ctx["sectors"]
    val = validate(ctx.out("11_backtest_results"), ctx.out("10_target_portfolios"), ctx.out("02_intent"), ctx.request, bt_ctx,
                   lambda t: sectors.get(t, t), ctx.settings)  # fmt: skip
    ctx.outputs["12_validation"] = val
    ctx.warn_all("12_validation", list(val["warnings"]))
    s = val["summary"]
    rec = val.get("recommended") or {}
    vd = rec.get("verdict") or {}
    head = vd.get("head_ko") or ("추천" if rec else "추천 없음")
    name = next((p.get("name_ko") for p in ctx.out("11_backtest_results")["portfolios"] if p["id"] == rec.get("id")), rec.get("id") or "-")
    return f"후보 {s.get('n_candidates', len(val['results']))}개 비교 · {head}: {name}" + (f" · 주의 {s['n_warn']}개" if s.get("n_warn") else "")


# ───────────────────────── bucket 5: 리포트 ─────────────────────────
def st_results(ctx: RunContext) -> str:
    o = ctx.outputs
    bundle = build_results(run_id=ctx.run_id, req=ctx.request, intent=o["02_intent"], cand=o["03_candidates"], tag=o["04_tagging"], sel=o["05_selection"],
                           expl=o.get("06_selection_explained"), spec=o["07_backtest_spec"], mm=o["08_market_model"], base=o["08_baseline_portfolios"],
                           views=o["09_views"], targets=o["10_target_portfolios"], bt=o["11_backtest_results"], val=o["12_validation"], desc=ctx.desc,
                           descriptor_info=ctx.desc_info, settings=ctx.settings, facts=ctx.facts, news_windows=ctx.news_windows,
                           walkforward=o.get("10w_target_paths"), forward=o.get("10f_forward_portfolios"), llm_usage=ctx.llm.usage_summary(),
                           extra_warnings=ctx.warnings)  # fmt: skip
    ctx.outputs["13_results"] = bundle
    return f"결과 통합: 포트폴리오 {len(bundle['backtest']['portfolios'])}개, 인용 색인 {len(bundle['evidence_index'])}건, 경고 {len(bundle['warnings'])}건"


def st_report(ctx: RunContext) -> str:
    summaries = {st.name: ctx.step_summaries[st.name] for st in STAGES if st.name in ctx.step_summaries}  # 완료 순서가 아니라 단계 순서로
    doc, warns = generate_report(ctx.out("13_results"), ctx.llm, ctx.settings, step_summaries=summaries)
    ctx.outputs["14_report"] = doc
    ctx.warn_all("14_report", list(warns))  # 숫자 대조·개발 용어 = debug (파일에만)
    return f"리포트 7섹션, KPI {len(doc['kpis'])}개, 근거 {len(doc['evidence'])}건" + (f" · 문장 검증 메모 {len(warns)}건" if warns else "")


def _warn_optimizer(ctx: RunContext, stage: str, ports: list[dict[str, Any]], *, dates: list[str] | None = None) -> None:
    """BL 효용 최적화 실패(기준 비중 유지)는 지금까지 침묵했다 → user 경고."""
    if any(str(a).startswith("optimizer_failed") for p in ports or [] for a in p.get("active_constraints", [])):
        ctx.warn(stage, "optimizer_failed_no_tilt", dates=dates or [])


def _warn_data_quality(ctx: RunContext, dq: dict[str, Any]) -> None:
    """품질 판정 결과(제외·채움·메모)를 경고 계약으로 올린다 (지금까지는 결과 묶음에만 있었음)."""
    if dq.get("filled"):
        ctx.warn("11_backtest", "data_quality_filled", tickers=sorted(dq["filled"]))
    for w in dq.get("warnings", []) or []:
        ctx.warn("11_backtest", "data_quality_note", text=str(w))


# deps: 러너가 의존이 끝난 단계를 묶어 동시에 돈다 (웨이브). 06·07·10f 는 05 뒤에 함께, 10·10w 는 07 뒤에 함께.
STAGES: list[Stage] = [
    Stage("01_request", "요청 확정과 자료 준비", "conditions", st_request, deps=()),
    Stage("02_intent", "의도 해석", "conditions", st_intent, deps=("01_request",)),
    Stage("03_candidates", "후보 검색", "candidates", st_candidates, deps=("02_intent",)),
    Stage("04_tagging", "테마 분류", "candidates", st_tagging, deps=("03_candidates",)),
    Stage("05_selection", "정량 선정", "candidates", st_selection, deps=("04_tagging",)),
    Stage("06_explain", "기업별 근거", "candidates", st_explain, deps=("05_selection",)),
    Stage("07_backtest_spec", "백테스트 사양·시작일 재선정", "candidates", st_backtest_spec, deps=("05_selection",)),
    Stage("10f_current", "현재 구성", "candidates", st_forward, deps=("05_selection",)),
    Stage("10_targets", "시작일 포트폴리오 구성", "candidates", st_targets, deps=("07_backtest_spec",)),
    Stage("10w_paths", "리밸런싱일별 재구성 (walk-forward)", "candidates", st_walkforward, deps=("07_backtest_spec",)),
    Stage("11_backtest", "백테스트", "backtest", st_backtest, deps=("10_targets", "10w_paths")),
    Stage("12_validation", "사용자 조건 검증", "validation", st_validation, deps=("11_backtest",)),
    Stage("13_results", "결과 통합", "report", st_results, deps=("06_explain", "10f_current", "12_validation")),
    Stage("14_report", "리포트 문서 생성·검증", "report", st_report, deps=("13_results",)),
]

OUTPUT_FILES: dict[str, str] = {
    "01_request": "01_request.json", "02_intent": "02_intent.json", "03_candidates": "03_candidates.json", "04_tagging": "04_tagging.json",
    "05_selection": "05_selection.json", "06_selection_explained": "06_selection_explained.json", "07_backtest_spec": "07_backtest_spec.json",
    "07_candidates_bt": "07_candidates_bt.json", "07_tagging_bt": "07_tagging_bt.json", "07_selection_bt": "07_selection_bt.json",
    "08_market_model": "08_market_model.json", "08_baseline_portfolios": "08_baseline_portfolios.json", "09_views": "09_views.json",
    "10_target_portfolios": "10_target_portfolios.json", "10w_target_paths": "10w_target_paths.json", "10f_forward_portfolios": "10f_forward_portfolios.json",
    "11_backtest_results": "11_backtest_results.json", "12_validation": "12_validation.json", "13_results": "13_results.json", "14_report": "14_report.json",
}  # fmt: skip


def stage_by_name(name: str) -> Stage:
    return next(s for s in STAGES if s.name == name)


def to_pandas_panel(obj: Any) -> pd.DataFrame | None:
    return obj if isinstance(obj, pd.DataFrame) else None

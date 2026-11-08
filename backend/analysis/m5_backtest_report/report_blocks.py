"""리포트의 데이터 블록 (표·차트·KPI·체크포인트) — 13_results 에서 코드가 만든다. LLM 은 여기 없다.

블록 타입은 Front 렌더러(features/report/blocks)와 같다: paragraphs, kpis, table, donut, line, area, bar, funnel, callout, cards, checkpoints, glossary, evidence.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from backend.analysis.common.labels import VOL_PREF_KO, enum_ko, field_ko, sector_counts_ko, sector_ko, sub_industry_ko, theme_ko, usd_ko
from backend.analysis.m2_data import metrics as M
from backend.analysis.m5_backtest_report.matched import stock_cash_ko
from backend.analysis.m5_backtest_report.validate import cautious_reason_ko, dd_bucket, tie_levels

BROAD_REASON_KO = "넓은 테마라 테마 판정으로 거르지 않고 선정 지표 순위로 고름"
NAMES = {"equal_weight": "동일비중", "market_cap": "시가총액비중", "inverse_volatility": "역변동성비중", "min_variance": "최소분산"}
STATUS_KO = {"pass": "통과", "warn": "주의", "fail": "미통과", "info": "참고", "flag": "허용 초과", "n/a": "-"}
LEVEL_KO = {"hard": "필수", "soft": "권장", "info": "참고", "flag": "표시"}
KIND_KO = {"black_litterman": "뉴스 뷰(BL)", "template": "규칙", "benchmark": "비교지수", "alternative": "대안", "matched": "낙폭 맞춤"}
VERDICT_HEAD_KO = {"recommended": "추천", "recommended_warn": "추천(주의)", "insufficient": "구성 불충분"}


def _usd(R) -> bool:
    """달러 요청이면 환율이 1 이라 원화 환산·'1 USD = 1.00 KRW' 표기는 뜻이 없다 (007: 다섯 군데에 나왔다, 계획 N-T3-8)."""
    return (R["request"].get("capital") or {}).get("currency") == "USD"


def pf_label(p: dict[str, Any]) -> str:
    if p.get("kind") in ("benchmark", "alternative", "matched"):
        return p.get("name_ko", p["id"])
    if p.get("title_ko"):
        return f"뉴스 뷰: {p['title_ko']}"
    return NAMES.get(p["id"], p.get("name_ko", p["id"]))


def all_blocks(R: dict[str, Any]) -> list[dict[str, Any]]:
    return [*R["backtest"]["portfolios"], *R["backtest"].get("benchmarks", [R["backtest"]["benchmark"]]), *R["validation"].get("alternatives", [])]


def find(R: dict[str, Any], pid: str) -> dict[str, Any]:
    return next(x for x in all_blocks(R) if x["id"] == pid)


def chosen_portfolio_id(R: dict[str, Any]) -> tuple[str, bool]:
    val = R["validation"]
    rec = val.get("recommended")
    cid = val.get("chosen_id") or (rec["id"] if rec else R["portfolio"]["targets"]["baseline"]["id"])
    return cid, bool(rec)


def table(title, columns, rows, note=None):
    b: dict[str, Any] = {"type": "table", "title_ko": title, "columns": [{"key": k, "label_ko": l, "format": f} for k, l, f in columns], "rows": rows}
    if note:
        b["note_ko"] = note
    return b


def kpis(R: dict[str, Any], chosen: str) -> list[dict[str, Any]]:
    p = find(R, chosen)
    h, krw = p["headline"], R["money_krw"]["by_portfolio"][chosen]
    bench = R["backtest"]["benchmark"]["id"].replace("benchmark_", "")
    short = not R["backtest"]["period"].get("annualized_reliable", True)
    days = R["backtest"]["period"].get("window_days", R["backtest"]["period"]["trading_days"])
    b = R["backtest"]["benchmark"]["metrics"]["return"]["total_return"]
    ret = ({"id": "cagr", "label_ko": f"기간 수익률 ({days}거래일)", "value": h.get("period_return"), "format": "pct", "note_ko": f"연 환산 {h['cagr']:+.1%} 는 1년 미만 창이라 참고만"}
           if short else {"id": "cagr", "label_ko": "연평균 수익률 (CAGR)", "value": h["cagr"], "format": "pct", "note_ko": "백테스트 기간 기준 연 환산"})  # fmt: skip
    ex = ({"id": "excess", "label_ko": f"비교지수({bench}) 대비 (기간)", "value": (p["metrics"]["return"]["total_return"] or 0) - b, "format": "pp", "note_ko": "같은 기간 누적 수익률 차이"}
          if short else {"id": "excess", "label_ko": f"비교지수({bench}) 대비", "value": h["excess_cagr"], "format": "pp", "note_ko": "같은 기간 CAGR 차이"})  # fmt: skip
    return [
        {"id": "final_value", "label_ko": "최종 평가금액", "value": h["final_value_usd"], "format": "usd",
         # 원화는 평가금액·원금을 같은 환율로 (034: '약 53,509,000원 · 투입 원금 39,296 USD' — 원화 평가액만 보여 5천만 원보다 이익처럼 읽혔는데 달러 기준 −6.3%)
         "note_ko": (f"약 {krw['final_value_krw']:,.0f}원 · 투입 원금 {p['money']['net_invested_usd']:,.0f} USD(약 {p['money']['net_invested_usd'] * R['money_krw']['fx_rate']:,.0f}원) — 둘 다 분석 기준일 환율"
                     if R["request"]["capital"].get("currency", "KRW") == "KRW" and R["money_krw"].get("fx_rate") else f"투입 원금 {p['money']['net_invested_usd']:,.0f} USD")},
        ret, ex,
        {"id": "mdd", "label_ko": "최대낙폭 (MDD)", "value": h["max_drawdown"], "format": "pct", "note_ko": _tolerance_note(R)},
        {"id": "sharpe", "label_ko": "Sharpe 비율", "value": h["sharpe"], "format": "ratio", "note_ko": f"무위험수익률 {R['parameters']['backtest']['risk_free_rate']:.0%} 가정"},
        _view_hit_kpi(R, p),
    ]  # fmt: skip


def _view_hit_kpi(R, p) -> dict[str, Any]:
    """뉴스 뷰 적중률 KPI. 낙폭 맞춤안은 뷰를 바탕 구성에서 물려받으므로 그 적중률을 쓴다 (060: walk-forward 뉴스 BL 을 줄인 맞춤안인데 '이 포트폴리오에는 뷰가 없습니다')."""
    h, via = p["headline"], ""
    if h.get("view_hit_ratio") is None and p.get("kind") == "matched" and p.get("base_id"):
        try:
            base = find(R, p["base_id"])
        except StopIteration:
            base = None
        if base is not None and base.get("headline", {}).get("view_hit_ratio") is not None:
            h, via = base["headline"], f"바탕 구성({pf_label(base)})의 뷰 · "
    if h.get("view_hit_ratio") is None:
        return {"id": "view_hit", "label_ko": "뉴스 뷰 적중률", "value": None, "format": "pct", "note_ko": "이 포트폴리오에는 뷰가 없습니다"}
    # 뷰가 비중을 한 번도 못 바꿨으면 '다음 리밸런싱까지' 적중률은 뜻이 없다 (055: 뷰 4개가 모두 상한에 묶였는데 '다음 리밸런싱까지는 0%', Q-175 와 같은 규칙)
    nxt = ("뷰가 비중을 바꾸지 못해 다음 리밸런싱까지 적중률은 따지지 않음" if views_moved(R, p) is False
           else f"다음 리밸런싱까지는 {h['view_hit_ratio_next_rb']:.0%}" if h.get("view_hit_ratio_next_rb") is not None else "")
    return {"id": "view_hit", "label_ko": "뉴스 뷰 적중률", "value": h["view_hit_ratio"], "format": "pct",
            "note_ko": via + "구성 뒤 12개월 기준" + (f" · {nxt}" if nxt else "")}


def views_moved(R, p: dict[str, Any] | None) -> bool | None:
    """이 포트폴리오의 뉴스 뷰가 비중을 실제로 바꿨나 (None = 뉴스 뷰 구성이 아님). 정적 BL 은 시작일 세트의 기준 대비 차이, walk-forward BL(과 그 맞춤안)은 뷰가 비중을 바꾼 날 수."""
    if not p:
        return None
    if p.get("kind") == "black_litterman" and p.get("mode") == "static":
        rec = next((x for x in R["portfolio"]["targets"]["portfolios"] if x["id"] == p["id"]), None)
        return None if rec is None else max((abs(float(d)) for d in (rec.get("delta_vs_baseline") or {}).values()), default=0.0) > 1e-4
    if p.get("id") == "wf_bl_news" or (p.get("kind") == "matched" and p.get("base_id") == "wf_bl_news"):
        ne = news_effect(R) or {}
        return None if ne.get("disabled") else bool(ne.get("n_dates"))
    return None


def _tolerance_note(R) -> str:
    """허용 낙폭 안내 (라운드 5: 입력값 그대로). 낙폭 맞춤안 목표가 다르면(손실 시 매도 ×0.8, 경험 없음 ×0.9) 그 이유를 함께."""
    eff = float(R["intent"]["risk_params"]["effective_max_drawdown"])
    inp = float(R["request"]["risk"].get("max_drawdown_tolerance", eff))
    if abs(eff - inp) < 1e-6:
        return f"손실 감내 수준 {inp:.1%}"
    why = []
    if R["request"]["risk"].get("loss_reaction") == "sell":
        why.append("손실 시 매도 성향 ×0.8")
    if R["request"].get("profile", {}).get("investment_experience") == "none":
        why.append("투자 경험 없음 ×0.9")
    return f"손실 감내 수준 {inp:.1%} · 낙폭 맞춤안 목표 {eff:.1%} ({', '.join(why) or '보정'})"


# ───────────────────────── 요청·의도 ─────────────────────────
def request_table(R):
    q, d, c, h, r = R["request"], R["request"]["derived"], R["request"]["capital"], R["request"]["horizon"], R["request"]["risk"]
    cur = "원" if c["currency"] == "KRW" else "USD"
    bfx = R["money_krw"].get("backtest_fx") or {}
    rows = [{"k": "투자금", "v": f"{c['initial_amount']:,.0f} USD" if _usd(R) else f"{c['initial_amount']:,.0f}{cur} → 백테스트 시작 {R['portfolio']['backtest_spec']['capital']['initial_amount_usd']:,.2f} USD (시작일 환율 {bfx.get('direction', '-')}, {bfx.get('fx_date', '-')}) · 현재 구성 {d['initial_amount_usd']:,.2f} USD (기준일 환율 {R['money_krw']['direction']}, {d['fx_date']})"},
            {"k": "월 적립", "v": ("없음" if not c.get("monthly_contribution") else
                                  f"{c['monthly_contribution']:,.0f}{cur} (매월 {c.get('contribution_day', 25)}일)" + (
                                      f" → 백테스트 {R['portfolio']['backtest_spec']['capital']['monthly_contribution_usd']:,.2f} USD (시작일 환율) · 현재 구성 {d['monthly_contribution_usd']:,.2f} USD (기준일 환율)"
                                      if c["currency"] == "KRW" else ""))},  # 투자금 줄처럼 두 환율을 다 적는다 (예전에는 기준일 환율만)
            {"k": "투자기간", "v": f"{h['target_years']}년 (분석 기준일 {d['as_of']}, 백테스트 {h.get('backtest_years', 3)}년)"},
            {"k": "투자성향", "v": f"{enum_ko(r['risk_tolerance'])} · 손실 감내 수준 {r['max_drawdown_tolerance']:.1%} · 손실 시 {enum_ko(r['loss_reaction'])}"},  # 영어 코드(moderate·hold) 대신
            {"k": "목표 수익률", "v": f"연 {r['target_annual_return']:.1%} · 비교지수 {r['benchmark']}"},
            {"k": "투자 유니버스", "v": ", ".join(R["request"]["constraints"]["universe"])},
            {"k": "투자 아이디어", "v": q["natural_language"]["idea"]}]  # fmt: skip
    return table("요청 내용", [("k", "항목", "text"), ("v", "내용", "text")], rows)


def themes_table(R):
    rows = [{"label": t["label_ko"], "desc": t["description_ko"], "codes": ", ".join(t["gics_codes"]), "kw": ", ".join(t["keywords"])} for t in R["intent"]["interpretation"]["themes"]]  # 전부 (022: 6개만 보여 '키워드 약함' 제외의 원인 키워드가 안 보였다)
    return table("추출한 테마", [("label", "테마", "text"), ("desc", "어떤 기업이 해당하는가", "text"), ("codes", "GICS 코드", "text"), ("kw", "검색 키워드", "text")], rows)


def constraints_table(R):
    c = R["request"]["constraints"]
    rb = R["request"]["derived"]["rebalance_rule"]
    rows = [{"k": "종목 수", "v": f"목표 {c['num_holdings']['target']}개 (허용 {c['num_holdings']['min']}~{c['num_holdings']['max']})"},
            {"k": "종목당 상한", "v": f"{c['max_weight_per_stock']:.0%}"}, {"k": "섹터당 상한", "v": f"{c['max_weight_per_sector']:.0%}"},
            {"k": "최소 현금 비율", "v": f"{c.get('min_cash_ratio', 0):.0%}"},
            {"k": "리밸런싱", "v": rb["description_ko"]},
            {"k": "제외", "v": ", ".join([*map(theme_ko, c["exclude_themes"]), *map(sector_ko, c["exclude_sectors"]), *c["exclude_tickers"]]) or "없음"},
            {"k": "필수 포함", "v": ", ".join(c.get("must_include_tickers", [])) or "없음"},
            {"k": "레버리지·공매도", "v": "모두 불허"},
            {"k": "최소 시가총액·거래대금", "v": f"시가총액 {usd_ko(c.get('min_market_cap_usd'))} · 일평균 거래대금 {usd_ko(c.get('min_avg_daily_volume_usd'))}"}]  # fmt: skip
    return table("지켜야 하는 조건 (하드 제약)", [("k", "항목", "text"), ("v", "값", "text")], rows)


def _pp(x: float) -> str:
    """비중 차이 한도 → '%p' (0.0333 → '3.33%p', 0.05 → '5%p'). 예전 '{:.0%}p' 는 3.33%p 를 '3%p' 로 적어 실제 +3.3%p 변화가 한도를 넘어 보였다 (010)."""
    return f"{round(float(x) * 100, 2):g}%p"


def _delta_ko(pairs) -> str:
    """기준 대비 비중 변화 → 'A +3.3%p, B -1.2%p'. 0.05%p 안은 계산 잡음이라 빼고, 다 빠지면 '변화 없음' (018: 모든 종목이 상한에 걸려 ±0.0%p 가 '주요 변화' 로 보였다)."""
    shown = [f"{t} {x * 100:+.1f}%p" for t, x in pairs if abs(x) >= 0.0005]
    # 이유는 붙이지 않는다 — 어느 상한이 묶었는지는 카드 문장(view_stuck_note)이 뷰마다 적는다 (049: 섹터는 30%·20% 로 상한 50% 에 안 걸렸는데 '종목·섹터 상한에 묶임')
    return ", ".join(shown) or "변화 없음"


def set_deltas(p: dict[str, Any], k: int) -> list[str]:
    """BL 세트 하나의 기준 대비 큰 변화 k 개. 그 세트의 뷰가 걸리지 않은 종목은 '(뷰 없음, 재배분)' — 날짜별 표시(Q-247)와 같은 규칙
    (068: 시작일 세트 bl_01 의 BMY +1.7%p 는 섹터 상한 재배분인데 뷰 효과처럼 읽혔고, 서술은 날짜별 값 +3.3%p 를 옮겼다)."""
    legs = {t for v in p.get("views_applied") or [] for t in [*v.get("long", []), *v.get("short", [])]}
    top = sorted((p.get("delta_vs_baseline") or {}).items(), key=lambda x: -abs(x[1]))[:k]
    return [f"{t} {x * 100:+.1f}%p" + ("" if t in legs else " (뷰 없음, 재배분)") for t, x in top if abs(x) >= 0.0005] or ["변화 없음"]


def _notes_ko(text: str) -> str:
    """분석 모델의 성향 해석 메모. 일본어가 섞이면 숨기고(018), 낙폭 맞춤 목표의 조정 이유는 바로 위 줄이 코드로 적으므로 그 문장은 뺀다
    (033: 투자 경험이 '초보' 인데 '초보 투자 경험에 해당하지 않는 입력을 반영해 … 조정하지 않았습니다' — 실제 이유는 '경험 없음' 이 아니라서)."""
    if re.search(r"[\u3040-\u30ff]", text):
        return ""
    return " ".join(x for x in re.split(r"(?<=[.!?다])\s+", text.strip()) if x and "낙폭 맞춤" not in x)


def soft_table(R):
    rp, nt = R["intent"]["risk_params"], R["intent"]["news_tilt"]
    rows = [{"k": "변동성 선호", "v": VOL_PREF_KO.get(rp["volatility_preference"], rp["volatility_preference"])}, {"k": "허용 최대낙폭·낙폭 맞춤안 목표", "v": _tolerance_note(R).replace("손실 감내 수준 ", "")},
            *([{"k": "해석 메모", "v": memo}] if (memo := _notes_ko(rp.get("notes_ko") or "")) else []),  # 빈 메모 줄은 보이지 않는다 (061·062)
            {"k": "뉴스 뷰 반영", "v": (f"켜짐 · 종목당 최대 {_pp(nt['max_tilt_per_stock'])}, 뷰 신뢰도 상한 {nt['max_view_confidence']}" if nt["enabled"] else "꺼짐 (뉴스 뷰 없이 비중 규칙만)")}]  # fmt: skip  (069: 추천이 동일비중인데 '기준 비중만')
    return table("성향 해석 (소프트 조건)", [("k", "항목", "text"), ("v", "해석", "text")], rows)


_PENDING = re.compile(r"답변\s*전까지|답하기\s*전까지|확인이\s*필요|확인 후|답을\s*받기\s*전")


def _plain(t: str) -> str:
    """'필드' 같은 개발 용어는 사용자 말로, 조사도 맞춰 (023: '…표현할 백테스트 종목 수 필드는 없습니다')."""
    for a, b in (("필드는", "조건은"), ("필드가", "조건이"), ("필드를", "조건을"), ("필드로", "조건으로"), ("필드", "조건")):
        t = t.replace(a, b)
    return t


def conflicts_view(R) -> list[dict[str, Any]]:
    """의도 해석의 충돌 목록을 사용자에게 보일 말로 — 카드와 서술(14b) 입력이 같이 쓴다.
    선정 기준 충돌의 처리는 실제로 쓴 기준 하나로 (032: '저평가 선호는 … 보조적으로 반영합니다' 라 했지만 선정·비중 어디에도 쓰이지 않았고,
    재실행은 대화 때 확정한 의도를 다시 쓰므로 02 규칙만으로는 고쳐지지 않는다)."""
    tmpl = ((R.get("request") or {}).get("strategy_preference") or {}).get("template")
    out = []
    for c in R["intent"]["interpretation"].get("conflicts", []) or []:
        res = (f"선정 순위는 {enum_ko(tmpl)} 기준 하나로 매깁니다 (다른 기준은 종목 선정·비중에 쓰지 않습니다)."
               if c.get("field") == "strategy_preference.template" and tmpl else c.get("resolution_ko", ""))
        if _PENDING.search(res):  # 리포트는 대화가 끝난 뒤 읽힌다 (041: 묻지 않은 유니버스 충돌이 '답변 전까지 지금 설정을 사용' 으로 남았다)
            res = "대화에서 따로 정하지 않아 지금 설정을 그대로 썼습니다."
        out.append({**c, "issue_ko": _plain(c.get("issue_ko", "")), "resolution_ko": _plain(res)})
    return out


def conflicts_cards(R):
    cs = conflicts_view(R)
    if not cs:
        return None
    return {"type": "cards", "title_ko": "입력 간에 확인한 점", "items": [{"title_ko": field_ko(c["field"]), "text_ko": c["issue_ko"] + " → " + c["resolution_ko"], "meta": []} for c in cs]}


# ───────────────────────── 선정 ─────────────────────────
def funnel(R):
    return {"type": "funnel", "items": [{"label_ko": f["label_ko"], "count": f["count"]} for f in R["selection"]["funnel"]]}


def selection_table(R):
    m = R["selection"]["metric"]
    now_as_of, bt_as_of = R["selection"]["as_of_now"]["as_of"], R["selection"]["backtest_as_of"]["as_of"]
    narrow = (R["selection"].get("tagging_summary") or {}).get("theme_filter_applied", True)  # 넓은 테마면 판정 사유·신뢰도를 보이지 않는다 (041)
    rows = [{"ticker": t["ticker"], "name": t["name"], "market": t.get("market", ""), "sector": sector_ko(t["sector"]), "summary": t["summary"],
             "reason": (t.get("theme_reason_ko") or "") if narrow else BROAD_REASON_KO,
             "conf": t["theme_confidence"] if narrow else None, "rank_bt": t["rank_backtest"], "metric_bt": t["metric_backtest"], "rank_now": t["rank_now"], "metric_now": t["metric_now"],
             "fact": t.get("metric_fact_id") or ""} for t in R["selection"]["table"]]  # fmt: skip
    return table(f"선정 종목 (백테스트 기준일 {bt_as_of} 순위 → 분석 기준일 {now_as_of} 순위)",
                 [("ticker", "티커", "text"), ("name", "회사", "text"), ("market", "시장", "text"), ("sector", "섹터", "text"), ("summary", "한 줄 소개", "text"),
                  ("reason", "테마 판정 사유", "text"), ("conf", "신뢰도", "num"), ("rank_bt", f"순위({bt_as_of})", "int"), ("metric_bt", m, "pct"),
                  ("rank_now", f"순위({now_as_of})", "int"), ("metric_now", m, "pct"), ("fact", "지표 근거 ID", "text")],
                 rows, note="순위가 비어 있으면 그 기준일에 선정되지 않았거나 필수 포함 종목입니다(필수 포함은 순위와 관계없이 담아 순위를 매기지 않음). 지표 근거 ID 는 출처 패널에서 값·기준일을 확인할 수 있습니다.")  # fmt: skip


def excluded_table(R):
    ex = R["selection"]["as_of_now"]["rejected_examples"]
    if not ex:
        return None
    rows = [{"ticker": r["ticker"], "name": r["name"], "reason": r["reason"], "metric": r.get("metric_value")} for r in ex]
    fmt = "num" if R["selection"].get("metric") == "pe_ttm" else "pct"  # PER 은 배수 (016: 'pct' 로 고정해 PER 97.1 이 +9,710% 로 보였다)
    broad = not (R["selection"].get("tagging_summary") or {}).get("theme_filter_applied", True)  # 넓은 테마는 테마 판정을 하지 않았다 (042: 테마 밖으로 판정된 종목이 '테마에는 해당하지만' 표에)
    return table(f"{'후보였지만' if broad else '테마에는 해당하지만'} 최종 선정에서 빠진 예 ({R['selection']['as_of_now']['as_of']} 기준)",
                 [("ticker", "티커", "text"), ("name", "회사", "text"), ("reason", "제외 이유", "text"), ("metric", "PER(배)" if fmt == "num" else "지표값", fmt)], rows)  # fmt: skip


LOOKAHEAD_KO = "분석 기준일 선정 목록을 과거에도 그대로 썼습니다(시작일 재선정 없음). 지금 알려진 정보로 고른 목록이라 과거 성과가 실제보다 좋게 보일 수 있습니다."


def diff_table(R):
    d = R["selection"]["backtest_as_of"]["diff_vs_original"]
    if R["selection"].get("backtest_reselected") is False:  # 재선정을 하지 않았다 — '같은 규칙을 다시 적용' 메모는 거짓 (054)
        return table("백테스트에 쓴 종목 목록", [("k", "구분", "text"), ("v", "종목", "text")],
                     [{"k": "백테스트 종목", "v": ", ".join(r["ticker"] for r in R["selection"]["backtest_as_of"].get("table") or []) or "-"}], note=LOOKAHEAD_KO)  # fmt: skip
    # 빠진 종목은 그날 사유별로 (049: 9개를 사유 없이 나열 — 8개가 그날 시가총액이 최소 시가총액에 못 미친 것이었다)
    why: dict[str, list[str]] = {}
    for r in R["selection"]["backtest_as_of"].get("removed_reasons_ko") or []:
        why.setdefault(r.get("reason_ko") or "", []).append(r["ticker"])
    removed = " · ".join(f"{', '.join(ts)} ({k})" if k else ", ".join(ts) for k, ts in sorted(why.items(), key=lambda x: -len(x[1]))) if why else ", ".join(d["removed"])
    rows = [{"k": "백테스트용 재선정에서 추가된 종목", "v": ", ".join(d["added"]) or "없음"}, {"k": "빠진 종목", "v": removed or "없음"}]
    broad = not (R["selection"].get("tagging_summary") or {}).get("theme_filter_applied", True)
    return table("분석 기준일 선정 목록과 백테스트 시작일 재선정 목록의 차이", [("k", "구분", "text"), ("v", "종목", "text")], rows,
                 note="백테스트는 시작일 당시에 알 수 있던 정보만으로 같은 규칙을 다시 적용합니다. 그래서 목록이 달라질 수 있습니다."
                      + (" 넓은 테마라 시작일에는 그날 후보 전체에서 그날 지표로 골랐고, 분석 모델이 판정하지 않은 종목은 제외 테마를 키워드로만 걸렀습니다." if broad else ""))  # fmt: skip


def company_cards(R):
    expl = R["selection"].get("explained")
    if not expl or not expl.get("per_ticker"):
        return None
    names = {t["ticker"]: t for t in R["selection"]["table"]}
    items = []
    for r in expl["per_ticker"]:
        t = names.get(r["ticker"], {})
        items.append({"title_ko": f"{r['ticker']} · {t.get('name', '')}", "text_ko": r.get("rationale_ko", ""),
                      "meta": [{"label_ko": "섹터", "value": sector_ko(t.get("sector", ""))}, {"label_ko": "테마 신뢰도", "value": f"{t.get('theme_confidence') or 0:.2f}"}]})  # fmt: skip
    return {"type": "cards", "title_ko": "기업별 선정 근거 (인용 ID 는 출처 패널 참조)", "items": items}


def infeasibility_callout(R):
    bt_sel, now = R["selection"]["backtest_as_of"], R["selection"]["as_of_now"]
    inf = bt_sel.get("infeasibility") or now.get("infeasibility")
    if inf:
        # 어느 시점 선정인지 밝힌다 (002: 시작일 2종목 얘기가 날짜 없이 나와 지금 9종목 구성도 50% 만 투자되는 것처럼 읽혔다)
        when = f"백테스트 시작일({bt_sel.get('as_of')})에 고른" if bt_sel.get("infeasibility") else f"분석 기준일({now.get('as_of')})에 고른"
        opts = [o for o in inf["options_ko"] if "해결 불가" not in o]  # 예전 결과 호환: '섹터 상한 완화로도 해결 불가' 는 보기가 아니다
        txt = (f"{when} 종목 {inf.get('n_selected', sum(inf['sector_counts'].values()))}개는 종목당 {inf['stock_cap']:.0%}·섹터당 {inf['sector_cap']:.0%} 상한 안에서 "
               f"투자금의 {inf['capacity']:.0%}까지만 배분할 수 있어 나머지는 현금으로 둡니다. 섹터별 종목 수: {sector_counts_ko(inf['sector_counts'])}."
               + (f" {inf['note_ko']}." if inf.get("note_ko") else "") + (" 해결 방법: " + " / ".join(opts) if opts else ""))  # fmt: skip
        return {"type": "callout", "tone": "caution", "title_ko": "상한 안에서 전액 배분할 수 없는 구성", "text_ko": txt}
    # 어느 날 선정인지 밝힌다 (008: 시작일 선정의 '정보기술 10개' 가 날짜 없이 나왔다). 두 날 다 있으면 둘 다 (026: 시작일 AMAT 만 나오고 지금 구성의 WDC 는 설명이 없었다)
    parts = [f"{when}({sel.get('as_of')}) 선정: {sel['sector_overflow']['note_ko']} (해당 종목: {', '.join(sel['sector_overflow']['tickers'])})"
             for when, sel in (("백테스트 시작일", bt_sel), ("분석 기준일", now)) if sel.get("sector_overflow")]  # fmt: skip
    if parts:
        return {"type": "callout", "tone": "info", "title_ko": "섹터 상한이 비중을 누른 부분", "text_ko": " ".join(parts)}
    note = _cap_squeeze_note(R)
    return {"type": "callout", "tone": "info", "title_ko": "섹터 상한이 비중을 누른 부분", "text_ko": note} if note else None


def _wf_delta_ko(R) -> str:
    """날짜별(walk-forward) 구성의 δ 범위 — 시작일 δ 만 적어 날짜마다 다른 δ(상한 8 포함)가 안 보였다 (078: 2.0·2.4·2.0·8.0, 8 인 날은 뷰 조정이 0.66%p 까지만)."""
    ds = [float(m["delta"]) for m in (((R.get("portfolio") or {}).get("walkforward") or {}).get("market_models_by_date") or {}).values() if m.get("delta") is not None]
    if len(ds) < 2 or max(ds) - min(ds) < 1e-4:
        return ""
    return f" · 날짜별(walk-forward) δ {min(ds):g}~{max(ds):g}" + (" (상한 8 적용 날짜 포함)" if max(ds) >= 8.0 - 1e-9 else "")


def _any_bl(R) -> bool:
    """뉴스 뷰 BL 구성을 하나라도 만들었나 (시작일 세트·walk-forward·분석 기준일 세트)."""
    pf = R.get("portfolio") or {}
    return bool(any(x.get("kind") == "black_litterman" for x in (pf.get("targets") or {}).get("portfolios") or [])
                or any(x.get("kind") == "black_litterman" for x in (pf.get("walkforward") or {}).get("portfolios") or [])
                or (pf.get("forward") or {}).get("portfolios"))  # fmt: skip


def _cap_squeeze_note(R) -> str | None:
    """섹터 선호를 쓰지 않았어도(순위대로 다 담겨 Q-189 로 건너뜀) 지금 구성에서 섹터 상한이 비중을 누를 수 있다 — 그 사실 (072: '동일비중' 인데
    산업재 10종목만 3.5%(다른 종목 6.0%), 맞춤안으로 줄여 1.21% vs 2.07% — 아무 설명이 없었다)."""
    try:
        chosen, _ = chosen_portfolio_id(R)
        p = find(R, chosen)
    except (KeyError, StopIteration, TypeError):
        return None
    matched = p.get("kind") == "matched"
    base = str(p.get("base_id") or chosen) if matched else chosen
    core = base[3:] if base.startswith("wf_") else base
    t = next((x for x in ((R["portfolio"].get("forward") or {}).get("templates") or []) if x.get("id") == core), None)
    secs = [str(c).split(":", 1)[1] for c in (t or {}).get("constraints_applied") or [] if str(c).startswith("sector_cap:")]
    counts = (R["selection"]["as_of_now"].get("summary") or {}).get("sector_counts") or {}
    cap = float(R["request"]["constraints"].get("max_weight_per_sector") or 1.0)
    parts = [f"{sector_ko(sc)} 종목이 {counts[sc]}개라 섹터 상한 {cap:.0%}를 나눠 가져(종목당 약 {cap / counts[sc]:.1%}) 같은 규칙인데도 다른 섹터 종목보다 비중이 낮습니다"
             for sc in secs if counts.get(sc)]  # fmt: skip
    if not parts:
        return None
    return (f"분석 기준일({R['selection']['as_of_now']['as_of']}) 구성({NAMES.get(core, core)}): " + "; ".join(parts) + "."
            + (" 낙폭 맞춤안은 이 비중을 주식 비율만큼 함께 줄입니다." if matched else ""))  # fmt: skip


# ───────────────────────── 구성 ─────────────────────────
def baseline_table(R):
    bl = R["portfolio"]["baselines"]
    base = next(p for p in bl["portfolios"] if p["id"] == bl["chosen_baseline"])
    n = len(base["weights"])
    sec = {t["ticker"]: sector_ko(t["sector"]) for t in R["selection"]["table"]}
    rows = [{"ticker": t, "sector": sec.get(t, ""), "raw": 1 / n, "final": w} for t, w in base["weights"].items()]
    return table(f"기준 포트폴리오({NAMES.get(base['id'], base['id'])}): 1/N 참고값 → 상한 적용 후 비중", [("ticker", "티커", "text"), ("sector", "섹터", "text"), ("raw", "1/N", "pct1"), ("final", "최종 비중", "pct1")], rows,
                 note=("적용된 제약: " + ", ".join(base["constraints_applied"])) if base["constraints_applied"] else "제약이 묶이지 않았습니다.")  # fmt: skip


def templates_table(R):
    rows = [{"name": NAMES.get(p["id"], p["id"]), "rule": p["rule_ko"], "vol": p["ex_ante"]["vol"], "neff": p["ex_ante"]["effective_n"], "top": max(p["weights"].values()), "cash": p.get("cash_weight", 0)}
            for p in R["portfolio"]["baselines"]["portfolios"]]  # fmt: skip
    return table("비중 규칙 4가지 비교 (구성일 기준 추정치)", [("name", "규칙", "text"), ("rule", "설명", "text"), ("vol", "예상 변동성", "pct"), ("neff", "유효 종목 수", "num"), ("top", "최대 비중", "pct1"), ("cash", "현금", "pct1")], rows)


def donut(title, weights, note=None):
    items = [{"label": t, "value": w} for t, w in sorted(weights.items(), key=lambda x: -x[1]) if w > 1e-6]
    b: dict[str, Any] = {"type": "donut", "title_ko": title, "items": items}
    if note:
        b["note_ko"] = note
    return b


def scenario_cards(R):
    ports = R["portfolio"]["targets"]["portfolios"]
    if not ports:
        return None
    items = []
    bt = {p["id"]: p for p in R["backtest"]["portfolios"]}
    for p in ports:
        views = "\n".join("· " + v["summary_ko"] for v in p["views_applied"])
        hit = bt.get(p["id"], {}).get("headline", {}).get("view_hit_ratio")
        stuck = view_stuck_note(R, p)
        items.append({"title_ko": p.get("title_ko") or p["name_ko"], "text_ko": (p.get("portfolio_view") or "").split("\n")[0] + "\n" + views + (f"\n{stuck}" if stuck else ""),
                      "meta": [{"label_ko": "기준 대비 주요 변화", "value": ", ".join(set_deltas(p, 3))},
                               {"label_ko": "뷰 적중률(백테스트)", "value": f"{hit:.0%}" if hit is not None else "-"},
                               {"label_ko": "근거", "value": ", ".join(sorted({i for v in p["views_applied"] for i in v.get("evidence_ids", [])})) or "-"}]})  # fmt: skip
    return {"type": "cards", "title_ko": "시작일 뉴스 뷰 Black-Litterman 포트폴리오", "items": items}


def allocation_table(R, chosen):
    p = find(R, chosen)
    init = R["portfolio"]["backtest_spec"]["capital"]["initial_amount_usd"]
    # 백테스트 시작일 배분이라 그날 환율로 (기준일 환율을 쓰면 원금 1,000만 원이 1,160만 원으로 보였다, 002)
    fx = float((R["money_krw"].get("backtest_fx") or {}).get("fx_rate") or R["money_krw"]["fx_rate"])
    sec = {t["ticker"]: sector_ko(t["sector"]) for t in R["selection"]["table"]}
    names = {t["ticker"]: t["name"] for t in R["selection"]["table"]}
    # 원화는 원화 원금 × 비중 — 반올림한 달러 원금 × 환율이면 합이 원금과 어긋났다 (052: 1,000만 원이 10,000,006원, Q-171 과 같은 규칙)
    krw0 = (R["portfolio"]["backtest_spec"]["capital"].get("initial_amount_krw") or None)
    rows = [{"ticker": t, "name": names.get(t, t), "sector": sec.get(t, ""), "w": w, "usd": init * w, "krw": (krw0 * w if krw0 else init * w * fx)}
            for t, w in sorted(p["target_weights"].items(), key=lambda x: -x[1])]  # fmt: skip
    cash = 1 - sum(p["target_weights"].values())
    if cash > 1e-6:
        rows.append({"ticker": "현금", "name": "", "sector": "", "w": cash, "usd": init * cash, "krw": (krw0 * cash if krw0 else init * cash * fx)})
    cols = [("ticker", "티커", "text"), ("name", "회사", "text"), ("sector", "섹터", "text"), ("w", "비중", "pct1"), ("usd", "USD", "usd")] + ([] if _usd(R) else [("krw", "원화", "krw")])
    return table(f"배분 금액 ({pf_label(p)}, 백테스트 시작일 초기 투자금 {init:,.0f} USD 기준" + (")" if _usd(R) else ", 원화는 시작일 환율)"), cols, rows)


def delta_bar(R, pid):
    p = next((x for x in R["portfolio"]["targets"]["portfolios"] if x["id"] == pid), None)
    if not p:
        return None
    # 0.05%p 안은 계산 잡음 — 다 잡음이면 차트를 그리지 않는다 (049: 움직이지 않은 세트의 차트에 'SO −0.00%p' 같은 막대만 있었다, 카드는 '변화 없음')
    items = [{"label": t, "value": v} for t, v in sorted(p["delta_vs_baseline"].items(), key=lambda x: -x[1]) if abs(v) >= 0.0005]
    if not items:
        return None
    return {"type": "bar", "title_ko": f"{p.get('title_ko') or p['name_ko']}: 기준 비중 대비 변화", "items": items, "format": "pp"}


def sector_bar(R, chosen):
    p = find(R, chosen)
    sw = p["metrics"]["composition"]["sector_weights_avg"]
    # 섹터 이름은 한국어로 (028: 문장은 '금융 87.4%' 인데 막대는 'Financials')
    return {"type": "bar", "title_ko": f"섹터 노출 (기간 평균 비중, {pf_label(p)})", "items": [{"label": sector_ko(k), "value": v} for k, v in sorted(sw.items(), key=lambda x: -x[1])], "format": "pct1"}


# ───────────────────────── 성과 ─────────────────────────
def assumptions_callout(R):
    e, s = R["backtest"]["engine"], R["portfolio"]["backtest_spec"]
    ex = (e.get("execution_rule") or {}).get("description_ko", "")
    # 적립액이 정수가 아니면 소수 둘째 자리까지 (055: 250.50 USD 를 '250 USD' 로 적어 순투입액과 17 USD 어긋났다)
    ca = float(e.get("contribution_usd") or 0)
    flow = (f"매월 {ca:,.0f} USD" if abs(ca - round(ca)) < 0.005 else f"매월 {ca:,.2f} USD") + f" 적립 {e['n_contributions']}회" if e.get("n_contributions") and ca else "적립 없음"  # '매월 0 USD 적립 0회' 대신
    txt = (f"기간 {s['period']['start']} ~ {s['period']['end']} ({R['backtest']['period']['trading_days']}거래일). 초기 투자금 {s['capital']['initial_amount_usd']:,.0f} USD, "
           f"{flow}. {s['rebalance_rule']['description_ko']}. {ex} 거래비용 거래대금의 {e['commission_bps'] / 100:.2f}%, "
           f"배당 재투자, 소수 주식 허용. 투자하지 않은 현금은 이자 없이 0%로 계산했고, 무위험수익률 연 {e['risk_free_rate']:.0%}는 Sharpe 계산에만 씁니다. "
           "과거 성과는 미래 성과를 보장하지 않습니다.")  # fmt: skip  (현금이 큰 낙폭 맞춤안의 수익·Sharpe 를 읽으려면 현금 0% 가정을 알아야 한다, 003)
    if _has_kr(R):  # 한국 종목이 있을 때만 (예전에는 미국 종목뿐인 리포트에도 '한국 종목은 거래일 환율로 환산' 이 붙었다)
        txt += (" 한국 종목은 거래일 환율로 USD 환산했습니다. 모든 성과·지표(수익률·변동성·낙폭·모멘텀)는 미국 달러 환산 가격 기준이라, "
                "원화 종목에는 환율 변동이 섞여 있습니다. 원화로 보는 수익과 다를 수 있습니다.")
    return {"type": "callout", "tone": "info", "title_ko": "백테스트 가정", "text_ko": txt}


def _has_kr(R) -> bool:
    tickers = [t.get("ticker") for t in (R.get("selection") or {}).get("table") or []]
    if not tickers:
        tickers = ((R.get("backtest") or {}).get("reproducibility") or {}).get("panel", {}).get("tickers") or []
    if not tickers:
        tickers = list(((R.get("portfolio") or {}).get("backtest_spec") or {}).get("selection", {}).get("tickers") or [])
    return any(str(t).endswith(".KS") for t in tickers)


def comparison_table(R):
    status = {r["id"]: r["status"] for r in R["validation"]["results"]}
    status.update({a["id"]: a["status"] for a in R["validation"].get("alternatives", [])})
    rows = []
    for p in all_blocks(R):
        h, m = p["headline"], p["metrics"]
        rows.append({"name": pf_label(p), "kind": KIND_KO[p["kind"]], "cagr": h["cagr"], "vol": m["risk"]["ann_vol"], "sharpe": h["sharpe"], "mdd": h["max_drawdown"],
                     "excess": h["excess_cagr"], "final": h["final_value_usd"], "irr": p["money"]["irr_annual"], "status": STATUS_KO.get(status.get(p["id"], "n/a"), "-")})  # fmt: skip
    return table("포트폴리오 비교 (같은 기간·같은 적립)", [("name", "포트폴리오", "text"), ("kind", "종류", "text"), ("cagr", "CAGR", "pct"), ("vol", "변동성", "pct"), ("sharpe", "Sharpe", "ratio"),
                 ("mdd", "최대낙폭", "pct"), ("excess", "비교지수 대비", "pp"), ("final", "최종 평가금액", "usd"), ("irr", "적립 기준 연수익(XIRR)", "pct"), ("status", "검증", "text")], rows,
                 note="비교지수 대비는 사용자가 지정한 비교지수(" + R["portfolio"]["backtest_spec"]["benchmark"] + ") 기준입니다. "
                 + ("'낙폭 맞춤'은 이름에 적힌 바탕 구성(기준 비중 또는 walk-forward 뉴스 뷰 BL)의 주식 비율을 줄여 과거 최대낙폭을 목표 안에 맞춘 후보입니다. " if any(x.get("kind") == "matched" for x in R["backtest"]["portfolios"]) else "")
                 + "검증 '주의'에는 허용 낙폭 초과 표시도 들어갑니다.")  # fmt: skip  (018·021: 없는 '낙폭 맞춤' 행을 설명했다)


def yearly_table(R, chosen):
    p, b = find(R, chosen), R["backtest"]["benchmark"]
    years = sorted(p["yearly_returns"])
    rows = [{"name": pf_label(p), **{y: p["yearly_returns"][y] for y in years}}, {"name": b["name_ko"], **{y: b["yearly_returns"].get(y) for y in years}}]
    return table("연도별 수익률", [("name", "구분", "text")] + [(y, y, "pct") for y in years], rows, note="첫해와 마지막 해는 일부 기간입니다.")


def monthly_table(R, chosen):
    p = find(R, chosen)
    by: dict[int, dict[int, float]] = {}
    for m in p["monthly_returns"]:
        by.setdefault(m["year"], {})[m["month"]] = m["return"]
    rows = [{"year": str(y), **{f"m{k}": by[y].get(k) for k in range(1, 13)}} for y in sorted(by)]
    return table("월별 수익률", [("year", "연도", "text")] + [(f"m{k}", f"{k}월", "pct") for k in range(1, 13)], rows)


def contribution_bar(R, chosen):
    """종목별 기여(로그 연결) + 거래비용 등 잔차 = 기간 수익률 (예전 단순합은 기간 수익률과 합이 맞지 않았다, 002: 125.4%p vs 205.4%)."""
    p = find(R, chosen)
    items = [{"label": t, "value": v} for t, v in sorted(p["ticker_contribution"].items(), key=lambda x: -(x[1] or 0)) if v is not None]
    resid = ((p.get("metrics") or {}).get("composition") or {}).get("ticker_contribution_residual")
    period = (p.get("headline") or {}).get("period_return")
    shown = sum(float(x["value"]) for x in items)
    # 잔차가 작아도 보이는 합(소수 첫째 자리)을 바꾸면 막대로 보인다 (072: 잔차 -0.046%p 를 빼 막대 합 -6.1% 인데 '기간 수익률 -6.2% 와 같습니다')
    if resid is not None and (abs(resid) >= 0.0005 or (period is not None and round(shown * 100, 1) != round(float(period) * 100, 1))):
        items.append({"label": "거래비용 등", "value": resid})
    return {"type": "bar", "title_ko": "종목별 수익 기여 (기간 전체)", "items": items, "format": "pp",
            **({"note_ko": f"막대를 모두 더하면 기간 수익률 {period * 100:+.1f}% 와 같습니다 (현금은 수익 0%라 기여 0)."} if period is not None else {})}


def _to_date_view(td: dict[str, Any] | None) -> dict[str, Any] | None:
    """시작부터 누적 성과. 1년이 안 된 구간의 연환산(CAGR·Sharpe·초과 CAGR)은 비운다 — 6주 수익을 '연 -16.6%' 로 보였다 (009·010).
    화면은 빈 값을 '–' 로 그린다. 기간 수익률·MDD 는 그대로."""
    if not td:
        return None
    out = {k: td.get(k) for k in ("total_return", "cagr", "max_drawdown", "sharpe", "excess_cagr")}
    if td.get("reliable") is False:
        out.update(cagr=None, sharpe=None, excess_cagr=None)
    return out


def checkpoints_block(R, chosen):
    p = find(R, chosen)
    items = []
    for cp in p["checkpoints"]:
        items.append({"seq": cp["seq"], "date": cp["date"], "kind": cp["kind"], "n_trading_days_to_date": cp["n_trading_days_to_date"],
                      "weights_before": cp["weights"]["before"], "weights_after": cp["weights"]["after"], "weights_target": cp["weights"]["target"],
                      "holdings": cp["holdings"], "since_last": cp["since_last"], "to_date": cp["to_date"], "n_trades": len(cp["trades"]),
                      "commission_usd": cp["commission_usd"], "value_usd": cp["money"]["value_usd"], "benchmark_value_usd": cp["money"]["benchmark_value_usd"],
                      "net_invested_usd": cp["money"]["net_invested_usd"], "drift": cp["drift"]})  # fmt: skip
    return {"type": "checkpoints", "title_ko": f"리밸런싱 시점별 구성과 성과 ({pf_label(p)})", "portfolio_id": chosen, "items": items}


def view_table(R, chosen):
    p = find(R, chosen)
    if not p.get("view_diagnostics"):
        return None
    rows = [{"view": v["summary_ko"].split(" — ")[0], "exp": v["expected_return_annual"], "real": v["realized"],
             "hit": "판정 보류(12개월 전)" if v.get("hit") is None else ("적중" if v["hit"] else "빗나감"),
             "ev": ", ".join(v.get("evidence_ids", []))} for v in p["view_diagnostics"]]  # fmt: skip
    return table("뉴스 뷰와 실제 결과 (구성 후 12개월)", [("view", "뷰", "text"), ("exp", "기대", "pct"), ("real", "실제", "pct"), ("hit", "방향", "text"), ("ev", "근거", "text")], rows)


def validation_tables(R, chosen):
    res = next((r for r in R["validation"]["results"] if r["id"] == chosen), None)
    alt = next((a for a in R["validation"].get("alternatives", []) if a["id"] == chosen), None)
    checks = res["checks"] if res else (alt["checks"] if alt else [])
    rows = [{"rule": c["rule"], "name": c["name_ko"], "level": LEVEL_KO.get(c["level"], c["level"]), "msg": c["message_ko"], "status": STATUS_KO[c["status"]]} for c in checks]
    integ = (res or alt or {}).get("integrity") or []
    n_int = sum(1 for c in integ if c["status"] == "pass")
    t1 = table(f"검증 규칙 ({pf_label(find(R, chosen))})", [("rule", "규칙", "text"), ("name", "항목", "text"), ("level", "수준", "text"), ("msg", "측정 결과", "text"), ("status", "판정", "text")], rows,
               note=(f"표시 = 추천 여부를 가르지 않고 순위에 반영(허용 낙폭을 조금이라도 넘으면 한 단계 뒤로, 그 뒤 5%p 마다 한 단계씩 더), 권장 = 주의로만 표시, 참고 = 판정에 넣지 않는 정보. 종목·섹터 상한 준수와 자료 무결성은 코드가 따로 점검했습니다 ({n_int}/{len(integ)} 통과, 실행 기록 참고)." if integ else None))  # fmt: skip
    rows2 = [{"name": pf_label(find(R, r["id"])), "status": STATUS_KO[r["status"]],
              "fails": ", ".join(f"{c['rule']} {c['name_ko']}" for c in r["checks"] if c["status"] == "fail") or "-",
              "warns": ", ".join(f"{c['rule']} {c['name_ko']}" + (" (허용 초과)" if c["status"] == "flag" else "") for c in r["checks"] if c["status"] in ("warn", "flag")) or "-"} for r in R["validation"]["results"]]  # fmt: skip
    # 손실 시 매도·투자 경험 없음이면 같은 조건에서 낙폭 맞춤안을 먼저 둔다 — 이 단계가 빠진 설명은 016 처럼 Sharpe 가 더 낮은 추천과 어긋나 보였다
    cautious = bool((R["validation"].get("criteria") or {}).get("cautious"))
    # 동점 처리까지 적는다 (049: 14개 후보가 모두 같은 성과라 사용자가 고른 기준 비중으로 정해졌는데 설명은 'Sharpe' 에서 끝났다)
    order = ("목표수익 → 비교지수 → 허용 낙폭 초과 폭 → " + ("같은 조건이면 낙폭 맞춤안 우선(손실 시 매도·투자 경험 없음) → " if cautious else "")
             + "Sharpe → 최대낙폭 → 사용자가 고른 기준 비중")  # fmt: skip
    t2 = table("전체 포트폴리오 검증 요약", [("name", "포트폴리오", "text"), ("status", "판정", "text"), ("fails", "미통과 항목", "text"), ("warns", "주의·표시 항목", "text")], rows2,
               note=f"추천은 순위({order}) 1위입니다. 미통과는 내부 점검(상한·자료 무결성)에 걸린 경우만 생깁니다.")  # fmt: skip
    return t1, t2


def recommendation_card(R):
    rec = R["validation"].get("recommended")
    s = R["validation"]["summary"]
    text = rec["reason_ko"] if rec else (next((n["message_ko"] for n in (R.get("notices") or []) if n.get("code") == "no_portfolio_passed"), None)
                                        or "모든 포트폴리오가 필수 검증 규칙을 통과하지 못했습니다.")  # 영어 검증 경고 대신 한국어 공지
    vd = (rec or {}).get("verdict")
    title = (f"{vd['head_ko']}: {pf_label(find(R, rec['id']))}" if vd else (f"추천: {pf_label(find(R, rec['id']))}" if rec else "조건을 통과한 포트폴리오 없음"))
    meta = ([{"label_ko": "비교 후보", "value": f"{s.get('n_candidates', len(R['validation']['results']))}개"}, {"label_ko": "주의·허용 초과 있는 후보", "value": f"{s['n_warn']}개"}]
            if vd else [{"label_ko": "통과/주의/미통과", "value": f"{s['n_pass']}/{s['n_warn']}/{s['n_fail']}"}])
    return {"type": "cards", "title_ko": "검증 결과", "items": [{"title_ko": title, "text_ko": text, "meta": meta}]}


def alternatives_cards(R):
    alts = R["validation"].get("alternatives", [])
    if not alts:
        return None
    items = []
    for a in alts:
        h = a["headline"]
        items.append({"title_ko": a["name_ko"], "text_ko": a["reason_ko"],
                      "meta": [{"label_ko": "검증", "value": STATUS_KO[a["status"]] + (" (" + ", ".join(c["rule"] for c in a["checks"] if c["status"] != "pass") + ")" if a["status"] != "pass" else "")},
                               {"label_ko": "CAGR / 최대낙폭 / Sharpe", "value": f"{h['cagr']:+.1%} / {h['max_drawdown']:.1%} / {(h['sharpe'] or 0):.2f}"},
                               {"label_ko": "최종 평가금액", "value": f"{h['final_value_usd']:,.0f} USD"}]})  # fmt: skip
    return {"type": "cards", "title_ko": "검토 가능한 대안 (검증 단계가 계산한 현금 혼합안)", "items": items}


# ───────────────────────── 뉴스·walk-forward·현재 구성 ─────────────────────────
def evidence_block(R, ids: list[str], title="인용된 근거"):
    idx = R["evidence_index"]
    items = []
    for i in ids:
        e = idx.get(i)
        if not e:
            continue
        items.append({"id": i, "kind": e["kind"], "title": e.get("title", ""), "source": e.get("source", ""), "url": e.get("url"), "published_at": e.get("published_at"),
                      "data_as_of": e.get("data_as_of"), "tickers": e.get("tickers", []), "value": e.get("value"), "unit": e.get("unit")})  # fmt: skip
    return {"type": "evidence", "title_ko": title, "items": items}


def news_used_ids(R) -> list[str]:
    out: set[str] = set()
    for p in R["portfolio"]["targets"]["portfolios"]:
        for v in p["views_applied"]:
            out.update(v.get("evidence_ids", []))
    wf = R["portfolio"].get("walkforward")
    if wf:
        for p in wf["portfolios"]:
            for d, views in (p.get("views_by_date") or {}).items():
                for v in views:
                    out.update(v.get("evidence_ids", []))
    f = R["portfolio"].get("forward")
    if f:
        for p in f["portfolios"]:
            for v in p["views_applied"]:
                out.update(v.get("evidence_ids", []))
    return sorted(out)


def shown_window(w: list[str] | None) -> list[str] | None:
    """근거 창 [시작, 끝) 의 끝은 그날을 빼는 경계 → 사람에게는 끝 전날까지로 (013: '07-02 ~ 07-16' 이라 기준일 뉴스도 쓴 것처럼 보였고, 시장 분석의 07-15 와 달랐다)."""
    import datetime as dt

    if not w or len(w) != 2:
        return w
    try:
        return [str(w[0]), str(dt.date.fromisoformat(str(w[1])[:10]) - dt.timedelta(days=1))]
    except ValueError:
        return w


def walkforward_changes_plan(R, chosen: str | None = None) -> dict[str, Any] | None:
    """날짜별 '직전 대비' 변화를 보여 줄 walk-forward 구성: 선택안이 walk-forward 규칙 구성(또는 그 구성의 낙폭 맞춤안)이면 그 구성, 아니면 기준 비중 구성
    (024: 추천은 시가총액비중 walk-forward 인데 기준(역변동성) 구성의 변화를 추천안의 리밸런싱 변화처럼 썼다)."""
    ports = {p["id"]: p for p in (R["portfolio"].get("walkforward") or {}).get("portfolios") or []}
    if chosen:
        bt = next((p for p in (R.get("backtest") or {}).get("portfolios") or [] if p["id"] == chosen), {})
        cid = bt.get("base_id") or chosen
        if cid in ports and ports[cid].get("kind") != "black_litterman":
            return ports[cid]
    return ports.get(f"wf_{R['portfolio']['targets']['baseline']['id']}")


def walkforward_weight_changes(R, k: int = 3, chosen: str | None = None) -> dict[str, list[str]]:
    """뉴스 반영 구성이 없을 때(뉴스 끔) walk-forward 구성의 리밸런싱일별 '직전 리밸런싱 대비' 큰 변화 (015: 빈 칸을 받아 '날짜별 비중 변화 내역이 제공되지 않았다' 고 썼다).
    어느 구성인지는 walkforward_changes_plan."""
    base = walkforward_changes_plan(R, chosen)
    wbd = (base or {}).get("weights_by_date") or {}
    out, prev = {}, None
    for d in sorted(wbd):
        if prev is not None:
            w, b = wbd[d], wbd[prev]
            top = sorted(((t, w.get(t, 0.0) - b.get(t, 0.0)) for t in {*w, *b}), key=lambda x: -abs(x[1]))[:k]
            out[d] = [f"{t} {x * 100:+.1f}%p" for t, x in top if abs(x) >= 0.0005] or ["변화 없음"]
        prev = d
    return out


def walkforward_largest_changes(R, chosen: str | None = None, k: int = 3) -> list[str]:
    """기간 전체에서 직전 리밸런싱 대비 가장 큰 비중 변화 k개 — walkforward_weight_changes 와 같은 구성
    (042: '큰 변화' 문장이 WMB −1.4%p 를 들면서 WMB +5.8%p·DOW −5.2%p 를 빠뜨렸다)."""
    wbd = (walkforward_changes_plan(R, chosen) or {}).get("weights_by_date") or {}
    moves, prev = [], None
    for d in sorted(wbd):
        if prev is not None:
            moves += [(d, t, wbd[d].get(t, 0.0) - wbd[prev].get(t, 0.0)) for t in {*wbd[d], *wbd[prev]}]
        prev = d
    return [f"{d} {t} {x * 100:+.1f}%p" for d, t, x in sorted((m for m in moves if abs(m[2]) >= 0.0005), key=lambda m: -abs(m[2]))[:k]]


def matched_on_wf_bl(R, chosen: str | None) -> dict[str, Any] | None:
    """선택안이 walk-forward 뉴스 반영 구성의 낙폭 맞춤안이면 그 포트폴리오 (비중 차이를 그 주식 비율로 줄여 보일 때)."""
    p = next((x for x in R["backtest"]["portfolios"] if x["id"] == chosen), None) if chosen else None
    return p if p and p.get("kind") == "matched" and str(p.get("base_id") or "") == "wf_bl_news" else None


def walkforward_top_deltas(R, k: int = 3, chosen: str | None = None) -> dict[str, list[str]]:
    """walk-forward 뉴스 반영 구성의 날짜별 '기준 비중 대비 큰 변화' (14b 입력: 예전에는 없어서 '비중 변화가 결과에 없다' 고 썼다).
    chosen 이 그 구성의 낙폭 맞춤안이면 타임라인처럼 그날 맞춤안의 주식 비율로 줄인다 (048: 서술은 'AMT -2.0%p' 인데 바로 아래 타임라인은 -1.0%p)."""
    wf = R["portfolio"].get("walkforward") or {}
    ports = {p["id"]: p for p in wf.get("portfolios") or []}
    bl = next((p for p in ports.values() if p.get("kind") == "black_litterman"), None)
    base = ports.get(f"wf_{R['portfolio']['targets']['baseline']['id']}")
    if not bl or not base:
        return {}
    pw_by = (matched_on_wf_bl(R, chosen) or {}).get("weights_by_date") or {}
    out = {}
    for d, w in (bl.get("weights_by_date") or {}).items():
        b = (base.get("weights_by_date") or {}).get(d) or {}
        pw = pw_by.get(d)
        f = (sum(pw.values()) / sum(w.values())) if pw and sum(w.values()) > 0 else 1.0
        # 그날 뷰가 걸리지 않은 종목의 변화는 상한·예산 재배분이다 — 뉴스 때문인 것처럼 읽히지 않게 표시 (059: 근거 없는 007660 +0.7%p 를 뷰 효과로 썼다)
        legs = {t for v in (bl.get("views_by_date") or {}).get(d) or [] for t in (*v.get("long", []), *v.get("short", []))}
        top = sorted(((t, (w[t] - b.get(t, 0.0)) * f) for t in w), key=lambda x: -abs(x[1]))[:k]
        out[d] = [f"{t} {x * 100:+.1f}%p" + ("" if t in legs else " (그날 뷰 없음, 재배분)") for t, x in top if abs(x) >= 0.0005] or ["변화 없음(기준 비중)"]
    return out


def walkforward_blocks(R):
    wf = R["portfolio"].get("walkforward")
    if not wf:
        return []
    bt_by = {p["id"]: p for p in R["backtest"]["portfolios"]}
    # 뉴스 반영 구성은 뉴스를 켜고 뷰가 반영된 날이 있을 때만 있다 (없으면 예전에는 next() 가 StopIteration 으로 리포트 단계를 멈췄다)
    bl = next((p for p in wf["portfolios"] if p["kind"] == "black_litterman"), None)
    base_id = "wf_" + R["portfolio"]["targets"]["baseline"]["id"]
    base_p = next((p for p in wf["portfolios"] if p["id"] == base_id), wf["portfolios"][0])
    rows = []
    for d in wf["dates"]:
        ns = wf["news_summary"].get(d, {})
        views = bl["views_by_date"].get(d, []) if bl else []
        top = []
        if views:
            w, base = bl["weights_by_date"][d], base_p["weights_by_date"][d]
            top = sorted(((t, w[t] - base[t]) for t in w if t in base), key=lambda x: -abs(x[1]))[:3]
        rows.append({"date": d, "window": " ~ ".join(ns.get("window", ["", ""])), "articles": ns.get("n_articles", 0), "tickers": ns.get("n_tickers_with_news", 0),
                     "views": len(views), "delta": ", ".join(f"{t} {x * 100:+.1f}%p" for t, x in top) if views else "기준 비중 유지"})  # fmt: skip
    blocks = [table("리밸런싱 시점별 뉴스와 비중 변화", [("date", "리밸런싱일", "text"), ("window", "뉴스 창", "text"), ("articles", "기사 수", "int"), ("tickers", "뉴스 있는 종목", "int"),
                    ("views", "뷰 수", "int"), ("delta", "기준 대비 주요 변화", "text")], rows)]  # fmt: skip
    cards = []
    for d in wf["dates"] if bl else []:
        for v in bl["views_by_date"].get(d, []):
            cards.append({"title_ko": f"{d} · {v['summary_ko'].split(' — ')[0]}", "text_ko": v.get("rationale_ko", ""),
                          "meta": [{"label_ko": "근거", "value": ", ".join(v.get("evidence_ids", [])) or "-"}, {"label_ko": "신뢰도", "value": f"{v['confidence']:.2f}"}]})  # fmt: skip
    if cards:
        blocks.append({"type": "cards", "title_ko": "뉴스로 만든 뷰 (리밸런싱 시점별)", "items": cards})
    for pid in [bl["id"] if bl else None, base_id]:
        p = bt_by.get(pid) if pid else None
        if p:
            h = p["headline"]
            blocks.append({"type": "callout", "tone": "info", "title_ko": p["name_ko"],
                           # 다른 곳과 같은 표기로 (035: '기간 수익률 -0.10%, 최대낙폭 -14.50%' — 둘째 자리라 첫 매수 수수료 차이가 보였고 낙폭에 부호가 붙었다)
                           "text_ko": f"기간 수익률 {h['period_return']:+.1%}, 최대낙폭 {abs(h['max_drawdown']):.1%}, 최종 평가금액 {h['final_value_usd']:,.0f} USD"
                                      + (f" · 기준 비중을 쓴 날짜: {', '.join(bl['fallback_dates'])}" if bl and pid == bl["id"] and bl["fallback_dates"] else "")
                                      + (f" · {cn}" if bl and pid == bl["id"] and (cn := (news_effect(R) or {}).get("capped_note_ko")) else "")})  # fmt: skip
    if bl is None and (wf.get("bl_omitted") or {}).get("reason_ko"):
        blocks.append({"type": "callout", "tone": "info", "title_ko": "뉴스 반영 구성", "text_ko": wf["bl_omitted"]["reason_ko"]})
    return blocks


def invested_gap_note(R, chosen: str) -> str | None:
    """백테스트(시작일 구성)의 주식 비중이 지금 구성보다 10%p 넘게 낮으면 — 최대낙폭·변동성이 그 현금만큼 눌린 값이라는 사실.
    062: 시작일 6종목 × 종목당 상한 10% 라 백테스트는 주식 60%·현금 40% 였는데 지금 구성은 주식 90% — '손실 감내 수준에 맞다' 고만 했다."""
    try:
        p = find(R, chosen)
    except StopIteration:
        return None
    cc = current_composition(R, chosen)
    if cc is None or not p.get("target_weights"):
        return None
    bt_inv, now_inv = float(sum(p["target_weights"].values())), float(sum(cc[0].values()))
    if now_inv - bt_inv < 0.10 - 1e-9:
        return None
    return (f"백테스트는 주식 {bt_inv:.0%}·현금 {1 - bt_inv:.0%}로 시작해 최대낙폭·변동성이 그 현금만큼 낮게 나왔습니다. "
            f"지금 구성은 주식 {now_inv:.0%}라 같은 흐름이면 손실 폭이 백테스트보다 클 수 있습니다")


def current_ex_ante_vol(R, chosen: str) -> float | None:
    """추천(선택)안 규칙으로 고른 분석 기준일 구성의 예상 연변동성 (10f 구성의 사전 추정치; 맞춤안은 주식 비율만큼 줄임)."""
    f = R["portfolio"].get("forward") or {}
    try:
        p = find(R, chosen)
    except StopIteration:
        return None
    matched = p.get("kind") == "matched"
    base = str(p.get("base_id") or chosen) if matched else chosen
    core = base[3:] if base.startswith("wf_") else base
    src = next((t for t in f.get("templates") or [] if t.get("id") == core), None)
    if src is None and core.startswith("bl"):
        cw = f.get("chosen_weights") or {}
        src = next((x for x in f.get("portfolios") or [] if x.get("weights") == cw), None)
    vol = ((src or {}).get("ex_ante") or {}).get("vol")
    if vol is None:
        return None
    if matched:
        cc = current_composition(R, chosen)
        base_inv = float(sum(((src or {}).get("weights") or {}).values()))
        if cc and base_inv > 0:
            vol = float(vol) * float(sum(cc[0].values())) / base_inv
    return float(vol)


def risk_gap_note(R, chosen: str) -> str | None:
    """지금 구성의 예상 변동성이 백테스트 실현 변동성보다 크게 높으면 — 종목이 바뀌어 과거 낙폭·변동성이 지금 위험을 다 보여 주지 못한다.
    080: 지금 구성(RDDT 82.6%·PLTR 64.3% 변동성)의 예상 변동성 41.9% 인데 백테스트 바구니(CDNS·SNPS·GOOGL…)는 실현 28.0% — 주의가 없었다 (Q-291 의 남은 부분)."""
    try:
        p = find(R, chosen)
    except StopIteration:
        return None
    now = current_ex_ante_vol(R, chosen)
    bt = ((p.get("metrics") or {}).get("risk") or {}).get("ann_vol")
    if now is None or not bt or now < 1.3 * float(bt) or now - float(bt) < 0.07:
        return None
    return (f"지금 구성의 예상 연변동성(최근 자료로 추정) {now:.1%}가 백테스트 실현 변동성 {float(bt):.1%}보다 크게 높습니다. "
            "종목이 바뀌어 과거 최대낙폭·변동성보다 위험이 클 수 있습니다")


def holdings_gap_note(R, chosen: str) -> str | None:
    """백테스트 구성과 지금 구성이 많이 다르면 — 과거 성과가 지금 구성을 그대로 대표하지 않는다 (2026-11 평가: 백테스트 수익을 이끈 NVDA(+29.6%p)가
    지금 구성에 없는데 리포트가 성과 해석에 잇지 않았다, 070·071·073). 지금 비중 중 백테스트에도 있던 종목의 몫이 절반 미만이거나, 기여 상위 3종목 중 지금 없는 종목이 있을 때."""
    try:
        p = find(R, chosen)
    except StopIteration:
        return None
    comp = current_composition(R, chosen)
    if not comp:
        return None
    now_w = {t: w for t, w in comp[0].items() if w > 1e-9}
    invested = sum(now_w.values())
    held_bt = set((p.get("weights_by_date") and {t for ws in p["weights_by_date"].values() for t, w in ws.items() if w > 1e-9})
                  or {t for t, w in (p.get("target_weights") or {}).items() if w > 1e-9})  # fmt: skip
    if not now_w or invested <= 1e-9:
        return None
    share = sum(w for t, w in now_w.items() if t in held_bt) / invested
    # 지금 비중이 아주 작은(2% 미만) 종목은 그 수익을 지금 구성이 거의 받지 못한다 (평가 022: DELL·ORCL·PLTR 이 지금 1% 라 '있다' 로 셌다)
    small = {t for t, w in now_w.items() if w < 0.02}
    pos = {t: v for t, v in (p.get("ticker_contribution") or {}).items() if v is not None and v > 0}
    tot_pos = sum(pos.values()) or 1.0
    contrib = [(t, v) for t, v in sorted(pos.items(), key=lambda x: -x[1])[:3] if v / tot_pos >= 0.10]  # 몫이 작은 종목은 '이끈' 이라 하지 않는다 (072: 3위 +1.7%p)
    gone = [(t, v) for t, v in contrib if t not in now_w or t in small]
    absent = [(t, v) for t, v in gone if t not in now_w]
    tiny = [(t, v) for t, v in gone if t in now_w]
    away = sum(v for t, v in pos.items() if t not in now_w or t in small) / sum(pos.values()) if pos else 0.0
    if share >= 0.5 and not gone and away < 0.5:
        return None
    names = {t["ticker"]: t.get("name") or t["ticker"] for t in (R.get("selection") or {}).get("table") or []}
    # 기준을 밝힌다: 전체 비중 합과 주식 부분 중 몫 (2026-11 평가 007·009·022: 주식 부분 기준 40% 를 밝히지 않아 화면 비중 합 38% 와 어긋나 보였다)
    total = sum(w for t, w in now_w.items() if t in held_bt)
    parts = [f"지금 구성에서 백테스트에도 있던 종목의 비중 합은 {total:.0%}(주식 부분의 {share:.0%})입니다"]
    if absent:  # '없음' 과 '2% 미만' 을 나눠 쓴다 (072: 지금 없는 종목을 '없거나 2% 미만' 이라 흐렸다)
        parts.append("백테스트 수익을 이끈 " + ", ".join(f"{names.get(t, t)}({v * 100:+.1f}%p)" for t, v in absent) + "은(는) 지금 구성에 없습니다")
    if tiny:
        parts.append(", ".join(f"{names.get(t, t)}({v * 100:+.1f}%p)" for t, v in tiny) + "은(는) 지금 구성 비중이 "
                     + ", ".join(f"{now_w[t]:.1%}" for t, _ in tiny) + "로 2% 미만입니다")
        kept = [(t, v) for t, v in contrib if (t, v) not in gone]
        if kept:  # 수익을 가장 많이 낸 종목이 지금도 있으면 함께 (001: AVGO(+87.1%p)가 지금도 30% 인데 '다른 종목이 낸 수익' 이라 과장)
            parts.append(", ".join(f"{names.get(t, t)}({v * 100:+.1f}%p)" for t, v in kept) + f"은(는) 지금도 {', '.join(f'{now_w[t]:.0%}' for t, _ in kept)} 들어 있습니다")
    if away >= 0.5:
        parts.append(f"백테스트에서 오른 종목들의 수익 중 {away:.0%}는 지금 구성에 없거나 비중이 2% 미만인 종목이 냈습니다")
    return " · ".join(parts) + ". 백테스트 성과를 지금 구성에 그대로 기대하기 어렵습니다"


def condition_check(R, chosen: str) -> dict[str, Any]:
    """추천(선택)안이 사용자 조건(허용 낙폭·목표 수익률·비교지수)을 맞췄는지와, 허용 낙폭을 지킨 후보 중 CAGR 이 가장 높은 안과 그 대가.
    리포트 해석(14a·14b)이 순위 규칙보다 먼저 쓰게 넘긴다 (2026-11 평가: 허용 낙폭을 넘는 안을 고른 이유를 동점 처리 같은 순위 규칙으로만 설명했다).
    허용 낙폭을 넘는 안도 추천할 수 있는 것은 정한 정책이다 — 이 사실은 그 선택을 바꾸지 않고, 사용자가 대안을 볼 수 있게 한다."""
    tol = float(R["request"]["risk"]["max_drawdown_tolerance"])
    target = float(R["intent"]["validation_criteria"]["target_annual_return"])
    p = find(R, chosen)
    h = p.get("headline") or {}

    def ok(x: dict[str, Any]) -> tuple[bool, bool]:
        hh = x.get("headline") or {}
        return abs(float(hh.get("max_drawdown") or 0)) <= tol + 1e-9, float(hh.get("cagr") or -9) >= target - 1e-9

    dd_ok, tgt_ok = ok(p)
    cands = [x for x in R["backtest"]["portfolios"] if x["id"] != chosen and ok(x)[0]]
    best = max(cands, key=lambda x: (ok(x)[1], float((x.get("headline") or {}).get("cagr") or -9)), default=None)
    out: dict[str, Any] = {"max_drawdown_within_tolerance": dd_ok, "target_return_met": tgt_ok,
                           "beats_benchmark": float(h.get("excess_cagr") or 0) > 0,
                           "drawdown_excess_pp": None if dd_ok else round((abs(float(h.get("max_drawdown") or 0)) - tol) * 100, 1),
                           "target_gap_pp": None if tgt_ok else round((float(h.get("cagr") or 0) - target) * 100, 1),
                           "any_candidate_within_tolerance": bool(cands) or dd_ok}
    if not dd_ok and best is not None:
        bh = best.get("headline") or {}
        # 목표 판정은 순위 규칙과 같은 R2 로 (098: 전체 CAGR 10.9% > 목표 7% 라 '목표도 충족' 이라 썼는데 R2 는 미달이라 순위에서 밀렸고 검증표는 '목표수익 주의')
        r2 = next((c.get("status") for r in (R.get("validation") or {}).get("results") or [] if r["id"] == best["id"] for c in r.get("checks") or [] if c.get("rule") == "R2"), None)
        out["best_within_tolerance"] = {"id": best["id"], "label": pf_label(best), "cagr": f"{float(bh.get('cagr') or 0):.1%}",
                                        "max_drawdown": f"{abs(float(bh.get('max_drawdown') or 0)):.1%}", "meets_target_r2": r2 == "pass",
                                        "cagr_vs_chosen_pp": round((float(bh.get("cagr") or 0) - float(h.get("cagr") or 0)) * 100, 1),
                                        **({"target_note_ko": f"전체 CAGR 은 목표보다 높지만 순위 규칙의 목표 판정(R2: 투자기간 길이 구간 중 목표를 넘은 비율)에서는 미달"}
                                           if r2 not in (None, "pass") and ok(best)[1] else {})}  # fmt: skip
    out.update(_ranking_facts(R, chosen, tol))
    out.update(_risk_now_facts(R, chosen, p, tol, target))
    return out


PURPOSE_KO = {"wealth_growth": "자산 증식", "income": "배당·이자 등 정기 현금흐름", "capital_preservation": "원금 보전", "retirement": "은퇴 자금"}
# 선정 지표가 재는 것 / 재지 않는 것 (02_intent 프롬프트 표와 같은 내용) — 리포트가 아이디어 중 직접 재지 않은 바람을 밝히게 (2026-11 평가 012 '밸류업', 005 '이익률')
METRIC_SCOPE_KO = {
    "pe_ttm": ("이익 대비 주가(PER, 0배 초과 50배 이하)", "성장성·재무 건전성·배당"),
    "roe_ttm": ("수익성(ROE, 자기자본이익률)", "이익률(마진)·부채 수준(보조 조건이 없을 때)·성장성. 부채가 많거나 자사주 매입으로 자본이 작으면 ROE 가 커 보일 수 있음"),
    "return_12m_1m": ("최근 1개월을 뺀 12개월 주가 상승률(0보다 큰 종목만)", "이익·재무·배당 같은 기업의 질"),
    "vol_60d": ("60거래일 주가 변동성(후보 중 낮은 절반에서)", "이익·재무·배당"),
    "dividend_yield_ttm": ("최근 12개월 배당수익률", "배당을 늘려 왔는지(보조 조건이 없을 때)·주주환원 정책·기업가치 제고(밸류업) 계획"),
}


def _nm(t: dict[str, Any]) -> str:
    """한국 종목은 이름, 미국 종목은 티커 (6자리 코드는 읽는 사람이 알아보기 어렵다)."""
    return str(t.get("name") or t["ticker"]) if str(t["ticker"]).endswith((".KS", ".KQ")) else str(t["ticker"])


def rejected_reason_ko(reason: Any) -> str:
    """선정에서 빠진 사유 코드 → 한국어 (리포트 표와 같은 말). 모르는 코드는 그대로."""
    from backend.analysis.common.warnings import guard_reason_ko

    r = str(reason or "")
    if r.startswith("metric_out_of_range("):
        return "자격선 밖 (" + r[len("metric_out_of_range("):].rstrip(")") + ")"
    known = {"sector_preference": "섹터 선호(순위가 더 낮은 다른 섹터 종목에 자리를 내줌)", "sector_preference_lower": "섹터 선호(같은 섹터 종목이 많아 다른 섹터 종목을 먼저 뽑음)",
             "rank_beyond_n": "순위 밖", "metric_missing": "지표 자료 없음", "no_dividend": "최근 12개월 배당 확인 안 됨"}  # fmt: skip
    return known.get(r) or guard_reason_ko(r) or r


def verdict_cautions(R, chosen: str, vd: dict[str, Any] | None) -> list[str]:
    """결론 옆에 보이는 주의 목록 — 검증의 주의(낙폭 초과 등) + 백테스트·지금 구성 차이 메모. 해석(14a)에도 이 목록을 넘긴다
    (2026-11 평가 001: 검증 verdict 의 빈 목록을 받아 '선택안의 주의 목록은 비어 있습니다' 라고 썼는데 화면에는 주의가 3개 있었다)."""
    return [*((vd or {}).get("cautions_ko") or []), *([g] if (g := invested_gap_note(R, chosen)) else []),
            *([rg] if (rg := risk_gap_note(R, chosen)) else []), *([hg] if (hg := holdings_gap_note(R, chosen)) else [])]


def weights_vs_metric_note(R, chosen: str) -> str | None:
    """비중 방식이 선정 지표 순위와 거꾸로 가면 (지표 상위 3분의 1 의 평균 비중이 하위 3분의 1 의 70% 미만) — 그 사실과 예.
    2026-11 평가 009·022: 최소분산이 모멘텀·ROE 상위 종목에 1%대, 하위 종목에 15% 를 줬는데 리포트가 아이디어('…위주로')와의 차이를 말하지 않았다."""
    cc = current_composition(R, chosen)
    if not cc:
        return None
    w = cc[0]
    met, asc = R["selection"]["metric"], R["selection"].get("direction") == "asc"
    rows = [t for t in R["selection"]["table"] if t.get("in_selection_now") and not t.get("forced") and t.get("metric_now") is not None and t["ticker"] in w]
    if len(rows) < 6:
        return None
    rows.sort(key=lambda t: float(t["metric_now"]), reverse=not asc)  # 좋은 순서
    k = len(rows) // 3
    top, bot = rows[:k], rows[-k:]
    wt, wb = sum(w[t["ticker"]] for t in top) / k, sum(w[t["ticker"]] for t in bot) / k
    if wt >= 0.7 * wb:
        return None
    ex_t = ", ".join(f"{_nm(t)} {w[t['ticker']]:.1%}" for t in top[:3])
    ex_b = ", ".join(f"{_nm(t)} {w[t['ticker']]:.1%}" for t in bot[-3:])
    p = find(R, chosen)
    return (f"지금 구성의 비중 방식({pf_label(p)})은 선정 지표({M.METRIC_SHORT_KO.get(met, met)}) 순위와 거꾸로 비중을 줍니다: "
            f"지표 상위 종목 {ex_t} / 하위 종목 {ex_b}. 종목은 지표로 골랐지만 비중은 변동성·상관관계 같은 다른 기준으로 정해졌습니다")


def selection_notes(R) -> dict[str, Any]:
    """선정 설명에 쓸 사실: 아이디어 원문, 선정 기준이 재는 것·재지 않는 것, 보조 조건, 테마별 선정 수, 후보가 거의 다 담겼는지 (2026-11 평가 006·012)."""
    it = R["intent"]
    met = R["selection"]["metric"]
    scr = it.get("screen") or {}
    guards = [g for g in ((f"최근 {scr['dividend_growth_years']}년 주당배당을 해마다 거의 빠짐없이 늘렸고 한 해도 깎지 않은 종목만"
                           if scr.get("dividend_require_growth", True) is not False else f"최근 {scr['dividend_growth_years']}년 주당배당을 한 해도 깎지 않은 종목만")
                          if scr.get("dividend_growth_years") else None,
                          f"부채비율(부채 ÷ 자본) {float(scr['max_debt_to_equity']):.0%} 이하만(금융 업종 제외)" if scr.get("max_debt_to_equity") else None,
                          f"선정일 시가총액 {scr['mega_cap_rank']}위 안만" if scr.get("mega_cap_rank") else None,
                          "영업이익률(최근 4개 분기)이 같은 유니버스 비금융 종목의 중앙값 이상만(금융 업종 제외)" if scr.get("high_margin") else None,
                          "법인 소재지가 미국인 기업만(정식 이름이 plc·N.V.·Ltd 같은 해외 법인 형태인 기업 제외)" if scr.get("us_hq_only") else None,
                          {"dividend_yield_ttm": "배당수익률이 같은 유니버스 종목의 중앙값 이상만", "pe_ttm": "PER이 같은 유니버스 종목의 중앙값 이하만"}.get(met)) if g]  # fmt: skip
    measures, not_measured = METRIC_SCOPE_KO.get(met, (M.METRIC_KO.get(met, met), ""))
    out: dict[str, Any] = {"idea_ko": (R["request"].get("natural_language") or {}).get("idea"), "metric_measures_ko": measures,
                           "metric_does_not_measure_ko": not_measured, "screen_guards_ko": guards,
                           "purpose_ko": PURPOSE_KO.get((R["request"].get("horizon") or {}).get("purpose"), (R["request"].get("horizon") or {}).get("purpose"))}
    themes = it["interpretation"]["themes"]
    now = [t for t in R["selection"]["table"] if t.get("in_selection_now")]
    if len(themes) > 1:
        cov = [{"theme": th["label_ko"], "n_selected_now": sum(1 for t in now if th["id"] in (t.get("themes") or []))} for th in themes]
        out["theme_coverage"] = cov
        gaps = [c["theme"] for c in cov if c["n_selected_now"] == 0]
        if gaps:
            out["theme_gap_note_ko"] = f"아이디어의 테마 중 {', '.join(gaps)}에 해당하는 종목은 지금 구성에 하나도 들지 않았습니다(다른 테마 종목이 선정 지표 순위에서 앞섬)"
    sm = (R["selection"].get("as_of_now") or {}).get("summary") or {}
    n_ok, n_sel, n_forced = sm.get("n_with_metric"), sm.get("n_selected"), int(sm.get("n_forced") or 0)
    if n_ok and n_sel and n_ok - n_forced >= 3 and n_sel - n_forced >= (n_ok - n_forced) - 1:
        ranked = sorted((t for t in now if not t.get("forced") and t.get("metric_now") is not None), key=lambda t: float(t["metric_now"]),
                        reverse=R["selection"].get("direction") != "asc")  # fmt: skip
        low = ranked[-1] if ranked else None
        all_in = n_sel - n_forced >= n_ok - n_forced
        out["pool_note_ko"] = (f"자격선 안 후보가 {n_ok - n_forced}개뿐이라 {'모두' if all_in else '거의 모두'} 담았습니다. 그래서 선정 지표로 더 거르지 못했습니다"
                               + (f"(지표가 가장 낮은 종목은 {_nm(low)} {M.display_metric(met, low['metric_now'])})" if low else ""))
    return out


def _ranking_facts(R, chosen: str, tol: float) -> dict[str, Any]:
    """순위 규칙(목표수익 R2 → 비교지수 R3 → 허용 낙폭 초과 5%p 구간 → (보수 성향) 맞춤안 → Sharpe)으로 본 다른 후보들.
    2026-11 평가: 못 맞춘 조건을 맞춘 후보가 있었는지(005: 목표·SPY 를 넘은 후보가 하나도 없었다는 말이 없음), Sharpe·CAGR 이 더 높은 후보가
    왜 밀렸는지(000: 시가총액비중 walk-forward 가 CAGR 11.4%·Sharpe 0.64 인데 이유가 없음)를 리포트가 말하지 못했다."""
    val = R.get("validation") or {}
    st = {r["id"]: {c["rule"]: c["status"] for c in r.get("checks") or []} for r in val.get("results") or []}
    rows = {t["id"]: t for t in val.get("comparison_table") or [] if t.get("kind") != "benchmark" and t["id"] in st}
    if chosen not in rows:
        return {}
    size = float(((R.get("parameters") or {}).get("backtest") or {}).get("dd_excess_bucket") or 0.05)
    req = R["request"]
    cautious = req["risk"].get("loss_reaction") == "sell" or (req.get("profile") or {}).get("investment_experience") == "none"

    def label(i: str) -> str:  # 화면 표와 같은 이름 (081: 'BL 타겟 1' 이라는 내부 이름이 표의 '뉴스 뷰: …' 와 달랐다)
        try:
            return pf_label(find(R, i))
        except StopIteration:
            return rows[i].get("name_ko") or i

    def facts(t: dict[str, Any]) -> dict[str, Any]:
        mdd = abs(float(t.get("max_drawdown") or 0))
        d = (float(t.get("cagr") or 0) - float(rows[chosen].get("cagr") or 0)) * 100
        ds = (float(t.get("sharpe") or 0) - float(rows[chosen].get("sharpe") or 0)) if t.get("sharpe") is not None and rows[chosen].get("sharpe") is not None else None
        return {"id": t["id"], "label": label(t["id"]), "cagr": f"{float(t.get('cagr') or 0):.1%}", "max_drawdown": f"{mdd:.1%}",
                "sharpe": None if t.get("sharpe") is None else round(float(t["sharpe"]), 2), "meets_target_r2": st[t["id"]].get("R2") == "pass",
                "beats_benchmark_r3": st[t["id"]].get("R3") == "pass", "within_tolerance": mdd <= tol + 1e-9,
                "cagr_vs_chosen_pp": round(d, 1),
                # 비교 문장을 미리 (081: 음수 CAGR 끼리 비교하며 'CAGR -2.7% 가 선택안(-0.9%)보다 높았다' 고 거꾸로 썼다)
                "vs_chosen_ko": (f"선택안보다 CAGR 이 {abs(d):.1f}%p {'높고' if d > 0.05 else '낮고' if d < -0.05 else '같고'}"
                                 + (f" Sharpe 가 {abs(ds):.2f} {'높음' if ds > 0.005 else '낮음' if ds < -0.005 else '같음'}" if ds is not None else ""))}  # fmt: skip

    me, others = rows[chosen], [t for t in rows.values() if t["id"] != chosen]
    out: dict[str, Any] = {"n_candidates": len(rows), "n_meeting_target_r2": sum(1 for i in rows if st[i].get("R2") == "pass"),
                           "n_beating_benchmark_r3": sum(1 for i in rows if st[i].get("R3") == "pass"),
                           "n_within_tolerance": sum(1 for t in rows.values() if abs(float(t.get("max_drawdown") or 0)) <= tol + 1e-9)}
    for rule, key in (("R2", "best_meeting_target"), ("R3", "best_beating_benchmark")):
        if st[chosen].get(rule) != "pass":  # 선택안이 못 맞춘 조건: 맞춘 후보 중 CAGR 이 가장 높은 안 (없으면 None = 맞춘 후보가 없음)
            hit = [t for t in others if st[t["id"]].get(rule) == "pass"]
            out[key] = facts(max(hit, key=lambda t: float(t.get("cagr") or -9))) if hit else None

    def lost_on(t: dict[str, Any]) -> str:
        a, b = st[t["id"]], st[chosen]
        if b.get("R2") == "pass" and a.get("R2") != "pass":
            return "목표 수익률 미달(순위 1단계)"
        if b.get("R3") == "pass" and a.get("R3") != "pass":
            return "비교지수 하회(순위 2단계)"
        da, db = dd_bucket(float(t.get("max_drawdown") or 0), tol, size), dd_bucket(float(me.get("max_drawdown") or 0), tol, size)
        if da > db:
            ex = (abs(float(t.get("max_drawdown") or 0)) - tol) * 100
            return f"허용 낙폭을 더 많이 넘음(초과 {ex:.1f}%p, 순위 3단계는 {size:.0%}p 단위 구간으로 비교)"
        if cautious and me.get("kind") == "matched" and t.get("kind") != "matched":  # 실제 해당 조건으로 (083: 공격 성향인데 '손실에 민감한 성향' 이라 썼다 — 사유는 투자 경험 없음)
            return f"{cautious_reason_ko(req)} 조건이라 같은 단계면 낙폭 맞춤안을 우선하는 규칙(순위 4단계)에서 밀림"
        if lv_s.get(t["id"]) != lv_s.get(chosen):
            return "Sharpe(위험 대비 수익)가 더 낮음(순위 5단계)"
        if lv_m.get(t["id"]) != lv_m.get(chosen):  # 000: Sharpe 가 같고 최대낙폭이 0.1%p 커서 밀렸는데 이유가 없었다
            return f"Sharpe 가 같고 최대낙폭이 더 큼({abs(float(t.get('max_drawdown') or 0)):.1%} vs {abs(float(me.get('max_drawdown') or 0)):.1%}, 순위 6단계)"
        return "성과가 같아 사용자가 고른 기준 비중을 우선(마지막 단계)"

    lv_s = tie_levels({i: (float(t["sharpe"]) if t.get("sharpe") is not None else -9.0) for i, t in rows.items()}, 5e-5, higher_first=True)
    lv_m = tie_levels({i: abs(float(t.get("max_drawdown") or 0)) for i, t in rows.items()}, 5e-5, higher_first=False)
    sh0, cg0 = float(me.get("sharpe") or -9), float(me.get("cagr") or -9)
    better = [t for t in others if float(t.get("sharpe") or -9) > sh0 + 5e-5 or float(t.get("cagr") or -9) > cg0 + 5e-4]
    better.sort(key=lambda t: -float(t.get("cagr") or -9))
    out["higher_cagr_or_sharpe_ranked_lower"] = [{**facts(t), "lost_on": lost_on(t)} for t in better[:3]]
    # 077: 후보 중 CAGR 도 가장 높았는데 Sharpe 로만 설명. 모두 같으면 '가장 높다' 가 아니다 (091·092: 8개 CAGR 이 똑같은데 'CAGR 도 가장 높아 1위')
    out["chosen_has_highest_cagr"] = all(float(t.get("cagr") or -9) <= cg0 + 5e-4 for t in others) and any(float(t.get("cagr") or -9) < cg0 - 5e-4 for t in others)
    if others and all(abs(float(t.get("cagr") or -9) - cg0) <= 5e-4 for t in others):
        out["all_candidates_same_cagr"] = True
    return out


def _risk_now_facts(R, chosen: str, p: dict[str, Any], tol: float, target: float) -> dict[str, Any]:
    """지금 구성의 위험을 허용 낙폭과 숫자로 견줄 자료 (2026-11 평가 007·012: 현금 40~60% 로 시작한 백테스트의 낙폭만 보고 '허용 낙폭을 지켰다' 고 했다).
    같은 규칙의 다른 운용 방식(시작일 고정 ↔ 리밸런싱마다 재계산) 성과, 기간 끝 낙폭, 목표를 넘은 해 수도 넘긴다 (009·022)."""
    out: dict[str, Any] = {}
    h = p.get("headline") or {}
    mdd = abs(float(h.get("max_drawdown") or 0))
    cc = current_composition(R, chosen)
    if cc and p.get("target_weights"):
        bt_inv, now_inv = float(sum(p["target_weights"].values())), float(sum(cc[0].values()))
        if now_inv - bt_inv >= 0.10 - 1e-9 and bt_inv > 1e-9:
            scaled = mdd * now_inv / bt_inv  # 같은 흐름을 주식 비중만큼 키운 단순 환산 (종목이 같다는 가정)
            out["invested_backtest"], out["invested_now"] = f"{bt_inv:.0%}", f"{now_inv:.0%}"
            out["scaled_max_drawdown_now"] = f"{scaled:.1%}"
            out["scaled_within_tolerance"] = scaled <= tol + 1e-9
    core = chosen[3:] if chosen.startswith("wf_") else chosen
    twin_id = core if chosen.startswith("wf_") else f"wf_{chosen}"
    twin = next((x for x in R["backtest"]["portfolios"] if x["id"] == twin_id), None)
    if twin is not None and p.get("kind") != "matched":
        th = twin.get("headline") or {}
        diff = (float(th.get("cagr") or 0) - float(h.get("cagr") or 0)) * 100
        out["same_rule_other_mode"] = {"id": twin_id, "label": pf_label(twin), "cagr": f"{float(th.get('cagr') or 0):.1%}",
                                       "max_drawdown": f"{abs(float(th.get('max_drawdown') or 0)):.1%}", "cagr_vs_chosen_pp": round(diff, 1),
                                       "large_gap": abs(diff) >= 3.0}
    if cc:  # 백테스트에도 있던 종목의 지금 비중 (전체 기준·주식 부분 기준) — 겹침을 종목 수가 아니라 비중으로 (005: '6개만 겹친다' 로만)
        held_bt = set((p.get("weights_by_date") and {t for ws in p["weights_by_date"].values() for t, w in ws.items() if w > 1e-9})
                      or {t for t, w in (p.get("target_weights") or {}).items() if w > 1e-9})  # fmt: skip
        inv = sum(w for w in cc[0].values() if w > 1e-9)
        tot = sum(w for t, w in cc[0].items() if w > 1e-9 and t in held_bt)
        out["holdings_overlap_now"] = {"weight_total": f"{tot:.0%}", "stock_share": f"{(tot / inv if inv > 1e-9 else 0):.0%}"}
    open_ep = next((e for e in reversed((p.get("metrics") or {}).get("risk", {}).get("drawdown_episodes") or []) if not e.get("recovery_date")), None)
    if open_ep and abs(float(open_ep.get("depth") or 0)) > 0.05:  # 기간 끝까지 회복하지 못한 하락 (022: 끝 날 10.2% 만 보고 '허용 이내' — 그 구간은 16.3% 까지 빠졌다)
        out["open_drawdown_episode"] = {"peak_date": open_ep.get("peak_date"), "trough_date": open_ep.get("trough_date"), "depth": f"{abs(float(open_ep['depth'])):.1%}",
                                        "beyond_tolerance": abs(float(open_ep["depth"])) > tol + 1e-9}  # fmt: skip
    dd = ((p.get("series") or {}).get("drawdown") or [])
    last = next((float(x) for x in reversed(dd) if x is not None), None) if isinstance(dd, list) else None
    if last is not None and last < -0.05:
        out["end_drawdown"] = f"{abs(last):.1%}"
        out["end_drawdown_beyond_tolerance"] = abs(last) > tol + 1e-9
    yr = p.get("yearly_returns") or {}
    part = set(R["backtest"]["period"].get("partial_years") or [])
    if not part and yr:
        ys = sorted(yr)
        sp = R["backtest"]["period"]
        part = {y for y in (ys[0], ys[-1]) if not (str(sp.get("start", ""))[5:10] <= "01-05" and y == ys[0]) and not (str(sp.get("end", ""))[5:10] >= "12-24" and y == ys[-1])}
    full = {y: float(v) for y, v in yr.items() if v is not None and y not in part}
    if full:
        out["full_years"] = len(full)
        out["full_years_meeting_target"] = sum(1 for v in full.values() if v >= target - 1e-9)
        # 일부 기간 연도의 값 (009: '2023·2026년 일부 기간이 평균을 끌어올렸다' — 2023년은 0.4% 였다)
        out["partial_year_returns"] = {y: f"{float(v):.1%}" for y, v in yr.items() if v is not None and y in part}
    return out


def concentration_note(R, chosen: str) -> str | None:
    """지금 구성의 종목 쏠림과 백테스트 수익의 한 종목 쏠림 (2026-11 평가 092: 22% 씩 세 종목을 '두 종목' 으로, 093·095: 수익의 58% 를 NVDA 한 종목이 냄)."""
    try:
        p = find(R, chosen)
    except StopIteration:
        return None
    parts = []
    cc = current_composition(R, chosen)
    names = {t["ticker"]: t.get("name") or t["ticker"] for t in (R.get("selection") or {}).get("table") or []}
    if cc:
        w = sorted(((t, x) for t, x in cc[0].items() if x > 1e-9), key=lambda z: -z[1])
        big = [(t, x) for t, x in w if x >= 0.20 - 1e-9]
        if big or (len(w) >= 2 and w[0][1] + w[1][1] >= 0.40 - 1e-9):
            sel = big if len(big) >= 2 else w[:2]
            parts.append("지금 구성에서 비중이 큰 종목: " + ", ".join(f"{names.get(t, t)} {x:.1%}" for t, x in sel) + f" (합 {sum(x for _, x in sel):.1%})")
    pos = {t: v for t, v in (p.get("ticker_contribution") or {}).items() if v is not None and v > 0}
    if pos:
        top_t, top_v = max(pos.items(), key=lambda z: z[1])
        share = top_v / sum(pos.values())
        if share >= 0.5:
            parts.append(f"백테스트에서 오른 종목들의 수익 중 {share:.0%}를 {names.get(top_t, top_t)} 한 종목이 냈습니다")
    return " · ".join(parts) if parts else None


def hindsight_note(R, chosen: str) -> str | None:
    """사용자가 지금 고른 필수 포함 종목이 백테스트 수익의 절반 이상을 냈으면 — 지금 알고 고른 종목을 과거에 넣어 성과가 좋아 보일 수 있다
    (2026-11 평가 006: NVDA·AVGO 가 558.5% 중 448.8%p 를 냈는데 사후 선택 효과를 알리지 않았다)."""
    try:
        p = find(R, chosen)
    except StopIteration:
        return None
    forced = {str(t).upper() for t in R["request"]["constraints"].get("must_include_tickers") or []}
    pos = {t: v for t, v in (p.get("ticker_contribution") or {}).items() if v is not None and v > 0}
    if not forced or not pos:
        return None
    mine = {t: v for t, v in pos.items() if t.upper() in forced}
    share = sum(mine.values()) / sum(pos.values())
    if share < 0.5:
        return None
    names = {t["ticker"]: t.get("name") or t["ticker"] for t in (R.get("selection") or {}).get("table") or []}
    top = ", ".join(f"{names.get(t, t)}({v * 100:+.1f}%p)" for t, v in sorted(mine.items(), key=lambda x: -x[1])[:3])
    return (f"백테스트에서 오른 종목들의 수익 중 {share:.0%}를 사용자가 지금 꼭 넣기로 한 종목({top})이 냈습니다. "
            "지금 알고 고른 종목을 과거에 넣어 본 결과라 성과가 실제보다 좋게 보일 수 있습니다(사후 선택 효과)")


def current_composition(R, chosen: str) -> tuple[dict[str, float], float, str] | None:
    """추천(선택)안의 규칙으로 고른 분석 기준일 구성 (weights, cash, 이름) — 모의투자 시작 비중(paper._report_weights)과 같은 규칙.

    템플릿 → 10f 의 같은 템플릿, 뉴스 반영(BL) → 10f 의 chosen_weights(뷰가 반영된 첫 세트, 없으면 기준 비중),
    낙폭 맞춤안 → 기준 구성을 백테스트에서 확인한 주식 비중(1 − cash_ratio_total)까지 줄임(기준일 구성이 그보다 적게 담으면 그대로),
    옛 현금 혼합안(cash_blend_*) → 템플릿 × (1 − 현금 비율).
    예전에는 추천과 상관없이 '첫 BL 또는 기준 템플릿' 을 보여 줘서 '낙폭 맞춤안(주식 52%)' 추천인데 대시보드는 현금 5% 로 보였다 (F13 / 논의사항 E1).
    맞춤안을 '× (1 − 현금 비율)' 로 옮기면, 시작일 종목이 적어 기준 구성이 이미 현금 50% 였던 백테스트(002)의 c=2% 가 기준일의 전액 투자 구성에
    붙어 '주식 49%' 로 검증한 안이 '주식 98%' 로 보였다 → 주식 비중 자체를 옮긴다 (2026-11 QA).
    (시작일 BL 세트 k 와 분석 기준일 세트 k 는 서로 다른 LLM 시나리오라 번호로 잇지 않는다.)
    """
    f = R["portfolio"].get("forward") or {}
    if not f or not (f.get("templates") or f.get("portfolios")):
        return None
    tmpl = {t["id"]: t for t in f.get("templates") or []}
    cash_ratio, label, target_inv = 0.0, None, None
    if chosen.startswith("cash_blend_"):
        alt = next((a for a in R["validation"].get("alternatives", []) if a.get("id") == chosen), None)
        core, cash_ratio = chosen[len("cash_blend_"):], float((alt or {}).get("cash_ratio") or 0.0)
    else:
        try:
            p = find(R, chosen)
        except StopIteration:
            return None
        matched = p.get("kind") == "matched"
        cash_ratio = float(p.get("cash_ratio") or 0.0) if matched else 0.0
        if matched and p.get("cash_ratio_total") is not None:
            target_inv = 1.0 - float(p["cash_ratio_total"])
        base = str(p.get("base_id") or chosen) if matched else chosen
        core = base[3:] if base.startswith("wf_") else base
        label = "낙폭 맞춤안" if matched else None
    if core in tmpl:
        w, name = dict(tmpl[core]["weights"]), tmpl[core].get("name_ko") or core
    elif core.startswith("bl"):
        if f.get("portfolios"):
            w = dict(f.get("chosen_weights") or f["portfolios"][0]["weights"])
            name = next((q.get("name_ko") for q in f["portfolios"] if q.get("weights") == w), "현재 구성 뉴스 반영")
        else:
            b = tmpl.get((f.get("baseline") or {}).get("id")) or next(iter(tmpl.values()))
            w, name = dict(b["weights"]), f"{b.get('name_ko') or b['id']} (분석 기준일에는 뉴스 뷰가 없어 기준 비중)"
    else:
        return None
    if target_inv is not None:
        inv_now = sum(w.values())
        k = min(1.0, target_inv / inv_now) if inv_now > 1e-12 else 0.0
        w = {t: x * k for t, x in w.items()}
    elif cash_ratio > 0:
        w = {t: x * (1 - cash_ratio) for t, x in w.items()}
    cash = max(0.0, 1 - sum(w.values()))
    if target_inv is not None or cash_ratio > 0:  # 이름은 이 구성의 실제 비중으로, 백테스트 이름과 같은 꼴 ('낙폭 맞춤안 (주식 a% + 현금 b%, X 기준)')
        # 백테스트 이름과 같은 자리수 (015: 백테스트는 '주식 98.5%', 대시보드는 '주식 99%' 로 달랐다). 현금 = 100 − 주식
        name = f"{label or '현금 혼합안'} ({stock_cash_ko(sum(w.values()))}, {name} 기준)"
    return w, cash, name


def forward_blocks(R, chosen: str | None = None):
    f = R["portfolio"].get("forward")
    if not f:
        return []
    blocks = []
    nw = f.get("news_window")
    blocks.append({"type": "callout", "tone": "info", "title_ko": f"현재 구성 (분석 기준일 {f['as_of']})",
                   "text_ko": ((f"뉴스 창 {' ~ '.join(shown_window(nw['window']))}, 기사 {nw['n_articles']}건, 뉴스 있는 종목 {nw['n_tickers_with_news']}개. " if nw else "")
                               # 위험회피 δ 는 뉴스 뷰 BL 에만 쓴다 — 규칙 4개만 만들었는데 δ 를 적었다 (070: 뉴스 끔)
                               + "기준일 시장모형(최근 변동성·공분산)으로 규칙 4개"
                               + (f"와 뉴스 뷰 Black-Litterman {len(f['portfolios'])}개(위험회피 δ={f['market_model']['delta']}, {_delta_src_ko(f['market_model'])})를 만들었습니다."
                                  if f["portfolios"] else f"를 만들었습니다 ({f.get('fallback_reason_ko') or '뉴스 뷰 없음'}).")
                               + " 이 구성은 분석 기준일의 제안이며 백테스트 결과가 아닙니다.")})  # fmt: skip
    for p in f["portfolios"]:
        stuck = view_stuck_note(R, p)
        blocks.append({"type": "cards", "title_ko": p["name_ko"], "items": [{"title_ko": p.get("title_ko") or p["name_ko"], "text_ko": p.get("portfolio_view", "") + (f"\n{stuck}" if stuck else ""), "meta": [
            {"label_ko": "기준 비중 대비 주요 변화", "value": ", ".join(set_deltas(p, 4))},
            # 모형 값이라고 밝힌다 (2026-11 평가 075·083: '121.0%' 가 연 121% 기대로 읽혔다)
            {"label_ko": "모형상 기대 수익·예상 변동성(최근 자료로 계산한 참고값, 수익 전망 아님)", "value": f"{p['ex_ante']['exp_return']:.1%} / {p['ex_ante']['vol']:.1%}"},
            {"label_ko": "근거", "value": ", ".join(sorted({i for v in p["views_applied"] for i in v.get("evidence_ids", [])})) or "-"}]}]})  # fmt: skip
    cc = current_composition(R, chosen) if chosen else None
    if cc is None:  # 선택안을 해석할 수 없을 때만 예전 규칙 (첫 BL 또는 기준 템플릿)
        c0 = f["portfolios"][0] if f["portfolios"] else next((t for t in f["templates"] if t["id"] == f["baseline"]["id"]), f["templates"][0])
        cc = (dict(c0["weights"]), max(0.0, 1 - sum(c0["weights"].values())), c0.get("name_ko", c0["id"]))
    w, cash, name = cc
    init, fx = f["capital"]["initial_amount_usd"], f["capital"]["fx_rate"]
    items = dict(sorted(w.items(), key=lambda x: -x[1]))
    if cash > 1e-6:  # 현금 행: 빠지면 표 합계가 투자금보다 작다
        items["현금"] = cash
    top8 = sorted(w.values(), reverse=True)[:8]
    donut_items = items if (cash > 1e-6 and (len(top8) < 8 or cash >= top8[-1])) else dict(sorted(w.items(), key=lambda x: -x[1]))
    blocks.append(donut(f"{name} 배분 비중 (현재 구성)", donut_items))  # 화면 도넛은 상위 8개 + '기타 N종목' 이라 작은 현금은 표에만
    krw0 = (R.get("money_krw") or {}).get("initial_amount_krw")  # 원화는 원화 원금 × 비중 (042: 반올림한 달러 원금 × 환율이라 4,500,000원이 4,499,999원)
    rows = [{"ticker": t, "w": x, "usd": round(init * x, 2), "krw": round(krw0 * x) if krw0 else round(init * x * fx)} for t, x in items.items() if x > 1e-6]
    blocks.append(table(f"배분 금액 ({name}, 투자금 {init:,.0f} USD" + (")" if _usd(R) else f", 환율 1 USD = {fx:,.2f} KRW)"),
                        [("ticker", "티커", "text"), ("w", "비중", "pct1"), ("usd", "USD", "usd")] + ([] if _usd(R) else [("krw", "원화", "krw")]), rows))  # fmt: skip
    return blocks


# ───────────────────────── 참고자료 ─────────────────────────
def sources_table(R):
    return table("자료 출처", [("name", "출처", "text"), ("what", "사용한 내용", "text"), ("url", "링크", "text")], [{"name": s["name"], "what": s["what"], "url": s["url"] or ""} for s in R["sources"]])


def _delta_src_ko(mm: dict[str, Any]) -> str:
    src = "시장 자료로 추정" if mm.get("delta_source") == "market_implied" else "성향별 고정값"
    dm, db = mm.get("delta_market"), mm.get("delta_base")
    mult = [(k, float(x)) for k, x in (("성향 배수", mm.get("delta_multiplier")), ("낙폭 배수", mm.get("delta_dd_multiplier"))) if x is not None and abs(float(x) - 1) > 1e-9]
    if mm.get("delta_capped"):
        # 상한을 넘은 것이 배수를 곱한 값이면 그렇게 (035·036·037: 시장 추정치 7.02 는 8 보다 작은데 '추정한 값이 상한 8을 넘어' 라고 썼다)
        if src.startswith("시장") and dm is not None and mult:
            prod = float(dm) * float(np.prod([x for _, x in mult]))
            return f"시장 추정치 {float(dm):.4g} × {' × '.join(f'{k} {x:g}' for k, x in mult)} = {prod:.3g} → 상한 8 적용"
        return f"{src}한 값이 상한 8을 넘어 상한 적용"
    if src.startswith("시장") and dm is not None and db is not None and float(dm) < float(db) - 1e-9:  # 020: 시장 추정치가 음수라 하한 × 배수였는데 '시장 자료로 추정' 이라고만 썼다
        return f"시장 추정치({float(dm):.2f})가 하한 {float(db):g}보다 낮아 하한에 성향·낙폭 배수를 곱한 값"
    # 배수를 곱했으면 밝힌다 (024: 시장 추정 7.5749 × 낙폭 배수 0.8 = 6.0599 인데 '시장 자료로 추정' 이라고만 썼다)
    if src.startswith("시장") and dm is not None and mult:
        return f"시장 추정치 {float(dm):.4g} × {' × '.join(f'{k} {x:g}' for k, x in mult)}"
    return src


SHRINK_KO = {"ledoit_wolf": "Ledoit-Wolf"}  # 023: 'ledoit_wolf 수축' 처럼 코드 값이 그대로 보였다


def _lookback_ko(R, lb: dict[str, Any] | None, pp: dict[str, Any]) -> str:
    """공분산 추정 창은 설정값이 아니라 실제로 쓴 거래일 수로 (023: '756거래일' 이라 썼는데 날짜 범위는 카카오뱅크 상장 뒤 487거래일이었다)."""
    lb = lb or {}
    req = int(lb.get("requested_days") or pp["lookback_days"])
    days = int(lb.get("days") or req)
    txt = f"{lb.get('start')}~{lb.get('end')} 의 {days}거래일"
    if days < req:
        names = {t["ticker"]: t.get("name") for t in (R.get("selection") or {}).get("table") or []}
        lim = [f"{names[t]}({t})" if names.get(t) else t for t in lb.get("limited_by") or []]
        txt += f" (설정 {req}거래일보다 짧음" + (f": {', '.join(lim)}의 상장 뒤 가격만 있음)" if lim else ")")
    return txt


def parameters_table(R):
    pp, pb, mm, d = R["parameters"]["portfolio"], R["parameters"]["backtest"], R["portfolio"]["market_model"], R["request"]["derived"]
    bfx = R["money_krw"].get("backtest_fx") or {}
    dsrc = mm.get("delta_source", "fixed")
    ddm = f" × 낙폭 배수 {mm['delta_dd_multiplier']} (허용 낙폭 {mm.get('delta_tolerance', 0):.0%} 기준 20% 대비)" if mm.get("delta_dd_multiplier") is not None else ""
    win = mm.get("delta_window", {}) or {}
    if dsrc == "market_implied":
        dm, db = mm.get("delta_market"), mm.get("delta_base")
        base_txt = (f"시장 내재 δ {dm} ({win.get('start')}~{win.get('end')})" if db is None or dm is None or float(dm) >= float(db)
                    else f"시장 내재 δ {dm} ({win.get('start')}~{win.get('end')}) → 하한 {pp['delta_floor']} 적용")  # fmt: skip
        dtxt = f"{base_txt} × 성향 배수 {mm.get('delta_multiplier')}{ddm} = {mm['delta']}"
    else:
        dtxt = f"성향별 상수{ddm} = {mm['delta']}"
    if mm.get("delta_capped"):  # 곱한 값이 상한을 넘었으면 '= 8.0' 이 거짓 등식이 된다
        dtxt = dtxt.rsplit(" = ", 1)[0] + f" → 상한 8 적용 = {mm['delta']}"
    ex = R["parameters"].get("execution_rule") or {}
    desc = R["parameters"].get("descriptor") or {}
    rows = [{"k": "분석 기준일", "v": str(d["as_of"])},
            *([{"k": "환율", "v": "달러 요청이라 환산하지 않음"}] if _usd(R) else [
                {"k": "환율(기준일)", "v": f"{R['money_krw']['direction']} ({d['fx_date']}, {d.get('fx_source', 'fx_daily')})"},
                {"k": "환율(백테스트 시작일)", "v": f"{bfx.get('direction', '-')} ({bfx.get('fx_date', '-')}) — 백테스트 초기자본·적립 환산에 사용"}]),
            {"k": "정보 마감·체결", "v": ex.get("description_ko", "t−1 정보, t 종가 체결")},
            {"k": "거래일 달력", "v": "평가는 종목·비교지수 시장 거래일의 합집합(휴장 시장은 직전 종가), 리밸런싱·적립 매매는 보유 종목 시장이 모두 연 날"},
            {"k": "공분산 추정", "v": f"구성일 이전 거래일 수익률, {SHRINK_KO.get(pp['shrinkage'], pp['shrinkage'])} 수축 — 백테스트 시작일 구성: {_lookback_ko(R, mm.get('lookback'), pp)}"
                                    + (f" / 분석 기준일 구성: {_lookback_ko(R, flb, pp)}" if (flb := ((R['portfolio'].get('forward') or {}).get('market_model') or {}).get('lookback')) else "")},
            # 뉴스 뷰 BL 을 하나도 만들지 않았으면 δ 를 적지 않는다 — 규칙 4개는 δ 를 쓰지 않는다 (072·069: 뉴스 끔인데 '위험회피 δ: 시장 내재 δ …')
            {"k": "Black-Litterman", "v": (f"τ={pp['tau']}, 위험회피 δ: {dtxt}{_wf_delta_ko(R)}, 뷰 신뢰도 하한 {pp['confidence_floor']}, 뉴스 창 {R['parameters']['news']['window_days']}일"
                                           if _any_bl(R) else ("만들지 않음 (뉴스 반영 끔)" if not (R["intent"].get("news_tilt") or {}).get("enabled") else "만들지 않음 (뉴스 뷰 없음)"))},
            {"k": "백테스트", "v": f"거래비용 {pb['commission_bps']}bp, 무위험수익률 {pb['risk_free_rate']:.0%}, 소수 주식 {'허용' if not pb['integer_positions'] else '불허'}, 점검 시점 {({'rebalance': '리밸런싱일마다', 'monthly': '리밸런싱일 + 매월 말'}).get(pb['checkpoint_freq'], pb['checkpoint_freq'])}"},  # 설정 원값 'rebalance' 를 그대로 적었다 (070)
            {"k": "종목 사전", "v": f"{desc.get('file', '-')} (구성종목 스냅샷 {desc.get('snapshot_date', '-')}, {desc.get('n_stocks', '-')}종목)"},
            {"k": "분석 모델", "v": _models_ko(R["parameters"]["llm"])}]  # fmt: skip
    return table("계산 조건", [("k", "항목", "text"), ("v", "값", "text")], rows)


LLM_TASK_KO = {"02_intent": "의도 해석", "04_classify": "테마 분류", "06_explain": "기업별 근거", "09_views_news": "뉴스 뷰",
               "14a_interpret": "서술", "14b_narrate": "서술", "14c_market": "서술"}


def _models_ko(llm: dict[str, Any]) -> str:
    """'gpt-6-luna (api 모드; 의도 해석·…) / 뉴스 뷰: gpt-4o-mini'. 단계별 모델(stage_models)이 없으면 예전 문장 그대로."""
    moved: dict[str, str] = {}
    for k, m in (llm.get("stage_models") or {}).items():
        moved.setdefault(LLM_TASK_KO.get(k, k), m)
    tasks = [t for t in ("의도 해석", "보충 질문", "테마 분류", "뉴스 뷰", "서술") if t not in moved]
    return f"{llm['model']} ({llm['mode']} 모드; {'·'.join(tasks)})" + "".join(f" / {t}: {m}" for t, m in moved.items())


def execution_table(R, step_summaries: dict[str, str] | None, usage: dict[str, Any] | None = None):
    u = usage or R.get("llm_usage") or {}
    rows = [{"stage": k, "what": v} for k, v in (step_summaries or {}).items()]
    integ = [c for r in R["validation"]["results"] for c in (r.get("integrity") or [])]
    if integ:
        n_ok = sum(1 for c in integ if c["status"] == "pass")
        rows.append({"stage": "내부 점검", "what": f"종목·섹터 상한 준수, 시계열 길이·리밸런싱 횟수 일치: 포트폴리오 {len(R['validation']['results'])}개 × 3항목 중 {n_ok}/{len(integ)} 통과" + ("" if n_ok == len(integ) else " — 실패 있음(경고 확인)")})
    models = ", ".join(u.get("models") or []) or u.get("model")  # 단계별 모델을 쓰면 실제로 부른 모델을 모두
    note = (f"LLM 호출 {u.get('calls', 0)}회 (캐시 적중 {u.get('cache_hits', 0)}), 비용 약 {u.get('cost_usd', 0):.4f} USD ({models})"
            + (" — 리포트 작성 포함" if usage else " — 리포트 작성 전까지") if u else None)
    return table("실행 기록", [("stage", "단계", "text"), ("what", "처리 내용", "text")], rows, note=note)


def data_quality_table(R):
    q = R.get("data_quality") or {}
    rows = [{"k": "기대 거래일", "v": str(q.get("expected_days", "-"))}, {"k": "가격 자료가 충분한 종목 (비교지수 포함)", "v": str(q.get("usable", "-"))},
            {"k": "제외 종목", "v": ", ".join(f"{t}: {r}" for t, r in (q.get("excluded") or {}).items()) or "없음"},
            {"k": "직전값으로 채운 종목(일수)", "v": ", ".join(f"{t} {n}" for t, n in (q.get("filled") or {}).items()) or "없음"}]  # fmt: skip
    # 수정주가 이어 붙이기 같은 보정 (023: 12건을 고쳤는데 표는 '이상 없음' 처럼 보였다). 한국어 문장만 (내부 영어 메모 제외)
    fixes = [w for w in q.get("warnings") or [] if re.search(r"[가-힣]", str(w))]
    if fixes:
        rows.append({"k": "가격 보정", "v": " ".join(fixes)})
    return table("가격 자료 품질 판정 (커버리지 0.95, 1거래일 결측만 채움)", [("k", "항목", "text"), ("v", "값", "text")], rows)


def notices_table(R):
    """§6 '분석 중 확인한 점': 사용자가 조건을 바꾸거나 알아야 하는 경고만 (level=user). 없으면 None."""
    rows = []
    for n in R.get("notices") or []:
        when = (f"{n['count']}회" if n.get("count", 1) > 1 else "") + (f" {n['dates'][0]}~{n['dates'][-1]}" if len(n.get("dates") or []) > 1 else (f" {n['dates'][0]}" if n.get("dates") else ""))
        rows.append({"msg": n["message_ko"], "when": when.strip() or "-"})
    if not rows:
        return None
    return table("분석 중 확인한 점 (조건을 바꾸면 달라질 수 있는 것)", [("msg", "내용", "text"), ("when", "횟수·기간", "text")], rows)


def _mcap_limitation(R) -> str:
    """정책 결정 7 뒤의 시가총액 처리 (예전 문구 '가치평가 항목이 비어 있는 종목은 0' 은 대체값·제외 규칙과 달랐다, 검토)."""
    days = int(((R.get("parameters") or {}).get("market") or {}).get("mcap_fallback_max_days") or 730)
    span = "2년" if days == 730 else f"{days}일"
    return (f"시가총액은 팀 데이터베이스의 유통주식수 × 종가를 씁니다. 그날 시가총액이 비어 있으면 그 전에 마지막으로 알려진 유통주식수(최대 {span} 전 기준) × 그날 종가로 추정하고, "
            "그래도 없으면 최소 시가총액 조건이 있을 때 후보에서 빼고, 필수 포함이라 남은 종목은 시가총액비중에서 최소 비중만 받습니다 (실제 크기와 다름).")  # 025: '0 으로 둔다' 했지만 표는 XOM 1.6%


def limitations(R):
    desc = R["parameters"].get("descriptor") or {}
    snap, as_of = str(desc.get("snapshot_date") or ""), str((R["request"].get("derived") or {}).get("as_of") or "")
    # 스냅샷이 분석 기준일보다 뒤면 지금 구성의 후보에도 해당한다 (2026-11 평가: 5개 리포트 모두 과거 백테스트 문제로만 설명했고, 077 은 기준일에 상장 전인 종목이 후보에 나왔다)
    after = (f" 이 스냅샷은 분석 기준일({as_of})보다 뒤의 것이라, 지금 구성의 후보 목록에도 기준일에는 지수에 없던(또는 아직 상장 전인) 종목이 들 수 있습니다."
             if snap and as_of and snap[:10] > as_of[:10] else "")
    out = [f"구성종목 사전은 {desc.get('snapshot_date', '최근')} 스냅샷 하나를 모든 과거 기준일에 적용했습니다. 그 사이 지수에서 빠지거나 상장폐지된 종목은 과거 후보에 없고(생존 편향), 당시에는 지수에 없던 종목이 과거 후보에 들어갈 수 있습니다(선견 편향)." + after,
           "뉴스 뷰는 팀 데이터베이스의 공시 목록(사건 종류·제목·이용 가능일만, 본문 없음)과 뉴스 헤드라인(본문 없음)만 근거로 하며, 근거가 없는 날짜는 기준 비중을 씁니다(종목·섹터 상한이 묶이면 뉴스 뷰가 없는 종목의 비중도 재배분으로 함께 움직일 수 있습니다). 공시는 사건의 존재만 알려 주고, 뉴스·공시가 성과의 원인이라고 단정하지 않습니다.",
           _mcap_limitation(R),
           "세금, 환전 수수료, 호가 차이(슬리피지)는 반영하지 않았습니다.",
           "리밸런싱일 t 의 비중은 t−1 까지 자료로 계산하고 t 종가로 체결했다고 가정합니다. 실제 체결 가격·시점은 다를 수 있습니다.",
           "회사 소개는 데이터베이스의 사업 설명 첫 문장이며, 이 리포트는 기업의 재무 상태나 경쟁력을 평가하지 않습니다."]  # fmt: skip
    if _has_kr(R):  # 미국 종목뿐인 리포트에는 붙이지 않는다
        out.append("한국 종목의 거래세·소수 주식 불가는 반영하지 않았습니다.")
        out.append("한국 종목의 가격·지표는 미국 달러로 환산해 계산했습니다. 환율이 오르내린 만큼 원화 기준 수익·변동성과 다를 수 있습니다.")
    for l in desc.get("limitations", []) or []:
        out.append(str(l))
    return out


# ───────────────────────── 문서 v2 블록 (라운드 4, 결정 R3: 요약 대시보드 + 접이식 7부분) ─────────────────────────
METRIC_SHORT_KO = {"return_12m_1m": "모멘텀", "vol_60d": "저변동성", "pe_ttm": "저PER", "roe_ttm": "퀄리티", "dividend_yield_ttm": "고배당"}
EVIDENCE_KIND_KO = {"news": "뉴스", "disclosure": "공시", "financial": "재무 지표", "calc": "계산값", "data_quality": "자료 품질"}


def evidence_ref(R, ids: list[str] | None, title: str) -> dict[str, Any]:
    """근거 색인을 본문에 복사하지 않고 참조만 둔다 (ids=None 이면 색인 전체). 화면은 출처 드로어에서 /evidence 로 연다."""
    idx = R["evidence_index"]
    chosen_ids = [i for i in ids if i in idx] if ids is not None else list(idx)
    kinds: dict[str, int] = {}
    for i in chosen_ids:
        k = idx[i]["kind"]
        kinds[k] = kinds.get(k, 0) + 1
    return {"type": "evidence_ref", "title_ko": title, "ids": chosen_ids if ids is not None else None, "count": len(chosen_ids), "kinds": kinds}


def weights_compare(R) -> dict[str, Any]:
    """규칙 4개 + 시작일 뉴스 뷰 BL 의 비중을 한 표로 (도넛 여러 개 대신)."""
    cols, rows_w, ex_ante = [], {}, {}
    sec = {t["ticker"]: sector_ko(t["sector"]) for t in R["selection"]["table"]}
    names = {t["ticker"]: t["name"] for t in R["selection"]["table"]}
    for p in R["portfolio"]["baselines"]["portfolios"]:
        cols.append({"id": p["id"], "label_ko": NAMES.get(p["id"], p["id"]), "kind": "template", "rule_ko": p.get("rule_ko", "")})
        rows_w[p["id"]] = p["weights"]
        ex_ante[p["id"]] = {"vol": p.get("ex_ante", {}).get("vol"), "effective_n": p.get("ex_ante", {}).get("effective_n"), "cash": p.get("cash_weight", 0)}
    for p in R["portfolio"]["targets"]["portfolios"]:
        cols.append({"id": p["id"], "label_ko": f"뉴스 뷰: {p.get('title_ko') or p['name_ko']}", "kind": "black_litterman", "rule_ko": (p.get("portfolio_view") or "").split("\n")[0]})
        rows_w[p["id"]] = p["weights"]
        ex_ante[p["id"]] = {"vol": p.get("ex_ante", {}).get("vol"), "exp_return": p.get("ex_ante", {}).get("exp_return"), "cash": max(0.0, 1 - sum(p["weights"].values()))}
    tickers = sorted({t for w in rows_w.values() for t in w}, key=lambda t: -max(w.get(t, 0) for w in rows_w.values()))
    rows = [{"ticker": t, "name": names.get(t, t), "sector": sec.get(t, ""), "weights": {c["id"]: rows_w[c["id"]].get(t, 0.0) for c in cols}} for t in tickers]
    cash = {c["id"]: max(0.0, 1 - sum(rows_w[c["id"]].values())) for c in cols}
    base_id = R["portfolio"]["targets"]["baseline"]["id"]
    return {"type": "weights_compare", "title_ko": "비중 규칙별 구성 (백테스트 시작일)", "columns": cols, "rows": rows, "cash": cash, "ex_ante": ex_ante, "baseline_id": base_id,
            # 규칙 4개는 각자의 규칙으로 만든 비중이다 (025·026: '기준 비중에 상한을 적용한 값' 이라 해 최소분산·시가총액 열까지 기준 비중처럼 읽혔다)
            "note_ko": ("규칙 4개는 각 규칙으로 만든 비중에 종목·섹터 상한을 적용한 값, 뉴스 뷰는 기준 비중을 Black-Litterman 으로 조정한 값입니다." if R["portfolio"]["targets"]["portfolios"]
                        else "규칙 4개는 각 규칙으로 만든 비중에 종목·섹터 상한을 적용한 값입니다 (뉴스 뷰 구성 없음).")}  # fmt: skip  (015: 뉴스 끔인데 없는 열을 설명했다)


def timeline(R, chosen) -> dict[str, Any] | None:
    """리밸런싱 시점별 한 줄: 평가금액·비교지수·구간 성과·거래 수 + (walk-forward 면) 그날의 뉴스·공시·뷰. 체크포인트 표·뷰 카드·walk-forward 표를 하나로."""
    p = find(R, chosen)
    cps = p.get("checkpoints") or []
    if not cps:
        return None
    wf = R["portfolio"].get("walkforward")
    base_id = p.get("base_id") or chosen
    bl = next((x for x in (wf or {}).get("portfolios", []) if x["id"] == base_id and x["kind"] == "black_litterman"), None)
    wf_base = None
    if wf:
        tmpl_id = "wf_" + R["portfolio"]["targets"]["baseline"]["id"]
        wf_base = next((x for x in wf["portfolios"] if x["id"] == tmpl_id), None)
    # 정적 BL 선택안은 시작일에 적용한 뷰를 그날 줄에 보인다 (047: bl_03 의 뷰 4개가 2022-08-29 줄에 없었는데 메모는 '그날의 뷰를 볼 수 있습니다')
    tg = R["portfolio"]["targets"]
    static_views = ((tg.get("as_of"), next((x.get("views_applied") or [] for x in tg["portfolios"] if x["id"] == chosen), []))
                    if p.get("mode") == "static" and p.get("kind") == "black_litterman" else (None, []))  # fmt: skip
    items = []
    for cp in cps:
        d = cp["date"]
        it = {"seq": cp["seq"], "date": d, "kind": cp["kind"], "n_trading_days_to_date": cp["n_trading_days_to_date"], "value_usd": cp["money"]["value_usd"],
              "benchmark_value_usd": cp["money"]["benchmark_value_usd"], "net_invested_usd": cp["money"]["net_invested_usd"],
              "since_last": ({k: cp["since_last"].get(k) for k in ("return", "benchmark_return", "excess", "max_drawdown")} if cp.get("since_last") else None),
              "n_trades": len(cp.get("trades") or []), "turnover": cp.get("turnover"), "commission_usd": cp.get("commission_usd"),
              "to_date": _to_date_view(cp.get("to_date")),
              # 계산 잡음으로 −0.0 이 '현금 -0.0%' 로 보였다 (058) → 0 아래는 0
              "cash_after": (max(0.0, float(cp["weights"]["cash_after"])) + 0.0 if cp["weights"].get("cash_after") is not None else None),
              "news": None, "views": [], "top_delta": []}  # fmt: skip
        if d == static_views[0] and static_views[1]:
            it["views"] = [{"summary_ko": v.get("summary_ko", ""), "confidence": v.get("confidence"), "evidence_ids": v.get("evidence_ids", []), "evidence_type": v.get("evidence_type")}
                           for v in static_views[1]]  # fmt: skip
        if bl is not None and d in (wf.get("news_summary") or {}):
            ns = wf["news_summary"][d]
            views = bl["views_by_date"].get(d, [])
            it["news"] = {"n_articles": ns.get("n_articles", 0), "n_disclosures": ns.get("n_disclosures", 0), "n_tickers_with_evidence": ns.get("n_tickers_with_evidence", ns.get("n_tickers_with_news", 0)),
                          "n_views": len(views), "fallback": d in (bl.get("fallback_dates") or []), "window": shown_window(ns.get("window")),
                          "disclosure_window": shown_window(ns.get("disclosure_window"))}  # fmt: skip
            it["views"] = [{"summary_ko": v.get("summary_ko", ""), "confidence": v.get("confidence"), "evidence_ids": v.get("evidence_ids", []), "evidence_type": v.get("evidence_type")} for v in views]
            if wf_base is not None and d in bl["weights_by_date"] and d in wf_base["weights_by_date"]:
                w, b = bl["weights_by_date"][d], wf_base["weights_by_date"][d]
                # 선택안이 이 구성의 낙폭 맞춤안이면 그 주식 비율로 줄인 차이 (046: 맞춤안 주식 46.6% 인데 95% 투자 기준 차이 'D −2.8%p' — D 의 목표는 0.49%)
                pw = (p.get("weights_by_date") or {}).get(d) if p.get("kind") == "matched" else None
                k = (sum(pw.values()) / sum(w.values())) if pw and sum(w.values()) > 0 else 1.0
                it["top_delta"] = [{"ticker": t, "delta": round((w[t] - b[t]) * k, 6)} for t in sorted((t for t in w if t in b), key=lambda t: -abs(w[t] - b[t]))[:3]]
        items.append(it)
    note = ("시점을 고르면 그날의 보유 종목·거래·뷰를 자세히 볼 수 있습니다. "
            + ("종목은 백테스트 시작일의 선정 종목을 유지하며" if (R.get("selection") or {}).get("backtest_reselected") is not False
               else "종목은 분석 기준일 선정 목록을 과거에도 그대로 쓰며(시작일 재선정 없음)") + ", 평가금액은 적립을 포함합니다.")  # fmt: skip
    if p.get("mode") == "static":
        rb_on = (R["portfolio"]["backtest_spec"].get("rebalance_rule") or {}).get("enabled", True)
        note += (" 이 구성의 목표 비중은 기간 중 고정이며, 리밸런싱 시 매매로 해당 비중을 되맞춥니다." if rb_on
                 else " 리밸런싱 없이 시작일에 산 비중 그대로 보유합니다 (적립금만 목표 비중대로 투자).")  # fmt: skip  (037)
    return {"type": "timeline", "title_ko": f"리밸런싱 타임라인 ({pf_label(p)})", "portfolio_id": chosen, "walkforward": bl is not None, "items": items,
            "note_ko": note}  # fmt: skip


def _paragraphs(text: str) -> list[str]:
    parts = [x.strip() for x in (text or "").split("\n\n") if x.strip()]
    return parts or ([text] if text else [])


def companies(R, chosen) -> dict[str, Any]:
    """선정 표 + 기업별 근거 카드를 하나로. 각 종목에 비중·순위·지표·근거 문단·인용 근거·뉴스/공시 수."""
    from backend.analysis.common.citations import CITE_RE

    p = find(R, chosen)
    # 비중 = 선택안 규칙으로 고른 분석 기준일 구성 (대시보드 배분과 같은 것). 예전에는 백테스트 시작일 목표 비중이라 지금 선정 9종목 중 7개가
    # '미보유' 로 보이고 날짜도 없었다 (002). 현재 구성을 못 만들면 시작일 목표 비중으로 두고 그렇게 적는다.
    cc = current_composition(R, chosen)
    weights = cc[0] if cc else (p.get("target_weights") or {})
    w_note = (f"비중은 분석 기준일({R['selection']['as_of_now']['as_of']}) 현재 구성({cc[2]})의 비중입니다." if cc
              else f"비중은 백테스트 시작일({R['selection']['backtest_as_of']['as_of']}) 목표 비중입니다.")
    expl = {r["ticker"]: r for r in ((R["selection"].get("explained") or {}).get("per_ticker") or [])}
    idx = R["evidence_index"]
    now = str(R["selection"]["as_of_now"]["as_of"])
    # 리포트가 말하는 분석 기준일 뉴스 창(현재 구성 뉴스 뷰의 창)으로 센다 — 기업 설명(06)용 창은 공시를 90일·더 많은 종류로 모아 같은 기준일에 따로 있다
    # (066·067: 카드는 PSKY 공시 8건인데 '공시 창 … 공시 11건(8종목)'). 그 창이 없으면 기준일 창의 근거 전체 (062: walk-forward 날짜 창은 섞지 않는다)
    pf = R.get("portfolio") or {}
    fw_nw = (pf.get("forward") or {}).get("news_window") or {}
    view_w = next((w for w in pf.get("news_windows") or [] if str(w.get("as_of")) == now and fw_nw
                   and w.get("window") == fw_nw.get("window") and w.get("disclosure_window") == fw_nw.get("disclosure_window")), None)  # fmt: skip
    ids_by: dict[str, dict[str, set[str]]] = {}
    if view_w is not None:
        for key, kind in (("tickers", "news"), ("tickers_dc", "disclosure")):
            for t, ids in (view_w.get(key) or {}).items():
                ids_by.setdefault(t, {"news": set(), "disclosure": set()})[kind] |= set(ids or [])
    else:
        for i, e in idx.items():
            if e["kind"] in ("news", "disclosure") and str(e.get("window_as_of") or now) == now:
                for t in e.get("tickers", []):
                    ids_by.setdefault(t, {"news": set(), "disclosure": set()})[e["kind"]].add(i)
    items = []
    broad_off = (R["selection"].get("tagging_summary") or {}).get("theme_filter_applied", True)  # False = 넓은 테마
    for t in R["selection"]["table"]:
        tk = t["ticker"]
        rat = (expl.get(tk) or {}).get("rationale_ko", "")
        cited = [c for c in CITE_RE.findall(rat) if c in idx]
        items.append({"ticker": tk, "name": t["name"], "market": t.get("market", ""), "sector": sector_ko(t["sector"]), "sub_industry": sub_industry_ko(t.get("sub_industry", "")), "summary": t.get("summary", ""),
                      # 넓은 테마는 테마 판정으로 거르지 않았으므로 판정 사유·신뢰도를 보이지 않는다 (041: '미국 시장 전반' 인데 Verizon 신뢰도 0.00, BRK-B 0.95)
                      "theme_reason_ko": ("필수 포함 종목 · " if t.get("forced") else "") + (t.get("theme_reason_ko") or "" if broad_off else BROAD_REASON_KO),
                      "theme_confidence": t.get("theme_confidence") if broad_off else None,
                      "weight": weights.get(tk),
                      "in_selection_now": t["in_selection_now"], "rank_now": t["rank_now"], "metric_now": t["metric_now"], "in_backtest": t["in_backtest"],
                      "rank_bt": t["rank_backtest"], "metric_bt": t["metric_backtest"], "fact_id": t.get("metric_fact_id"),
                      "rationale_ko": _paragraphs(rat), "evidence_ids": list(dict.fromkeys(cited)),
                      # 카드 글이 인용한 근거도 센다 — 기업 설명은 공시 90일 창으로 써서 '0건 공시' 인데 공시를 인용했다 (073 INTC)
                      "n_news": len((ids_by.get(tk) or {}).get("news", set()) | {c for c in cited if c.startswith("ev")}),
                      "n_disclosures": len((ids_by.get(tk) or {}).get("disclosure", set()) | {c for c in cited if c.startswith("dc")})})  # fmt: skip
    items.sort(key=lambda x: (x["weight"] is None, -(x["weight"] or 0), x["rank_now"] if x["rank_now"] is not None else 99))
    m = R["selection"]["metric"]
    return {"type": "companies", "title_ko": "선정 종목과 기업별 근거", "metric": m, "metric_ko": METRIC_SHORT_KO.get(m, m), "direction": R["selection"]["direction"],
            "as_of_now": R["selection"]["as_of_now"]["as_of"], "as_of_bt": R["selection"]["backtest_as_of"]["as_of"], "portfolio_id": chosen, "items": items,
            # 지표 없는 필수 포함 종목도 순위가 비어 있다 (036: COST 가 시작일에 담겼는데 '선정되지 않은 종목' 으로 읽혔다 — Q-120 부작용)
            "note_ko": f"{w_note} 순위는 그 기준일 선정 종목 중 필수 포함을 뺀 종목 안의 선정 지표 순위이고, 비어 있으면 그 기준일에 선정되지 않았거나 필수 포함 종목입니다(필수 포함은 순위와 관계없이 담아 순위를 매기지 않음). 인용 ID 를 누르면 출처를 볼 수 있습니다."}  # fmt: skip


_DASH_RANK = {"must_include_not_in_universe": 0, "exclude_sector_unknown": 0, "added_tickers_ignored": 0, "must_include_below_filters": 0, "backtest_start_shifted": 1, "backtest_start_clamped": 1,
              "fewer_holdings_at_start": 2, "weight_capacity": 3, "too_few_eligible": 4, "too_few_with_metric": 4, "too_few_candidates": 4}


def dashboard_notices(R, k: int = 3) -> list[str]:
    """대시보드는 공지 k 개만 보인다 → 요청이 반영되지 않은 사실과, 백테스트 종목 수·현금을 설명하는 공지를 먼저 (011: 현금 50% 의 원인 공지가 5번째라 잘렸다).
    결론 옆 기간 메모(period_note)에 이미 나온 공지는 빼서 같은 문장이 두 번 자리를 차지하지 않게 (011·010 검토)."""
    pn = period_note(R) or ""
    users = sorted((n for n in (R.get("notices") or []) if n.get("level", "user") == "user" and n["message_ko"] not in pn),
                   key=lambda n: _DASH_RANK.get(n.get("code"), 9))  # fmt: skip
    return [n["message_ko"] for n in users][:k]


def build_summary(R, chosen: str, interp: dict[str, Any], narr: dict[str, Any]) -> dict[str, Any]:
    """'한눈에 보기' 대시보드 자료: 판단·KPI(비교지수 동반)·배분·미니 시계열·검증·다음 행동."""
    p = find(R, chosen)
    val = R["validation"]
    rec = val.get("recommended")
    res = next((r for r in val["results"] if r["id"] == chosen), None) or next((a for a in val.get("alternatives", []) if a["id"] == chosen), None)
    chosen_status = (res or {}).get("status", "n/a")
    failed = [f"{c['name_ko']}" for c in (res or {}).get("checks", []) if c["status"] == "fail"]
    warned = [f"{c['name_ko']}" for c in (res or {}).get("checks", []) if c["status"] == "warn"]
    info_notes = [c["message_ko"] for c in (res or {}).get("checks", []) if c["status"] == "info" and c.get("ok") is False]  # 투자 비율 낮음, 드리프트, 시장도 같이 빠진 낙폭 등
    rule_msgs = {c["rule"]: c["message_ko"] for c in (res or {}).get("checks", [])}
    vd = (rec or {}).get("verdict")
    if vd:  # 라운드 5: 추천은 항상 하나, 라벨은 주의 목록을 그대로 보여 준다
        status = vd["status"]
        label = f"{vd.get('head_ko') or VERDICT_HEAD_KO.get(status, '추천')}: {pf_label(p)}"
    elif rec and chosen_status == "pass":
        status, label = "recommended", f"추천: {pf_label(p)}"
    elif rec:
        status, label = "recommended_warn", f"추천 (주의 있음): {pf_label(p)}"
    elif p.get("kind") == "alternative":
        status, label = "none_cash_blend", f"추천 없음 · 현금 혼합안 ({pf_label(p)})"
    else:
        status, label = "none_baseline", f"추천 없음 · 기준 포트폴리오 ({pf_label(p)})"
    headline = (interp.get("headline_ko") or "").strip() or next((x for x in (narr.get("overview_ko") or []) if x.strip()), "")
    reason = rec["reason_ko"] if rec else next((n["message_ko"] for n in (R.get("notices") or []) if n.get("code") == "no_portfolio_passed"), None)
    bench = R["backtest"]["benchmark"]
    bh, bm = bench["headline"], bench["metrics"]
    r1c = next((c for c in (res or {}).get("checks", []) if c["rule"] == "R1"), None)
    r1 = ({"mdd": r1c["value"], "tolerance": r1c["threshold"], "benchmark_mdd": abs(bh["max_drawdown"] or 0.0), "excess": round(max(0.0, (r1c["value"] or 0) - (r1c["threshold"] or 0)), 6),
           "status": r1c["status"], "match_target": R["validation"]["criteria"].get("match_target")} if r1c else None)  # fmt: skip
    user_notices = dashboard_notices(R)
    kp = kpis(R, chosen)
    bench_vals = {"final_value": bh["final_value_usd"], "cagr": (bm["return"]["total_return"] if not R["backtest"]["period"].get("annualized_reliable", True) else bh["cagr"]),
                  "excess": None, "mdd": bh["max_drawdown"], "sharpe": bh["sharpe"], "view_hit": None}  # fmt: skip
    kpi_items = [{**k, "benchmark_value": bench_vals.get(k["id"]), "benchmark_label_ko": bench["name_ko"] if bench_vals.get(k["id"]) is not None else None}
                 for k in kp if not (k["id"] == "view_hit" and k["value"] is None)]  # fmt: skip
    init = R["portfolio"]["backtest_spec"]["capital"]["initial_amount_usd"]
    names = {t["ticker"]: t["name"] for t in R["selection"]["table"]}
    sec = {t["ticker"]: sector_ko(t["sector"]) for t in R["selection"]["table"]}
    f = R["portfolio"].get("forward")
    cc = current_composition(R, chosen)
    if f and cc is not None:  # 추천안의 규칙으로 고른 분석 기준일 구성 (F13)
        alloc_w, basis, basis_ko, a_init, fx = cc[0], "forward", f"분석 기준일 {f['as_of']} 구성 ({cc[2]})", f["capital"]["initial_amount_usd"], f["capital"]["fx_rate"]
    else:
        alloc_w, basis, basis_ko, a_init, fx = p.get("target_weights") or {}, "backtest", f"백테스트 선택안 ({pf_label(p)})", init, R["money_krw"]["fx_rate"]
    krw0 = (R.get("money_krw") or {}).get("initial_amount_krw") if basis == "forward" else None  # 기준일 구성은 원화 원금 × 비중 (042)
    items = [{"ticker": t, "name": names.get(t, t), "sector": sec.get(t, ""), "weight": w, "usd": round(a_init * w, 2), "krw": round(krw0 * w) if krw0 else round(a_init * w * fx)}
             for t, w in sorted(alloc_w.items(), key=lambda x: -x[1]) if w > 1e-6]  # fmt: skip
    cash_w = max(0.0, 1 - sum(alloc_w.values()))
    return {"verdict": {"status": status, "label_ko": label, "headline_ko": headline, "reason_ko": reason, "chosen_portfolio_id": chosen, "chosen_label_ko": pf_label(p),
                        "cautions_ko": verdict_cautions(R, chosen, vd),
                        "period_note_ko": period_note(R), "notices_ko": user_notices,
                        "n_notices": len([n for n in (R.get("notices") or []) if n.get("level", "user") == "user"])},
            "validation": {"n_pass": val["summary"]["n_pass"], "n_warn": val["summary"]["n_warn"], "n_fail": val["summary"]["n_fail"], "n_candidates": val["summary"].get("n_candidates"),
                           "chosen_status": chosen_status, "failed_rules_ko": failed, "warned_rules_ko": warned, "info_notes_ko": info_notes,
                           "rules_ko": [{"rule": c["rule"], "name_ko": c["name_ko"], "level": c["level"], "status": c["status"], "message_ko": c["message_ko"]} for c in (res or {}).get("checks", []) if c["level"] != "info"],
                           "tolerance_note_ko": _tolerance_note(R), "r1_ko": rule_msgs.get("R1"), "r1": r1},
            "news_effect": news_effect(R),
            "kpis": kpi_items,
            "allocation": {"basis": basis, "basis_ko": basis_ko, "items": items, "cash_weight": cash_w, "initial_amount_usd": a_init, "fx_rate": fx, "fx_direction": None if _usd(R) else f"1 USD = {fx:,.2f} KRW"},
            "mini_series": {"dataset": "index", "ids": list(dict.fromkeys([chosen, bench["id"]])), "label_ko": "누적 수익률 (시작 = 100)"},
            "period": R["backtest"]["period"], "next_actions_ko": list(interp.get("next_actions_ko") or [])}  # fmt: skip


def _stuck_views(views, bw: dict[str, float], sw: dict[str, float], cap: float, floor: float = 0.0,
                 holds: set[str] | frozenset[str] = frozenset(), by_ticker: dict[str, set[str]] | None = None) -> tuple[int, dict[str, int], set[str]]:
    """뷰가 걸린 종목 비중이 기준 비중과 같은 뷰 — (뷰 수, 종목별 횟수, 묶은 경계들: 'cap'·'floor'·'both'·'other').
    종목당 상한은 비중을 올리는 쪽(오름·상대 뷰의 강한 쪽)만, 최소 비중은 내리는 쪽(내림·상대 뷰의 약한 쪽)만 막는다
    (036·037: '내림' 뷰를 '종목당 상한에 묶여' 라고 썼다, 060: 29개 중 23개가 최소 비중 1% 에 묶인 내림 쪽이었는데 '상한·섹터 예산' 탓)."""
    n, stuck, kinds = 0, {}, set()
    # 같은 세트 안에서 한 종목에 방향이 엇갈린 뷰(예: 'CRWD 내림' 과 'CRWD > MSFT')가 있으면 서로 상쇄된다 — 상한 탓이 아니다 (076)
    signs: dict[str, set[int]] = {}
    for v in views:
        down_abs = v.get("type") != "relative" and v.get("direction") == "down"
        for t in v.get("long", []):
            signs.setdefault(t, set()).add(-1 if down_abs else 1)
        for t in v.get("short", []):
            signs.setdefault(t, set()).add(-1)
    conflicted = {t for t, sg in signs.items() if len(sg) > 1}
    for v in views:
        legs = [*v.get("long", []), *v.get("short", [])]
        # '바꾸지 못함' 은 카드의 비중 변화 표시(_delta_ko)와 같은 잡음 기준 0.05%p 로 (063: SNDK 내림 뷰가 1.0153% → 최소 비중 1.00% 로
        # 0.015%p 만 움직여 표에는 '변화 없음' 인데 1e-4 기준으로는 움직인 뷰라 최소 비중 설명이 없었다). 경계는 BL 비중이 닿았는지로 본다
        if legs and all(abs(bw.get(t, 0.0) - sw.get(t, 0.0)) < 0.0005 for t in legs):
            n += 1
            down_abs = v.get("type") != "relative" and v.get("direction") == "down"
            ups = [] if down_abs else list(v.get("long", []))
            downs = list(v.get("long", [])) if down_abs else list(v.get("short", []))
            at_cap = all(abs(bw.get(t, 0.0) - cap) < 1e-4 for t in ups)
            at_floor = floor > 0 and all(bw.get(t, 0.0) <= floor + 1e-4 for t in downs)
            if set(legs) & conflicted:
                kind = "conflict"
            elif holds and set(legs) <= set(holds):  # '뷰 방향 유지' 경계가 기준 비중에 고정 (056·065)
                kind = "hold"
            elif at_cap and (not downs or at_floor):
                kind = "cap" if not downs else "floor" if not ups else "both"
            else:
                kind = "other"
            kinds.add(kind)
            for t in legs:
                stuck[t] = stuck.get(t, 0) + 1
                if by_ticker is not None:  # 종목마다 그 종목이 닿은 경계 (이유가 섞이면 종목별로 적는다, 066)
                    # 뷰 하나의 이유를 다리마다 붙이면 틀린다 — 오른 쪽은 상한, 내린 쪽은 최소 비중을 본다
                    # (071: 'GOOGL > GDDY' 의 'both' 를 둘 다에 붙여 GoDaddy(1%)에 '종목당 상한 25%', Alphabet(25%)에 '최소 비중 1%')
                    if t in conflicted:
                        leg = "conflict"
                    elif t in holds:
                        leg = "hold"
                    elif t in ups:
                        leg = "cap" if abs(bw.get(t, 0.0) - cap) < 1e-4 else "other"
                    else:
                        leg = "floor" if floor > 0 and bw.get(t, 0.0) <= floor + 1e-4 else "other"
                    by_ticker.setdefault(t, set()).add(leg)
    return n, stuck, kinds


def _floor(R) -> float:
    return float(((R.get("parameters") or {}).get("portfolio") or {}).get("min_weight") or 0.0)


def _stuck_note_ko(R, n_views: int, n_stuck: int, stuck: dict[str, int], kinds: set[str], cap: float, held: bool = False,
                   by_ticker: dict[str, set[str]] | None = None) -> str:
    names = {t["ticker"]: t.get("name") for t in (R.get("selection") or {}).get("table") or []}
    order = [t for t, _ in sorted(stuck.items(), key=lambda x: -x[1])[:3]]
    top = [f"{names.get(t) or t}" for t in order]
    fl = _floor(R)
    lab = {"conflict": "같은 세트의 반대 방향 뷰와 상쇄", "hold": "뷰 방향 유지", "cap": f"종목당 상한 {cap:.0%}", "floor": f"최소 비중 {fl:.0%}"}
    generic = "상한·섹터 예산 같은 제약"
    each = {t: generic if "other" in by_ticker[t] else "·".join(lab[k] for k in ("conflict", "hold", "cap", "floor") if k in by_ticker[t])
            for t in order if by_ticker and by_ticker.get(t)}  # fmt: skip
    if not held and len(set(each.values())) > 1:
        # 이유가 섞이면 종목마다 따로 (066: DIS 는 '뷰 방향 유지', EBAY 는 최소 비중 1% 인데 하나라도 'other' 면 모두 '상한·섹터 예산' 이라고 썼다)
        return (f"뉴스 뷰 {n_views}개 중 {n_stuck}개는 뷰가 걸린 종목이 제약에 묶여 그 종목 비중을 바꾸지 못했습니다 ("
                + ", ".join(f"{names.get(t) or t}: {v}" for t, v in each.items()) + f"{' 등' if len(stuck) > 3 else ''}) (기준 비중과 같음)")  # fmt: skip
    # 상한이 아니라 '뷰 방향 유지' 경계에 걸린 경우 (056: KMI 는 상한과 멀었는데 상관이 높은 WMB 오름 뷰 때문에 최적화가 오히려 줄이려 해 기준 비중에 고정됐다)
    why = ("같은 세트에 그 종목의 방향이 엇갈린 뷰(오름·내림)가 함께 있어 서로 상쇄되어" if kinds == {"conflict"}
           else "다른 뷰와 함께 최적화하면 오히려 반대쪽으로 움직여야 해서 기준 비중에 고정되어(뷰 방향 유지)" if held or kinds == {"hold"}
           else "상한·섹터 예산 같은 제약 때문에" if not kinds or "other" in kinds or "hold" in kinds
           else f"종목당 상한({cap:.0%})에 묶여 있어" if kinds == {"cap"}
           else f"최소 비중({fl:.0%})에 묶여 더 줄일 수 없어" if kinds == {"floor"}
           else f"종목당 상한({cap:.0%})이나 최소 비중({fl:.0%})에 묶여 있어")  # fmt: skip
    return f"뉴스 뷰 {n_views}개 중 {n_stuck}개는 뷰가 걸린 종목({'·'.join(top)}{' 등' if len(stuck) > 3 else ''})이 {why} 그 종목 비중을 바꾸지 못했습니다 (기준 비중과 같음)"


def view_stuck_note(R, p: dict[str, Any] | None) -> str | None:
    """한 BL 구성(시작일 세트·분석 기준일 세트)에서 비중을 바꾸지 못한 뷰. 날짜별(walk-forward) 구성은 news_effect 가 센다.
    047: 선택안 bl_03 의 MSFT·GOOGL '오름' 뷰는 두 종목이 이미 상한 15% 라 비중이 그대로였는데 '관점이 맞았다' 로만 읽혔고,
    추천 현재 구성(fwd_bl_01)은 뷰 4개 중 3개가 상한에 묶인 종목이었는데 '뉴스 기반 구성' 이라고만 했다."""
    views = (p or {}).get("views_applied") or []
    if not views:
        return None
    bw = {t: float(x) for t, x in (p.get("weights") or {}).items()}
    sw = {**bw, **{t: bw.get(t, 0.0) - float(d) for t, d in (p.get("delta_vs_baseline") or {}).items()}}  # 기준 = BL − 차이
    cap = float(R["request"]["constraints"].get("max_weight_per_stock") or 1.0)
    # 모든 종목이 종목당 상한에 걸려 있으면(투자할 돈 = 상한 합) 어떤 뷰도 비중을 못 바꾼다 — walk-forward 카드(capped_note_ko)와 같은 이유로
    # (062: 6종목 × 10% 인 시작일 BL 다섯 개가 '상한·섹터 예산 같은 제약 때문' 이라고 썼는데 섹터는 30% 로 상한 50% 와 멀었다)
    held_w = [x for x in sw.values() if x > 1e-9]
    if held_w and all(abs(x - cap) < 1e-4 for x in held_w) and max(abs(bw.get(t, 0.0) - x) for t, x in sw.items()) < 0.0005:
        return f"모든 종목이 종목당 상한({cap:.0%})에 걸려 있어 뉴스 뷰 {len(views)}개가 비중을 바꿀 수 없었습니다 (기준 비중과 같음)"
    holds = {str(x).split(":", 1)[1] for x in p.get("active_constraints") or [] if str(x).startswith("view_direction_hold:")}
    per: dict[str, set[str]] = {}
    n, stuck, kinds = _stuck_views(views, bw, sw, cap, _floor(R), holds, by_ticker=per)
    held = bool(stuck) and set(stuck) <= holds
    return _stuck_note_ko(R, len(views), n, stuck, kinds, cap, held=held, by_ticker=per) if n else None


def news_effect(R) -> dict[str, Any] | None:
    """뉴스 반영 효과 카드 재료 (라운드 5): wf_bl_news vs 같은 종목의 기준 비중(wf_<baseline>) — 추천이 다른 포트폴리오여도 보여 준다."""
    ports = {p["id"]: p for p in R["backtest"]["portfolios"]}
    bl = ports.get("wf_bl_news")
    if bl is None:
        enabled = bool((R["intent"].get("news_tilt") or {}).get("enabled"))
        omitted = ((R["portfolio"].get("walkforward") or {}).get("bl_omitted") or {}).get("reason_ko")
        return {"disabled": True, "reason_ko": (omitted or "뉴스 반영 구성을 만들지 못했습니다") if enabled else "뉴스 반영을 끈 분석입니다"}
    base_id = R["portfolio"]["targets"]["baseline"]["id"]
    base = ports.get(f"wf_{base_id}") or ports.get(base_id)
    views = bl.get("views_by_date") or {}
    n_views = sum(len(v or []) for v in views.values())
    n_dates = sum(1 for v in views.values() if v)
    bh = bl["headline"]
    # 뷰가 있어도 모든 종목이 종목당 상한에 걸려 있으면 비중을 바꿀 수 없다 — 그 날 수와 이유를 남긴다 (018: 3종목 × 14% 라 37개 날짜 모두 기준과 같았는데 이유가 없었다)
    cap = float(R["request"]["constraints"].get("max_weight_per_stock") or 1.0)
    bw, sw = bl.get("weights_by_date") or {}, (base or {}).get("weights_by_date") or {}
    capped_days = {d for d, v in views.items() if v and d in bw and d in sw and all(abs(x - cap) < 1e-4 for x in sw[d].values() if x > 1e-9)
                   and max((abs(bw[d].get(t, 0.0) - x) for t, x in sw[d].items()), default=0.0) < 0.0005}  # fmt: skip
    capped = len(capped_days)
    capped_note = (f"뉴스 뷰가 있던 {n_dates}개 날짜 중 {capped}개는 모든 종목이 종목당 상한({cap:.0%})에 걸려 있어 뷰가 비중을 바꿀 수 없었습니다 (기준 비중과 같음)"
                   if capped else None)  # fmt: skip
    # 일부 종목만 묶여 그 종목의 뷰가 비중을 못 바꾼 경우 (023: 금융 섹터 상한 70% + 전액 투자라 KT&G·KT 가 늘 15% — 두 종목 뷰가 그 종목 비중을 한 번도 못 바꿨는데 설명이 없었다)
    stuck: dict[str, int] = {}
    n_stuck, kinds = 0, set()
    per: dict[str, set[str]] = {}
    # '뷰 방향 유지' 경계는 10w 구성에만 있다 — 백테스트 결과에는 옮겨지지 않아 늘 비어 있었다 (073·075: Q-272 가 실제 실행에서 한 번도 안 보였다)
    wf10 = next((x for x in ((R.get("portfolio") or {}).get("walkforward") or {}).get("portfolios") or [] if x.get("id") == bl["id"]), {})
    holds_by_date = wf10.get("holds_by_date") or bl.get("holds_by_date") or {}
    for d, vs in views.items():
        if not vs or d not in bw or d not in sw or d in capped_days:
            continue
        k, st, kd = _stuck_views(vs, bw[d], sw[d], cap, _floor(R), set(holds_by_date.get(d) or []), by_ticker=per)
        n_stuck, kinds = n_stuck + k, kinds | kd
        for t, c in st.items():
            stuck[t] = stuck.get(t, 0) + c
    if n_stuck:
        part = _stuck_note_ko(R, n_views, n_stuck, stuck, kinds, cap, by_ticker=per)
        capped_note = f"{capped_note}. {part}" if capped_note else part
    moved = sum(1 for d, v in views.items() if v and d in bw and d in sw and max((abs(bw[d].get(t, 0.0) - x) for t, x in {**sw[d], **{k: 0.0 for k in bw[d] if k not in sw[d]}}.items()), default=0.0) >= 0.0005)
    return {"disabled": False, "bl_id": bl["id"], "bl_label_ko": pf_label(bl), "base_id": base["id"] if base else None, "base_label_ko": pf_label(base) if base else None,
            "n_dates_capped": capped, "capped_note_ko": capped_note,
            "bl_cagr": bh["cagr"], "base_cagr": base["headline"]["cagr"] if base else None, "diff_cagr": round((bh["cagr"] or 0) - (base["headline"]["cagr"] or 0), 6) if base else None,
            "bl_excess_cagr": bh["excess_cagr"], "base_excess_cagr": base["headline"]["excess_cagr"] if base else None,
            "bl_mdd": bh["max_drawdown"], "base_mdd": base["headline"]["max_drawdown"] if base else None,
            # n_dates = 뷰가 비중을 실제로 바꾼 날, n_fallback = 기준 비중 그대로였던 날 (근거 부족·최적화 실패 + 상한에 묶임) — 018: '뉴스 적용 36회' 인데 실제로 바뀐 날은 0
            # '뷰로 비중을 바꾼 기간 안' 적중률은 비중이 한 번도 안 바뀌었으면 뜻이 없다 (038: 바꾼 날 0 인데 62.5%)
            "hit_365": bh.get("view_hit_ratio"), "hit_next_rb": bh.get("view_hit_ratio_next_rb") if moved else None, "n_views": n_views, "n_dates": moved, "n_dates_with_views": n_dates,
            "n_rebalances": len(views), "n_fallback": len(views) - moved, "annualized_reliable": R["backtest"]["period"].get("annualized_reliable", True)}  # fmt: skip


def period_note(R) -> str | None:
    """요청한 백테스트 기간과 실제 평가 창이 다르면(시작일 이동·자료 시작·시작 시 종목 부족) 결론 옆에 적는 한 줄 (라운드 5)."""
    import datetime as dt

    sp = R["portfolio"]["backtest_spec"]["period"]
    try:
        start, end = dt.date.fromisoformat(str(sp["start"])), dt.date.fromisoformat(str(sp["end"]))
    except (KeyError, ValueError):
        return None
    actual = (end - start).days / 365.25
    years_req = float(R["request"]["horizon"].get("backtest_years") or R["parameters"].get("backtest", {}).get("default_backtest_years") or 3.0)
    codes = ("selection_lookahead", "backtest_start_shifted", "backtest_start_clamped", "fewer_holdings_at_start", "window_clamped")  # 선견(재선정 없음)이 먼저 (054)
    notes = [n["message_ko"] for n in (R.get("notices") or []) if n.get("code") in codes]
    if actual < years_req * 0.9 - 1e-9:
        # '요청' 이라고 쓰지 않는다 — 요청 스키마의 기본값(3년)이라 사용자가 정한 값인지 알 수 없다 (2026-11 평가 007·012: '요청 3년' 을 서술이
        # '요청한 3년' 으로 옮겼는데 사용자는 백테스트 기간을 말한 적이 없고 투자기간은 2년·7년)
        return f"백테스트 기간 {years_req:g}년 중 {actual:.1f}년만 평가했습니다 ({sp['start']} ~ {sp['end']}, 투자기간과는 별개)" + (f" — {notes[0]}" if notes else "")
    return notes[0] if notes else None


def _episode_troughs(d: list[float | None], depth: float = 0.05) -> set[int]:
    """하락 구간(고점 대비 0 아래로 내려갔다 돌아오기까지)마다 가장 깊은 날 — 5% 넘게 빠진 구간만.
    069: 두 번째로 깊은 −23.9%(2026-03-04)가 표본에서 빠져 차트에 −16.9% 로 보였다 (예전에는 시리즈마다 최저점 하나만 고정)."""
    out: set[int] = set()
    lo_i, lo = None, 0.0
    for i, v in enumerate(d):
        x = float(v) if v is not None else 0.0
        if x < -1e-9:
            if lo_i is None or x < lo:
                lo_i, lo = i, x
        elif lo_i is not None:
            if lo <= -depth:
                out.add(lo_i)
            lo_i, lo = None, 0.0
    if lo_i is not None and lo <= -depth:
        out.add(lo_i)
    return out


def sample_series(dates: list[str], series: dict[str, dict[str, Any]], max_points: int = 600, pin_id: str | None = None) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, Any] | None]:
    """긴 시계열은 stride 로 줄이고 첫/끝 + 선택안 최대낙폭의 고점·저점은 고정한다. 전체 해상도는 /reports/{id}/series 로."""
    n = len(dates)
    if n <= max_points:
        return dates, series, None
    import math

    stride = math.ceil(n / max_points)
    keep = set(range(0, n, stride)) | {0, n - 1}
    pinned: list[str] = []
    s = series.get(pin_id or "", {})
    dd = s.get("drawdown")
    if dd and len(dd) == n:
        trough = min(range(n), key=lambda i: dd[i] if dd[i] is not None else 0)
        idx = s.get("index") or []
        peak = max(range(trough + 1), key=lambda i: idx[i] if i < len(idx) and idx[i] is not None else -1) if idx else 0
        keep |= {trough, peak}
        pinned = [dates[peak], dates[trough]]
    # 다른 시리즈(비교지수 등)의 최저점도 고정한다: 표본에서 빠지면 차트 최저점이 KPI·본문의 MDD 와 달랐다 (010 QQQ: 차트 -21.3% vs 22.8%)
    troughs = set()
    for ser in series.values():
        d = ser.get("drawdown")
        if isinstance(d, list) and len(d) == n and any(v is not None for v in d):
            troughs.add(min(range(n), key=lambda i: d[i] if d[i] is not None else 0))
            troughs |= _episode_troughs(d)
    keep |= troughs
    order = sorted(keep)
    out_series = {}
    for sid, ser in series.items():
        out_series[sid] = {k: ([v[i] for i in order] if isinstance(v, list) and len(v) == n else v) for k, v in ser.items()}
    return [dates[i] for i in order], out_series, {"method": "stride", "stride": stride, "full_points": n, "points": len(order), "pinned": pinned,
                                                   "pinned_troughs": sorted(dates[i] for i in troughs)}  # fmt: skip

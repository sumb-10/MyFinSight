"""M5-05 리포트 문서 생성기. 일곱 섹션 (상세설계 4장 '바'):

  verdict 종합 투자 판단 · market 산업과 시장 분석 · companies 기업별 투자 근거 · construction 포트폴리오 구성과 운용 ·
  performance 과거 성과와 해석 · assumptions 판단의 전제와 재검토 조건 · references 참고자료와 분석 조건

표·차트·KPI 는 코드(report_blocks), 해석·서술 문단은 LLM (14a 해석 · 14b 서술 · 14c 시장 분석). 문단의 숫자·인용은 report_check 가 대조하고
실패하면 ReportCheckError (리포트를 내지 않음).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from backend.analysis.common.capacity import cap_cause_ko, cap_limits
from backend.analysis.common.jsonio import now_iso
from backend.analysis.common.labels import NEWS_SOURCE_KO, sector_ko
from backend.analysis.common.llm import LlmClient, messages_from_prompts
from backend.analysis.common.prompts import load_prompts
from backend.analysis.errors import ReportCheckError
from backend.analysis.m5_backtest_report import report_blocks as B
from backend.analysis.m5_backtest_report.report_check import check
from backend.analysis.schemas.report import ReportDoc
from backend.analysis.settings import AnalysisSettings
from backend.analysis.m2_data import disclosure_labels as DL
from backend.analysis.m2_data import metrics as M


def _need(ans: dict[str, Any], key: str, min_n: int = 1) -> None:
    v = ans.get(key)
    if not isinstance(v, list) or len(v) < min_n:
        raise ValueError(f"'{key}' must be a list with >= {min_n} items")


def cash_breakdown(R: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    """선택안의 주식·현금 비율과 현금이 생긴 이유 (백테스트 시작일 구성 기준). 예전에는 숫자만 있어 서술이 '종목·섹터 상한 때문에 주식 49%' 처럼
    낙폭 맞춤으로 더 줄인 몫까지 상한 탓으로 썼다 (002: 상한 때문 50% + 낙폭 맞춤 1%p)."""
    inv = float(sum((p.get("target_weights") or {}).values()))
    mc = float(R["request"]["constraints"].get("min_cash_ratio", 0) or 0)
    base = B.find(R, p["base_id"]) if p.get("kind") == "matched" and p.get("base_id") else p
    base_inv = float(sum((base.get("target_weights") or {}).values()))
    # 나눈 몫은 보이는 자리수(소수 첫째)로 계산해 합이 맞게: 마지막 몫은 '총 현금 − 앞의 몫' (016: 15.0% + 7.7% 를 22.6% 라고 했다)
    tot = round((1 - inv) * 100, 1)
    mc_p = round(mc * 100, 1) if mc > 1e-9 else 0.0
    has_caps, has_add = 1 - mc - base_inv > 0.001, base is not p and base_inv - inv > 0.0005
    caps_p = round(max(0.0, 1 - mc - base_inv) * 100, 1) if has_caps else 0.0
    add_p = round(tot - mc_p - caps_p, 1) if has_add else 0.0
    if has_caps and not has_add:
        caps_p = round(tot - mc_p, 1)
    out = {"stocks": f"{100 - tot:.1f}%", "cash": f"{tot:.1f}%", "min_cash_by_user": f"{mc_p:.1f}%" if mc > 1e-9 else None,
           "cash_by_caps": f"{caps_p:.1f}%" if has_caps else None, "cash_added_by_drawdown_match": f"{add_p:.1f}%" if has_add else None}
    # 상한 때문에 남은 현금의 원인을 R9 와 같은 판단으로 (011: '종목·섹터 상한 때문' 이라는 꼬리표를 그대로 옮겨 섹터 상한 100% 인데 섹터 탓을 했다)
    out["cash_by_caps_cause_ko"] = None
    if out["cash_by_caps"]:
        sec = {t["ticker"]: t.get("sector") or "기타" for t in (R.get("selection") or {}).get("table", [])}
        cnt: dict[str, int] = {}
        for t, x in (base.get("target_weights") or {}).items():
            if x > 1e-9:
                cnt[sec.get(t, "기타")] = cnt.get(sec.get(t, "기타"), 0) + 1
        cons = R["request"]["constraints"]
        a, b = float(cons["max_weight_per_stock"]), float(cons["max_weight_per_sector"])
        cause = cap_cause_ko(cap_limits(cnt, a, b, 1 - mc), a, b, clause=True)
        out["cash_by_caps_cause_ko"] = f"백테스트 시작일 구성은 {cause} 남은 몫" if cause else None
    out["basis_ko"] = "백테스트 구성(시작일에 고른 종목) 기준 — 지금 구성(allocation_now)의 현금과 다를 수 있음"  # 011: 백테스트 2종목·현금 50% 를 지금 포트폴리오처럼 썼다
    # '더 줄인 몫' 이 현금을 줄였다고 읽혔다 — 주식을 줄여 현금을 더 넣은 것이다 (072: '낙폭 맞춤으로 더 줄인 62.2%' 와 '추가한 62.2%' 가 한 리포트에)
    out["note_ko"] = "현금 = 사용자 최소 현금 + 상한 때문에 배분하지 못한 몫(원인은 cash_by_caps_cause_ko) + 낙폭 맞춤으로 주식을 줄여 더 넣은 현금 (없는 항목은 null)"
    return out


def _rebalance_targets_ko(p: dict[str, Any], rebalance: bool = True) -> str:
    """선택안이 리밸런싱 때 맞추는 목표 (016: walk-forward 정의를 정적 구성에도 붙여 '리밸런싱일마다 비중을 다시 계산했다' 고 썼다).
    리밸런싱을 끈 요청이면 그대로 (037: '리밸런싱 없음' 인데 '리밸런싱마다 되돌렸습니다' 라고 해, 서술이 둘이 어긋난다고 썼다)."""
    if not rebalance:
        return "리밸런싱 없이 백테스트 시작일 비중으로 산 뒤 그대로 보유했습니다 (매수 후 보유, 적립금은 목표 비중대로 투자)."
    # 완결된 문장으로 (023: 'walk-forward: …맞춤' 꼴 그대로 따옴표째 옮겨 적혔다)
    if p.get("mode") == "walkforward":
        return "walk-forward 방식이라 종목은 백테스트 시작일 목록 그대로 두고, 리밸런싱일마다 그때까지의 자료로 비중을 다시 계산해 그 비중으로 맞췄습니다."
    return "정적 구성이라 백테스트 시작일에 정한 목표 비중으로 리밸런싱마다 되돌렸습니다 (비중을 다시 계산하지 않음)."


def _rebalances(R: dict[str, Any]) -> bool:
    """요청이 리밸런싱을 하는가 (끄면 매수 후 보유)."""
    return bool(((R.get("portfolio") or {}).get("backtest_spec") or {}).get("rebalance_rule", {}).get("enabled", True))


def _shown_news_window(nw: dict[str, Any] | None) -> dict[str, Any] | None:
    """창의 끝은 그날을 빼는 경계라 사람에게 보이는 끝은 전날 (013: '07-02 부터 07-16 까지' 라고 써서 기준일 뉴스도 쓴 것처럼 읽혔다).
    출처·사건 종류는 한국어 이름으로 (023: '출처 기록은 GOOGLE_RSS이며' 처럼 코드 값이 문장에 나왔다)."""
    if not nw:
        return nw
    out = {**nw, "window": B.shown_window(nw.get("window")), "disclosure_window": B.shown_window(nw.get("disclosure_window")),
           "window_note": "window·disclosure_window 는 양 끝 날짜를 포함한 기간 (기준일 당일 뉴스·공시는 쓰지 않음)"}  # fmt: skip
    if isinstance(nw.get("by_source"), dict):  # 기사 출처만이다 — 공시는 DART·SEC EDGAR (038: '기사와 공시 자료는 구글 뉴스 수집분' 이라고 썼다)
        out.pop("by_source", None)
        out["article_sources"] = {NEWS_SOURCE_KO.get(k, k): v for k, v in nw["by_source"].items()}
        out["disclosure_source_note"] = "공시는 한국 DART·미국 SEC EDGAR 공시 목록 (기사 출처와 다름)"
    if isinstance(nw.get("by_event_type"), dict):
        out["by_event_type"] = {DL.label_ko(k): v for k, v in nw["by_event_type"].items()}
    return out


def _chosen_news_use(R: dict[str, Any], chosen: str, p: dict[str, Any]) -> dict[str, Any]:
    """추천 현재 구성이 뉴스 뷰를 쓰는지 (013·017: 추천은 시가총액비중·낙폭 맞춤안인데 '뉴스 기반 비중 조정이 현재 제안' 이라고 썼다).
    뉴스 뷰 구성(forward.portfolios)은 추천이 BL 일 때만 추천 현재 구성이고, 아니면 참고 대안이다."""
    uses = p.get("kind") == "black_litterman" or (p.get("kind") == "matched" and str(p.get("base_id") or "").startswith(("bl_", "wf_bl")))
    cc = B.current_composition(R, chosen)
    label = cc[2] if cc else B.pf_label(p)
    f = (R.get("portfolio") or {}).get("forward") or {}
    cw = f.get("chosen_weights") or {}
    # 추천 현재 구성이 뉴스 뷰 구성이면 어느 세트인지 (021: 고르지 않은 세트(법률·보험 위험)의 뷰를 추천 구성에 반영됐다고 썼다)
    rec = next((x for x in f.get("portfolios") or [] if cw and all(abs(x["weights"].get(t, 0.0) - w) < 1e-9 for t, w in cw.items())), None) if uses else None
    rec_id = rec["id"] if rec else None
    rec_title = (rec.get("title_ko") or rec.get("name_ko") or "") if rec else ""  # 사람에게 보이는 이름 (021: 안내 문장의 'fwd_bl_01'·'views' 가 그대로 리포트에 옮겨졌다)
    # 뉴스 뷰 구성이 기준 비중에서 실제로 움직였나 (029: 9종목이 모두 상한 10% 라 다섯 세트 모두 기준과 같았는데 '뷰는 그 대안의 비중만 바꿨습니다' 라고 했다)
    moved = any(max((abs(float(d)) for d in (x.get("delta_vs_baseline") or {}).values()), default=0.0) > 1e-4 for x in f.get("portfolios") or [])
    stuck = "모든 종목이 종목·섹터 상한에 묶여 뷰가 비중을 바꾸지 못해 기준 비중과 같습니다"
    if not f.get("portfolios"):  # 022: 뉴스 끔이라 뉴스 뷰 구성이 없는데 '아래 대안' 이 있다고 했다
        # '기준 비중 규칙' 은 사용자가 고른 기준(예: 역변동성)이라, 추천이 다른 규칙이면 틀린 말이다 (033: 추천 시가총액비중)
        note = f"추천 현재 구성({label})은 그 비중 규칙으로 만든 구성이며, 뉴스 반영을 꺼서 뉴스 뷰 구성은 만들지 않았습니다."
    elif uses:
        rs = B.view_stuck_note(R, rec) if rec_id and moved else None  # 일부 뷰만 비중을 바꿨으면 그것도 (047: 뷰 4개 중 3개가 상한에 묶인 종목)
        note = (f"추천 현재 구성은 뉴스 뷰 구성 '{rec_title}'의 비중입니다. " + ("이 구성에는 그 관점의 뷰만 반영됐고, 다른 뉴스 뷰 구성은 참고용 대안입니다." if moved
                else f"다만 {stuck}.") + (f" {rs}." if rs else "") if rec_id else f"추천 현재 구성({label})이 뉴스 뷰를 반영한 구성입니다.")  # fmt: skip
    else:
        note = (f"추천 현재 구성({label})은 뉴스 뷰를 쓰지 않습니다. 아래 뉴스 뷰 구성은 참고용 대안이며, " + ("뷰는 그 대안의 비중만 바꿨습니다." if moved
                else f"그 대안도 {stuck}."))  # fmt: skip
    return {"chosen_uses_news_views": uses, "chosen_current_label": label, "chosen_news_note_ko": note, "recommended_forward_id": rec_id}


def _theme_search_ko(R: dict[str, Any]) -> str | None:
    """테마 관련 종목을 찾은 방법을 코드가 문장으로 (051·054: '찾는 방법은 산업 분류 64개, 키워드 58개' — 방법·키워드 수처럼 읽힘,
    056: '합계와 중복되지 않습니다' 처럼 뜻이 뒤집힘). 서술은 이 문장을 그대로 쓴다."""
    st = R["selection"].get("candidates_summary") or {}
    br = st.get("by_rule") or {}
    parts = [f"{lab} {int(br[k])}개" for k, lab in (("gics_match", "산업 분류로"), ("keyword_match", "키워드로"), ("example_match", "예시 종목으로")) if br.get(k)]
    n = st.get("n_matched")
    if not parts or n is None:
        return None
    return f"{', '.join(parts)} 종목이 걸렸고, 여러 방법에 함께 걸린 종목을 한 번만 세면 테마 관련 종목은 {int(n)}개입니다."


def _stuck_fact(R: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    """비중을 바꾸지 못한 뷰 안내 — 없으면 키를 넘기지 않는다 (빈 값을 보고 '없었다' 고 쓰지 않게)."""
    n = B.view_stuck_note(R, p)
    return {"views_not_moving_ko": n} if n else {}


def _news_effect_display(ne: dict[str, Any] | None) -> dict[str, Any] | None:
    """뉴스 효과 숫자를 보이는 자리수로 맞춘다 (013: 14.2% vs 14.0% 를 '0.3%p 높았다' 고 써서 보이는 숫자끼리 맞지 않았다)."""
    if ne and not ne.get("disabled") and ne.get("hit_next_rb") is None and "hit_next_rb" in ne:
        # 값을 비운 이유를 넘긴다 — null 키만 넘기면 '제공되지 않았습니다' 라고 썼다 (058)
        ne = {k: v for k, v in ne.items() if k != "hit_next_rb"}
        # 이유는 사실대로 (061: 매수 후 보유라 리밸런싱이 시작일 하루뿐이었고 그날 뷰는 비중을 바꿨는데 '뷰가 비중을 바꾼 날이 없어' 라고 했다)
        ne["hit_next_rb_note"] = ("시작 뒤 리밸런싱이 없어 '다음 리밸런싱까지' 적중률은 따로 재지 않음" if int(ne.get("n_rebalances") or 0) <= 1
                                  else "뷰가 비중을 바꾼 날이 없어 다음 리밸런싱까지 적중률은 따지지 않음" if not ne.get("n_dates")
                                  else "다음 리밸런싱까지의 구간이 아직 끝나지 않아 적중률을 따지지 않음")  # fmt: skip
    if not ne or ne.get("disabled") or ne.get("bl_cagr") is None or ne.get("base_cagr") is None:
        return ne
    a, b = round(ne["bl_cagr"] * 100, 1), round(ne["base_cagr"] * 100, 1)
    out = {**ne, "bl_cagr_pct": f"{a:.1f}%", "base_cagr_pct": f"{b:.1f}%", "diff_cagr_pp": f"{a - b:+.1f}%p"}
    if ne.get("bl_mdd") is not None and ne.get("base_mdd") is not None:
        m1, m2 = round(abs(ne["bl_mdd"]) * 100, 1), round(abs(ne["base_mdd"]) * 100, 1)
        out.update(bl_mdd_pct=f"{m1:.1f}%", base_mdd_pct=f"{m2:.1f}%", diff_mdd_pp=f"{m1 - m2:+.1f}%p")
    out["display_note"] = "숫자를 말할 때는 *_pct·*_pp 표시값을 쓴다 (차이는 표시값끼리 뺀 값)"
    return out


def _holdings_vs_request(R: dict[str, Any], chosen: str) -> str | None:
    """지금 구성 종목 수와 요청(목표·최소)의 관계를 문장으로 (015: '10개로 목표 10개 및 최소 8개와 같습니다' 라고 썼다)."""
    nh = R["request"]["constraints"]["num_holdings"]
    cc = B.current_composition(R, chosen)
    if not cc:
        return None
    n, tgt, lo = sum(1 for x in cc[0].values() if x > 1e-6), nh.get("target"), nh.get("min")

    def rel(k: int | None, name: str) -> str:
        return "" if k is None else (f"{name} {k}개와 같고" if n == k else f"{name} {k}개보다 {abs(n - k)}개 {'많고' if n > k else '적고'}")

    # 콜론 없이 한 문장으로 (024: 그대로 옮긴 서술이 '…다음과 같습니다: 지금 구성은 10종목입니다: …' 처럼 콜론이 겹쳤다)
    if tgt is not None and tgt == lo:  # 목표 = 최소면 한 번만 (034: '목표 5개와 같고, 최소 5개와 같습니다')
        return f"지금 구성은 {n}종목으로 " + rel(tgt, "목표·최소").rstrip("고") + "습니다."
    return f"지금 구성은 {n}종목으로 " + ", ".join(x for x in (rel(tgt, "목표"), rel(lo, "최소")) if x).rstrip("고") + "습니다."


def _news_summary(R: dict[str, Any]) -> Any:
    if not (R["intent"].get("news_tilt") or {}).get("enabled"):
        return "뉴스 반영을 꺼서 리밸런싱일마다 뉴스를 불러오지 않았습니다 (리밸런싱일 헤드라인 건수 없음)"
    # 창 끝은 그날을 빼는 경계 → 보이는 끝은 전날 (019: 시작일 창을 '09-01~09-15' 로 썼다, Q-077 의 나머지)
    return {d: _shown_news_window(w) if isinstance(w, dict) else w for d, w in (R["portfolio"]["walkforward"]["news_summary"] or {}).items()}


def _shown_views(views: dict[str, Any] | None) -> dict[str, Any] | None:
    """시작일 뉴스 뷰 입력의 근거 창도 끝 전날까지로 (019)."""
    if not views or not isinstance(views.get("window"), dict):
        return views
    return {**views, "window": _shown_news_window(views["window"])}


def _current_sector_pct(R: dict[str, Any], chosen: str) -> dict[str, str]:
    """지금 구성(분석 기준일)의 섹터 비중 (020: 백테스트 평균 섹터 비중을 '현재 구성' 에 붙였다)."""
    cc = B.current_composition(R, chosen)
    if not cc:
        return {}
    sec = {t["ticker"]: sector_ko(t.get("sector")) for t in R["selection"]["table"]}
    out: dict[str, float] = {}
    for t, w in cc[0].items():
        if w > 1e-9:
            out[sec.get(t, "기타")] = out.get(sec.get(t, "기타"), 0.0) + w
    return {k: f"{v * 100:.1f}%" for k, v in sorted(out.items(), key=lambda x: -x[1])}


def _vs_baseline_display(R: dict[str, Any], p: dict[str, Any]) -> dict[str, str] | None:
    """기준 대비 CAGR 을 보이는 자리수끼리 (019: 30.8% vs 29.9% 를 '0.8%p 높았다' 고 썼다, Q-089 와 같은 종류)."""
    base_id = R["portfolio"]["targets"]["baseline"]["id"]
    base = next((x for x in R["backtest"]["portfolios"] if x["id"] == base_id), None)
    a, b = (p.get("headline") or {}).get("cagr"), ((base or {}).get("headline") or {}).get("cagr")
    if a is None or b is None or p["id"] == base_id:
        return None
    ra, rb = round(a * 100, 1), round(b * 100, 1)
    return {"chosen_cagr": f"{ra:.1f}%", "baseline_cagr": f"{rb:.1f}%", "cagr_diff": f"{ra - rb:+.1f}%p", "baseline_label": B.pf_label(base),
            "note": "기준 대비 차이를 말할 때는 이 표시값을 쓴다"}  # fmt: skip


def _headline_display(h: dict[str, Any] | None) -> dict[str, str]:
    """성과 숫자를 보이는 자리수 문자열로 (031: 맞춤안 최대낙폭 7.8955% 를 '8.0%' 로 반올림해 목표 8.0% 에 딱 맞춘 것처럼 썼다)."""
    h = h or {}
    out = {k: f"{abs(float(h[k])) * 100 if k == 'max_drawdown' else float(h[k]) * 100:.1f}%" for k in ("cagr", "period_return", "max_drawdown") if h.get(k) is not None}
    if h.get("final_value_usd") is not None:
        out["final_value_usd"] = f"{float(h['final_value_usd']):,.0f}"
    return out


def _vs_benchmark_display(R: dict[str, Any], p: dict[str, Any]) -> dict[str, str] | None:
    """비교지수 대비 차이도 보이는 자리수끼리 (032: 20.2% vs 18.5% 를 '1.8%p 높았다', 최대낙폭 19.1% vs 18.7% 를 '0.3%p 컸다' 고 썼다 — Q-099 의 비교지수 쪽)."""
    b = R["backtest"]["benchmark"]
    ph, bh = p.get("headline") or {}, b.get("headline") or {}
    if ph.get("cagr") is None or bh.get("cagr") is None:
        return None
    ra, rb = round(ph["cagr"] * 100, 1), round(bh["cagr"] * 100, 1)
    out = {"benchmark_label": b.get("name_ko", b.get("id")), "chosen_cagr": f"{ra:.1f}%", "benchmark_cagr": f"{rb:.1f}%", "cagr_diff": f"{ra - rb:+.1f}%p"}
    if ph.get("max_drawdown") is not None and bh.get("max_drawdown") is not None:
        ma, mb = round(abs(ph["max_drawdown"]) * 100, 1), round(abs(bh["max_drawdown"]) * 100, 1)
        out.update(chosen_mdd=f"{ma:.1f}%", benchmark_mdd=f"{mb:.1f}%", mdd_diff=f"{ma - mb:+.1f}%p")
    out["note"] = "비교지수 대비 차이를 말할 때는 이 표시값을 쓴다 (차이는 표시값끼리 뺀 값)"
    return out


def _asof_news(R: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """근거 색인에서 분석 기준일 창(가장 늦은 window_as_of)의 뉴스·공시만. walk-forward 날짜 창의 옛 근거가 '최근' 으로 섞이지 않게."""
    idx = R["evidence_index"]
    win = max((v.get("window_as_of") or "" for v in idx.values() if v.get("kind") in ("news", "disclosure")), default="")

    def ok(v: dict[str, Any]) -> bool:
        return not win or (v.get("window_as_of") or win) == win

    news = [{"id": k, **v} for k, v in idx.items() if v.get("kind") == "news" and ok(v)]
    discl = [{"id": k, **v} for k, v in idx.items() if v.get("kind") == "disclosure" and ok(v)]
    # 공시는 리포트가 말하는 분석 기준일 공시 창(현재 구성 뉴스 뷰의 창)만 — 기업 설명(06)용 90일 공시가 같은 기준일 창에 섞여 있었다
    # (074: 시장 분석 '공시 기간 05-29~08-14 … 73건' vs 같은 리포트 '공시 창 07-04~08-17, 52건')
    view_dc = _view_window_ids(R, "tickers_dc")
    if view_dc is not None:
        discl = [d for d in discl if d["id"] in view_dc]
    return win, news, discl


def _view_window_ids(R: dict[str, Any], key: str) -> set[str] | None:
    """현재 구성 뉴스 뷰 창의 근거 id (key = 'tickers' 뉴스 / 'tickers_dc' 공시). 그 창을 찾지 못하면 None."""
    pf = R.get("portfolio") or {}
    fw = (pf.get("forward") or {}).get("news_window") or {}
    now = str(((R.get("selection") or {}).get("as_of_now") or {}).get("as_of") or "")
    w = next((x for x in pf.get("news_windows") or [] if fw and str(x.get("as_of")) == now
              and x.get("window") == fw.get("window") and x.get("disclosure_window") == fw.get("disclosure_window")), None)  # fmt: skip
    return {i for ids in (w.get(key) or {}).values() for i in ids or []} if w is not None else None


def _mode_ko(mode: Any) -> Any:
    """백테스트 방식 이름 (static_weights = 시작일 비중 고정 구성, walkforward = 리밸런싱일마다 비중 다시 계산)."""
    if not isinstance(mode, str) or not mode:
        return mode
    ko = {"static_weights": "정적 구성(시작일 비중으로 리밸런싱)", "walkforward": "날짜별 재계산(walk-forward)"}
    return " + ".join(ko.get(x.strip(), x.strip()) for x in mode.split("+"))


def _win_of(R: dict[str, Any]) -> list[str] | None:
    """분석 기준일 뉴스 창 [시작, 끝] (현재 구성의 뉴스 창)."""
    w = ((R["portfolio"].get("forward") or {}).get("news_window") or {}).get("window")
    return list(B.shown_window(w)) if w else None  # 화면의 '뉴스 창 …' 과 같은 표기


def _forward_news_note(R: dict[str, Any]) -> str | None:
    """뉴스를 끈 분석의 기준일 구성 설명용 (009: '뉴스 창과 헤드라인 건수가 없고 인용할 evidence id 도 없다' 고 썼는데, 같은 리포트가 기준일 헤드라인을 인용했다)."""
    if (R["intent"].get("news_tilt") or {}).get("enabled"):
        return None
    _w, news, discl = _asof_news(R)
    if not news and not discl:
        return "뉴스 반영을 꺼서 분석 기준일 구성에 뉴스 뷰(비중 조정)를 쓰지 않았습니다."
    parts = []
    if news:
        nd = sorted(x.get("published_at") or "" for x in news)
        parts.append(f"헤드라인 {len(news)}건({nd[0]} ~ {nd[-1]})")
    if discl:  # 022: 공시 정보를 넘기지 않아 '공시 창과 건수는 이 입력에 없다' 고 썼다 (같은 리포트가 공시 31건 인용)
        dd = sorted(x.get("filed_at") or x.get("available_on") or "" for x in discl)
        parts.append(f"공시 {len(discl)}건({dd[0]} ~ {dd[-1]})")
    return f"뉴스 반영을 꺼서 분석 기준일 구성에 뉴스 뷰(비중 조정)를 쓰지 않았습니다. 다만 기업 설명·시장 분석에는 분석 기준일 직전 {'와 '.join(parts)}을 참고로 불러왔습니다."


def _allocation_now(R: dict[str, Any], chosen: str) -> list[dict[str, Any]]:
    """선택안 규칙으로 고른 분석 기준일 구성 (대시보드 배분과 같은 것), 퍼센트 문자열."""
    cc = B.current_composition(R, chosen)
    if not cc:
        return []
    names = {t["ticker"]: t["name"] for t in R["selection"]["table"]}
    rows = [{"ticker": t, "name": names.get(t, t), "weight": f"{w * 100:.1f}%"} for t, w in sorted(cc[0].items(), key=lambda x: -x[1]) if w > 1e-6]
    return rows + ([{"ticker": "현금", "name": "", "weight": f"{cc[1] * 100:.1f}%"}] if cc[1] > 1e-6 else [])


def _wf_changes_note(R: dict[str, Any], chosen: str) -> str:
    """weight_changes_by_date 가 어느 구성의 변화인지 (024: 이름이 없어 기준 구성의 변화를 추천안의 변화로 썼다).
    이름표에 메모를 붙여 넘기면 그대로 따옴표째 옮겨 적는다 (035: '‘역변동성비중 — 기준 비중 구성, 선택안과 다름’의 변화이지') → 평범한 문장으로."""
    p = B.walkforward_changes_plan(R, chosen)
    if not p:
        return ""
    bt = next((x for x in R["backtest"]["portfolios"] if x["id"] == chosen), {})
    name = B.NAMES.get(p["id"].removeprefix("wf_"), p.get("name_ko", p["id"]))
    if (bt.get("base_id") or chosen) == p["id"]:
        return f"선택안인 {name} walk-forward 구성의 리밸런싱일별 직전 대비 큰 변화 (뉴스와 무관)"
    return f"{name} walk-forward 구성의 리밸런싱일별 직전 대비 큰 변화 (뉴스와 무관). 이 구성은 선택안이 아니라 기준 비중 구성이므로 선택안의 변화라고 쓰지 않는다"


def _partial_years_note(R: dict[str, Any], p: dict[str, Any]) -> str | None:
    """연도별 수익률의 첫해·마지막 해가 일부 기간이면 그 기간 (063: 1~10월만인 2026년 19.5% 를 한 해 수익률처럼 썼다)."""
    per = R["backtest"]["period"]
    ys = sorted(p.get("yearly_returns") or {})
    start, end = str(per.get("start") or ""), str(per.get("end") or "")
    if not ys or len(start) < 10 or len(end) < 10:
        return None
    cut_start = start[:4] == ys[0] and start[5:] > "01-05"  # 연초 첫 거래일이면 한 해 전체로 본다
    cut_end = end[:4] == ys[-1] and end[5:] < "12-28"
    if len(ys) == 1:
        parts = [f"{ys[0]}년은 {start}~{end}"] if cut_start or cut_end else []
    else:
        parts = ([f"{ys[0]}년은 {start}부터"] if cut_start else []) + ([f"{ys[-1]}년은 {end}까지"] if cut_end else [])
    return (" · ".join(parts) + "의 일부 기간 수익률 (한 해 전체가 아님)") if parts else None


def _filtered_names_ko(R: dict[str, Any], k: int = 8) -> str | None:
    """후보 검색에서 빠진 종목을 '이름(사유)' 로 — 사유별 묶음(candidates_filtered)의 예시를 그대로 (사유는 짧게)."""
    rows = R["selection"].get("candidates_filtered") or []
    out = [f"{name}: {str(r.get('reason_ko') or '').split(' (')[0]}" for r in rows for name in (r.get("examples") or [])]
    if not out:
        return None
    n = sum(int(r.get("count") or 0) for r in rows)
    return " / ".join(out[:k]) + (f" / … 모두 {n}개" if n > len(out[:k]) else "")


def _infeasibility_fact(R: dict[str, Any]) -> dict[str, Any] | None:
    """시작일 배분 한도 사실 + 언제의 일인지 + 지금 구성은 얼마나 담는지 (070: 시작일 목록의 75% 한도를 '분석 기준일 선정 종목은 섹터 상한 때문에
    투자 비율이 제한됐다' 고 써서 다 담는 지금 구성(90%)에 섹터 상한을 올리라고 권했다)."""
    inf = R["selection"]["backtest_as_of"].get("infeasibility")
    if not inf:
        return None
    bt_day, now_day = R["selection"]["backtest_as_of"]["as_of"], R["selection"]["as_of_now"]["as_of"]
    invest = 1.0 - float(R["request"]["constraints"].get("min_cash_ratio") or 0.0)
    cap_now = (R["selection"]["as_of_now"].get("summary") or {}).get("weight_capacity")
    now = (f"분석 기준일({now_day}) 구성은 투자 비율 {invest:.0%}를 모두 담음 — 지금 구성의 투자 비율이 상한 때문에 제한됐다고 쓰지 않음"
           if cap_now is not None and float(cap_now) >= invest - 0.005 else
           f"분석 기준일({now_day}) 구성도 {float(cap_now):.0%}까지만 담음" if cap_now is not None else None)  # fmt: skip
    return {**inf, "when_ko": f"백테스트 시작일({bt_day}) 선정 종목의 배분 한도", **({"now_ko": now} if now else {})}


def _same_top_note(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """규칙별 시작일 최대 비중이 같은 것끼리 — 있으면 '서로 다르다' 고 쓰지 않게 이름을 적어 넘긴다 (061·065: 15.0% 가 둘인데 '서로 다릅니다')."""
    by: dict[str, list[str]] = {}
    for r in rows:
        by.setdefault(f"{r['top']:.1%}", []).append(str(r["name"]))
    same = [f"{'·'.join(v)}는 둘 다 {k}" if len(v) == 2 else f"{'·'.join(v)}는 모두 {k}" for k, v in by.items() if len(v) > 1]
    return {"top_weight_same_ko": " / ".join(same) + " — 같은 값이 있으니 '서로 다르다' 고 쓰지 않음"} if same else {}


def _top_delta_facts(R: dict[str, Any], chosen: str) -> dict[str, Any]:
    """walk-forward 뉴스 반영 구성의 날짜별 기준 대비 차이 — 비면 키를 넘기지 않는다 (050). 선택안이 그 구성의 낙폭 맞춤안이면 그 주식 비율로 줄인 값과 그 사실 (048)."""
    td = B.walkforward_top_deltas(R, chosen=chosen)
    if not td:
        return {}
    m = B.matched_on_wf_bl(R, chosen)
    # 어느 구성의 값인지 밝힌다 (061: walk-forward 값을 '시작일 뉴스 반영 구성' 이라 쓰고 바로 아래 시작일 세트 카드와 숫자가 달랐다;
    # 065: '(그날 뷰 없음, 재배분)' 표시를 빼고 옮겨 재배분만으로 움직인 종목이 뉴스 뷰 효과처럼 읽혔다)
    label = ("top_delta_by_date = walk-forward 뉴스 뷰 BL 의 리밸런싱일별 기준 비중(walk-forward) 대비 차이 — 백테스트 시작일 뉴스 뷰 세트(scenarios)·분석 기준일 세트와 다른 구성이라 "
             "섞지 않고 'walk-forward' 라고 밝힘. '(그날 뷰 없음, 재배분)' 이 붙은 종목은 그 표시를 함께 씀")  # fmt: skip
    return {"top_delta_by_date": td, "top_delta_label": label, **({"top_delta_note": f"선택안({B.pf_label(m)})의 주식 비율로 줄인 차이 — 타임라인과 같은 값"} if m else {})}


def _wf_changes_facts(R: dict[str, Any], chosen: str, prefix: str) -> dict[str, Any]:
    """walk-forward 구성의 날짜별 '직전 대비' 변화 — 뉴스 반영 구성이 있으면(그쪽 변화를 쓴다) 또는 자료가 없으면 아무 키도 넘기지 않는다."""
    wc = {} if B.walkforward_top_deltas(R) else B.walkforward_weight_changes(R, chosen=chosen)
    # 날짜마다 '변화 없음' 이면 알릴 것이 없다 — 넘기면 선택안과 무관하다는 안내까지 문장으로 옮겼다 (050: 동일비중 walk-forward 는 늘 같은 비중)
    if not wc or all(v == ["변화 없음"] for v in wc.values()):
        return {}
    return {"weight_changes_by_date": wc, "weight_changes_note": prefix + _wf_changes_note(R, chosen), "weight_changes_largest": B.walkforward_largest_changes(R, chosen)}


def facts_for_interpret(R: dict[str, Any], chosen: str) -> dict[str, Any]:
    bt = R["backtest"]
    p, b = B.find(R, chosen), bt["benchmark"]
    base = next(x for x in bt["portfolios"] if x["id"] == R["portfolio"]["targets"]["baseline"]["id"])
    val = R["validation"]
    periods = [{"date": c["date"], "return": c["since_last"]["return"], "benchmark_return": c["since_last"]["benchmark_return"], "best": c["since_last"]["best"], "worst": c["since_last"]["worst"]}
               for c in p["checkpoints"] if c["since_last"]]  # fmt: skip  (리밸런싱 구간별 — 주기가 분기가 아닐 수 있다)
    contrib = sorted(((t, v) for t, v in p["ticker_contribution"].items() if v is not None), key=lambda x: -x[1])
    calc_ids = {k: v["id"] for k, v in R["evidence_index"].items() if k.startswith("calc:") and k.endswith(":" + chosen)}
    return {"citation_rule": "숫자를 쓸 때 가능한 곳마다 [calc:<metric>:<portfolio_id>] 형식의 근거 ID 를 붙인다 (아래 calc_ids 에 있는 것만).",
            "calc_ids": sorted(calc_ids), "all_calc_ids": sorted(k for k in R["evidence_index"] if k.startswith("calc:")),
            "user": {"max_drawdown_tolerance": float(R["request"]["risk"]["max_drawdown_tolerance"]), "matched_target": R["intent"]["risk_params"].get("effective_max_drawdown"),
                     "target_annual_return": R["intent"]["validation_criteria"]["target_annual_return"],
                     "volatility_preference": R["intent"]["risk_params"]["volatility_preference"], "risk_tolerance": R["request"]["risk"]["risk_tolerance"],
                     "horizon_years": R["request"]["horizon"]["target_years"], "benchmark": R["portfolio"]["backtest_spec"]["benchmark"],
                     # 011: 최소 8개를 '목표 8개' 라고 썼다 → 목표·최소를 이름 붙여 넘긴다
                     "num_holdings": {"target": R["request"]["constraints"]["num_holdings"].get("target"), "min": R["request"]["constraints"]["num_holdings"].get("min")}},
            "assumptions": {**bt["engine"], "period": bt["period"]},
            "rebalance_ko": R["portfolio"]["backtest_spec"]["rebalance_rule"].get("description_ko"),
            "baseline_rule": {"id": base["id"], "label": B.pf_label(base), "rule_ko": next((x.get("rule_ko") for x in R["portfolio"]["baselines"]["portfolios"] if x["id"] == base["id"]), None)},
            "chosen": {"id": chosen, "label": B.pf_label(p), "kind": p["kind"], "mode": p.get("mode"), "rebalance_targets_ko": _rebalance_targets_ko(p, _rebalances(R)),
                       "is_recommended": bool(val.get("recommended")), "verdict": (val.get("recommended") or {}).get("verdict"),
                       "base_id": p.get("base_id"), "cash_ratio": p.get("cash_ratio"), "match_target": p.get("match_target"), "headline": p["headline"], "return": p["metrics"]["return"],
                       "risk": p["metrics"]["risk"], "risk_adjusted": p["metrics"]["risk_adjusted"], "vs_benchmark": p["metrics"]["vs_benchmark"], "vs_baseline": p["metrics"]["vs_baseline"],
                       "composition": {k: p["metrics"]["composition"][k] for k in ["effective_n", "top3_contribution_share", "sector_weights_avg"]}, "trading": p["metrics"]["trading"],
                       # 020: 백테스트 평균 섹터 비중(73.4%)을 '현재 구성' 에 붙였다 → 이름을 밝히고 지금 구성의 섹터 비중을 따로
                       "composition_note": "composition = 백테스트 기간 평균 (지금 구성 아님). 지금 구성의 섹터 비중은 current_sector_weights_pct",
                       "current_sector_weights_pct": _current_sector_pct(R, chosen), "vs_baseline_display": _vs_baseline_display(R, p),
                       "vs_benchmark_display": _vs_benchmark_display(R, p), "headline_display": _headline_display(p.get("headline")),
                       "money": {**p["money"], **({} if R["request"]["capital"].get("currency") == "USD" else R["money_krw"]["by_portfolio"][chosen])},
                       "yearly_returns": p["yearly_returns"], "yearly_returns_note": _partial_years_note(R, p), "rebalance_periods": periods,
                       # 기여도는 기간 수익률의 %p (045: 'V 19.2%' 처럼 % 로 썼다)
                       "ticker_contribution_top": [(t, f"{v * 100:+.1f}%p") for t, v in contrib[:3]], "ticker_contribution_bottom": [(t, f"{v * 100:+.1f}%p") for t, v in contrib[-3:]],
                       "view_diagnostics": p["view_diagnostics"],
                       **({"start_views_not_moving_ko": sv} if p.get("mode") == "static" and (sv := B.view_stuck_note(R, next((x for x in R["portfolio"]["targets"]["portfolios"] if x["id"] == chosen), None))) else {}),
                       "cash_weight": round(1 - sum(p["target_weights"].values()), 4), "cash_breakdown": cash_breakdown(R, p),
                       # 011: 백테스트 2종목·현금 50% 를 지금 포트폴리오처럼 썼다 (14b 에는 있었고 14a 에는 없었다)
                       "n_holdings_backtest": sum(1 for x in p["target_weights"].values() if x > 1e-9), "allocation_now": _allocation_now(R, chosen),
                       "holdings_now_vs_request_ko": _holdings_vs_request(R, chosen),
                       # 백테스트 주식 비중이 지금 구성보다 크게 낮으면 낙폭·변동성이 현금으로 눌린 값 (062)
                       **({"invested_gap_note_ko": g} if (g := B.invested_gap_note(R, chosen)) else {}),
                       # 지금 구성의 예상 변동성이 백테스트보다 크게 높으면 (080)
                       **({"risk_gap_note_ko": rg} if (rg := B.risk_gap_note(R, chosen)) else {})},
            "benchmark": {"label": b["name_ko"], "headline": b["headline"], "headline_display": _headline_display(b["headline"]), "yearly_returns": b["yearly_returns"], "money": b["money"]},
            "other_benchmarks": [{"label": x["name_ko"], "headline": x["headline"]} for x in bt.get("benchmarks", []) if x["id"] != b["id"]],
            "matched": [{"id": x["id"], "label": x["name_ko"], "base_id": x.get("base_id"), "cash_ratio": x.get("cash_ratio"), "cash_ratio_total": x.get("cash_ratio_total"),
                         "match_target": x.get("match_target"), "headline": x["headline"], "headline_display": _headline_display(x["headline"]),
                         # 선택안보다 낙폭이 정말 낮은가 (036: 맞춤안 최대낙폭 11.9% 가 추천 11.3% 보다 큰데 '낙폭을 더 낮추려면 맞춤안' 을 권했다)
                         "lower_drawdown_than_chosen": abs((x.get("headline") or {}).get("max_drawdown") or 0) < abs((p.get("headline") or {}).get("max_drawdown") or 0) - 1e-9,
                         "status": next((r["status"] for r in val["results"] if r["id"] == x["id"]), None),
                         # 010: 기준이 이미 허용 낙폭 안인데 '허용 낙폭에 맞춰 줄였다' 고 썼다 → 기준의 낙폭과 허용 낙폭 안이었는지를 같이 넘긴다
                         "base_max_drawdown": (B.find(R, x["base_id"]).get("headline") or {}).get("max_drawdown") if x.get("base_id") else None,
                         "base_within_tolerance": (abs((B.find(R, x["base_id"]).get("headline") or {}).get("max_drawdown") or 0)
                                                   <= float(R["request"]["risk"]["max_drawdown_tolerance"]) + 1e-9) if x.get("base_id") else None}
                        for x in bt["portfolios"] if x.get("kind") == "matched"],
            # 맞춤안이 없을 때 이유 — 백테스트와 같은 규칙(기준 구성의 MDD vs 낙폭 맞춤 목표)으로 (001: 이미 허용 낙폭 안인데 '맞춤안을 따로 확인하라' 고 했다)
            "matched_note": _matched_note(R),
            "news_effect": _news_effect_display(B.news_effect(R)),
            "window": {"trading_days": bt["period"]["trading_days"], "annualized_reliable": bt["period"].get("annualized_reliable", True),
                       "note": "창이 1.5년 미만이면(annualized_reliable=false) CAGR·Sharpe·XIRR 같은 연환산 값은 참고용이며 기간 수익률(total_return)로 말해야 함",
                       "period_note_ko": B.period_note(R)},
            # 뉴스를 끈 분석은 뉴스를 불러오지 않는다 → 날짜별 '0건' 을 넘기면 서술이 '헤드라인 0건' 이라고 썼다 (004)
            "walkforward": ({"dates": R["portfolio"]["walkforward"]["dates"], "news_summary": _news_summary(R),
                             "fallback_dates": next((p for p in R["portfolio"]["walkforward"]["portfolios"] if p["kind"] == "black_litterman"), {}).get("fallback_dates", []),
                             "news_bl_omitted_ko": (R["portfolio"]["walkforward"].get("bl_omitted") or {}).get("reason_ko"),  # 뉴스 반영 구성을 만들지 않은 이유 (없으면 BL 후보 자체가 없다)
                             # 변화 자료가 없으면 키째 넘기지 않는다 (023·046: 빈 자료를 보고 '직전 리밸런싱 대비 변화 자료는 확인할 수 없지만' 이라고 썼다, 050: 빈 top_delta_by_date)
                             **_top_delta_facts(R, chosen),
                             **_wf_changes_facts(R, chosen, "weight_changes_by_date = "),
                             # 뷰가 비중을 한 번도 못 바꿨으면 '다음 리밸런싱까지' 적중률을 넘기지 않는다 (055: 카드는 비우는데 14a 가 이 표의 37.5% 를 옮겼다)
                             "results": [{"id": x["id"], "label": x["name_ko"],
                                          "headline": {**x["headline"], **({"view_hit_ratio_next_rb": None} if B.views_moved(R, x) is False else {})}}
                                         for x in bt["portfolios"] if x.get("mode") == "walkforward"]}
                            if R["portfolio"].get("walkforward") else None),
            "selection_infeasibility": _infeasibility_fact(R), "sector_overflow": R["selection"]["backtest_as_of"].get("sector_overflow"),
            "baseline": {"id": base["id"], "headline": base["headline"], "money": base["money"]}, "comparison": B.comparison_table(R)["rows"],
            "validation": {"criteria": val["criteria"], "chosen_checks": (next((r for r in val["results"] if r["id"] == chosen), None) or next((a for a in val.get("alternatives", []) if a["id"] == chosen), {})).get("checks"),
                           "summary": val["summary"], "per_portfolio_status": {r["id"]: r["status"] for r in val["results"]}, "recommended": ({**val["recommended"], "reason_ko": reason_prose_ko(val["recommended"].get("reason_ko"))} if val.get("recommended") else None),
                           "chosen_id": val.get("chosen_id"), "warnings": [n["message_ko"] for n in (R.get("notices") or []) if n.get("stage") == "12_validation"]},
            "fx": None if R["request"]["capital"].get("currency") == "USD" else R["money_krw"]["direction"]}  # fmt: skip  (달러 요청에 '1 USD = 1.00 KRW' 를 넘기지 않음)


def _matched_note(R: dict[str, Any]) -> str | None:
    bt = R["backtest"]
    if any(x.get("kind") == "matched" for x in bt["portfolios"]):
        return None
    target = float(R["intent"]["risk_params"].get("effective_max_drawdown") or R["request"]["risk"]["max_drawdown_tolerance"])
    bases = [R["portfolio"]["targets"]["baseline"]["id"], "wf_bl_news"]
    mdds = [abs((x.get("headline") or {}).get("max_drawdown") or 0) for x in bt["portfolios"] if x["id"] in bases]
    # 할 수 있는 일은 이유마다 다르다: 이미 목표 안이면 허용 낙폭을 낮춰 다시 분석하면 생기지만, 하한 때문이면 낮출수록 더 못 만든다 (011 검토)
    if mdds and all(m <= target + 1e-9 for m in mdds):
        worst = max(mdds)  # 목표가 이 값보다 작아져야 맞춤안이 생긴다 (그래도 주식 30% 하한에 막힐 수 있어 '만들어진다' 고 단정하지 않는다)
        # 어느 구성의 낙폭인지 이름을 붙인다 (021: 뉴스 반영 walk-forward 의 11.8% 를 '기준 구성의 최대낙폭' 이라고 했다 — 기준 역변동성비중은 11.1%)
        named = ", ".join(f"{B.pf_label(x)} {abs((x.get('headline') or {}).get('max_drawdown') or 0):.1%}" for x in bt["portfolios"] if x["id"] in bases)
        return (f"맞춤안을 만드는 바탕 구성의 과거 최대낙폭({named})이 이미 낙폭 맞춤 목표({target:.1%}) 안이라 현금을 섞은 낙폭 맞춤안을 만들 필요가 없었습니다. "
                f"그런 안이 필요하면 낙폭 맞춤 목표가 {worst:.1%}보다 작아지도록 손실 감내 수준을 낮춰 다시 분석하면 만들 수 있습니다.")  # 마침표 (025·026: 그대로 옮긴 문장이 마침표 없이 끝났다)
    floor = float(((R.get("parameters") or {}).get("backtest") or {}).get("matched_min_invested", 0.30))  # 정책 결정 2
    return (f"주식 비중을 {floor:.0%} 이상 남기면서는 과거 최대낙폭을 목표({target:.1%}) 안으로 맞추지 못해 낙폭 맞춤안(주식 + 현금)을 만들지 않았습니다. "
            "손실 감내 수준을 낮추면 목표가 더 엄격해져 역시 만들 수 없으니, 허용 낙폭을 다시 생각하거나 변동성이 낮은 구성을 검토할 수 있습니다.")


def _subtitle_ko(R: dict[str, Any], chosen: str) -> str:
    """머리말 부제 = 요청 해석. 선택안의 주식 비중이 요청 투자 비율과 다르면 '요청:' 을 붙인다
    (027: '투자 비율 85%를 배분합니다' 바로 옆에 '낙폭 맞춤안 (주식 44.6% + 현금 55.4%)' 가 나와 서로 어긋나 보였다)."""
    # 대화가 끝난 뒤의 머리말에 '확인이 필요합니다' 같은 미정 문장은 빼다 (041: 묻지도 않은 유니버스를 '확인이 필요' 로 남겼다)
    # 백테스트 시작일 조건(대화 보기에서 알린 결과)을 바람처럼 적은 문장도 머리말에서는 뺀다 (044: '백테스트 시작 시에는 … 60%만 운용하길 원합니다' — 사용자가 바란 게 아님).
    # 사실로 적은 문장은 둔다 — 같은 문장에 필수 포함·제외 조건이 함께 있다 (032 'CVX를 반드시 포함하며, … 백테스트 시작 시점에는 … 11개 종목으로 평가합니다')
    # 확정 요청과 다른 투자기간을 말하는 문장도 뺀다 (045: 아이디어의 '약 15년' 을 머리말에 썼는데 분석은 10년)
    yrs = float((R["request"].get("horizon") or {}).get("target_years") or 0)

    def fix_horizon(x: str) -> str:
        """다른 투자기간은 확정 기간으로 바꾼다 — 문장째 빼면 같은 문장의 테마까지 사라졌다 (045 재실행: 머리말이 '마스터카드(MA)는 반드시 포함하며…' 만 남음).
        '투자 기간 … N년' 꼴이 아니어도 확정 기간보다 긴 'N년(간)' 은 바꾼다 (065: '약 15년간 자산 증식' — 투자기간은 10년까지만 받는다). 백테스트·과거 기간 문장은 건드리지 않는다."""
        m = re.search(r"(투자\s*기간[^.]*?)(?:약\s*)?(\d+(?:\.\d+)?)\s*년", x)
        if m and yrs and abs(float(m.group(2)) - yrs) > 1e-9:
            return x[: m.start()] + m.group(1) + f"{yrs:g}년" + x[m.end():]
        if yrs and not re.search(r"백테스트|과거|최근|지난|동안의 성과", x):
            return re.sub(r"(?:약\s*)?(\d+(?:\.\d+)?)\s*년(간|동안)?", lambda k: (f"{yrs:g}년{k.group(2) or ''}" if float(k.group(1)) > yrs + 1e-9 else k.group(0)), x)
        return x

    def start_wish(x: str) -> bool:
        return bool(re.search(r"백테스트|시작\s*(?:시|때|시점)", x) and re.search(r"원합니다|원하|바랍니다|희망", x))

    text = " ".join(fix_horizon(x) for x in re.split(r"(?<=[.!?다])\s+", R["intent"]["interpretation"]["summary_ko"].strip())
                    if x and not B._PENDING.search(x) and not start_wish(x))  # fmt: skip
    cc = B.current_composition(R, chosen)
    want = 1 - float(R["request"]["constraints"].get("min_cash_ratio") or 0)
    # 지금 구성의 종목 수가 요청 목표보다 적어도 '요청:' (069: 머리말 '15개를 선정' 인데 선정은 11개)
    target = int(((R["request"]["constraints"].get("num_holdings") or {}).get("target")) or 0)
    short = bool(cc) and target > 0 and sum(1 for x in cc[0].values() if x > 1e-6) < target
    if cc and (abs((1 - cc[1]) - want) > 0.01 or short):
        return f"요청: {text}"
    return text


def _chosen_note(R: dict[str, Any], p: dict[str, Any], is_rec: bool) -> str:
    vd = (R["validation"].get("recommended") or {}).get("verdict")
    if vd:
        if vd["status"] == "insufficient":
            cause = vd.get("cause_ko") or "투자 비율이 낮습니다"
            # 원인은 백테스트 시작일 구성의 것 — 지금 구성(분석 기준일)이 충분히 담으면 그렇게 말한다 (018: 3종목·42% 는 시작일, 지금은 7종목·95%)
            cc = B.current_composition(R, p["id"])
            inv_now = 1.0 - cc[1] if cc else None
            enough = inv_now is not None and inv_now >= float(((R.get("parameters") or {}).get("backtest") or {}).get("min_invested_for_recommendation", 0.5)) - 1e-4
            tail = (f"지금 구성(분석 기준일)은 {sum(1 for x in cc[0].values() if x > 1e-6)}종목·투자 {inv_now:.0%}입니다." if enough
                    else "순위 1위 구성을 중심으로 설명하지만 그대로 투자하기에는 부족합니다.")  # fmt: skip
            return (f"백테스트 시작일 구성은 {cause}. {tail}" + (" 주의: " + " · ".join(vd["cautions_ko"]) + "." if vd.get("cautions_ko") else ""))
        if vd.get("cautions_ko"):
            return "후보 중 순위 1위 구성입니다. 주의: " + " · ".join(vd["cautions_ko"]) + "."
        return "후보 중 순위 1위로 추천된 구성입니다."
    if is_rec:
        return "검증 결과 추천된 포트폴리오입니다."
    if p["kind"] == "alternative":
        return "조건을 통과한 포트폴리오가 없어 검증 단계가 계산한 현금 혼합안을 중심으로 설명합니다."
    return "조건을 통과한 포트폴리오가 없어 기준 포트폴리오를 중심으로 설명합니다."


def _balanced_news(news: list[dict[str, Any]], held: set[str], k: int) -> list[dict[str, Any]]:
    """종목마다 돌아가며(보유 종목 먼저) 최신순으로 k 건. 009: 전체 최신 60건만 넘겨 이틀치·일부 종목만 남았고, 서술이 'SOLV 헤드라인 근거 없음' 이라고 썼다."""
    by_t: dict[str, list[dict[str, Any]]] = {}
    for x in sorted(news, key=lambda x: (x.get("published_at") or ""), reverse=True):
        by_t.setdefault(x["ticker"], []).append(x)
    order = sorted(by_t, key=lambda t: (t not in held, t))
    picked: list[dict[str, Any]] = []
    i = 0
    while len(picked) < k and any(i < len(by_t[t]) for t in order):
        picked += [by_t[t][i] for t in order if i < len(by_t[t])][: k - len(picked)]
        i += 1
    return sorted(picked, key=lambda x: (x.get("published_at") or ""), reverse=True)


def facts_for_market(R: dict[str, Any]) -> dict[str, Any]:
    _win, news_all, discl_all = _asof_news(R)
    news = [{"id": v["id"], "ticker": (v.get("tickers") or [""])[0], "published_at": v.get("published_at"), "title": v.get("title"), "source": v.get("source"), "language": v.get("language")}
            for v in news_all]  # fmt: skip
    news.sort(key=lambda x: (x["published_at"] or ""), reverse=True)
    held = {t["ticker"] for t in R["selection"]["table"] if t.get("in_selection_now")}
    n_by_ticker: dict[str, int] = {}
    for x in news:
        n_by_ticker[x["ticker"]] = n_by_ticker.get(x["ticker"], 0) + 1
    picked = _balanced_news(news, held, 60)
    # 공시 날짜는 하나로 (접수일, 근거 패널과 같은 날짜) — 기간은 접수일로, 예시는 공개일(다음 날)로 써서 '09-11 실적 발표 공시' 가 근거의 09-10 과 어긋났다 (071)
    discl = [{"id": v["id"], "ticker": (v.get("tickers") or [""])[0], "date": v.get("filed_at") or v.get("available_on"), "event": v.get("event_label_ko"),
              "form": v.get("form"), "items": v.get("items"), "title": v.get("title"), "source": v.get("source")} for v in discl_all]  # fmt: skip
    discl.sort(key=lambda x: (x["date"] or ""), reverse=True)
    nd = sorted(x["published_at"] or "" for x in news)
    dd = sorted(x["date"] or "" for x in discl)
    event_summary: dict[str, dict[str, int]] = {}
    for d_ in discl:
        event_summary.setdefault(d_["ticker"], {})
        event_summary[d_["ticker"]][d_["event"] or "기타"] = event_summary[d_["ticker"]].get(d_["event"] or "기타", 0) + 1
    chosen, _ = B.chosen_portfolio_id(R)
    p = B.find(R, chosen)
    bench = R["backtest"]["benchmark"]
    f = R["portfolio"].get("forward") or {}
    h, bh = p["headline"], bench["headline"]

    def pct(x: Any, d: int = 1) -> str | None:
        return None if x is None else f"{float(x) * 100:.{d}f}%"

    reliable = bool(R["backtest"]["period"].get("annualized_reliable", True))
    cc = B.current_composition(R, chosen)
    now_w, now_cash = (cc[0], cc[1]) if cc else ({}, 0.0)
    sec_of = {t["ticker"]: sector_ko(t["sector"]) for t in R["selection"]["table"]}
    now_sec: dict[str, float] = {}
    for t, w_ in now_w.items():
        if w_ > 1e-9:
            now_sec[sec_of.get(t, "기타")] = now_sec.get(sec_of.get(t, "기타"), 0.0) + w_
    return {"annualized_reliable": reliable, "annualized_note": None if reliable else "창이 1.5년 미만이라 연환산 수익률(cagr)은 참고용 — 우열은 기간 수익률(period_return)로 말한다",
            "citation_rule": "뉴스·공시에 관한 사실 문장은 [ev123](뉴스) 또는 [dc45](공시) 처럼 아래 목록의 id 를 인용한다. 성과·섹터 비중 숫자(chosen·benchmark·sector_exposure_pct)는 인용 없이 그대로 쓴다. 목록에 없는 id·숫자·사건을 만들지 않는다. 헤드라인과 공시는 사건의 존재·종류·시점만 알려 준다 (실적 발표 공시 ≠ 좋은 실적).",
            # 선택안 성과 (예전에는 없어서 'SPY 대비 우열을 판단할 수 없다' 고 쓰고, 바로 위 KPI 와 모순됐다)
            "chosen": {"label": B.pf_label(p), "period": f"{R['backtest']['period']['start']} ~ {R['backtest']['period']['end']}", "cagr": pct(h.get("cagr")),
                       "period_return": pct(h.get("period_return")), "max_drawdown": pct(abs(h.get("max_drawdown") or 0)), "excess_cagr_vs_benchmark_pp": (None if h.get("excess_cagr") is None else (_vs_benchmark_display(R, p) or {}).get("cagr_diff") or f"{h['excess_cagr'] * 100:+.1f}%p")},  # 036: 14c 만 원값(-16.3%p)
            "as_of": R["request"]["derived"]["as_of"], "summary_ko": R["intent"]["interpretation"]["summary_ko"],
            "themes": [{"id": t["id"], "label": t["label_ko"], "description": t["description_ko"]} for t in R["intent"]["interpretation"]["themes"]],
            # 섹터는 한국어 이름으로 (영어 GICS 이름을 넘기면 'Communication Services 업종' 처럼 그대로 옮겨 적었다)
            # 지금 보유(분석 기준일 구성)와 백테스트 보유(시작일에 고른 종목, 기간 내내 고정)를 나눠 넘긴다. 예전에는 지금 9종목 옆에 백테스트(2종목 + 현금 48%)의
            # 평균 섹터 비중을 붙여 '선택안의 평균 산업재 비중 51.6%' 처럼 지금 구성(산업재 75%)과 다른 숫자가 나왔다 (002).
            "universe": R["request"]["constraints"]["universe"],
            # 시장은 상장 시장이다 (047: market 'US' 를 국적으로 읽어 캐나다 기업 Shopify 가 있는데 '보유 종목은 모두 미국 기업' 이라고 썼다)
            "holdings": [{"ticker": t["ticker"], "name": t["name"], "sector": sector_ko(t["sector"]), "listed_market": _LISTED_KO.get(t.get("market"), t.get("market")),
                          "weight_now": pct(now_w.get(t["ticker"]))}
                         for t in R["selection"]["table"] if t["in_selection_now"]],
            "holdings_note": f"분석 기준일({R['selection']['as_of_now']['as_of']}) 선정 종목과 현재 구성 비중" + (f" (현금 {pct(now_cash)})" if now_cash else ""),
            "current_sector_weights_pct": {k: pct(v) for k, v in sorted(now_sec.items(), key=lambda x: -x[1])},
            "backtest_holdings": [t["name"] for t in R["selection"]["table"] if t["in_backtest"]],
            "sector_exposure_pct": {sector_ko(k): pct(v) for k, v in sorted((p["metrics"]["composition"]["sector_weights_avg"] or {}).items(), key=lambda x: -(x[1] or 0))},
            "sector_exposure_note": "백테스트 기간(시작일에 고른 backtest_holdings, 기간 내내 고정) 선택안의 평균 섹터 비중 — 나머지는 현금. 지금 구성의 섹터 비중은 current_sector_weights_pct",
            # 큰 순서를 문자열로 (061: 정보기술 6.9% 를 건너뛰고 '…경기소비재 10.0%, 유틸리티 6.1% 등' 이라고 써 순서가 틀렸다)
            "sector_exposure_top_ko": ", ".join(f"{sector_ko(k)} {pct(v)}" for k, v in sorted((p["metrics"]["composition"]["sector_weights_avg"] or {}).items(), key=lambda x: -(x[1] or 0))[:5]),
            "benchmark": {"label": bench["name_ko"], "cagr": pct(bh.get("cagr")), "period_return": pct(bh.get("period_return")), "max_drawdown": pct(abs(bh.get("max_drawdown") or 0))},
            "news": picked, "news_count_by_ticker": {t: n_by_ticker.get(t, 0) for t in sorted(held)},
            "news_dates": {"from": nd[0], "to": nd[-1], "n": len(news)} if nd else None,
            # 종목마다 가장 최근 N건까지만 담는다는 사실과 뉴스 창을 같이 (067: 창은 09-24~10-07 인데 종목마다 최근 10건이 10-06~10-07 에 몰려
            # '헤드라인 관찰 기간은 10-06~10-07 로 한정, 종목별 10건씩' 이라 써서 같은 리포트의 '창 14일·40건' 과 어긋났다)
            "news_note": (f"news 는 종목마다 돌아가며 고른 최대 60건. 뉴스 창은 {' ~ '.join(_win_of(R) or [])}이고 종목마다 가장 최근 {int(((R.get('parameters') or {}).get('news') or {}).get('per_ticker') or 10)}건까지만 담았다 — "
                          "news_count_by_ticker 는 그 상한 안의 건수(그 종목 뉴스 전체가 아님), news_dates 는 실제 담긴 기사의 날짜 범위(뉴스 창과 다를 수 있음). 둘을 함께 말할 때 이 차이를 밝힘"),
            "disclosures": discl[:40], "event_summary": event_summary, "disclosure_dates": {"from": dd[0], "to": dd[-1], "n": len(discl)} if dd else None,
            "news_window": f.get("news_window"),
            "forward_views": [v["summary_ko"] for pp in f.get("portfolios", []) for v in pp["views_applied"]]}  # fmt: skip


_LISTED_KO = {"US": "미국 시장 상장 (회사 국적과 다를 수 있음)", "KR": "한국 시장 상장"}


def facts_for_narrate(R: dict[str, Any], chosen: str, interp: dict[str, Any]) -> dict[str, Any]:
    p = B.find(R, chosen)
    bl = R["portfolio"]["baselines"]
    base = next(x for x in bl["portfolios"] if x["id"] == bl["chosen_baseline"])
    f = R["portfolio"].get("forward")
    return {"citation_rule": "선정·구성 설명에서 지표 값을 말할 때는 [fin:...] 근거 ID(선정 표의 fact id), 성과 숫자는 [calc:...] 를 인용한다. 목록에 없는 id 는 쓰지 않는다.",
            # 기준일 값 = metric_fact_id, 시작일 값 = metric_backtest_fact_id (예전에는 기준일 ID 만 있어 시작일 PER 에 기준일 ID 를 붙였다, 003)
            "fact_ids": list(dict.fromkeys(i for t in R["selection"]["table"] for i in (t.get("metric_fact_id"), t.get("metric_backtest_fact_id")) if i)),
            "calc_ids": sorted(k for k in R["evidence_index"] if k.startswith("calc:") and k.endswith(":" + chosen)),
            # 첫 문단의 비교지수 대비 차이도 표시값끼리 (032: '18.5%보다 1.8%p 높았습니다' — 표시된 20.2% 와 맞지 않음)
            "chosen_headline_display": _headline_display(p.get("headline")), "vs_benchmark_display": _vs_benchmark_display(R, p),
            "request": {r["k"]: r["v"] for r in B.request_table(R)["rows"]},
            "rebalance_ko": R["portfolio"]["backtest_spec"]["rebalance_rule"].get("description_ko"),
            "intent": {"summary": R["intent"]["interpretation"]["summary_ko"], "themes": [{"label": t["label_ko"], "description": t["description_ko"]} for t in R["intent"]["interpretation"]["themes"]],
                       "conflicts": B.conflicts_view(R), "risk_params": R["intent"]["risk_params"], "constraints": {r["k"]: r["v"] for r in B.constraints_table(R)["rows"]}},
            "selection": {"metric": R["selection"]["metric"], "metric_ko": M.METRIC_KO.get(R["selection"]["metric"], R["selection"]["metric"]), "funnel": R["selection"]["funnel"],
                          "candidates_filtered": R["selection"].get("candidates_filtered") or [],  # 테마 관련 종목 중 시가총액·거래대금 등으로 빠진 사유·예
                          # 이름마다 사유를 괄호로 붙인 한 줄 — 사유가 다른 두 종목을 한 구절로 이어 'Walmart와 같은 회사의 다른 주식인 Alphabet C' 로 읽혔다 (073)
                          **({"candidates_filtered_ko": cf} if (cf := _filtered_names_ko(R)) else {}),
                          "table": [{**t, "sector": sector_ko(t.get("sector")),
                                     "metric_now_display": (M.display_metric(R["selection"]["metric"], t.get("metric_now")) if t.get("in_selection_now") else "분석 기준일 목록에 없음"),
                                     "metric_backtest_display": (M.display_metric(R["selection"]["metric"], t.get("metric_backtest")) if t.get("in_backtest") else "백테스트 시작일 목록에 없음")}
                                    for t in R["selection"]["table"]],
                          "theme_filter_applied": R["selection"].get("tagging_summary", {}).get("theme_filter_applied", True),
                          "excluded_examples": R["selection"]["as_of_now"]["rejected_examples"],
                          "excluded_by_theme": R["selection"].get("excluded_by_theme") or [],  # 테마에는 해당하지만 제외 테마로 뺀 종목 (024)
                          **({"theme_search_ko": ts} if (ts := _theme_search_ko(R)) else {}),
                          "diff": {k: v for k, v in R["selection"]["backtest_as_of"]["diff_vs_original"].items() if k != "removed_reasons"},
                          # 시작일 재선정을 하지 않았으면 그 사실 (054: '두 날짜의 PER 이 같다' — 시작일 값은 기준일 값의 복사본이었다)
                          **({"backtest_reselected": False, "backtest_list_note_ko": B.LOOKAHEAD_KO} if R["selection"].get("backtest_reselected") is False else {}),
                          # 시작일 목록에서 빠진 종목과 그날 사유 (candidates_filtered 는 분석 기준일 후보 단계 사유라 시작일 설명에 쓰면 틀린다, 011)
                          "backtest_start_removed": R["selection"]["backtest_as_of"].get("removed_reasons_ko") or [],
                          "backtest_only_reasons": R["selection"]["backtest_as_of"].get("backtest_only_reasons_ko") or [],  # 시작일 목록에만 있던 종목의 기준일 사유
                          "warnings": [n["message_ko"] for n in (R.get("notices") or []) if n.get("stage") in ("05_selection", "07_backtest_spec")], "explained": R["selection"].get("explained")},
            "construction": {"baseline": {"id": base["id"], "rule": base["rule_ko"], "n": len(base["weights"]), "weights": base["weights"], "cash_weight": base.get("cash_weight", 0),
                                          "constraints_applied": base["constraints_applied"], "sector_weights": base["sector_weights"],
                                          # 시작일 값이라고 밝힌다 (061: 시작일 최소분산의 필수소비재 39.4% 를 지금 추천 구성 문장 옆에 붙여 지금 값처럼 읽혔다 — 지금은 9.9%)
                                          "note": f"백테스트 시작일({R['portfolio']['backtest_spec']['period']['as_of']}) 기준 비중 구성 — weights·sector_weights 는 지금 구성이 아님"},
                             # 소수 그대로 넘기면 LLM 이 '36.7611%' 처럼 옮겨 적는다 → 표시 문자열로 (표 블록은 그대로 숫자)
                             # 'vol' 은 시작일 구성 때의 추정치라 이름에 밝힌다 (서술이 '연변동성 36.8%' 라고 써서 실현 변동성 43.3% 와 어긋났다, 003)
                             "templates": [{**{k: v for k, v in r.items() if k not in ("vol", "top")}, "est_vol_at_start": f"{r['vol']:.1%}", "top_weight_at_start": f"{r['top']:.1%}", "cash": f"{r['cash']:.1%}",
                                            "neff": round(float(r["neff"]), 1)} for r in B.templates_table(R)["rows"]],
                             "templates_note": "est_vol_at_start = 백테스트 시작일에 과거 자료로 추정한 예상 변동성 (백테스트 실현 변동성이 아님), top_weight_at_start = 백테스트 시작일 구성의 가장 큰 종목 비중 (지금 구성 아님, 045)",
                             **_same_top_note(B.templates_table(R)["rows"]),
                             # 시작일에 뉴스 뷰가 없으면 BL 파라미터가 비어 'max_tilt 가 정해져 있지 않다' 고 썼다 → 해당 없음을 밝힌다
                             # 뉴스를 껐으면 그 이유로 (027: 뉴스 끔인데 '시작일에 뉴스 뷰가 없어' 라고 써 뉴스를 찾았는데 없던 것처럼 읽혔다)
                             # 표시 문자열 %p 로 (052: 0.1066… 을 '종목당 최대 10.67% 조정 폭' 으로 옮겨 상대 10.67% 처럼 읽혔다)
                             "max_tilt": (f"{float(mt_) * 100:.2f}%p" if (mt_ := R["portfolio"]["targets"]["parameters"].get("max_tilt_per_stock")) else None) or ("해당 없음 (백테스트 시작일에 뉴스 뷰가 없어 BL 구성을 만들지 않음)"
                                                                                                              if R["intent"]["news_tilt"]["enabled"] else "해당 없음 (뉴스 반영을 꺼서 BL 구성을 만들지 않음)"),
                             "news_tilt_enabled": R["intent"]["news_tilt"]["enabled"], "start_views": _shown_views(R["portfolio"]["views"]),
                             "scenarios": [{"id": s["id"], "title": s.get("title_ko"), "narrative": (s.get("portfolio_view") or "").split("\n")[0], "views": [v["summary_ko"] for v in s["views_applied"]],
                                            "top_delta": B.set_deltas(s, 3), **_stuck_fact(R, s)} for s in R["portfolio"]["targets"]["portfolios"]],
                             # 시작일 배분과 지금 배분을 나눠 이름 붙인다 (005: 시작일 비중을 '최종 구성' 이라 쓰고 소수 '14.6818%' 를 그대로 옮겼다)
                             # 맞춤안이면 무엇을 줄였는지 (046: 뉴스 반영 walk-forward 를 줄인 맞춤안을 '동일비중에 낙폭 맞춤을 적용' 이라고 썼다)
                             "chosen": {"id": chosen, "label": B.pf_label(p), "mode": p.get("mode"), "rebalance_targets_ko": _rebalance_targets_ko(p, _rebalances(R)),
                                        "base_label": B.pf_label(B.find(R, p["base_id"])) if p.get("base_id") else None,
                                        "backtest_start": str(R["portfolio"]["backtest_spec"]["period"]["as_of"]),
                                        "allocation_at_backtest_start": [{"ticker": r["ticker"], "name": r["name"], "weight": f"{r['w'] * 100:.1f}%", "usd": round(r["usd"]), "krw": round(r["krw"])}
                                                                         for r in B.allocation_table(R, chosen)["rows"]],
                                        "as_of_now": R["selection"]["as_of_now"]["as_of"], "allocation_now": _allocation_now(R, chosen), "cash_breakdown": cash_breakdown(R, p)},
                             "walkforward": R["portfolio"].get("walkforward") and {"dates": R["portfolio"]["walkforward"]["dates"], "news_summary": _news_summary(R),
                                                                                   **_top_delta_facts(R, chosen),
                                                                                   "news_bl_capped_note_ko": (B.news_effect(R) or {}).get("capped_note_ko"),
                                                                                   **_wf_changes_facts(R, chosen, "")}},
            "interpretation": {**interp, "window": R["backtest"]["period"]},
            "forward": ({"as_of": f["as_of"], "news_window": _shown_news_window(f.get("news_window")), "fallback_reason": f.get("fallback_reason_ko"), "news_note_ko": _forward_news_note(R),
                         **_chosen_news_use(R, chosen, p),
                         "portfolios": [{"id": x["id"], "title": x.get("title_ko"), "narrative": (x.get("portfolio_view") or "").split("\n")[0], "views": [v["summary_ko"] for v in x["views_applied"]],
                                         "evidence_ids": sorted({i for v in x["views_applied"] for i in v.get("evidence_ids", [])}), "top_delta": B.set_deltas(x, 3),
                                         **_stuck_fact(R, x)} for x in f["portfolios"]],
                         "evidence": {i: {"date": e["published_at"], "publisher": e.get("publisher"), "title": e["title"]} for i, e in f["evidence"].items()}} if f else None),
            "data_quality": R.get("data_quality"), "limitations": B.limitations(R), "parameters": {r["k"]: r["v"] for r in B.parameters_table(R)["rows"]}}  # fmt: skip


def call_interpret(R, chosen, llm):
    system, user = load_prompts("14a_interpret", facts_json=json.dumps(facts_for_interpret(R, chosen), ensure_ascii=False, indent=1, default=str))

    def _check(a):
        for k, n in [("performance_ko", 2), ("risk_fit_ko", 1), ("validation_ko", 1), ("next_actions_ko", 2)]:
            _need(a, k, n)

    ans = llm.complete_json("14a_interpret", messages_from_prompts(system, user), validator=_check)
    if not any(x.get("kind") == "matched" for x in R["backtest"]["portfolios"]):
        _drop_matched_suggestions(ans, ("performance_ko", "risk_fit_ko", "validation_ko", "next_actions_ko"))
    ans.setdefault("headline_ko", "")
    ans.setdefault("view_review_ko", [])
    ans.setdefault("news_ko", [])
    ans.setdefault("assessment", {"intent_fit": None, "logic_consistency": None, "comments_ko": []})
    return ans


def call_market(R, llm):
    system, user = load_prompts("14c_market", facts_json=json.dumps(facts_for_market(R), ensure_ascii=False, indent=1, default=str))
    ans = llm.complete_json("14c_market", messages_from_prompts(system, user), validator=lambda a: _need(a, "market_ko", 1))
    return ans


def call_narrate(R, chosen, interp, llm):
    system, user = load_prompts("14b_narrate", facts_json=json.dumps(facts_for_narrate(R, chosen, interp), ensure_ascii=False, indent=1, default=str),
                                interpretation_json=json.dumps(interp, ensure_ascii=False, indent=1))  # fmt: skip

    def _check(a):
        for k, n in [("overview_ko", 2), ("request_interpretation_ko", 1), ("selection_ko", 1), ("construction_ko", 1), ("assumptions_ko", 1), ("reconsideration_ko", 1), ("glossary", 5)]:
            _need(a, k, n)

    ans = llm.complete_json("14b_narrate", messages_from_prompts(system, user), validator=_check)
    ans.setdefault("forward_ko", [])
    if not any(x.get("kind") == "matched" for x in R["backtest"]["portfolios"]):
        _drop_matched_suggestions(ans, ("overview_ko", "reconsideration_ko"))
    return ans


# '낙폭 맞춤안 … 검토/살펴/확인해 보/볼 수/고려/선택할' 처럼 맞춤안을 보라고 권하는 꼴. 부정(없·않·못)은 맞춤안~동사 사이와 동사 뒤 8자 안에서만 본다
# (문장 전체에서 보면 '…살펴볼 수 있지만, 이번에는 필요하지 않았습니다' 가 빠져나갔고, '없으므로 …검토해 보세요' 는 지워졌다)
_MATCHED_SUGGEST = re.compile(r"낙폭\s*맞춤안(.*?)(검토|살펴|확인해\s*보|볼\s*수|고려|선택할|선택해)(.{0,8})")
_MATCHED_NEG = re.compile(r"없|않|못")
_RERUN = re.compile(r"다시\s*분석|재분석")


def _suggests_matched(sent: str) -> bool:
    if _RERUN.search(sent):  # '손실 감내 수준을 낮춰 다시 분석하면 만들어집니다' 는 matched_note 가 주는 안내
        return False
    return any(not _MATCHED_NEG.search(m.group(1) + m.group(3)) for m in _MATCHED_SUGGEST.finditer(sent))


def _drop_matched_suggestions(ans: dict[str, Any], keys: tuple[str, ...]) -> None:
    """맞춤안이 없는데 '낙폭 맞춤안을 검토할 수 있습니다' 같은 문장을 빼낸다 (001 Q-013 에 이어 011 에서도 프롬프트만으로는 막지 못했다).
    '만들 필요가 없었습니다' 처럼 없다는 사실을 말하는 문장과 다시 분석하라는 안내는 둔다. 항목이 비면 항목째 빼되, 목록이 비지는 않게 한다."""
    for k in keys:
        items = ans.get(k)
        if not isinstance(items, list):
            continue
        out = []
        for it in items:
            if not isinstance(it, str):
                out.append(it)
                continue
            sents = re.split(r"(?<=[.!?])\s+", it.strip())
            keep = [x for x in sents if not _suggests_matched(x)]
            if keep:
                out.append(" ".join(keep))
        ans[k] = out or items


# 사용자가 보지 못하는 입력을 가리키는 말 (023·030·032·033: '제공된 모멘텀만으로', '입력된 규칙대로', '라벨에 적힌 대로' — 프롬프트 규칙만으로는 계속 새었다)
_PROMPT_TALK = re.compile(r"(?:제공된|입력된|라벨에 적힌 대로)\s+|(?:제시된|주어진)\s+(?=모멘텀|지표|자료|정보|근거|수치|숫자|목록|헤드라인|뉴스|데이터)")  # 033: '제시된 모멘텀 지표만으로', 043: '주어진 뉴스에는'
# 한글 사이에 섞인 흔한 한자 (046: 용어 풀이 '投자 시작부터')
_HANJA = str.maketrans({"投": "투", "資": "자", "收": "수", "益": "익", "率": "율", "期": "기", "間": "간", "株": "주", "價": "가", "額": "액", "金": "금"})


# '…는 다음과 같습니다: A · B · C.' — 지시문 투 머리말 + 코드 사유 문자열 그대로 (056, Q-124 와 같은 금지)
_LEAD_IN = re.compile(r"(은|는)?\s*다음과\s*같습니다\s*[:：]\s*([^.]*(?:\.\d[^.]*)*\.?)")
# 인용 id 가 아닌 한국어 문장을 감싼 대괄호 (056: '[뉴스 뷰의 반영 결과만으로 … 없습니다.]' 가 편집 메모처럼 보였다)
_BRACKET_KO = re.compile(r"\[([^\[\]]*[가-힣][^\[\]]*)\]")


def _lead_in_fix(m: re.Match) -> str:
    return (m.group(1) or "") + " " + m.group(2).replace(" · ", ", ")


def reason_prose_ko(reason: str | None) -> str | None:
    """추천 사유(코드 문자열 '1위 · … · 최대낙폭 21.5% vs 허용 20.0% (1.5%p 초과) · … USD.')를 문장에 넣을 수 있는 말로.
    14a 가 이 문자열을 '그대로' 옮겨 ' · '·'vs' 가 서술에 남았다 (063: 앞말 '다음과 같습니다:' 없이 붙여 Q-234 처리를 비켜 갔고, 064: '… USD.입니다')."""
    if not reason:
        return reason
    out = re.sub(r"최대낙폭 (\S+) vs 허용 (\S+) \(여유 ([^)]+)\)", r"최대낙폭 \1(허용 \2, 여유 \3)", reason)
    out = re.sub(r"최대낙폭 (\S+) vs 허용 (\S+) \(([^)]+) 초과\)", r"최대낙폭 \1(허용 \2보다 \3 큼)", out)
    return out.replace(" vs ", " 대비 ").replace(" · ", ", ").rstrip(". ")


def _plain_llm(obj: Any) -> Any:
    """LLM 문장에서 입력을 가리키는 말만 지운다 (나머지 문장은 그대로). 딕셔너리·목록 안의 문자열 모두."""
    if isinstance(obj, str):
        out = _PROMPT_TALK.sub("", obj).translate(_HANJA)
        out = _LEAD_IN.sub(_lead_in_fix, out)
        out = re.sub(r"(?<=[A-Za-z가-힣%)])\.(?=입니다|였습니다|이었습니다)", "", out)  # 'USD.입니다' (064)
        return _BRACKET_KO.sub(r"\1", out)
    if isinstance(obj, list):
        return [_plain_llm(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _plain_llm(v) for k, v in obj.items()}
    return obj


def _group(blocks: list[dict[str, Any] | None], group_ko: str, *, open_: bool = False) -> list[dict[str, Any]]:
    """연속 블록을 접힘 묶음으로 (Front 가 group_ko 가 같은 연속 블록을 하나의 접이식 묶음으로 그린다)."""
    out = []
    for b in blocks:
        if b:
            out.append({**b, "group_ko": group_ko, **({"group_open": True} if open_ else {})})
    return out


def cited_ids(sections: list[dict[str, Any]], idx: dict[str, Any]) -> list[str]:
    """문서가 실제로 인용한 근거 ID (문단·카드 인용, 기업 근거, 지표 근거, 근거 참조 블록, 뷰의 근거). 색인 순서로."""
    from backend.analysis.common.citations import CITE_RE

    used: set[str] = set()
    for sec in sections:
        for b in sec["blocks"]:
            t = b["type"]
            if t == "paragraphs":
                for x in b["items"]:
                    used.update(CITE_RE.findall(x))
            elif t == "cards":
                for it in b["items"]:
                    used.update(CITE_RE.findall(it.get("text_ko", "")))
                    for m in it.get("meta", []):
                        used.update(c for c in str(m.get("value", "")).replace(",", " ").split() if c in idx)
            elif t == "companies":
                for it in b["items"]:
                    used.update(it.get("evidence_ids", []))
                    if it.get("fact_id"):
                        used.add(it["fact_id"])
            elif t == "evidence_ref" and b.get("ids"):
                used.update(b["ids"])
            elif t == "timeline":
                for it in b["items"]:
                    for v in it.get("views", []):
                        used.update(v.get("evidence_ids", []))
            elif t == "table":
                for r in b.get("rows", []):
                    for v in r.values():
                        if isinstance(v, str) and v in idx:
                            used.add(v)
    return [k for k in idx if k in used]


def build_doc(R: dict[str, Any], *, interp: dict[str, Any], narr: dict[str, Any], market: dict[str, Any], step_summaries: dict[str, str] | None,
              settings: AnalysisSettings, usage: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    """문서 v2: 요약 대시보드(summary) + 7부분. 무거운 표는 묶음(group_ko)으로 접고, 근거 색인은 인용된 것만 evidence 에 싣는다 (나머지는 /evidence)."""
    interp, narr, market = _plain_llm(interp), _plain_llm(narr), _plain_llm(market)
    chosen, is_rec = B.chosen_portfolio_id(R)
    p = B.find(R, chosen)
    bt = R["backtest"]
    dates = bt["series_dates"]
    series = {x["id"]: {"label_ko": B.pf_label(x), "kind": x["kind"], **x["series"]} for x in B.all_blocks(R)}
    led = {l["date"]: l["amount_usd"] for l in p["contribution_ledger"]}
    inv, cum = [], p["money"]["initial_usd"]
    for d in dates:
        cum += led.get(d, 0.0)
        inv.append(round(cum, 2))
    series["net_invested"] = {"label_ko": "투입 원금(누적)", "kind": "reference", "value_usd": inv}
    all_ids = [x["id"] for x in B.all_blocks(R)]
    base_id = R["portfolio"]["targets"]["baseline"]["id"]
    default_on = list(dict.fromkeys([chosen, bt["benchmark"]["id"], base_id]))[:3]
    label = B.pf_label(p)
    themes = R["intent"]["interpretation"]["themes"]
    metric = R["selection"]["metric"]
    title_short = f"{themes[0]['label_ko']}" + (f" 외 {len(themes) - 1}" if len(themes) > 1 else "") + f" · {B.METRIC_SHORT_KO.get(metric, metric)} 전략"
    header = {"title_ko": title_short,
              "title_detail_ko": f"{themes[0]['label_ko']}" + (f" 외 {len(themes) - 1}개 테마" if len(themes) > 1 else "") + f" · {B.METRIC_SHORT_KO.get(metric, metric)} 기준 선정 · {label}",
              "subtitle_ko": _subtitle_ko(R, chosen), "created_at": dt.date.today().isoformat(),
              "selection_as_of": R["selection"]["as_of_now"]["as_of"], "backtest_period": R["portfolio"]["backtest_spec"]["period"],
              "data_as_of": str(R["request"]["derived"]["as_of"]), "chosen_portfolio_id": chosen, "chosen_label_ko": label,
              "chosen_note_ko": _chosen_note(R, p, is_rec),
              "disclaimer_ko": "이 리포트는 투자 판단을 돕기 위한 자료이며 특정 종목의 매수·매도를 지시하지 않습니다. 과거 성과는 미래 성과를 보장하지 않습니다.",
              # 화면에 그대로 보인다 — 내부 값('static_weights + walkforward') 대신 한국어로 (079)
              "run_id": R["run_id"], "backtest_mode": _mode_ko(bt.get("mode"))}  # fmt: skip
    kp = B.kpis(R, chosen)
    bl_ids = [x["id"] for x in R["portfolio"]["targets"]["portfolios"]]
    bl_for_bar = chosen if chosen in bl_ids else (bl_ids[0] if bl_ids else None)
    v_tab = B.view_table(R, chosen)
    t1, t2 = B.validation_tables(R, chosen)
    news_ids = B.news_used_ids(R)
    inf = B.infeasibility_callout(R)
    alt = B.alternatives_cards(R)
    # 맞춤안이 없으면 그 이유를 코드로도 보인다 (037: 이유 문장이 14a 입력에만 있어 리포트 어디에도 안 나왔다)
    mn = {"type": "callout", "tone": "info", "title_ko": "낙폭 맞춤안", "text_ko": mtxt} if (mtxt := _matched_note(R)) else None
    conf = B.conflicts_cards(R)
    wf_tl = B.timeline(R, chosen)
    wf_notes = [b for b in B.walkforward_blocks(R) if b["type"] == "callout"]  # walk-forward 요약 콜아웃만 (표·뷰 카드는 타임라인으로)
    fwd = B.forward_blocks(R, chosen)

    def nz(*blocks):
        return [b for b in blocks if b]

    sections = [
        {"id": "verdict", "title_ko": "종합 투자 판단", "blocks": nz(
            {"type": "paragraphs", "items": narr["overview_ko"], "tone": "lead", "src": "14b"}, {"type": "kpis", "ids": [k["id"] for k in kp]},
            {"type": "paragraphs", "items": interp["risk_fit_ko"], "src": "14a"})},
        {"id": "market", "title_ko": "산업과 시장 분석", "blocks": nz(
            {"type": "paragraphs", "items": narr["request_interpretation_ko"], "src": "14b"},
            *_group([B.themes_table(R), conf, B.request_table(R), B.constraints_table(R), B.soft_table(R)], "요청 조건 확인"),
            {"type": "paragraphs", "items": market["market_ko"], "src": "14c"}, B.sector_bar(R, chosen),
            B.evidence_ref(R, sorted(set(news_ids) | set(market.get("evidence_ids_used", []))), "시장 분석·뷰에 인용된 뉴스·공시 근거") if (news_ids or market.get("evidence_ids_used")) else None)},
        {"id": "companies", "title_ko": "기업별 투자 근거", "blocks": nz(
            {"type": "paragraphs", "items": narr["selection_ko"], "src": "14b"}, B.funnel(R), inf,
            {"type": "callout", "tone": "info", "title_ko": "선정 지표", "text_ko": _metric_note(metric)},
            B.companies(R, chosen), *_group([B.excluded_table(R), B.diff_table(R)], "제외된 종목과 재선정 차이" if R["selection"].get("backtest_reselected") is not False
                                            else "제외된 종목과 백테스트 목록"))},
        {"id": "construction", "title_ko": "포트폴리오 구성과 운용", "blocks": nz(
            {"type": "paragraphs", "items": narr["construction_ko"], "src": "14b"}, B.weights_compare(R), B.scenario_cards(R),
            B.delta_bar(R, bl_for_bar) if bl_for_bar else None, B.allocation_table(R, chosen),
            *([{"type": "paragraphs", "items": interp.get("news_ko") or [], "src": "14a"}] if interp.get("news_ko") else []),
            wf_tl, *wf_notes,
            *_group([*([{"type": "paragraphs", "items": narr.get("forward_ko") or [], "src": "14b"}] if narr.get("forward_ko") else []), *fwd], "분석 기준일의 현재 구성", open_=True))},
        {"id": "performance", "title_ko": "과거 성과와 해석", "blocks": nz(
            B.assumptions_callout(R),
            {"type": "line", "title_ko": "누적 수익률 (시작 = 100)", "dataset": "index", "series_ids": all_ids, "default_on": default_on, "y_format": "index"},
            {"type": "paragraphs", "items": interp["performance_ko"], "src": "14a"},
            {"type": "line", "title_ko": "평가금액과 투입 원금 (USD)", "dataset": "value_usd", "series_ids": [chosen, bt["benchmark"]["id"], "net_invested"], "default_on": [chosen, bt["benchmark"]["id"], "net_invested"], "y_format": "usd"},
            {"type": "area", "title_ko": "고점 대비 낙폭", "dataset": "drawdown", "series_ids": default_on, "default_on": default_on, "y_format": "pct"},
            B.comparison_table(R), *_group([B.yearly_table(R, chosen), B.monthly_table(R, chosen)], "연도별·월별 수익률"), B.contribution_bar(R, chosen),
            *_group([*([v_tab, {"type": "paragraphs", "items": interp["view_review_ko"], "src": "14a"}] if v_tab and interp.get("view_review_ko") else []),
                     {"type": "paragraphs", "items": interp["validation_ko"], "src": "14a"}, t1, t2, mn, alt], "검증 상세", open_=True))},
        {"id": "assumptions", "title_ko": "판단의 전제와 재검토 조건", "blocks": nz(
            {"type": "paragraphs", "items": narr["assumptions_ko"] + narr["reconsideration_ko"], "src": "14b"}, B.data_quality_table(R), B.notices_table(R),
            {"type": "cards", "title_ko": "다음에 검토할 수 있는 선택지", "src": "14a", "items": [{"title_ko": f"선택지 {i + 1}", "text_ko": s, "meta": []} for i, s in enumerate(interp["next_actions_ko"])]},
            {"type": "cards", "title_ko": "확인한 한계", "items": [{"title_ko": f"한계 {i + 1}", "text_ko": s, "meta": []} for i, s in enumerate(B.limitations(R))]})},
        {"id": "references", "title_ko": "참고자료와 분석 조건", "blocks": nz(
            *_group([B.sources_table(R), B.parameters_table(R), B.execution_table(R, step_summaries, usage)], "자료 출처·계산 조건·실행 기록"),
            {"type": "glossary", "items": narr["glossary"]},
            B.evidence_ref(R, None, "근거 색인 (뉴스·공시·재무 지표·계산값)"))},
    ]  # fmt: skip
    idx = R["evidence_index"]
    used = cited_ids(sections, idx)
    evidence = [{"id": k, "kind": v["kind"], "title": v.get("title", ""), "source": v.get("source", ""), "url": v.get("url"), "published_at": v.get("published_at"),
                 "data_as_of": v.get("data_as_of"), "tickers": v.get("tickers", []), "value": v.get("value"), "unit": v.get("unit"), "language": v.get("language"),
                 **({"event_type": v.get("event_type"), "event_label_ko": v.get("event_label_ko"), "form": v.get("form"), "items": v.get("items"),
                     "filed_at": v.get("filed_at"), "available_on": v.get("available_on")} if v["kind"] == "disclosure" else {})}
                for k, v in ((k, idx[k]) for k in used)]  # fmt: skip
    by_kind: dict[str, int] = {}
    for v in idx.values():
        by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1
    dates_s, series_s, sampling = B.sample_series(dates, series, max_points=settings.report.max_series_points, pin_id=chosen)
    datasets = {"dates": dates_s, "series": series_s, **({"sampling": sampling} if sampling else {})}
    execution = [{"step": k, "summary": v} for k, v in (step_summaries or {}).items()]
    summary = B.build_summary(R, chosen, interp, narr)
    doc = ReportDoc(request_id=R["request_id"], run_id=R["run_id"], generated_at=now_iso(), source="13_results", header=header, kpis=kp,
                    nav=[{"id": s["id"], "title_ko": s["title_ko"]} for s in sections], sections=sections, datasets=datasets,
                    assessment=interp["assessment"], evidence=evidence, execution=execution, tracking={"eligible": True, "reason_ko": None},
                    sources=R["sources"], parameters=R["parameters"], warnings=[], notices=list(R.get("notices") or []),
                    doc_version=2, summary=summary, evidence_summary={"total": len(idx), "cited": len(used), "by_kind": by_kind})  # fmt: skip
    return doc.model_dump(mode="json")


def present_doc(doc: dict[str, Any], R: dict[str, Any] | None = None) -> dict[str, Any]:
    """저장된 문서를 화면용으로 (읽기 시 정규화). v2 는 그대로. v1(라운드 3 이전) 은 근거 색인을 인용된 것만 남기고 evidence 블록을 evidence_ref 로 바꾼다.

    R(13_results) 이 있으면 v1 에도 summary 를 보강한다. 저장 문서는 바꾸지 않는다.
    """
    if doc.get("doc_version", 1) >= 2:
        return doc
    out = json.loads(json.dumps(doc))
    idx = {e["id"]: e for e in out.get("evidence", [])}
    for sec in out["sections"]:
        blocks = []
        for b in sec["blocks"]:
            if b["type"] == "evidence":
                ids = [it["id"] for it in b.get("items", [])]
                full = len(ids) >= max(1, len(idx)) - 2  # 색인 전체를 복사한 블록(참고자료)
                blocks.append({"type": "evidence_ref", "title_ko": b.get("title_ko", "근거"), "ids": None if full else ids, "count": len(ids),
                               "kinds": {k: sum(1 for i in ids if idx.get(i, {}).get("kind") == k) for k in {idx.get(i, {}).get("kind") for i in ids if i in idx}}})  # fmt: skip
            else:
                blocks.append(b)
        sec["blocks"] = blocks
    used = cited_ids(out["sections"], idx)
    by_kind: dict[str, int] = {}
    for v in idx.values():
        by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1
    out["evidence"] = [idx[k] for k in used]
    out["evidence_summary"] = {"total": len(idx), "cited": len(used), "by_kind": by_kind}
    out["presented_from_version"] = 1
    out["doc_version"] = 1  # 저장 문서의 형식은 그대로 1 (화면은 이 값으로 변환 여부를 안다)
    if R is not None and out.get("summary") is None:
        try:
            chosen = out["header"].get("chosen_portfolio_id") or B.chosen_portfolio_id(R)[0]
            next_actions = next((b for s_ in out["sections"] for b in s_["blocks"] if b["type"] == "cards" and b.get("title_ko", "").startswith("다음에 검토")), None)
            interp_like = {"next_actions_ko": [it["text_ko"] for it in (next_actions or {}).get("items", [])]}
            narr_like = {"overview_ko": next((b["items"] for s_ in out["sections"] if s_["id"] == "verdict" for b in s_["blocks"] if b["type"] == "paragraphs"), [])}
            out["summary"] = B.build_summary(R, chosen, interp_like, narr_like)
        except Exception:  # noqa: BLE001 — 옛 문서 보강은 실패해도 문서 자체는 보여 준다
            out["summary"] = None
    return out


def _metric_note(metric: str) -> str:
    # 재무 지표는 기준일 전 거래일 자료(정보 마감 t−1)이고, 자격선(정책 결정 3: PER 0~50배 · ROE 0 초과 · 배당 0 초과~30%) 밖은 뽑지 않는다 — 예전 문구에는 둘 다 없었다
    return {"return_12m_1m": "모멘텀은 최근 12개월 주가 수익률에서 가장 최근 1개월을 뺀 값입니다. 단기 반전 효과를 피하려 최근 1개월을 빼며, 값이 높은 순서로 뽑습니다.",
            "vol_60d": "저변동성은 최근 60거래일 일수익률의 연환산 표준편차입니다. 값이 낮은 순서로 뽑습니다.",
            "pe_ttm": "저PER은 기준일 전 거래일 종가를 그날까지 공시된 최근 4분기 주당순이익으로 나눈 값입니다. 적자 기업과 PER 50배 초과 종목은 제외하고 낮은 순서로 뽑습니다.",
            "roe_ttm": "퀄리티(ROE)는 최근 4분기 순이익을 평균 자본으로 나눈 자기자본이익률입니다. ROE 가 0 이하이거나 1,000% 를 넘는(자기자본이 0 근처라 생긴 왜곡) 종목은 제외하고 높은 순서로 뽑습니다.",
            "dividend_yield_ttm": "고배당은 최근 1년 주당배당금을 기준일 전 거래일 종가로 나눈 값입니다. 배당이 없거나 30% 를 넘는(자료 오류로 보는) 종목은 제외하고 높은 순서로 뽑습니다."}.get(metric, metric)  # fmt: skip


def _retry_feedback(errors: list[str]) -> dict[str, str]:
    return {"role": "user", "content": ("직전 리포트 문단 검증에서 다음 문제가 있었습니다. 고쳐서 같은 스키마로 다시 출력하세요.\n"
                                       "- banned phrase 는 그 단어를 문장에서 빼고 다른 말로 바꾸라는 뜻입니다 (예: '보장' → '장담할 수 없습니다', '달라질 수 있습니다').\n"
                                       "- unknown citation 은 근거 목록에 없는 인용 ID 를 썼다는 뜻입니다. 목록에 있는 ID 만 쓰거나 인용을 빼세요.\n"
                                       "- missing section 은 일곱 부분 중 빠진 것이 있다는 뜻입니다.\n문제 목록:\n- " + "\n- ".join(errors[:12]))}


def _both(a, b, parallel: bool):
    """두 LLM 호출을 동시에 (14a ∥ 14c). 둘 다 서로의 결과를 쓰지 않는다."""
    if not parallel:
        return a(), b()
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="mfs-report") as pool:
        fa, fb = pool.submit(a), pool.submit(b)
        return fa.result(), fb.result()


def _usage(llm: Any) -> dict[str, Any] | None:
    """리포트 작성(14a·14b·14c)까지 포함한 이 실행의 LLM 사용량 (13 결과 묶음의 사용량은 리포트 호출 전이라 적게 나왔다)."""
    try:
        return llm.usage_summary()
    except Exception:  # noqa: BLE001 — 사용량을 못 얻으면 결과 묶음 값으로
        return None


def generate_report(R: dict[str, Any], llm: LlmClient, settings: AnalysisSettings, *, step_summaries: dict[str, str] | None = None) -> tuple[dict[str, Any], list[str]]:
    """LLM 세 번(14a ∥ 14c → 14b) → 문서 → 검증. 검증 오류가 있으면 오류를 낸 호출만 피드백으로 1회 다시 받고, 그래도 실패면 ReportCheckError."""
    chosen, _ = B.chosen_portfolio_id(R)
    parallel = settings.executor.parallel_report_calls
    interp, market = _both(lambda: call_interpret(R, chosen, llm), lambda: call_market(R, llm), parallel)
    narr = call_narrate(R, chosen, interp, llm)
    doc = build_doc(R, interp=interp, narr=narr, market=market, step_summaries=step_summaries, settings=settings, usage=_usage(llm))
    res = check(doc, R, settings)
    if res.errors:
        srcs = res.sources_to_retry() or {"14b", "14c"}  # 어디서 났는지 모르면 예전처럼 서술 둘을 다시
        by = res.errors_by_src
        no_matched = not any(x.get("kind") == "matched" for x in R["backtest"]["portfolios"])

        def _errs(*keys: str) -> list[str]:
            got = [e for k in keys for e in by.get(k, [])]
            return got or res.errors

        def _redo_interp():
            system, user = load_prompts("14a_interpret", facts_json=json.dumps(facts_for_interpret(R, chosen), ensure_ascii=False, indent=1, default=str))
            a = llm.complete_json("14a_interpret", [*messages_from_prompts(system, user), {"role": "assistant", "content": json.dumps(interp, ensure_ascii=False)}, _retry_feedback(_errs("14a"))])
            for k, v in [("view_review_ko", []), ("news_ko", []), ("assessment", interp.get("assessment"))]:
                a.setdefault(k, v)
            if no_matched:
                _drop_matched_suggestions(a, ("performance_ko", "risk_fit_ko", "validation_ko", "next_actions_ko"))
            return a

        def _redo_market():
            system, user = load_prompts("14c_market", facts_json=json.dumps(facts_for_market(R), ensure_ascii=False, indent=1, default=str))
            return llm.complete_json("14c_market", [*messages_from_prompts(system, user), {"role": "assistant", "content": json.dumps(market, ensure_ascii=False)}, _retry_feedback(_errs("14c", "doc"))],
                                     validator=lambda a: _need(a, "market_ko", 1))  # fmt: skip

        if "14a" in srcs and "14c" in srcs:
            interp, market = _both(_redo_interp, _redo_market, parallel)
        elif "14a" in srcs:
            interp = _redo_interp()
        elif "14c" in srcs:
            market = _redo_market()
        if "14b" in srcs or "14a" in srcs:  # 서술(14b)은 해석(14a)을 입력으로 쓰므로 14a 가 바뀌면 함께
            system, user = load_prompts("14b_narrate", facts_json=json.dumps(facts_for_narrate(R, chosen, interp), ensure_ascii=False, indent=1, default=str),
                                        interpretation_json=json.dumps(interp, ensure_ascii=False, indent=1))  # fmt: skip
            narr = llm.complete_json("14b_narrate", [*messages_from_prompts(system, user), {"role": "assistant", "content": json.dumps(narr, ensure_ascii=False)}, _retry_feedback(_errs("14b", "doc"))])
            narr.setdefault("forward_ko", [])
            if no_matched:
                _drop_matched_suggestions(narr, ("overview_ko", "reconsideration_ko"))
        doc = build_doc(R, interp=interp, narr=narr, market=market, step_summaries=step_summaries, settings=settings, usage=_usage(llm))
        res = check(doc, R, settings)
        if res.errors:
            raise ReportCheckError("리포트 검증 실패: " + "; ".join(res.errors[:5]), details={"errors": res.errors, "warnings": res.warnings, "by_src": res.errors_by_src})
    doc["warnings"] = [w for w in res.warnings if "development term" not in w]  # 숫자 대조 메모만 문서에 (개발 용어 메모는 실행 기록 파일로)
    return doc, res.warnings

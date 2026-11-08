"""LLM 심사용 자료 묶음.

- rule  (항목 5 전략 구현 정확성): 시나리오마다 '자연어 아이디어' 와 '실제로 실행된 규칙'(해석·선정 기준·선정 종목·비중·리밸런싱·대화 답).
- report (항목 3 투자 논리·근거): 리포트마다 결론·핵심 수치·본문 문단·인용한 근거의 제목과 날짜.

  PYTHONPATH=. python docs/mvp/evaluation/scripts/packets.py rule <runs.txt> <out_dir> <batch_size>
  PYTHONPATH=. python docs/mvp/evaluation/scripts/packets.py report <runs.txt> <out_dir> <batch_size>
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

OUT = Path(os.environ.get("EVAL_OUT") or "output")  # 리포트만 다시 만든 폴더를 볼 때 EVAL_OUT
RUNS = Path("docs/mvp/scenario_qa/runs")
CITE = re.compile(r"\[((?:ev|dc|fin|calc|px|news)[^\]\s]*)\]")


FILT_KO = {"min_avg_daily_volume_usd": "일평균 거래대금 하한 미달", "min_market_cap_usd": "시가총액 하한 미달", "keyword_weak": "테마 키워드가 약하게만 일치",
           "market_cap_missing": "시가총액 자료 없음(하한이 있으면 제외하는 정책)", "exclude_tickers": "제외 종목", "exclude_sectors": "제외 섹터",
           "exclude_theme": "제외 테마", "asset_types": "자산 유형 제외", "insufficient_price_history": "가격 이력 부족", "share_class_duplicate": "같은 회사의 다른 주식",
           "candidate_cap": "후보 상한 밖(테마 일치 규칙·거래대금 순)",
           "candidate_cap_metric": "넓은 테마라 선정 지표 순위 상위 120개만 다음 단계로 넘김(최종 선정도 같은 지표의 상위 종목에서 고름)"}
REJ_KO = {"sector_preference": "섹터 선호(순위가 더 낮은 다른 섹터 종목에 자리를 내줌)", "sector_preference_lower": "섹터 선호(같은 섹터 종목이 많아 다른 섹터 종목을 먼저 뽑음)",
          "metric_missing": "지표 자료 없음", "no_dividend": "최근 12개월 배당 확인 안 됨"}


def rej_ko(reason: str) -> str:
    from backend.analysis.common.warnings import _out_of_range_ko, guard_reason_ko

    if reason.startswith("metric_out_of_range("):  # 자격선·중앙값 기준선 밖: 원문 소수 대신 한국어 (예: '배당수익률 0.12%로 같은 유니버스 중앙값 1.97% 미만')
        return "자격선 밖: " + _out_of_range_ko(reason[len("metric_out_of_range("):].rstrip(")"))
    return REJ_KO.get(reason) or guard_reason_ko(reason) or reason


def j(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pct(x, d=1):
    return "-" if x is None else f"{x * 100:.{d}f}%"


def rule_packet(name: str, rid: str, rec: dict) -> str:
    scen = j(Path(rec["scenario_file"]))
    d = OUT / rid
    req, it, sel, spec, tg, val = (j(d / f"{n}.json") or {} for n in ("01_request", "02_intent", "05_selection", "07_backtest_spec", "10_target_portfolios", "12_validation"))
    interp = it.get("interpretation") or {}
    c = req.get("constraints") or {}
    sp = req.get("strategy_preference") or {}
    r = req.get("risk") or {}
    lines = [f"### {name}", "", f"아이디어(사용자 원문): {scen['natural_language']['idea']}", ""]
    lines.append("프로필·요청의 정형 조건(확정 후): " + json.dumps({
        "시장": c.get("universe"), "목표 종목 수": c.get("num_holdings"), "종목당 상한": c.get("max_weight_per_stock"), "섹터당 상한": c.get("max_weight_per_sector"),
        "최소 현금": c.get("min_cash_ratio"), "필수 포함": c.get("must_include_tickers"), "제외 종목": c.get("exclude_tickers"), "제외 섹터": c.get("exclude_sectors"),
        "제외 테마": c.get("exclude_themes"), "리밸런싱": c.get("rebalance"), "선정 기준(템플릿)": sp.get("template"), "기준 비중": sp.get("baseline_weighting"),
        "뉴스 반영": sp.get("use_news_tilt"), "위험 성향": r.get("risk_tolerance"), "허용 낙폭": r.get("max_drawdown_tolerance"), "목표 수익": r.get("target_annual_return"),
        "투자기간(년)": (req.get("horizon") or {}).get("target_years"),
        "초기 투자금": f"{(req.get('capital') or {}).get('initial_amount')} {(req.get('capital') or {}).get('currency')}",
        "월 적립": f"{(req.get('capital') or {}).get('monthly_contribution')} {(req.get('capital') or {}).get('currency')}"}, ensure_ascii=False))  # 처음 심사 자료에 투자금·적립이 빠져 E5 를 다시 매겼다 (2026-11 평가)
    lines.append(f"시험 정규화(서비스 입력 범위 밖이라 시험 도구가 바꾼 값): {rec.get('normalized') or '없음'}")
    qa = rec.get("qa") or []
    if qa:
        lines.append("대화 질문과 답(시험 도구가 늘 첫 보기를 고름):")
        for q in qa:
            lines.append(f"- [{q.get('field')}] {str(q.get('question_ko'))[:220]} → 답: {str(q.get('answer'))[:160]}")
    lines.append("")
    lines.append(f"시스템의 해석: {interp.get('summary_ko')}")
    for t in interp.get("themes") or []:
        lines.append(f"- 테마 '{t.get('label_ko')}': 경계 「{t.get('description_ko')}」 GICS {t.get('gics_codes', [])}, 키워드 {t.get('keywords', [])}")
    rules = it.get("exclude_theme_rules") or []
    if rules:
        lines.append("- 제외 테마 규칙: " + "; ".join(f"{x.get('theme')}(GICS {x.get('gics_codes', [])[:3]}, 키워드 {x.get('keywords', [])[:4]})" for x in rules))
    sm = sel.get("summary") or {}
    scr = it.get("screen") or {}
    # 실행한 코드의 규칙대로 적는다: 2026-11-08 이후 실행(설정에 style_floor_median 이 있음)은 이익률을 유니버스 중앙값과 비교하고,
    # 고배당·저PER 중앙값 기준선과 미국 법인 조건이 있다 (예전 설명 '테마 후보 중 위쪽 절반' 이 새 실행에도 그대로 나가 심사자가 규칙과 결과가 다르다고 봤다)
    new_rules = "style_floor_median" in ((((j(d / "run_meta.json") or {}).get("settings") or {}).get("selection")) or {})
    floor = ({"dividend_yield_ttm": "배당수익률이 같은 유니버스(같은 시장) 종목의 중앙값 이상만(테마 후보가 모두 밖이면 후보 중 배당수익률이 높은 절반)",
              "pe_ttm": "PER 이 같은 유니버스(같은 시장) 종목의 중앙값 이하만(테마 후보가 모두 밖이면 후보 중 PER 이 낮은 절반)"}.get(sm.get("metric")) if new_rules else None)
    guards = [g for g in ((f"최근 {scr['dividend_growth_years']}년 주당배당 해마다 인상(한 해만 쉬어도 됨)·삭감 없음" if scr.get("dividend_require_growth", True) is not False
                           else f"최근 {scr['dividend_growth_years']}년 주당배당 삭감 없음") if scr.get("dividend_growth_years") else None,
                          f"부채비율 {scr['max_debt_to_equity']:.0%} 이하(금융 제외)" if scr.get("max_debt_to_equity") else None,
                          f"선정일 시가총액 {scr['mega_cap_rank']}위 안" if scr.get("mega_cap_rank") else None,
                          (("영업이익률(최근 4개 분기)이 같은 유니버스 비금융 종목의 중앙값 이상(금융 제외)" if new_rules else "영업이익률(최근 4개 분기) 테마 후보 중 위쪽 절반(금융 제외)")
                           if scr.get("high_margin") else None),
                          "법인 소재지가 미국인 기업만(회사 소개의 정식 이름이 plc·N.V.·Ltd 같은 해외 법인 형태면 제외)" if scr.get("us_hq_only") else None, floor) if g]
    lines.append(f"실행된 선정 규칙: 지표 {sm.get('metric')} ({sm.get('direction')}), 보조 조건 {guards or '없음'}, 테마 통과 {sm.get('n_tagged')}개 중 {sm.get('n_selected')}개 선정, 섹터 분포 {sm.get('sector_counts')}")
    cand = j(d / "03_candidates.json") or {}
    by: dict = {}
    for f in cand.get("filtered_out") or []:
        by.setdefault(str(f.get("reason")).split("(")[0], []).append(f["ticker"])
    if by:
        lines.append("후보 단계에서 빠진 종목(사유별): " + "; ".join(f"{FILT_KO.get(k, k)} {len(v)}개 {v[:8]}" for k, v in by.items()))
    tag = j(d / "04_tagging.json") or {}
    ex = tag.get("excluded_by_theme") or []
    if ex:
        lines.append("제외 테마로 뺀 종목(분류 판정): " + "; ".join(f"{x['ticker']}({x.get('excluded_theme')})" for x in ex[:12]))
    off = [x["ticker"] for x in tag.get("tagged") or [] if x["ticker"] not in set(tag.get("passed_tickers") or [])]
    if off:
        lines.append(f"테마에 해당하지 않는다고 판정한 후보 {len(off)}개(일부): {off[:15]}")
    rep_doc = j(d / "14_report.json") or {}
    nts = [n.get("message_ko") for n in rep_doc.get("notices") or [] if isinstance(n, dict) and n.get("message_ko")]
    if nts:
        lines.append("사용자에게 보인 공지: " + " / ".join(nts[:14]))
    lines.append("선정 종목(분석 기준일): " + "; ".join(
        f"{s['ticker']} {s.get('name', '')}({s.get('sector', '')}{', 필수' if s.get('forced') else ''}, 지표 {s.get('metric_value') if s.get('metric_value') is None else round(float(s['metric_value']), 4)})"
        for s in sel.get("selected", [])))
    rej = [x for x in sel.get("rejected", []) if x.get("reason") != "rank_beyond_n"][:16]
    if rej:
        lines.append("순위 밖이 아닌 이유로 빠진 종목(일부): " + "; ".join(f"{x['ticker']}({rej_ko(str(x.get('reason')))})" for x in rej))
    rr = spec.get("rebalance_rule") or {}
    eng = (j(d / "11_backtest_results.json") or {}).get("engine") or {}
    lines.append(f"백테스트: {get_period(spec)} · 리밸런싱 '{rr.get('description_ko')}' · 적립 {eng.get('n_contributions')}회 × {eng.get('contribution_usd')} USD · 시작일 종목 {len((spec.get('selection') or {}).get('tickers', []))}개 ({(spec.get('selection') or {}).get('source')})")
    lines.append(f"기준 비중 방식(실행): {(tg.get('baseline') or {}).get('id')} · 비중 규칙 후보 {[p['id'] for p in tg.get('templates', [])]} · 뉴스 반영 구성 {len(tg.get('portfolios', []))}개")
    rec_ = (val.get("recommended") or {})
    lines.append(f"추천: {((rec_.get('verdict') or {}).get('label_ko'))} → {rec_.get('id')}")
    return "\n".join(lines)


def get_period(spec: dict) -> str:
    p = spec.get("period") or {}
    return f"{p.get('start')}~{p.get('end')} ({p.get('trading_days')}거래일)"


SKIP_TABLES = ("월별 수익률", "자료 출처", "계산 조건", "실행 기록", "가격 자료 품질", "배분 금액", "요청 내용")


def fmt(v, f):
    if isinstance(v, (int, float)) and f in ("pct", "pct1", "pct2"):
        return f"{v * 100:.1f}%"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def table_text(b: dict) -> str:
    cols = b.get("columns") or []
    rows = b.get("rows") or []
    head = " | ".join(c.get("label_ko", c.get("key")) for c in cols)
    body = ["   " + " | ".join(fmt(r.get(c["key"]), c.get("format")) for c in cols) for r in rows[:20]]
    more = [f"   (행 {len(rows) - 20}개 더)"] if len(rows) > 20 else []
    note = [f"   주: {b['note_ko']}"] if b.get("note_ko") else []
    return "\n".join([f"- (표) {b.get('title_ko', '')}: {head}", *body, *more, *note])


def report_packet(name: str, rid: str, rec: dict) -> str:
    d = OUT / rid
    doc = j(d / "14_report.json") or {}
    R = j(d / "13_results.json") or {}
    scen = j(Path(rec["scenario_file"])) or {}
    idx = R.get("evidence_index") or {}
    sm = doc.get("summary") or {}
    vd = sm.get("verdict") or {}
    lines = [f"### {name}", "", f"사용자 아이디어: {(scen.get('natural_language') or {}).get('idea')}", ""]
    req = R.get("request") or {}
    lines.append("사용자 조건: " + json.dumps({"위험 성향": (req.get("risk") or {}).get("risk_tolerance"), "허용 낙폭": (req.get("risk") or {}).get("max_drawdown_tolerance"),
                                          "목표 수익": (req.get("risk") or {}).get("target_annual_return"), "비교지수": (req.get("risk") or {}).get("benchmark"),
                                          "투자기간": (req.get("horizon") or {}).get("target_years"), "투자 경험": (req.get("profile") or {}).get("investment_experience")}, ensure_ascii=False))
    lines.append(f"결론 라벨: {vd.get('label_ko')}")
    lines.append(f"결론 문장: {vd.get('headline_ko')}")
    for k in ("reasons_ko", "cautions_ko", "notices_ko"):
        if vd.get(k):
            lines.append(f"{k}: " + " / ".join(str(x) for x in vd[k]))
    kp = sm.get("kpis") or []
    if kp:
        lines.append("대시보드 KPI: " + "; ".join(f"{x.get('label_ko')} {x.get('value_ko') or x.get('value')}" for x in kp if isinstance(x, dict)))
    # 핵심 수치표 (선택안·비교지수)
    bt = R.get("backtest") or {}
    val = R.get("validation") or {}
    lines.append(f"선택안 id: {val.get('chosen_id')} · 추천 사유(코드): {(val.get('recommended') or {}).get('reason_ko')}")
    lines.append("")
    lines.append("본문:")
    cited = []
    for s in doc.get("sections", []):
        lines.append(f"## [{s.get('id')}] {s.get('title_ko', '')}")
        for b in s.get("blocks", []):
            if b["type"] == "paragraphs":
                for t in b["items"]:
                    lines.append(f"- {t}")
                    cited += CITE.findall(t)
            elif b["type"] == "companies":
                for it in b["items"]:
                    rat = " ".join(it.get("rationale_ko", []))
                    where = "지금 구성" if it.get("in_selection_now") else ("백테스트 시작일 종목(지금 구성에는 없음)" if it.get("in_backtest") else "참고")
                    if not rat and not it.get("in_selection_now"):
                        rat = "(지금 구성에 없는 백테스트 종목이라 근거 문단을 만들지 않음 — 정상)"
                    lines.append(f"- (기업 · {where}) {it.get('ticker')} {it.get('name', '')}: {rat}")
                    cited += CITE.findall(rat)
            elif b["type"] == "cards":
                for it in b["items"]:
                    tx = str(it.get("text_ko", ""))
                    lines.append(f"- (카드) {it.get('title_ko', '')}: {tx}")
                    cited += CITE.findall(tx)
            elif b["type"] == "callout":
                lines.append(f"- (안내 상자) {b.get('title_ko', '')}: {b.get('text_ko', '')}")
            elif b["type"] == "table" and not any(k in str(b.get("title_ko")) for k in SKIP_TABLES):
                lines.append(table_text(b))
            elif b["type"] in ("donut", "bar") and b.get("items"):
                lines.append(f"- (그림) {b.get('title_ko', '')}: " + ", ".join(f"{x.get('label')} {fmt(x.get('value'), b.get('format') or 'pct1')}" for x in b["items"]))
    uniq = list(dict.fromkeys(cited))
    lines.append("")
    lines.append(f"인용된 근거 {len(uniq)}개 (색인 내용 전부):")
    for cid in uniq:
        e = idx.get(cid)
        if not e:
            lines.append(f"- {cid}: (색인에 없음)")
            continue
        when = e.get("published_at") or e.get("available_on") or e.get("data_as_of") or ""
        lines.append(f"- {cid} [{e.get('kind')}] {str(when)[:10]} {str(e.get('title') or e.get('label_ko') or e.get('text') or e.get('value'))[:240]}")
    lines.append(f"분석 기준일: {(req.get('derived') or {}).get('as_of')}")
    return "\n".join(lines)


def main() -> int:
    kind, runs_txt, out_dir, bs = sys.argv[1], sys.argv[2], Path(sys.argv[3]), int(sys.argv[4])
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs = [ln.split() for ln in Path(runs_txt).read_text().splitlines() if ln.strip()]
    rec_dir = Path(sys.argv[5]) if len(sys.argv) > 5 else RUNS
    texts = []
    for name, rid in pairs:
        rec = j(rec_dir / f"{name}.json")
        texts.append(rule_packet(name, rid, rec) if kind == "rule" else report_packet(name, rid, rec))
    for i in range(0, len(texts), bs):
        p = out_dir / f"{kind}_batch_{i // bs + 1:02d}.md"
        p.write_text("\n\n---\n\n".join(texts[i : i + bs]), encoding="utf-8")
        print(p, len(p.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

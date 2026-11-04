"""시나리오 실행 점검 (2026-11 시나리오 QA): 실행 하나를 사람이 읽기 쉬운 요약 + 모듈 넘김 규칙 검사로 정리한다.

  python -m backend.analysis.eval.audit --from docs/mvp/scenario_qa/runs --names scenario_000,scenario_001

- 입력: run_scenarios 결과 JSON(질문·답·run_id) + 시나리오 파일 + 저장소의 요청 문서(점검 숫자) + output/<run_id>/01~14*.json.
- 출력: <out>/<이름>.md (요약 + 규칙 검사 ✅/❌). 규칙은 확정 요청(01_request) 기준이다 — 대화 답변이 시나리오 값을 바꿀 수 있으므로.
- 규칙 검사는 판독을 돕는 도구일 뿐이다. 리포트 문장은 사람이 직접 읽는다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from backend.analysis.paths import REPO_ROOT, run_dir, store_dir

ELIGIBLE = {"pe_ttm": (0.0, 50.0), "roe_ttm": (0.0, 10.0), "dividend_yield_ttm": (0.0, 0.30)}  # 정책 결정 3 + 자료 오류 거름 (하한은 초과, 상한은 이하)
SHARE_CLASS = [{"GOOG", "GOOGL"}, {"FOX", "FOXA"}, {"NWS", "NWSA"}, {"BRK-A", "BRK-B"}]
TOL = 1e-6


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 없거나 깨진 파일은 None (요약에 '없음' 으로 표시)
        return None


def _pct(x: Any, d: int = 1) -> str:
    try:
        return f"{float(x) * 100:.{d}f}%"
    except (TypeError, ValueError):
        return "-"


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


class Audit:
    def __init__(self, name: str, res: dict[str, Any]) -> None:
        self.name, self.res = name, res
        self.lines: list[str] = []
        self.checks: list[tuple[str, bool, str]] = []
        self.o: dict[str, Any] = {}
        rid = res.get("run_id")
        if rid:
            d = run_dir(rid)
            for f in sorted(d.glob("*.json")) if d.exists() else []:
                self.o[f.stem] = _load(f)
        sf = res.get("scenario_file")
        self.scenario = _load(Path(sf)) if sf else None
        self.req_doc = _load(store_dir() / "requests" / f"{res.get('request_id')}.json") if res.get("request_id") else None

    # ───────── helpers ─────────
    def w(self, s: str = "") -> None:
        self.lines.append(s)

    def chk(self, cid: str, ok: bool, detail: str = "") -> None:
        self.checks.append((cid, bool(ok), detail))

    @property
    def req(self) -> dict[str, Any]:
        return self.o.get("01_request") or (self.req_doc or {}).get("effective_request") or {}

    def sectors(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for key in ("05_selection", "07_selection_bt"):
            for s in (self.o.get(key) or {}).get("selected", []):
                out[s["ticker"]] = s.get("sector") or ""
        for r in ((self.o.get("07_backtest_spec") or {}).get("selection") or {}).get("table", []):
            out.setdefault(r["ticker"], r.get("sector") or "")
        return out

    # ───────── sections ─────────
    def run(self) -> str:
        r = self.res
        self.w(f"# 점검 {self.name}")
        self.w()
        self.w(f"- 상태: **{r.get('status')}** · run `{r.get('run_id')}` · 요청 `{r.get('request_id')}` · 대화 {r.get('dialog_seconds')}s · 실행 {r.get('run_seconds')}s")
        if r.get("error") or r.get("report_error"):
            self.w(f"- 오류: `{json.dumps(r.get('error') or r.get('report_error'), ensure_ascii=False)[:600]}`")
        u = r.get("llm_usage") or {}
        self.w(f"- LLM: 실행 {u.get('calls', '-')}회 ${u.get('cost_usd', '-')} · 대화 ${r.get('dialog_cost_usd', '-')}")
        self.chk("실행 완료", r.get("status") in ("success", "partial"), str(r.get("status")))
        for name, fn in [("조건", self.conditions), ("대화", self.dialog), ("선정", self.selection), ("구성", self.construction),
                         ("백테스트", self.backtest), ("검증·추천", self.validation), ("리포트", self.report)]:  # fmt: skip
            try:
                fn()
            except Exception as e:  # noqa: BLE001 — 한 구역이 깨져도 나머지는 보여 준다
                self.w(f"\n## {name}\n\n(요약 실패: {type(e).__name__}: {e})")
                self.chk(f"{name} 요약", False, f"{type(e).__name__}: {e}")
        out = [*self.lines, "", "## 규칙 검사", ""]
        n_bad = sum(1 for _, ok, _ in self.checks if not ok)
        out.append(f"실패 {n_bad} / {len(self.checks)}")
        out.append("")
        for cid, ok, det in self.checks:
            out.append(f"- {'✅' if ok else '❌'} {cid}" + (f" — {det}" if det else ""))
        return "\n".join(out) + "\n"

    def conditions(self) -> None:
        sc, rq = self.scenario or {}, self.req
        self.w("\n## 조건 (시나리오 → 확정 요청)\n")
        self.w(f"아이디어: {((sc.get('natural_language') or {}).get('idea') or '')}")
        for n in self.res.get("normalized") or []:
            self.w(f"- 시험용 정규화: {n}")
        if self.res.get("replay_of"):
            self.w(f"- 재실행: {self.res['replay_of']} 의 확정 요청을 대화 없이 다시 돌림")
        self.w()
        keys = [("constraints", "num_holdings"), ("constraints", "max_weight_per_stock"), ("constraints", "max_weight_per_sector"), ("constraints", "min_cash_ratio"),
                ("constraints", "universe"), ("constraints", "exclude_tickers"), ("constraints", "exclude_sectors"), ("constraints", "exclude_themes"),
                ("constraints", "must_include_tickers"), ("constraints", "rebalance"), ("constraints", "min_market_cap_usd"), ("constraints", "min_avg_daily_volume_usd"),
                ("strategy_preference", "template"), ("strategy_preference", "baseline_weighting"), ("strategy_preference", "use_news_tilt"),
                ("risk", "risk_tolerance"), ("risk", "max_drawdown_tolerance"), ("risk", "loss_reaction"), ("risk", "target_annual_return"), ("risk", "benchmark"),
                ("horizon", "start_date"), ("horizon", "target_years"), ("horizon", "backtest_years"), ("profile", "investment_experience"), ("capital", "currency")]  # fmt: skip
        self.w("| 항목 | 시나리오 | 확정 |")
        self.w("| --- | --- | --- |")
        for a, b in keys:
            v0, v1 = (sc.get(a) or {}).get(b), (rq.get(a) or {}).get(b)
            mark = "" if v0 == v1 or v0 is None else " **(바뀜)**"
            self.w(f"| {a}.{b} | {json.dumps(v0, ensure_ascii=False)} | {json.dumps(v1, ensure_ascii=False)}{mark} |")
        d = rq.get("derived") or {}
        self.w()
        self.w(f"파생: 기준일 {d.get('as_of')} · 백테스트 {d.get('backtest_start')}~{d.get('backtest_end')} · 환율 {d.get('fx_rate')} ({d.get('fx_date')}) · "
               f"시작 환율 {d.get('backtest_fx_rate')} ({d.get('backtest_fx_date')}) · 투자금 {d.get('initial_amount_usd')} USD")  # fmt: skip

    def dialog(self) -> None:
        self.w("\n## 대화 (질문 → 답)\n")
        qa = self.res.get("qa") or []
        if not qa:
            self.w("질문 없음")
        for q in qa:
            self.w(f"- Q{q.get('seq')} [{q.get('kind')}] `{q.get('field')}`: {q.get('question_ko')}")
            self.w(f"  - 보기: {' / '.join(q.get('options') or []) or '(자유 입력)'} → 답: **{q.get('answer')}**")
        pc = (self.req_doc or {}).get("precheck") or {}
        if pc:
            now, st = pc.get("as_of") or {}, pc.get("start") or {}
            self.w(f"- 실행 전 점검: 기준일 후보 {now.get('n_candidates')}·지표 {now.get('n_with_metric')} / 시작일 후보 {st.get('n_candidates')}·지표 {st.get('n_with_metric')}"
                   f" · short_now={pc.get('short_now')} short_at_start={pc.get('short_at_start')}")  # fmt: skip
        topics = [q.get("field") for q in qa]
        replay = bool(self.res.get("replay_of"))
        note = " (재실행: 대화는 처음 실행 것이라 판정 생략)" if replay else ""
        dup = ", ".join(t for t in topics if topics.count(t) > 1)
        self.chk("같은 항목 반복 질문 없음" + note, replay or len(topics) == len(set(topics)), dup)
        single = [f"Q{q.get('seq')} {q.get('field')}" for q in qa if len(q.get("options") or []) == 1]
        self.chk("보기가 하나뿐인 질문 없음" + note, replay or not single, ", ".join(single))

    def selection(self) -> None:
        o, rq = self.o, self.req
        cons = rq.get("constraints") or {}
        self.w("\n## 선정\n")
        it = o.get("02_intent") or {}
        th = (it.get("interpretation") or {}).get("themes") or []
        sc = it.get("screen") or {}
        self.w(f"- 의도: 테마 {[t.get('label_ko') for t in th]} · 선정 기준 {sc.get('template')}({sc.get('metric')}, {sc.get('direction')}) · "
               f"뉴스 {((it.get('news_tilt') or {}).get('enabled'))} · 제외 테마 규칙 {[r.get('theme') for r in (it.get('exclude_theme_rules') or [])]}")  # fmt: skip
        c3 = o.get("03_candidates") or {}
        fo = c3.get("filtered_out") or []
        reasons: dict[str, int] = {}
        for f in fo:
            k = str(f.get("reason", "")).split("(")[0]
            reasons[k] = reasons.get(k, 0) + 1
        self.w(f"- 03 후보 {len(c3.get('candidates') or [])}개, 제외 {len(fo)}개 {reasons}")
        kw_excl = [f"{f.get('ticker')}({f.get('reason')})" for f in fo if "keyword" in str(f.get("reason", "")) and "keyword_weak" not in str(f.get("reason", ""))]
        kw_weak = [f"{f.get('ticker')}({f.get('reason')})" for f in fo if "keyword_weak" in str(f.get("reason", ""))]
        if kw_excl:
            self.w(f"  - 제외 테마 키워드로 제외: {', '.join(kw_excl[:30])}")
        if kw_weak:
            self.w(f"  - 테마 키워드 약한 일치로 후보에서 뺌: {', '.join(kw_weak[:30])}")
        t4 = o.get("04_tagging") or {}
        self.w(f"- 04 테마 통과 {len(t4.get('passed_tickers') or [])}개")
        sel = o.get("05_selection") or {}
        rows = sel.get("selected") or []
        self.w(f"- 05 선정 {len(rows)}개 (요약 {json.dumps({k: (sel.get('summary') or {}).get(k) for k in ('metric', 'n_candidates', 'n_tagged', 'n_with_metric', 'n_target', 'weight_capacity')}, ensure_ascii=False)})")
        for s in rows:
            self.w(f"  - {s['ticker']} {s.get('name', '')} · {s.get('sector', '')} · {s.get('metric_name')} {s.get('metric_value')}" + (" · 필수" if s.get("forced") else ""))
        pref = [f"{x['ticker']}({x.get('metric_value')})" for x in sel.get("rejected") or [] if x.get("reason") == "sector_preference"]
        if pref:
            self.w(f"  - 섹터 선호로 빠진 상위 순위: {', '.join(pref)}")
        for wn in (sel.get("warnings") or [])[:8]:
            self.w(f"  - ⚠ {wn}")
        spec = o.get("07_backtest_spec") or {}
        per, ss = spec.get("period") or {}, spec.get("selection") or {}
        self.w(f"- 07 백테스트 {per.get('start')}~{per.get('end')} (시작 체결일 {per.get('as_of')}, {per.get('trading_days')}거래일) · 종목 {len(ss.get('tickers') or [])}개 ({ss.get('source')})")
        self.w(f"  - 시작일 종목: {', '.join(ss.get('tickers') or [])}")
        for wn in (spec.get("warnings") or [])[:8]:
            self.w(f"  - ⚠ {wn}")
        # 규칙: 제외·필수·종목 수·자격선
        excl = {str(x).upper() for x in cons.get("exclude_tickers", [])}
        fam = set(excl)
        for g in SHARE_CLASS:
            if g & excl:
                fam |= g
        picked = {s["ticker"] for s in rows} | set(ss.get("tickers") or [])
        bad = sorted(t for t in picked if t.upper() in fam or t.upper().split(".")[0] in {e.split(".")[0] for e in excl})
        self.chk("제외 종목·같은 회사 주식 없음", not bad, ", ".join(bad))
        xs = {s.lower() for s in cons.get("exclude_sectors", [])}
        secs = self.sectors()
        bad = sorted(t for t in picked if (secs.get(t) or "").lower() in xs)
        self.chk("제외 섹터 종목 없음", not bad, ", ".join(f"{t}({secs.get(t)})" for t in bad))
        unknown = [w_ for w_ in (c3.get("warnings") or []) if "unknown sector" in str(w_)]
        self.chk("제외 섹터 이름 모두 인식", not unknown, "; ".join(map(str, unknown)))
        must = {str(x).upper() for x in cons.get("must_include_tickers", [])}
        got = {s["ticker"].upper() for s in rows} | {s["ticker"].upper().split(".")[0] for s in rows}
        miss = sorted(m for m in must if m not in got and m.split(".")[0] not in got)
        self.chk("필수 포함 종목 포함(기준일)", not miss, ", ".join(miss))
        nh = cons.get("num_holdings") or {}
        n = len(rows)
        self.chk("종목 수 최소~최대(기준일)", nh.get("min", 0) <= n <= nh.get("max", 10**6), f"{n} vs {nh.get('min')}~{nh.get('max')}")
        n_bt = len(ss.get("tickers") or [])
        kept = bool(((self.req_doc or {}).get("overrides") or {}).get("_allow_fewer_at_start"))  # 사용자가 '기간 유지' 를 고름 → 미달은 정책대로 (라벨에 '종목 수 부족')
        lab = str((((o.get("12_validation") or {}).get("recommended") or {}).get("verdict") or {}).get("label_ko") or "")
        self.chk("종목 수 최소 이상(시작일)" + (" — 사용자가 기간 유지를 골라 라벨 표시로 대신" if kept and n_bt < nh.get("min", 0) else ""),
                 n_bt >= nh.get("min", 0) or (kept and n_bt >= 2 and "종목 수 부족" in lab), f"{n_bt} vs 최소 {nh.get('min')}")  # fmt: skip
        rng = ELIGIBLE.get(str(sc.get("metric")))
        if rng:
            lo, hi = rng
            out_ = []
            for s in [*rows, *((o.get("07_selection_bt") or {}).get("selected") or [])]:
                v = _num(s.get("metric_value"))
                if s.get("forced") or v is None:
                    continue
                if not (v > lo and (hi is None or v <= hi)):
                    out_.append(f"{s['ticker']}={v:.4g}")
            self.chk(f"자격선 {sc.get('metric')} {lo}<v" + (f"≤{hi}" if hi else ""), not out_, ", ".join(sorted(set(out_))))

    def _check_weights(self, label: str, w: dict[str, float], cash: float | None, cons: dict[str, Any], secs: dict[str, str]) -> list[str]:
        errs = []
        tot = sum(w.values())
        cash = (1 - tot) if cash is None else cash
        if any(x < -TOL for x in w.values()):
            errs.append(f"{label}: 음수 비중")
        if abs(tot + cash - 1) > 1e-4:
            errs.append(f"{label}: 합 {tot + cash:.6f}")
        ms, mx = cons.get("max_weight_per_stock", 1), cons.get("max_weight_per_sector", 1)
        big = [f"{t} {x:.4f}" for t, x in w.items() if x > ms + 1e-5]
        if big:
            errs.append(f"{label}: 종목 상한 {ms:.2f} 초과 {big[:3]}")
        by: dict[str, float] = {}
        for t, x in w.items():
            by[secs.get(t) or "?"] = by.get(secs.get(t) or "?", 0) + x
        sb = [f"{k} {v:.4f}" for k, v in by.items() if v > mx + 1e-5 and k != "?"]
        if sb:
            errs.append(f"{label}: 섹터 상한 {mx:.2f} 초과 {sb[:3]}")
        if cash < cons.get("min_cash_ratio", 0) - 1e-5:
            errs.append(f"{label}: 현금 {cash:.4f} < 최소 {cons.get('min_cash_ratio')}")
        return errs

    def construction(self) -> None:
        o, rq = self.o, self.req
        cons = rq.get("constraints") or {}
        secs = self.sectors()
        self.w("\n## 구성\n")
        mm = o.get("08_market_model") or {}
        self.w(f"- δ {mm.get('delta')} ({mm.get('delta_source')}, 시장 {mm.get('delta_market')} · 기준 {mm.get('delta_base')} · 성향 ×{mm.get('delta_multiplier')} · 낙폭 ×{mm.get('delta_dd_multiplier')})")
        base = o.get("08_baseline_portfolios") or {}
        chosen = base.get("chosen_baseline")
        self.chk("기준 비중 = 사용자 선택", chosen == (rq.get("strategy_preference") or {}).get("baseline_weighting"), f"{chosen}")
        errs: list[str] = []
        tg = o.get("10_target_portfolios") or {}
        for p in [*(tg.get("templates") or []), *(tg.get("portfolios") or [])]:
            errs += self._check_weights(f"10:{p['id']}", p["weights"], p.get("cash_weight"), cons, secs)
            en = (p.get("ex_ante") or {}).get("effective_n")
            nz = sum(1 for x in p["weights"].values() if x > 1e-9)
            if en is not None and en > nz + 1e-6:
                errs.append(f"10:{p['id']}: 실효 종목 수 {en} > 보유 {nz}")
        for p in tg.get("templates") or []:
            self.w(f"- 시작일 {p['id']}: 현금 {_pct(p.get('cash_weight'))} · 상위 {', '.join(f'{t} {_pct(x)}' for t, x in sorted(p['weights'].items(), key=lambda z: -z[1])[:5])}")
        news_on = bool(((o.get("02_intent") or {}).get("news_tilt") or {}).get("enabled"))
        for p in tg.get("portfolios") or []:
            dv = p.get("delta_vs_baseline") or {}
            self.w(f"- 시작일 BL {p['id']} {p.get('name_ko')}: 뷰 {len(p.get('views_applied') or [])}개 · 큰 변화 "
                   + ", ".join(f"{t} {x * 100:+.1f}%p" for t, x in sorted(dv.items(), key=lambda z: -abs(z[1]))[:4]))  # fmt: skip
            for v in p.get("views_applied") or []:
                self.w(f"  - {v.get('summary_ko')}")
                q, pr, d = _num(v.get("expected_return_annual")), _num(v.get("prior_return")), v.get("direction")
                if q is not None and pr is not None and d in ("up", "down") and v.get("type") == "absolute":
                    if (q - pr) * (1 if d == "up" else -1) < -1e-9:
                        errs.append(f"{p['id']}: 뷰 방향 {d} 인데 Q {q} vs 사전 {pr}")
        wf = o.get("10w_target_paths") or {}
        ports = {p["id"]: p for p in wf.get("portfolios") or []}
        bl = ports.get("wf_bl_news")
        base_wf = ports.get(f"wf_{chosen}")
        for pid, p in ports.items():
            for d, w in (p.get("weights_by_date") or {}).items():
                errs += self._check_weights(f"10w:{pid}@{d}", w, None, cons, secs)
        if bl and base_wf:
            moved, with_views = 0, 0
            for d, vs in (bl.get("views_by_date") or {}).items():
                if vs:
                    with_views += 1
                    diff = max(abs(bl["weights_by_date"][d].get(t, 0) - base_wf["weights_by_date"][d].get(t, 0)) for t in base_wf["weights_by_date"][d])
                    moved += diff > 1e-4
            self.w(f"- walk-forward: 리밸런싱 {len(wf.get('dates') or [])}회 · 뷰 있는 날 {with_views} · 그중 비중이 바뀐 날 {moved} · 기준 비중 유지 {len(bl.get('fallback_dates') or [])} · 최적화 메모 {list((bl.get('optimizer_notes') or {}).items())[:2]}")
            self.chk("뷰가 있는 날 BL 비중이 실제로 바뀜", moved == with_views, f"{moved}/{with_views}")
        self.chk("뉴스 끔이면 BL 없음", news_on or not bl, "wf_bl_news 있음" if bl else "")
        fw = o.get("10f_forward_portfolios") or {}
        for p in [*(fw.get("templates") or []), *(fw.get("portfolios") or [])]:
            errs += self._check_weights(f"10f:{p['id']}", p["weights"], p.get("cash_weight"), cons, secs)
        self.chk("비중 규칙(합·상한·최소 현금·방향)", not errs, "; ".join(errs[:6]) + (f" … 외 {len(errs) - 6}건" if len(errs) > 6 else ""))

    def backtest(self) -> None:
        o, rq = self.o, self.req
        bt = o.get("11_backtest_results") or {}
        self.w("\n## 백테스트\n")
        per = bt.get("period") or {}
        self.w(f"- 기간 {per.get('start')}~{per.get('end')} · {per.get('trading_days')}거래일 · 비교지수 {(bt.get('benchmark') or {}).get('id')}")
        self.w("\n| id | 종류 | 기준 | 투자비중 | CAGR | 기간수익 | MDD | Sharpe |")
        self.w("| --- | --- | --- | --- | --- | --- | --- | --- |")
        bad_floor = []
        seen_ids: set[str] = set()
        for p in [bt.get("benchmark") or {}, *(bt.get("benchmarks") or []), *(bt.get("portfolios") or [])]:
            if not p or p.get("id") in seen_ids:
                continue
            seen_ids.add(p.get("id"))
            h = p.get("headline") or {}
            inv = sum((p.get("target_weights") or {}).values()) if p.get("target_weights") else None
            self.w(f"| {p.get('id')} | {p.get('kind')} | {p.get('base_id') or ''} | {_pct(inv) if inv is not None else '-'} | {_pct(h.get('cagr'))} | {_pct(h.get('period_return'))} | {_pct(h.get('max_drawdown'))} | {h.get('sharpe')} |")
            if p.get("kind") == "matched" and inv is not None and inv < 0.30 - 1e-6:
                bad_floor.append(f"{p['id']} {inv:.2%}")
        self.chk("낙폭 맞춤안 주식 비중 ≥ 30%", not bad_floor, ", ".join(bad_floor))
        spec_days = ((o.get("07_backtest_spec") or {}).get("period") or {}).get("trading_days")
        self.chk("07·11 거래일 수 같음", spec_days == per.get("trading_days"), f"07 {spec_days} vs 11 {per.get('trading_days')}")
        cur = (rq.get("capital") or {}).get("currency")
        txt = json.dumps(o.get("14_report") or {}, ensure_ascii=False)
        self.chk("USD 요청에 '1 USD = 1.00 KRW' 없음", cur != "USD" or "1 USD = 1.00 KRW" not in txt, cur or "")

    def validation(self) -> None:
        o, rq = self.o, self.req
        v = o.get("12_validation") or {}
        rec = v.get("recommended") or {}
        vd = rec.get("verdict") or {}
        self.w("\n## 검증·추천\n")
        self.w(f"- 추천: **{vd.get('label_ko')}** (`{rec.get('id')}`)")
        self.w(f"- 사유: {rec.get('reason_ko')}")
        self.w(f"- 순위: {', '.join((rec.get('ranking') or [])[:8])}")
        self.w(f"- 요약: {v.get('summary')}")
        bt = {p["id"]: p for p in (o.get("11_backtest_results") or {}).get("portfolios") or []}
        p = bt.get(rec.get("id")) or {}
        h = p.get("headline") or {}
        tol = (rq.get("risk") or {}).get("max_drawdown_tolerance")
        mdd = abs(h.get("max_drawdown") or 0)
        if tol:
            self.chk("낙폭 초과면 라벨에 주의", mdd <= tol + 1e-9 or "허용 낙폭 초과" in str(vd.get("label_ko")), f"MDD {mdd:.1%} vs 허용 {tol:.0%} · {vd.get('label_ko')}")
        reason = str(rec.get("reason_ko") or "")
        risk, prof = rq.get("risk") or {}, rq.get("profile") or {}
        bad = []
        if "손실 시 매도" in reason and risk.get("loss_reaction") != "sell":
            bad.append(f"'손실 시 매도' but loss_reaction={risk.get('loss_reaction')}")
        if "투자 경험 없음" in reason and prof.get("investment_experience") != "none":
            bad.append(f"'투자 경험 없음' but experience={prof.get('investment_experience')}")
        self.chk("성향 문구 = 실제 요청값", not bad, "; ".join(bad))
        tgt = risk.get("target_annual_return")
        if "충족" in reason and tgt is not None and h.get("cagr") is not None:
            self.chk("'목표수익 충족' 이면 CAGR ≥ 목표", h["cagr"] >= tgt - 1e-9, f"CAGR {h['cagr']:.2%} vs 목표 {tgt:.0%}")

    def report(self) -> None:
        o = self.o
        d = o.get("14_report") or {}
        self.w("\n## 리포트\n")
        if not d:
            self.w("리포트 없음")
            return
        h, sm = d.get("header") or {}, d.get("summary") or {}
        self.w(f"- 제목: {h.get('title_ko')} · {h.get('title_detail_ko')}")
        self.w(f"- 부제: {h.get('subtitle_ko')}")
        self.w(f"- 선택안 메모: {h.get('chosen_note_ko')}")
        vd = sm.get("verdict") or {}
        self.w(f"- 결론: {vd.get('label_ko')} · {vd.get('headline_ko') or ''}")
        for k in ("period_note_ko", "notices_ko", "cautions_ko"):
            if vd.get(k):
                self.w(f"  - {k}: {vd.get(k)}")
        al = sm.get("allocation") or {}
        items = al.get("items") or []
        cash = max(0.0, 1 - sum(float(i.get("weight") or 0) for i in items if i.get("ticker") not in ("현금", "CASH")))
        self.w(f"- 배분({al.get('basis_ko')}): " + ", ".join(f"{i.get('ticker')} {_pct(i.get('weight'))}" for i in items[:8]) + f" · 현금 {_pct(cash)}")
        ne = sm.get("news_effect") or {}
        self.w(f"- 뉴스 효과: {json.dumps({k: ne.get(k) for k in ('disabled', 'reason_ko', 'n_views', 'n_fallback')}, ensure_ascii=False)}")
        self.w(f"- 다음 행동: {sm.get('next_actions_ko')}")
        notices = d.get("notices") or []
        for n in notices[:8]:
            self.w(f"- 공지: {n.get('message_ko') if isinstance(n, dict) else n}")
        self.w("\n### 본문 (LLM·코드 문단)\n")
        for s in d.get("sections") or []:
            self.w(f"#### {s.get('title_ko')}")
            for b in s.get("blocks") or []:
                t = b.get("type")
                if t == "paragraphs":
                    for ptxt in b.get("items") or b.get("paragraphs") or []:
                        self.w(f"- {ptxt if isinstance(ptxt, str) else json.dumps(ptxt, ensure_ascii=False)}")
                elif t == "callout":
                    self.w(f"- [{b.get('title_ko', '')}] {b.get('text_ko', '')}")
        rec = ((o.get("12_validation") or {}).get("recommended") or {}).get("id")
        rec_label = next((p.get("name_ko") for p in (o.get("11_backtest_results") or {}).get("portfolios") or [] if p.get("id") == rec), rec)
        basis = str(al.get("basis_ko") or "")
        core = re.sub(r"^(wf_|dd_match_(wf_)?)", "", str(rec or ""))
        tmpl_ko = {"equal_weight": "동일비중", "market_cap": "시가총액비중", "inverse_volatility": "역변동성비중", "min_variance": "최소분산"}
        ok = (tmpl_ko.get(core, "@@") in basis) or (str(rec_label) in basis) or ("BL" in basis and core.startswith("bl"))
        self.chk("추천안 = 대시보드 배분 규칙", ok, f"추천 {rec_label} vs 배분 '{basis}'")
        m1, m2 = re.search(r"주식 (\d+)%", str(rec_label)), re.search(r"주식 (\d+)%", basis)
        if m1 and m2:  # 낙폭 맞춤안: 백테스트로 확인한 주식 비중 = 대시보드 주식 비중 (기준일 구성이 더 적게 담는 경우만 예외)
            self.chk("맞춤안 주식 비중 = 대시보드 주식 비중", int(m2.group(1)) <= int(m1.group(1)) + 1, f"추천 주식 {m1.group(1)}% vs 대시보드 주식 {m2.group(1)}%")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="backend.analysis.eval.audit")
    ap.add_argument("--from", dest="src", default=str(REPO_ROOT / "docs" / "mvp" / "scenario_qa" / "runs"))
    ap.add_argument("--names", required=True, help="쉼표로 구분한 시나리오 이름 (run_scenarios 결과 JSON 파일 이름)")
    ap.add_argument("--out", default=str(REPO_ROOT / "docs" / "mvp" / "scenario_qa" / "audit"))
    a = ap.parse_args(argv)
    src, out = Path(a.src), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name in [x.strip() for x in a.names.split(",") if x.strip()]:
        res = _load(src / f"{name}.json") or {"status": "missing"}
        au = Audit(name, res)
        md = au.run()
        dst = out / f"{name}.md"
        if dst.exists():  # 다른 실행의 점검이면 history/ 로 보관 (재실행이 첫 실행 점검을 덮어쓰지 않게)
            m_old, m_new = re.search(r"run `([^`]+)`", dst.read_text(encoding="utf-8")), re.search(r"run `([^`]+)`", md)
            if m_old and (not m_new or m_old.group(1) != m_new.group(1)):
                (out / "history").mkdir(exist_ok=True)
                dst.replace(out / "history" / f"{name}__{m_old.group(1)}.md")
        dst.write_text(md, encoding="utf-8")
        bad = [c for c in au.checks if not c[1]]
        print(f"{name}: {res.get('status')} · 규칙 실패 {len(bad)}/{len(au.checks)} → {out / (name + '.md')}")
        for cid, _, det in bad:
            print(f"   ❌ {cid}: {det[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

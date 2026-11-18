"""4. 과거 성과 → 투자 조건 충족 여부 → 「조건별 근거 보기」의 쉬운 문장 (2026-11-16 사용자 요청).

- 「선택 전략의 조건별 결과」 표: 점검 항목 / 기준과 측정값 / 결과. 규칙 번호·수준은 화면에 두지 않는다(행 자료의 rule 은 남김).
  결과는 충족·주의·허용 초과·미충족과, 참고(info)를 뜻에 따라 나눈 '판정 보류'(짧은 평가 기간으로 판단하지 않음)·'측정 결과'(기준 없이 값만)로.
- 「전략별 점검 결과」 표: 전략 / 결과 / 이유. 주의·미통과는 실제 이유를, 통과는 최종 선택인지와 왜 선택됐는지·안 됐는지를.
- selection_sentence_ko: 어떤 전략을 왜 골랐는지 한 문장 (14a validation_ko 가 그대로 옮긴다).
validate.py 의 원래 문장(message_ko)은 바꾸지 않는다 — 화면의 다른 부분(parseVolCheck 등)이 그 형식을 읽는다.
"""

from __future__ import annotations

import re
from typing import Any

from backend.analysis.m5_backtest_report import report_blocks as B
from backend.analysis.m5_backtest_report.caution_text import PREF_LABEL, _cap, _Ctx, _josa, _pct

NAME_PLAIN = {"R1": "최대낙폭과 허용 한도", "R1b": "비교지수와 최대낙폭 비교", "R2": "목표 수익률 달성 여부", "R3": "비교지수와 수익률 비교",
              "R7": "변동성 기준 충족 여부", "R4b": "조정일 사이 종목 비중 변화", "R5b": "조정일 사이 업종 비중 변화", "R9": "주식과 현금 비중",
              "R4": "비중을 맞추는 날의 종목 비중 한도", "R5": "비중을 맞추는 날의 업종 비중 한도", "R8": "가격 자료 점검"}  # fmt: skip
RESULT_KO = {"pass": "충족", "warn": "주의", "fail": "미충족", "flag": "허용 초과"}
HELD, MEASURED = "판정 보류", "측정 결과"


def _short(c: _Ctx) -> bool:
    return not bool((c.R["backtest"].get("period") or {}).get("annualized_reliable", True))


def result_ko(ck: dict[str, Any]) -> str:
    """참고(info)는 기준값이 있는데 평가 기간이 짧아 판단하지 않은 것(R2·R7) = 판정 보류, 나머지 = 측정 결과."""
    st = ck.get("status")
    if st == "info":
        return HELD if ck.get("rule") in ("R2", "R7") and ck.get("threshold") is not None else MEASURED
    return RESULT_KO.get(st, st)


def _ret_pair(c: _Ctx) -> tuple[str, float, float]:
    """비교지수와 견줄 수익률: 짧은 기간이면 같은 기간 수익률, 아니면 연평균 수익률(CAGR). 판정(초과 CAGR)과 부호가 같다."""
    bm = ((c.R["backtest"]["benchmark"].get("metrics") or {}).get("return") or {})
    m = (c.p.get("metrics") or {}).get("return") or {}
    if _short(c):
        return "같은 기간 수익률", float(m.get("total_return") or 0), float(bm.get("total_return") or 0)
    return "연평균 수익률(CAGR)", float(m.get("cagr") or 0), float(bm.get("cagr") or 0)


def _vol_base(c: _Ctx, ck: dict[str, Any]) -> str:
    band = ck.get("threshold")
    pref = PREF_LABEL.get(str(c.crit.get("volatility_preference")), "변동성 기준")
    if band is None:
        return f"이번 분석에 적용한 {pref}은 변동성 상한을 두지 않습니다"
    if c.bench_vol:
        mult = round(float(band) / float(c.bench_vol), 2)
        if abs(mult - 1) < 1e-9:
            return f"이번 분석에 적용한 {pref} — {c.bench}의 연변동성 {_pct(float(c.bench_vol))}를 그대로 쓴 {_pct(float(band))} 이하"
        return f"이번 분석에 적용한 {pref} — {c.bench}의 연변동성 {_pct(float(c.bench_vol))}에 {mult:g}을 곱한 {_pct(float(band))} 이하"
    return f"이번 분석에 적용한 {pref} — 연변동성 {_pct(float(band))} 이하(고정 기준)"


def _drift_cell(c: _Ctx, kind: str, ck: dict[str, Any]) -> str:
    what = "종목" if kind == "stock" else "업종"
    cap = float(c.crit.get("max_weight_per_stock" if kind == "stock" else "max_weight_per_sector") or 0)
    tol = float(c.crit.get("drift_tolerance") or 0.25)
    lim = cap * (1 + tol)
    top, who = c.comp.get(f"max_{kind}_weight"), c.comp.get("max_stock_weight_ticker" if kind == "stock" else "max_sector_weight_sector")
    when = "비중을 맞추는 날" if c.rebal else "처음 비중을 정한 날"
    base = f"기준: {when}의 {what}당 목표 비중 한도 {_cap(cap)}"
    base += f", 조정일 사이에 비중이 크게 벗어났는지 보는 별도 점검 기준 {_pct(lim)}." if lim < 1 - 1e-9 else "."
    if top is None:  # 최대 비중 자료가 없는 예전 결과 → 원래 측정 문장
        return f"{base} 측정값: {ck.get('message_ko')}"
    nm = (c.names.get(who, who) if kind == "stock" else B.sector_ko(who)) if who else None
    s = f"{base} 측정값: 조정일 사이 가장 높았던 {what} 비중 {_pct(float(top))}" + (f"({nm})" if nm else "") + "."
    days, n = int(c.comp.get(f"days_above_{kind}_cap") or 0), c.comp.get("n_days")
    if not days:
        return s + f" {_cap(cap)}를 넘은 날은 없었습니다."
    s += f" {_cap(cap)}를 넘은 {_josa(what, '이가')} 하나라도 있던 날 {f'{n}거래일 중 ' if n else ''}{days}일"
    tdays = c.comp.get(f"days_above_{kind}_tol")
    if tdays is not None and lim < 1 - 1e-9:
        s += f", {_pct(lim)}를 넘은 날 {int(tdays)}일" if tdays else f", {_pct(lim)}를 넘은 날은 없음"
    return s + "."


def check_cell(c: _Ctx, ck: dict[str, Any]) -> str:
    """「기준과 측정값」 칸: '기준: … 측정값: …' (같은 기간 날짜는 표 메모에 한 번)."""
    r, v, thr = ck.get("rule"), ck.get("value"), ck.get("threshold")
    msg = str(ck.get("message_ko") or "")
    if r == "R1":
        tol = float(thr if thr is not None else c.crit.get("max_drawdown") or 0)
        s = f"기준: 최대낙폭이 허용 한도 {_cap(tol)} 이내. 측정값: 이 전략의 최대낙폭 {_pct(c.mdd)}"
        s += f"(같은 날 같은 금액을 {c.bench}에 넣었다면 {_pct(c.bench_mdd)})." if c.bench_mdd is not None else "."
        return s + (f" 허용 한도보다 {(c.mdd - tol) * 100:.1f}%p 컸습니다." if c.mdd > tol + 1e-9 else "")
    if r == "R1b" and c.bench_mdd is not None:
        gap = (c.mdd - c.bench_mdd) * 100
        return (f"기준: 같은 날 같은 금액을 {c.bench}에 넣었을 때의 최대낙폭 {_pct(c.bench_mdd)}. 측정값: 이 전략 {_pct(c.mdd)}"
                + (f"로 {gap:.1f}%p 더 크게 떨어졌습니다." if gap > 0.05 else "로 더 크게 떨어지지 않았습니다."))
    if r == "R2":
        target = float(c.crit.get("target_annual_return") or 0)
        if m := re.match(r"투자기간 ([\d.]+)년 구간 (\d+)개 중 (\d+)%가", msg):
            return (f"기준: 과거 주가에서 투자기간 {m.group(1)}년 길이의 구간 중 {_cap(float(thr or 0.5))} 이상에서 연 {_cap(target)} 목표 수익률을 넘을 것. "
                    f"측정값: {m.group(2)}개 구간 중 {m.group(3)}%.")
        if ck.get("status") == "info":
            tr = c.total_return
            return f"기준: 연 {_cap(target)} 목표 수익률. 측정값: 이 기간 수익률 {_pct(tr) if tr is not None else '-'}. 평가 기간이 짧아 판정 보류."
        whole = " 투자기간 길이의 구간을 여러 개 만들 만큼 기간이 길지 않아 백테스트 전체 기간으로 판정했습니다." if "전체 CAGR" in msg else ""
        return f"기준: 연평균 수익률(CAGR) 연 {_cap(target)} 이상. 측정값: {_pct(c.cagr)}.{whole}"
    if r == "R3":
        label, own, bm = _ret_pair(c)
        return f"기준: 같은 날 같은 금액을 {c.bench}에 넣었을 때보다 수익률이 높을 것. 측정값: {label} {_pct(own)}, {c.bench} {_pct(bm)}({(own - bm) * 100:+.1f}%p)."
    if r == "R7":
        s = f"기준: {_vol_base(c, ck)}. 측정값: 이 전략의 백테스트 연변동성 {_pct(c.vol)}"
        s += f"({c.bench} {_pct(float(c.bench_vol))})." if thr is None and c.bench_vol else "."
        return s + (" 평가 기간이 짧아 판정 보류." if ck.get("status") == "info" and thr is not None else "")
    if r in ("R4b", "R5b"):
        return _drift_cell(c, "stock" if r == "R4b" else "sector", ck)
    if r == "R9":
        inv = min(float(v), 1.0) if v is not None else None
        mc = float(c.crit.get("min_cash_ratio") or 0)
        s = (f"기준: 요청한 최소 현금 {_cap(mc)}. " if mc > 1e-6 else "")
        s += f"측정값: 백테스트 시작일 구성은 투자금의 {inv:.0%}를 주식, {max(0.0, 1 - inv):.0%}를 현금으로 두었습니다." if inv is not None else f"측정값: {msg}"
        if m := re.search(r"— 백테스트 시작일 구성은 (.+?)(?: · |$)", msg):
            s += f" {m.group(1).strip().rstrip('.')}."
        if m := re.search(r"현금은 (?:최저 ([\d.]+%)(?:\((\S+?)\))?까지 내려가 )?최소 현금 (\S+?)보다 낮았던 날이 (?:(\d+)거래일 중 )?(\d+)일", msg):
            s += f" 현금 비중이 최소 현금보다 낮았던 날 {f'{m.group(4)}거래일 중 ' if m.group(4) else ''}{m.group(5)}일" + (f"(최저 {m.group(1)})" if m.group(1) else "") + "."
        return s
    return msg


def chosen_rows(R: dict[str, Any], chosen: str) -> list[dict[str, Any]]:
    """「선택 전략의 조건별 결과」 행: {rule(숨김), name, msg, status}. 내부 점검(종목·업종 한도, 자료)이 실패했으면 그 행도."""
    c = _Ctx(R, chosen)
    res = next((r for r in R["validation"]["results"] if r["id"] == chosen), None) or \
        next((a for a in R["validation"].get("alternatives", []) if a["id"] == chosen), {})  # fmt: skip
    rows = [{"rule": ck["rule"], "name": NAME_PLAIN.get(ck["rule"], ck.get("name_ko")), "msg": check_cell(c, ck), "status": result_ko(ck)} for ck in res.get("checks") or []]
    rows += [{"rule": ck["rule"], "name": NAME_PLAIN.get(ck["rule"], ck.get("name_ko")), "msg": integrity_reason(c, ck), "status": "미통과"}
             for ck in res.get("integrity") or [] if ck.get("status") == "fail"]  # fmt: skip
    return rows


# ───────────────────────── 전략별 점검 결과 ─────────────────────────

def integrity_reason(c: _Ctx, ck: dict[str, Any]) -> str:
    r, v, thr = ck.get("rule"), ck.get("value"), ck.get("threshold")
    if r in ("R4", "R5") and v is not None and thr is not None:
        what = "종목" if r == "R4" else "업종"
        return f"비중을 맞추는 날 한 {what}의 비중이 최대 {_pct(float(v))}로, {what}당 한도 {_cap(float(thr))}를 넘었습니다."
    if r == "R8" and v is not None and thr is not None:
        if float(v) < float(thr):
            return f"가격 자료가 {int(v)}일치로, 백테스트 기간에 필요한 {int(thr)}일보다 짧았습니다."
        return f"가격 자료 점검에서 문제가 확인됐습니다({ck.get('message_ko')})."
    return str(ck.get("message_ko") or ck.get("name_ko") or "")


def _issue(c: _Ctx, ck: dict[str, Any], name: str) -> str | None:
    r, thr = ck.get("rule"), ck.get("threshold")
    msg = str(ck.get("message_ko") or "")
    if r == "R1":
        return f"최대낙폭 {_pct(c.mdd)}가 허용 한도 {_cap(float(thr or 0))}보다 컸습니다."
    if r == "R2":
        if m := re.match(r"투자기간 ([\d.]+)년 구간 (\d+)개 중 (\d+)%가", msg):
            return f"투자기간 {m.group(1)}년 길이의 과거 구간 중 목표 수익률을 넘은 구간이 {m.group(3)}%로, 기준 {_cap(float(thr or 0.5))}보다 적었습니다."
        return f"연평균 수익률 {_pct(c.cagr)}가 목표 연 {_cap(float(c.crit.get('target_annual_return') or 0))}보다 낮았습니다."
    if r == "R3":
        label, own, bm = _ret_pair(c)
        return f"{name} 전략의 {label}은 {_pct(own)}로 {c.bench}의 {_pct(bm)}보다 낮았습니다."
    if r == "R7" and thr is not None:
        return f"연변동성 {_pct(c.vol)}가 기준 {_pct(float(thr))}보다 높았습니다."
    return msg or None


def _mode_phrase(R: dict[str, Any], p: dict[str, Any]) -> str:
    """두 방식(정적·워크포워드)을 함께 비교한 리포트에서만: 그 전략이 어떤 방식인지."""
    if not any(str(x.get("id", "")).startswith("wf_") for x in R["validation"]["results"]):
        return ""
    desc = str(((R["portfolio"].get("backtest_spec") or {}).get("rebalance_rule") or {}).get("description_ko") or "")
    freq = (m.group(1) if (m := re.match(r"^(\S+?)(?:마다)? 첫 거래일", desc)) else "")
    freq = {"매월": "매월", "분기": "분기마다", "매주": "매주", "매년": "매년"}.get(freq, freq)
    if str(p.get("id", "")).startswith("wf_") or p.get("mode") == "walkforward":
        return f"비중을 맞추는 날마다({freq}) 그때까지의 자료로 목표 비중을 새로 계산하는 방식입니다. " if freq else "비중을 맞추는 날마다 그때까지의 자료로 목표 비중을 새로 계산하는 방식입니다. "
    return "비중을 맞추는 날마다 백테스트 시작일에 정한 목표 비중으로 되돌리는 방식입니다. "


def _metrics(R: dict[str, Any], pid: str) -> tuple[float | None, float]:
    m = B.find(R, pid).get("metrics") or {}
    sh = (m.get("risk_adjusted") or {}).get("sharpe")
    return (None if sh is None else round(float(sh), 4)), round(abs(float((m.get("risk") or {}).get("max_drawdown") or 0)), 4)


def _why_not(R: dict[str, Any], pid: str, chosen: str) -> str:
    """통과했지만 선택되지 않은 이유: 순위 키에서 처음 갈린 값(샤프 비율 → 최대낙폭 → 사용자가 고른 기준 비중)."""
    (s1, d1), (s0, d0) = _metrics(R, pid), _metrics(R, chosen)
    cl = B.pf_label(B.find(R, chosen))
    if s1 is not None and s0 is not None and s1 < s0:
        return f"샤프 비율 {s1:.2f}이 {cl}의 {s0:.2f}보다 낮아 선택되지 않았습니다."
    if s1 == s0 and d1 > d0:
        return f"샤프 비율은 {cl}와 같지만 최대낙폭 {_pct(d1)}가 {_pct(d0)}보다 커서 선택되지 않았습니다."
    if s1 == s0 and d1 == d0:
        return f"성과가 {cl}와 같아, 사용자가 고른 기준 비중 쪽을 선택했습니다."
    return f"순위가 {cl}보다 뒤라 선택되지 않았습니다."


def strategy_rows(R: dict[str, Any], chosen: str) -> list[dict[str, Any]]:
    """「전략별 점검 결과」 행: {name, status, reason}. 결과의 '최종 선택' 과 검증 통과는 따로 쓴다."""
    out = []
    for r in R["validation"]["results"]:
        p = B.find(R, r["id"])
        name = B.pf_label(p)
        c = _Ctx(R, r["id"])
        st = {"pass": "통과", "warn": "주의", "fail": "미통과"}.get(r["status"], r["status"])
        fails = [integrity_reason(c, ck) for ck in r.get("integrity") or [] if ck.get("status") == "fail"]
        fails += [t for ck in r["checks"] if ck.get("status") == "fail" and (t := _issue(c, ck, name))]
        warns = [t for ck in r["checks"] if ck.get("status") in ("warn", "flag") and (t := _issue(c, ck, name))]
        reason = " ".join(fails + warns)
        mode = _mode_phrase(R, p) if r["status"] == "pass" or r["id"] == chosen else ""
        if r["id"] == chosen:
            st += " · 최종 선택"
            reason = mode + (reason + " 그래도 " if reason else "") + selection_basis_ko(R, chosen, short=True)
        elif r["status"] == "pass":
            reason = mode + "모든 점검을 통과했지만, " + _why_not(R, r["id"], chosen)
        out.append({"name": name, "status": st, "reason": reason or "-"})
    return out


def selection_basis_ko(R: dict[str, Any], chosen: str, *, short: bool = False) -> str:
    """선택을 가른 기준: 'SPY보다 수익률이 높고 최대낙폭이 허용한 30% 이내였던 전략 중, 샤프 비율이 가장 높은 최소분산 전략을 선택했습니다.'
    순위 키(validate.rank_key)의 앞 조건 중 선택 전략이 충족한 것을 조건으로, 처음 갈린 값을 결정 이유로."""
    c = _Ctx(R, chosen)
    name = B.pf_label(c.p)
    tol = float(c.crit.get("max_drawdown") or 0)
    quals = []
    if c.checks.get("R2", {}).get("status") == "pass":
        quals.append(f"목표 수익률 연 {_cap(float(c.crit.get('target_annual_return') or 0))}를 넘었고")
    if c.checks.get("R3", {}).get("status") == "pass":
        quals.append(f"{c.bench}보다 수익률이 높고")
    if c.mdd <= tol + 1e-9:
        quals.append(f"최대낙폭이 허용한 {_cap(tol)} 이내였던")
    pool = [r["id"] for r in R["validation"]["results"] if all(r_ck.get("status") == c.checks.get(k, {}).get("status")
            for k in ("R2", "R3") for r_ck in [next((x for x in r["checks"] if x["rule"] == k), {})]) and r["status"] != "fail"]  # fmt: skip
    s0, d0 = _metrics(R, chosen)
    same_sh = [i for i in pool if _metrics(R, i)[0] == s0]
    if len(same_sh) > 1 and all(_metrics(R, i)[1] == d0 for i in same_sh):
        why = "성과가 같은 전략 중 사용자가 고른 기준 비중인"
    elif len(same_sh) > 1:
        why = "샤프 비율이 같은 전략 중 최대낙폭이 가장 작은"
    elif s0 is not None and s0 <= 0:
        why = "샤프 비율이 가장 덜 나쁜"
    else:
        why = "샤프 비율이 가장 높은"
    if quals:  # 마지막 조건은 '…전략' 을 꾸미는 꼴로 ('높고' → '높았던', '넘었고' → '넘은')
        quals[-1] = re.sub(r"높고$", "높았던", re.sub(r"넘었고$", "넘은", quals[-1]))
    lead = f"{' '.join(quals)} 전략 중" if quals else "비교한 전략 중"
    if short:
        return f"{lead}, {why} 전략이라 최종 선택했습니다."
    return f"{lead}, {why} {name} 전략을 선택했습니다."


def selection_sentence_ko(R: dict[str, Any], chosen: str) -> str:
    return selection_basis_ko(R, chosen)


def table_note_ko(R: dict[str, Any], chosen: str) -> str:
    c = _Ctx(R, chosen)
    res = next((r for r in R["validation"]["results"] if r["id"] == chosen), None) or {}
    integ = res.get("integrity") or []
    n_ok = sum(1 for x in integ if x.get("status") == "pass")
    s = (f"측정값은 {c.start}부터 {c.end}까지 백테스트 결과입니다. 판정 보류는 평가 기간이 짧아 기준 충족 여부를 판단하지 않은 항목, "
         "측정 결과는 기준 충족 여부를 따지지 않고 값을 알려 주는 항목입니다.")
    if integ:
        s += f" 비중을 맞추는 날의 종목·업종 비중 한도와 가격 자료는 따로 점검했고 {len(integ)}개 중 {n_ok}개를 통과했습니다."
    return s

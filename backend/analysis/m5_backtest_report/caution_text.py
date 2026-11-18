"""「7. 주의 사항과 전제 → 중요한 주의 사항」에 보여 줄 쉬운 문장 (2026-11-16 사용자 요청: 처음 투자하는 사람도 이해할 수 있게).

검증 규칙 문구(validate.py 의 message_ko)와 주의 이름(cautions_ko: '허용 낙폭 초과' 등)은 검증 상세 표·추천 라벨·모델 입력·리포트 숫자 검사·
프론트의 문구 해석이 함께 쓰므로 그대로 두고, 화면에 보일 문장을 여기서 따로 만든다. 문장은 결과의 구조화된 값(판정·기준·날짜·비중 쏠림 일수)으로
만들고, 각 문장에 무엇을 확인했는지 · 어느 시점의 결과인지 · 어떤 기준과 비교했는지 · 왜 알아 둘 필요가 있는지를 담는다.
저장된 리포트는 text_overrides 가 같은 함수로 계산한 문장을 덧씌운다 (모델을 부르지 않는다).
"""

from __future__ import annotations

import re
from typing import Any

from backend.analysis.m5_backtest_report import report_blocks as B

PREF_LABEL = {"low": "낮은 변동성 기준", "medium": "중간 변동성 기준", "high": "높은 변동성 기준"}


def _d(x: Any) -> str:
    s = str(x or "")[:10]
    return f"{s[:4]}년 {int(s[5:7])}월 {int(s[8:10])}일" if len(s) == 10 and s[4] == "-" else s


def _pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%"


def _cap(x: float) -> str:
    return f"{x:.0%}" if abs(x * 100 - round(x * 100)) < 1e-6 else f"{x:.1%}"


def _josa(word: str, pair: str) -> str:
    from backend.analysis.m5_backtest_report.report import (
        _josa as j,  # 함수 안에서 (순환 import 피함)
    )

    return j(word, pair)


class _Ctx:
    """문장에 필요한 값 묶음."""

    def __init__(self, R: dict[str, Any], chosen: str) -> None:
        self.R, self.chosen = R, chosen
        self.p = B.find(R, chosen)
        per = R["backtest"]["period"]
        self.start, self.end = _d(per.get("start")), _d(per.get("end"))
        sel = R.get("selection") or {}
        self.now = _d((sel.get("as_of_now") or {}).get("as_of"))
        self.bt = _d(((R.get("portfolio") or {}).get("backtest_spec") or {}).get("period", {}).get("as_of") or per.get("start"))
        bench = R["backtest"]["benchmark"]
        # 'SPY 매수보유 (동일 적립)' → 'SPY' (문장 안에서 짧게, 같은 날 같은 금액 가정은 문장에서 밝힌다 — 2026-11-16 사용자 예시 'SPY의 변동성')
        self.bench = re.sub(r"\s*매수보유\s*\(동일 적립\)\s*$", "", bench.get("name_ko") or "") or "비교지수"
        bm = (bench.get("metrics") or {})
        self.bench_vol = ((bm.get("risk") or {}).get("ann_vol"))
        self.bench_mdd = abs(float((bm.get("risk") or {}).get("max_drawdown") or 0)) if bm else None
        m = self.p.get("metrics") or {}
        self.vol = float(((m.get("risk") or {}).get("ann_vol")) or 0)
        self.mdd = abs(float(((m.get("risk") or {}).get("max_drawdown")) or 0))
        tr = (m.get("return") or {}).get("total_return")
        self.total_return = None if tr is None else float(tr)
        self.cagr = float(((m.get("return") or {}).get("cagr")) or 0)
        self.crit = (R.get("validation") or {}).get("criteria") or {}
        res = next((r for r in (R.get("validation") or {}).get("results") or [] if r["id"] == chosen), None) or \
            next((a for a in (R.get("validation") or {}).get("alternatives") or [] if a["id"] == chosen), {})  # fmt: skip
        self.checks = {c["rule"]: c for c in res.get("checks") or []}
        self.names = {t["ticker"]: t.get("name") or t["ticker"] for t in sel.get("table") or []}
        self.n_rebal = (m.get("trading") or {}).get("n_rebalances")
        self.comp = m.get("composition") or {}

    @property
    def rebal(self) -> bool:  # 시작일 매수 1회뿐이면 비중을 다시 맞추지 않은 것 (값이 없는 예전 결과는 리밸런싱이 있었다고 본다)
        return self.n_rebal is None or int(self.n_rebal) > 1


# ───────────────────────── 판정 규칙 ─────────────────────────

def _r1(c: _Ctx) -> str:
    tol = float(c.checks.get("R1", {}).get("threshold") or c.crit.get("max_drawdown") or 0)
    s = (f"{c.start}부터 {c.end}까지 백테스트에서 고점 대비 가장 크게 떨어진 폭(최대낙폭)은 {_pct(c.mdd)}로, "
         f"허용하기로 한 {_cap(tol)}보다 {(c.mdd - tol) * 100:.1f}%p 컸습니다.")
    if c.bench_mdd is not None:
        s += f" 같은 기간 같은 날 같은 금액을 {c.bench}에 넣었다면 최대낙폭은 {_pct(c.bench_mdd)}였습니다."
    return s + " 비슷한 하락이 다시 오면 감내하기로 한 손실보다 더 크게 떨어질 수 있습니다."


def _r2(c: _Ctx) -> str:
    ck = c.checks.get("R2") or {}
    target = float(c.crit.get("target_annual_return") or 0)
    msg = str(ck.get("message_ko") or "")
    m = re.match(r"투자기간 ([\d.]+)년 구간 (\d+)개 중 (\d+)%가", msg)
    if m:  # 투자기간 길이의 과거 구간 중 목표를 넘은 비율로 판정
        thr = float(ck.get("threshold") or 0.5)
        return (f"과거 주가에서 투자기간 {m.group(1)}년 길이의 구간 {m.group(2)}개를 살펴보니, 연 {_cap(target)} 목표 수익률을 넘은 구간은 {m.group(3)}%였습니다. "
                f"기준({_cap(thr)} 이상)에 못 미쳐 목표 수익률을 충족하지 못한 것으로 판정했습니다. 과거에도 목표에 못 미친 기간이 많았다는 뜻입니다.")
    return (f"{c.start}부터 {c.end}까지의 수익률을 1년 기준으로 환산한 값은 {_pct(c.cagr)}로, 목표한 연 {_cap(target)}보다 {(target - c.cagr) * 100:.1f}%p 낮았습니다. "
            "과거 성과로는 목표 수익률에 못 미쳤다는 뜻입니다.")


def _r3(c: _Ctx) -> str:
    from backend.analysis.m5_backtest_report.report import _vs_benchmark_display

    diff = (_vs_benchmark_display(c.R, c.p) or {}).get("cagr_diff") or f"{float(((c.p.get('metrics') or {}).get('vs_benchmark') or {}).get('excess_cagr') or 0) * 100:+.1f}%p"
    return (f"{c.start}부터 {c.end}까지 같은 날 같은 금액을 {c.bench}에 넣었다고 가정했을 때보다 연평균 수익률이 {str(diff).lstrip('+-−')} 낮았습니다. "
            "같은 기간 시장 대표 지수에 투자하는 것보다 성과가 낮았다는 뜻입니다.")


def _vol_sentence(c: _Ctx, tail: str) -> str | None:
    """변동성 기준과 전략의 변동성을 한 묶음으로. tail = 전략 변동성 뒤 말('로 기준보다 컸습니다' / '였습니다').
    예: 'SPY의 변동성을 1년 기준으로 환산한 값은 13.6%였습니다. 여기에 1.3을 곱한 17.7%가 이번 분석에 적용한 중간 변동성 기준이었고, 백테스트에서 계산한 전략의 변동성은 33.3%였습니다.'"""
    ck = c.checks.get("R7") or {}
    band = ck.get("threshold")
    if band is None:
        return None
    pref = PREF_LABEL.get(str(c.crit.get("volatility_preference")), "변동성 기준")
    strat = f"{c.start}부터 {c.end}까지 백테스트에서 계산한 전략의 변동성은 {_pct(c.vol)}{tail}"
    if c.bench_vol:
        mult = round(float(band) / float(c.bench_vol), 2)
        head = f"{c.bench}의 변동성을 1년 기준으로 환산한 값은 {_pct(float(c.bench_vol))}였습니다."
        if abs(mult - 1) < 1e-9:  # 배수 1 이면 비교지수 변동성 그대로가 기준
            return f"{head} 이 값을 그대로 이번 분석에 적용한 {pref}으로 썼고, {strat}"
        return f"{head} 여기에 {mult:g}을 곱한 {_pct(float(band))}가 이번 분석에 적용한 {pref}이었고, {strat}"
    return f"이번 분석에 적용한 {pref}은 연 {_pct(float(band))}였고, {strat}"


def _r7(c: _Ctx) -> str | None:
    t = _vol_sentence(c, "로 기준보다 컸습니다.")
    return None if t is None else t + " 변동성이 크면 평가금액이 짧은 기간에도 크게 오르내릴 수 있습니다."


def plain_rules(R: dict[str, Any], chosen: str) -> dict[str, str]:
    """미충족·주의로 보이는 판정 규칙(R1·R2·R3·R7)의 쉬운 문장 {규칙: 문장}. 해당하지 않는 규칙은 넣지 않는다."""
    c = _Ctx(R, chosen)
    out: dict[str, str] = {}
    if (ck := c.checks.get("R1")) and ck.get("ok") is False:
        out["R1"] = _r1(c)
    if (ck := c.checks.get("R2")) and ck.get("status") in ("warn", "fail"):
        out["R2"] = _r2(c)
    if (ck := c.checks.get("R3")) and ck.get("status") in ("warn", "fail"):
        out["R3"] = _r3(c)
    if (ck := c.checks.get("R7")) and ck.get("status") in ("warn", "fail") and (t := _r7(c)):
        out["R7"] = t
    return out


# ───────────────────────── 참고 ─────────────────────────

def _drift(c: _Ctx, kind: str) -> str:
    """리밸런싱 사이(또는 보유 기간 중) 한 종목·섹터 비중이 얼마나 올라갔는지 — 상한과 별도 점검 기준을 구분해서."""
    what = "종목" if kind == "stock" else "섹터"
    cap = float(c.crit.get("max_weight_per_stock" if kind == "stock" else "max_weight_per_sector") or 0)
    tol = float(c.crit.get("drift_tolerance") or 0.25)
    lim = cap * (1 + tol)
    top, who = c.comp.get(f"max_{kind}_weight"), c.comp.get("max_stock_weight_ticker" if kind == "stock" else "max_sector_weight_sector")
    nm = (c.names.get(who, who) if kind == "stock" else B.sector_ko(who)) if who else None
    head = ("정해진 날에 목표 비중을 맞춘 뒤, 다음 조정일까지 주가가 움직이면서 한 " + what + "의 비중이 커질 수 있습니다." if c.rebal
            else "처음 정한 비중으로 산 뒤 비중을 다시 맞추지 않아, 보유 기간 동안 주가가 움직이면서 한 " + what + "의 비중이 커질 수 있습니다.")
    if top is None:  # 최대 비중 자료가 없는 예전 결과
        over = [b.split(":", 1)[1] for b in c.comp.get("breaches") or [] if b.startswith(f"{kind}_cap:")]
        names = [c.names.get(t, t) if kind == "stock" else B.sector_ko(t) for t in over]
        body = f" 이번 백테스트에서는 {', '.join(names) + ' ' if names else ''}{what} 비중이 점검 기준(상한 {_cap(cap)}의 {1 + tol:g}배)을 넘은 적이 있었습니다."
    else:
        body = f" 이번 백테스트에서는 {nm + '의 ' if nm else ''}비중이 한때 전체 포트폴리오 평가금액의 {_pct(float(top))}까지 올랐습니다."
        body += (f" {_cap(cap)}는 비중을 정하는 날 한 {what}에 배정하는 최대 비율(상한)이고, {_pct(lim)}는 조정일 사이에 비중이 크게 벗어난 날을 세기 위한 별도 점검 기준입니다."
                 if lim < 1 - 1e-9 else f" {_cap(cap)}는 비중을 정하는 날 한 {what}에 배정하는 최대 비율(상한)입니다.")
        days, n = int(c.comp.get(f"days_above_{kind}_cap") or 0), c.comp.get("n_days")
        if days:
            body += f" {_cap(cap)}를 넘은 {_josa(what, '이가')} 하나라도 있던 날은 {f'{n}거래일 중 ' if n else ''}{days}일이었고"
            tdays = c.comp.get(f"days_above_{kind}_tol")
            over = [b.split(":", 1)[1] for b in c.comp.get("breaches") or [] if b.startswith(f"{kind}_cap:")]
            if tdays is not None and lim < 1 - 1e-9:
                ov = [c.names.get(t, t) if kind == "stock" else B.sector_ko(t) for t in over]
                who_tol = f"{ov[0]}의 비중이 " if len(ov) == 1 else (f"{', '.join(ov)} 중 하나라도 비중이 " if ov else "")
                body += (f", {who_tol}{_pct(lim)}를 넘은 날은 {int(tdays)}일이었습니다." if tdays else f", {_pct(lim)}를 넘은 날은 없었습니다.")
            else:
                body = body.rstrip("고") + "습니다."
    fix = (" 비중을 맞추는 간격을 짧게 하면 목표 비중에 더 자주 맞출 수 있습니다. 얼마나 달라지는지는 그 주기로 다시 계산해 확인할 수 있습니다." if c.rebal
           else " 정해진 날마다 비중을 다시 맞추면(리밸런싱) 목표 비중에 더 가깝게 유지할 수 있습니다. 얼마나 달라지는지는 그 방식으로 다시 계산해 확인할 수 있습니다.")
    return head + body + fix


def _r9(c: _Ctx) -> str | None:
    ck = c.checks.get("R9") or {}
    msg = str(ck.get("message_ko") or "")
    inv = ck.get("value")
    out = []
    if ck.get("ok") is False and inv is not None:
        inv = min(float(inv), 1.0)
        mc = float(c.crit.get("min_cash_ratio") or 0)
        s = f"{c.bt} 백테스트 시작일 구성은 투자금의 {inv:.0%}를 주식에 넣고 {max(0.0, 1 - inv):.0%}를 현금으로 두었습니다"
        s += f"(요청한 최소 현금 {_cap(mc)} 포함)." if mc > 1e-6 else "."
        if m := re.search(r"— 백테스트 시작일 구성은 (.+?)(?: · |$)", msg):
            s += f" {m.group(1).strip()}"
        s += " 현금은 이자 없이 계산해, 그만큼 수익과 손실이 모두 작게 나옵니다."
        out.append(s)
    if m := re.search(r"현금은 (?:최저 ([\d.]+%)(?:\((\S+?)\))?까지 내려가 )?최소 현금 (\S+?)보다 낮았던 날이 (?:(\d+)거래일 중 )?(\d+)일", msg):
        low = f" 최저 {m.group(1)}{f'({_d(m.group(2))})' if m.group(2) else ''}까지 내려갔고," if m.group(1) else ""
        span = "정해진 날에 비중을 맞춘 뒤 다음 조정일까지" if c.rebal else "처음 산 뒤 다시 맞추지 않아 보유 기간 동안"
        out.append(f"{span} 주가가 움직이면서 현금 비중이{low} 요청한 최소 현금 {m.group(3)}보다 낮았던 날이 {f'{m.group(4)}거래일 중 ' if m.group(4) else ''}{m.group(5)}일 있었습니다.")
    return " ".join(out) or None


def plain_info(R: dict[str, Any], chosen: str) -> list[str]:
    """「참고」 상자 문장: 판정 보류(짧은 평가 기간) · 비교지수 대비 낙폭 · 비중 쏠림 · 투자 비율·현금. 같은 내용은 한 번만."""
    c = _Ctx(R, chosen)
    out: list[str] = []
    r2, r7 = c.checks.get("R2") or {}, c.checks.get("R7") or {}
    held = []
    if r2.get("status") == "info" and r2.get("threshold") is not None:
        held.append(f"연 {_cap(float(c.crit.get('target_annual_return') or 0))} 목표 수익률")
    if r7.get("status") == "info" and r7.get("threshold") is not None:
        held.append("변동성 기준")
    if held:
        s = (f"{c.start}부터 {c.end}까지의 수익률은 {_pct(c.total_return)}였습니다. " if c.total_return is not None else "")
        s += f"평가 기간이 짧아 {_josa(held[0], '과와') + ' ' + held[1] if len(held) == 2 else held[0]}의 충족 여부는 판정하지 않았습니다."
        if "변동성 기준" in held and (vs := _vol_sentence(c, "였습니다.")):
            s += " 참고로 " + vs.replace(f"{c.start}부터 {c.end}까지 백테스트에서", "백테스트에서")  # 날짜는 앞 문장에 있다
        out.append(s)
    r1, r1b = c.checks.get("R1") or {}, c.checks.get("R1b") or {}
    if r1b.get("ok") is False and r1.get("ok") is not False and c.bench_mdd is not None:  # 허용 낙폭 미달이면 그 문장에 비교지수 낙폭이 이미 있다
        out.append(f"{c.start}부터 {c.end}까지 같은 날 같은 금액을 {c.bench}에 넣었다면 최대낙폭은 {_pct(c.bench_mdd)}였고, 이 전략은 {_pct(c.mdd)}로 더 크게 떨어졌습니다. 시장 전체보다 하락 위험이 컸다는 뜻입니다.")
    for rule, kind in (("R4b", "stock"), ("R5b", "sector")):
        if (c.checks.get(rule) or {}).get("ok") is False:
            out.append(_drift(c, kind))
    if (t := _r9(c)):
        out.append(t)
    return out


# ───────────────────────── 주의(cautions) ─────────────────────────

def plain_cautions(R: dict[str, Any], chosen: str, cautions: list[str]) -> list[dict[str, str]]:
    """verdict.cautions_ko 의 항목마다 쉬운 문장 [{key: 원래 주의, text: 쉬운 문장}]. key 는 화면이 같은 규칙의 미충족과 겹치지 않게 거르는 데 쓴다."""
    c = _Ctx(R, chosen)
    out = []
    for k in cautions:
        if k.startswith("시작일 재선정 없이"):
            t = (f"{c.bt} 백테스트에는 {c.now} 분석에서 고른 종목 목록을 그대로 썼습니다. "
                 "당시에는 알 수 없던 정보로 고른 목록이라 과거 성과가 실제보다 좋게 보일 수 있습니다.")
        elif k.startswith("허용 낙폭 초과"):
            t = _r1(c)
        elif k.startswith("목표수익 미달"):
            t = _r2(c)
        elif k.startswith("비교지수 하회"):
            t = _r3(c)
        elif m := re.match(r"종목 수 부족 \((\d+)/(\d+)개\)", k):
            t = (f"{c.bt} 백테스트 시작일에 담은 종목은 {m.group(1)}개로, 요청한 최소 {m.group(2)}개보다 적었습니다. "
                 "종목 수가 적으면 한 종목의 움직임이 결과를 크게 좌우합니다.")
        else:  # 투자 비율·위험·종목 차이 문장(report_blocks)은 이미 쉬운 말
            t = k
        t = t.rstrip()
        out.append({"key": k, "text": t if t.endswith((".", "!", "?")) else t + "."})
    return out


def plain_verdict_label(R: dict[str, Any], chosen: str) -> str | None:
    """'구성 불충분' 등 추천하지 않은 결과의 뜻."""
    vd = ((R.get("validation") or {}).get("recommended") or {}).get("verdict") or {}
    if vd.get("status") != "insufficient":
        return None
    mn = float(((R.get("validation") or {}).get("criteria") or {}).get("min_invested_for_recommendation") or 0.5)
    inv = vd.get("base_invested")
    s = (f"이번 분석에서 고른 구성은 투자금 가운데 주식에 넣을 수 있는 비율이 {float(inv):.0%}로, 기준 {_cap(mn)}보다 낮아 추천 대신 '구성 불충분'으로 표시했습니다."
         if inv is not None else "주식에 넣을 수 있는 비율이 기준보다 낮아 추천 대신 '구성 불충분'으로 표시했습니다.")
    return s + (f" {vd['cause_ko']}" if vd.get("cause_ko") else "")


# ───────────────────────── 기간 안내 ─────────────────────────

_NOTICE_RULES: list[tuple[re.Pattern[str], Any]] = [
    (re.compile(r"^백테스트 시작일 (\S+) 에는 테마 후보 중 선정 가능한 종목이 최소 종목 수\((\d+)\)보다 적어 시작을 (\S+) 로 옮김 \((\d+)개월 뒤, 선정 (\d+)종목\)"),
     lambda m: f"처음 정한 백테스트 시작일 {_d(m[1])}에는 조건에 맞는 종목이 최소 {m[2]}개보다 적어, 시작일을 {m[4]}개월 뒤인 {_d(m[3])}로 옮겼습니다. 옮긴 날에는 {m[5]}종목을 골랐습니다."),
    (re.compile(r"^백테스트 시작일 (\S+) 에는 선정 가능한 종목이 (\d+)개뿐이라 시작을 (\S+) 로 자동으로 옮김 \((\d+)개월 뒤, 선정 (\d+)종목\)"),
     lambda m: f"처음 정한 백테스트 시작일 {_d(m[1])}에는 조건에 맞는 종목이 {m[2]}개뿐이라, 시작일을 {m[4]}개월 뒤인 {_d(m[3])}로 옮겼습니다. 옮긴 날에는 {m[5]}종목을 골랐습니다."),
    (re.compile(r"^백테스트 시작일 (\S+) 에는 선정 가능한 종목이 (\d+)개\(최소 (\d+)개\)입니다\. ?(.*?) ?그 종목으로 시작합니다"),
     lambda m: f"백테스트 시작일 {_d(m[1])}에는 조건에 맞는 종목이 {m[2]}개로, 요청한 최소 {m[3]}개보다 적었습니다. "
               + (f"{m[4].rstrip(' ,')} " if m[4] else "") + f"그 {m[2]}종목으로 백테스트를 시작했습니다. 종목 수가 적으면 한 종목의 움직임이 결과를 크게 좌우합니다."),
    (re.compile(r"^(.+?) 선정에 쓰는 재무 지표 자료가 (\S+) 부터 있어 백테스트 시작을 (\S+) → (\S+) 로 옮김"),
     lambda m: f"{m[1]} 선정에 쓰는 재무 지표 자료가 {_d(m[2])}부터 있어, 백테스트 시작일을 {_d(m[3])}에서 {_d(m[4])}로 옮겼습니다."),
    (re.compile(r"^최소 시가총액 조건에 쓰는 시가총액 자료가 (\S+) 부터 있어 백테스트 시작을 (\S+) → (\S+) 로 옮김"),
     lambda m: f"최소 시가총액 조건에 쓰는 시가총액 자료가 {_d(m[1])}부터 있어, 백테스트 시작일을 {_d(m[2])}에서 {_d(m[3])}로 옮겼습니다."),
    (re.compile(r"^backtest start_date (\S+) clamped to data start (\S+)"),
     lambda m: f"가격 자료가 {_d(m[2])}부터 있어, 백테스트 시작일을 {_d(m[1])}에서 {_d(m[2])}로 옮겼습니다."),
    (re.compile(r"^backtest end_date (\S+) clamped to data end (\S+)"),
     lambda m: f"가격 자료가 {_d(m[2])}까지 있어, 백테스트 종료일을 {_d(m[1])}에서 {_d(m[2])}로 당겼습니다."),
]


def plain_notice(text: str) -> str:
    """기간 관련 알림(백테스트 시작일 이동·자료 시작·시작 시 종목 부족)을 쉬운 문장으로. 틀이 다르면 그대로."""
    for rx, fn in _NOTICE_RULES:
        if m := rx.match(text.strip()):
            return fn(m)
    return text


def plain_period_note(R: dict[str, Any], notes: list[str], actual_years: float | None, years_req: float | None) -> str | None:
    """period_note 의 쉬운 문장: 실제로 계산한 기간이 정해 둔 기간보다 짧으면 그 사실과 날짜, 그리고 기간 알림을 쉬운 말로."""
    sp = R["portfolio"]["backtest_spec"]["period"]
    parts = []
    if actual_years is not None and years_req is not None:
        parts.append(f"과거 주가로 투자 결과를 계산한 기간(백테스트)은 {_d(sp.get('start'))}부터 {_d(sp.get('end'))}까지 약 {actual_years:.1f}년으로, "
                     f"정해 둔 {years_req:g}년보다 짧습니다. 이 기간은 앞으로 투자하려는 기간과는 별개입니다.")
    parts += [plain_notice(n) for n in notes[:1]]
    return " ".join(parts) or None


def summary_patch(R: dict[str, Any], chosen: str) -> dict[str, Any]:
    """build_summary 와 같은 값의 쉬운 문장 묶음 — 새 리포트는 build_summary 가, 저장된 리포트는 text_overrides 가 summary 에 덧씌운다."""
    vd = ((R.get("validation") or {}).get("recommended") or {}).get("verdict")
    cautions = B.verdict_cautions(R, chosen, vd)
    return {"verdict": {"period_note_ko": B.period_note(R), "cautions_ko": cautions, "cautions_plain": plain_cautions(R, chosen, cautions),
                        **({"label_plain_ko": lp} if (lp := plain_verdict_label(R, chosen)) else {})},
            "validation": {"rules_plain_ko": plain_rules(R, chosen), "info_plain_ko": plain_info(R, chosen)}}  # fmt: skip

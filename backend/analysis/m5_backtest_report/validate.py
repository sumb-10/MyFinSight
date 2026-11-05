"""M5-03 규칙 검증·추천 (라운드 5 재설계: 최대낙폭은 합격 기준이 아니라 표시·순위 신호).

사용자 규칙: R1 최대낙폭(flag — 추천 여부를 가르지 않고 순위에 반영) · R2 목표수익(권장, 투자기간 구간 비율) · R3 비교지수 대비(권장) · R7 변동성(권장)
정보: R1b 비교지수 대비 낙폭 · R4b/R5b 드리프트 · R9 투자 비율. 코드 자체 점검(integrity): R4 종목 상한 · R5 섹터 상한 · R8 자료 무결성(hard).

추천은 항상 하나다. 순위 = (무결성 실패, 목표수익 미달, 비교지수 열위, 허용 낙폭 초과 구간(5%p 단위), 보수 성향이면 낙폭 맞춤안 우선, −Sharpe, 낙폭).
허용 낙폭은 사용자 입력값 그대로 보여 준다. 손실 시 매도(×0.8)·경험 없음(×0.9) 보정은 낙폭 맞춤안(dd_match_*, 11 단계가 만드는 정식 후보)의 목표에만 쓴다.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from backend.analysis.common.capacity import cap_cause_ko, cap_fix_ko, cap_limits
from backend.analysis.common.labels import sector_ko
from backend.analysis.m5_backtest_report.matched import share_pct
from backend.analysis.schemas.results import Validation
from backend.analysis.settings import AnalysisSettings

PREF_KO = {"low": "안정 성향", "medium": "중립 성향", "high": "적극 성향"}
NAMES_KO = {"equal_weight": "동일비중", "market_cap": "시가총액비중", "inverse_volatility": "역변동성비중", "min_variance": "최소분산"}


def excess_pp_ko(cagr: float | None, bench_cagr: float | None, ex: float | None) -> str:
    """비교지수 대비 초과 CAGR 을 보이는 자리수끼리 뺀 값으로 (034: 서술은 33.7 − (−2.1) = 35.8%p, 검증·추천 사유는 원값 35.9%p 라 한 리포트에 두 숫자).
    두 CAGR 이 없으면 원값."""
    if cagr is not None and bench_cagr is not None:
        return f"{round(float(cagr) * 100, 1) - round(float(bench_cagr) * 100, 1):+.1f}%p"
    return f"{float(ex or 0.0) * 100:+.1f}%p"


def check(rule, name, level, ok, value, threshold, msg):
    if level == "info":
        status = "info"
    elif level == "flag":
        status = "pass" if ok else "flag"
    else:
        status = "pass" if ok else ("fail" if level == "hard" else "warn")
    return {"rule": rule, "name_ko": name, "level": level, "status": status, "ok": bool(ok), "value": value, "threshold": threshold, "message_ko": msg}


def _rows_per_year(res, td: int) -> float:
    """백테스트 달력의 1년 행 수 (series_dates 의 실제 경과 기간으로). 없으면 설정값."""
    d = res.get("series_dates") or []
    try:
        days = (pd.Timestamp(d[-1]) - pd.Timestamp(d[0])).days
    except (IndexError, ValueError, TypeError):
        return float(td)
    return (len(d) - 1) / (days / 365.25) if days > 0 and len(d) > 1 else float(td)


def target_window_ratio(index, target_years: float, target: float, td: int):
    """투자기간 길이의 모든 과거 구간(하루씩 이동)에서 연환산 수익률이 목표 이상인 비율. 창이 투자기간보다 짧으면 None."""
    import numpy as np

    w = int(round(target_years * float(td)))
    idx = np.asarray(index, dtype=float)
    if w - 5 <= len(idx) - 1 < w:  # 휴장일 때문에 며칠 모자라면 같은 길이로 본다 (038: 3년을 다 돌렸는데 1행 모자라 '창이 투자기간보다 짧아' 라고 했다)
        w = len(idx) - 1
    if w < 5 or len(idx) - 1 < w:
        return None
    ann = (idx[w:] / idx[:-w]) ** (1.0 / target_years) - 1.0
    return {"ratio": float((ann >= target).mean()), "n": int(len(ann)), "median": float(np.median(ann)), "worst": float(ann.min())}


def _cap_pct(x: float) -> str:
    """상한 표시: 0.15 → '15%', 0.125 → '12.5%'."""
    return f"{round(float(x) * 100, 1):g}%"


def _drift_msg_ko(kind: str, comp: dict[str, Any], cap: float, drift_tol: float, over: list[str], rebal: bool = True) -> str:
    """R4b/R5b 문구: 리밸런싱 사이 실제 최대 비중을 상한·허용 폭(상한 × (1 + drift_tol))과 함께 사실대로.
    019·020·021·022: 섹터 비중이 상한을 넘었는데(019 정보기술 63.1% vs 55%, 020 금융 778거래일 중 501일 73% 초과) 허용 폭 안이라
    '상한 안에 머묾' 이라고 썼다. 값도 비중이 아니라 목표와의 차이(드리프트)였다.
    날 수는 어느 한 종목(섹터)이라도 넘은 날이다 (037: '최대 35.0%(JNJ) — 상한 27%를 넘은 날 752일' 을 JNJ 의 날 수로 옮겼다; JNJ 는 299일).
    rebal=False(매수 후 보유)면 '리밸런싱 사이'·'리밸런싱 주기를 줄이면' 대신 맞는 말로 (037)."""
    what = "종목" if kind == "stock" else "섹터"
    subj = f"{what}{'이' if kind == 'stock' else '가'}"
    names = over if kind == "stock" else [sector_ko(s) for s in over]
    span = "리밸런싱 사이" if rebal else "보유 기간 중"
    fix = "리밸런싱 주기를 줄이면 완화됩니다" if rebal else "리밸런싱을 하면 완화됩니다"
    top = comp.get(f"max_{kind}_weight")
    if top is None:  # 최대 비중이 없는 예전 결과: 예전 문구
        if not over:
            return f"{span} {what} 비중이 상한 안에 머묾"
        return f"{span}에 {what} 비중이 상한의 {1 + drift_tol:g}배를 넘은 적 있음" + (f" ({', '.join(names)})" if kind == "stock" else "") + f" — {fix}"
    who = comp.get("max_stock_weight_ticker" if kind == "stock" else "max_sector_weight_sector")
    head = f"{span} 최대 {what} 비중 {top:.1%}" + (f"({who if kind == 'stock' else sector_ko(who)})" if who else "")
    days, n = int(comp.get(f"days_above_{kind}_cap") or 0), comp.get("n_days")
    when = f"{n}거래일 중 {days}일" if n else f"{days}일"
    no_line = cap * (1 + drift_tol) >= 1 - 1e-9  # 허용 폭이 100% 이상이면 이 점검은 걸릴 수 없다
    lim = f"상한의 {1 + drift_tol:g}배" + ("" if no_line else f", {cap * (1 + drift_tol):.1%}")  # 100% 이상이면 숫자는 뜻이 없다 (021: '106.2%')
    above = f"상한 {_cap_pct(cap)}를 넘은 {subj} 있던 날이 {when}"
    if over:
        tol_days = comp.get(f"days_above_{kind}_tol")
        if tol_days is None:  # 허용 폭을 넘은 날 수가 없는 예전 결과: 예전 문구
            return f"{head} — {above}이고 허용 폭({lim})도 넘음 ({', '.join(names)}). {fix}"
        # 두 날 수를 따로 (031: '상한 10%를 넘은 날이 754거래일 중 747일이고 허용 폭(12.5%)도 넘음' 을 서술이 '12.5% 를 747일 넘었다' 로 옮겼다. 12.5% 를 넘은 날은 90일)
        # 허용 폭을 잡음 기준(0.05%p) 안에서만 넘었으면 실제로 넘은 폭을 적는다 (064: '0.05%p 안쪽으로만 넘음' 을 서술이 '허용 폭을 0.05%p 넘었다' 로 옮겼다 — 실제 0.04%p)
        ex = max(0.0, float(top) - cap * (1 + drift_tol))
        beyond = (f"허용 폭({lim})을 넘은 {subj} 있던 날은 {int(tol_days)}일" if tol_days
                  else f"허용 폭({lim})은 최대 {ex * 100:.2f}%p만 넘어 잡음 기준(0.05%p) 안이라 넘은 날로 세지 않음")  # fmt: skip
        return f"{head} — {above}, {beyond} ({', '.join(names)}). {fix}"
    if days and no_line:  # 031: 섹터 상한 90% 면 허용 폭이 112.5% 라 늘 통과인데 '허용 폭 안' 이라 써서 서술이 '허용 폭 안이었습니다' 라고 했다
        return f"{head} — {above} (허용 폭이 100% 이상이라 이 점검으로는 거르지 않음)"
    if days:
        return f"{head} — {above} 있었지만 허용 폭({lim}) 안"
    return f"{head} — 상한 {_cap_pct(cap)} 안에 머묾"


def evaluate_checks(p, crit, n_days, expected_rb, sector_of, drift_tol, short_window=False, *, bench=None, settings=None):
    """사용자 기준 규칙(checks)과 코드 자체 점검(integrity)을 나눠 돌려준다.

    checks  : R1 최대낙폭(flag) · R2 목표수익(권장) · R3 비교지수 대비(권장) · R7 변동성(권장) + 정보: R1b · R4b/R5b · R9
    integrity: R4 종목 상한 · R5 섹터 상한 · R8 자료 무결성 — 구성 단계가 보장하는 값이라 사용자 표에 안 보이고 실패하면 경고로만 올린다.
    돌려주는 값: (checks, status, n_fail, n_warn, integrity, n_flag). status 는 fail(무결성 실패만) / warn(주의·표시 있음) / pass.
    """
    m = p["metrics"]
    cks = []
    soft = "info" if short_window else "soft"
    bm = (bench or {}).get("metrics") or {}
    bench_name = (bench or {}).get("name_ko") or crit["benchmark"]
    bench_mdd = abs(bm["risk"]["max_drawdown"]) if bm else None
    bench_vol = bm["risk"]["ann_vol"] if bm else None
    tol = float(crit["max_drawdown"])
    # R1 최대낙폭 (표시) — 추천 여부를 가르지 않고 순위에 반영. 비교지수 낙폭을 같이 보여 준다
    mdd = abs(m["risk"]["max_drawdown"])
    ok1 = mdd <= tol + 1e-9
    cks.append(check("R1", "최대낙폭", "flag", ok1, mdd, tol,
                     f"최대낙폭 {mdd:.1%} vs 허용 {tol:.1%}" + (f" (같은 기간 {bench_name} {bench_mdd:.1%})" if bench_mdd is not None else "")
                     + ("" if ok1 else f" — 허용보다 {gap_pp(mdd - tol)} 큼")))  # fmt: skip
    if bench_mdd is not None:  # 두 낙폭이 같은 때 일어났는지 보지 않으므로 '시장 전체가 빠진 구간' 같은 원인은 말하지 않는다 (009: 시장 반등 뒤 업종 하락이었다)
        cks.append(check("R1b", "비교지수 대비 낙폭", "info", mdd <= bench_mdd, mdd, bench_mdd,
                         f"비교지수보다 낙폭이 {'작음' if mdd <= bench_mdd else '큼'} ({mdd:.1%} vs {bench_mdd:.1%})" + (" — 허용 낙폭은 넘었지만 같은 기간 비교지수의 최대낙폭보다는 작습니다" if (not ok1 and mdd <= bench_mdd) else "")))  # fmt: skip
    # R2 목표수익 (권장) — 투자기간 길이의 과거 구간 중 목표 달성 비율
    cg = m["return"]["cagr"] or 0.0
    td = float(crit.get("rows_per_year") or (settings.backtest.trading_days if settings else 252))  # 실제 달력의 1년 행 수 (합집합 달력이면 ≈259)
    tw = target_window_ratio(p["series"]["index"], float(crit.get("horizon_years") or 0), crit["target_annual_return"], td) if crit.get("horizon_years") else None
    min_ratio = settings.backtest.target_window_min_ratio if settings else 0.5
    short_note = " (창이 짧아 참고만)" if short_window else ""
    if tw is not None:
        ok2 = tw["ratio"] >= min_ratio
        cks.append(check("R2", "목표수익", soft, ok2, tw["ratio"], min_ratio,
                         f"투자기간 {crit['horizon_years']:g}년 구간 {tw['n']}개 중 {tw['ratio']:.0%}가 목표 연 {crit['target_annual_return']:.1%} 달성 "
                         f"(구간 수익률 중앙값 연 {tw['median']:+.1%}, 최악 연 {tw['worst']:+.1%}; 전체 CAGR {cg:.1%})" + short_note))  # fmt: skip
    else:
        cks.append(check("R2", "목표수익", soft, cg >= crit["target_annual_return"], cg, crit["target_annual_return"],
                         f"CAGR {cg:.1%} vs 목표 {crit['target_annual_return']:.1%} (백테스트 창이 투자기간 {crit.get('horizon_years', 0):g}년보다 짧아 전체 CAGR 로 판정)"
                         + (f" (기간 수익률 {m['return']['total_return']:+.1%}; 창이 짧아 참고만)" if short_window else "")))  # fmt: skip
    # R3 비교지수 대비 (권장)
    ex = m["vs_benchmark"]["excess_cagr"] or 0.0
    cks.append(check("R3", "비교지수 대비", "soft", ex > 0, ex, 0.0,
                     f"{crit['benchmark']} 대비 초과 CAGR {excess_pp_ko(m['return'].get('cagr'), (bm.get('return') or {}).get('cagr'), ex)}"))  # fmt: skip
    # R7 변동성 (권장) — 비교지수 변동성의 배수
    vol = m["risk"]["ann_vol"] or 0.0
    pref = crit["volatility_preference"]
    mult = (settings.backtest.vol_multipliers if settings else {"low": 1.0, "medium": 1.3, "high": None}).get(pref)
    if mult is None:
        cks.append(check("R7", "변동성 적합", "info", True, vol, None, f"연변동성 {vol:.1%}" + (f" (비교지수 {bench_vol:.1%})" if bench_vol else "") + f" — {PREF_KO.get(pref, pref)}은 변동성 상한을 두지 않습니다"))
    elif bench_vol:
        band = bench_vol * mult
        cks.append(check("R7", "변동성 적합", soft, vol <= band, vol, band,
                         f"연변동성 {vol:.1%} vs 비교지수 {bench_vol:.1%}의 {mult:g}배({PREF_KO.get(pref, pref)}) = {band:.1%}" + short_note))  # fmt: skip
    else:
        cks.append(check("R7", "변동성 적합", soft, vol <= crit["vol_band"], vol, crit["vol_band"], f"연변동성 {vol:.1%} vs {PREF_KO.get(pref, pref)} 상한 {crit['vol_band']:.1%}"))
    # 정보: 드리프트 (규칙이 아니라 리밸런싱 주기의 결과). 판정(ok)은 예전대로 '상한 × (1 + 허용 폭)' 을 넘었나지만, 문구·값은 실제 최대 비중으로
    comp = m["composition"]
    n_rb = (m.get("trading") or {}).get("n_rebalances")  # 시작일 매수 1회뿐이면 리밸런싱 없음(매수 후 보유) — 값이 없는 예전 결과는 리밸런싱이 있었다고 본다
    for rule, name, kind, cap, drift_key in (("R4b", "종목 비중 드리프트", "stock", float(crit["max_weight_per_stock"]), "max_weight_drift"),
                                             ("R5b", "섹터 비중 드리프트", "sector", float(crit["max_weight_per_sector"]), "max_sector_drift")):  # fmt: skip
        over = [b.split(":", 1)[1] for b in comp["breaches"] if b.startswith(f"{kind}_cap:")]
        top = comp.get(f"max_{kind}_weight")
        cks.append(check(rule, name, "info", not over, top if top is not None else comp[drift_key], cap * (1 + drift_tol),
                         _drift_msg_ko(kind, comp, cap, drift_tol, over, rebal=n_rb is None or int(n_rb) > 1)))  # fmt: skip
    # 정보: 투자 비율 (상한 때문에 남은 현금). 낙폭 맞춤안의 현금은 의도된 것이라 적용하지 않는다
    invested = float(sum(p["target_weights"].values()))
    min_inv = settings.backtest.min_invested_ratio if settings else 0.9
    if p.get("kind") not in ("alternative", "matched"):
        # 사용자가 정한 최소 현금은 상한 탓이 아니다 (예전: 최소 현금 15% 인 요청마다 '상한 때문에 돈을 다 넣지 못했다' 고 써서
        # 리포트·다음 행동이 '상한을 풀라' 고 권했다). 투자 가능 비율(1 − 최소 현금) 대비 부족분만 상한 탓으로 본다.
        min_cash = float(crit.get("min_cash_ratio") or 0.0)
        expected = 1.0 - min_cash
        gap = max(0.0, expected - invested)
        ok = gap <= (1 - min_inv) + 1e-6
        # 보이는 값은 0~100% 로 (030: 투자 비율 1.000003 이 '투자 100%, 현금 -0%' 로 보였다)
        msg = f"투자 {min(invested, 1.0):.0%}, 현금 {max(0.0, 1 - invested):.0%}" + (f" (요청한 최소 현금 {_cap_pct(min_cash)} 포함)" if min_cash > 1e-6 else "")
        if not ok:  # 원인을 사실대로(common/capacity), 백테스트 시작일 구성이라고 밝힌다 (011: 섹터 상한 100% 인데 '종목·섹터 상한 때문' 이라 썼고, 지금 구성의 현금처럼 읽혔다)
            cnt: dict[str, int] = {}
            for t, x in p["target_weights"].items():
                if x > 1e-9:
                    cnt[sector_of(t)] = cnt.get(sector_of(t), 0) + 1
            stock_cap, sector_cap = float(crit["max_weight_per_stock"]), float(crit["max_weight_per_sector"])
            lim = cap_limits(cnt, stock_cap, sector_cap, expected)
            cause = cap_cause_ko(lim, stock_cap, sector_cap, clause=True)
            msg += (f" — 백테스트 시작일 구성은 {cause} {gap:.0%}를 더 넣지 못했습니다. {cap_fix_ko(lim)}" if cause
                    else f" — 백테스트 시작일 구성은 {gap:.0%}를 더 넣지 못했습니다 (종목·섹터 상한 때문은 아닙니다)")  # fmt: skip
        # 리밸런싱 사이에 현금이 최소 현금 아래로 내려간 날 (031: 모두 에너지 종목이라 섹터 비중이 90% 를 넘은 565일은 현금이 10% 아래였는데
        # 서술은 리밸런싱일 목표대로 '현금 10.0%' 라고만 했다)
        low_days = int(comp.get("days_cash_below_min") or 0)
        if min_cash > 1e-6 and low_days > 0:
            lo, lo_d, nd = comp.get("min_cash_weight"), comp.get("min_cash_date"), comp.get("n_days")
            rebal = int((m.get("trading") or {}).get("n_rebalances") or 0) > 1  # 시작일 1회뿐(매수 후 보유)이면 다시 맞추는 날이 없다
            low = (f"최저 {max(0.0, float(lo)):.1%}" + (f"({lo_d})" if lo_d else "") + "까지 내려가 ") if lo is not None else ""
            msg += (f" · {'리밸런싱 사이 ' if rebal else ''}현금은 {low}최소 현금 {_cap_pct(min_cash)}보다 낮았던 날이 " + (f"{nd}거래일 중 {low_days}일" if nd else f"{low_days}일")
                    + (" (리밸런싱 때 다시 맞춤)" if rebal else " (시작 뒤 리밸런싱이 없어 다시 맞추지 않음)"))  # fmt: skip
        cks.append(check("R9", "투자 비율", "info", ok, invested, round(expected - (1 - min_inv), 6), msg))  # fmt: skip
    elif p.get("kind") == "matched":
        # 맞춤안은 현금을 일부러 늘린 구성이라 투자 비율 비교는 하지 않지만, 현금이 최소 현금 아래로 내려간 날은 다른 구성처럼 밝힌다
        # (061: 추천 맞춤안의 현금이 752일 중 485일 최소 현금 10% 아래였는데 R9 를 통째로 건너뛰어 리포트 어디에도 없었다)
        min_cash = float(crit.get("min_cash_ratio") or 0.0)
        low_days = int(comp.get("days_cash_below_min") or 0)
        if min_cash > 1e-6 and low_days > 0:
            lo, lo_d, nd = comp.get("min_cash_weight"), comp.get("min_cash_date"), comp.get("n_days")
            rebal = int((m.get("trading") or {}).get("n_rebalances") or 0) > 1
            low = (f"최저 {max(0.0, float(lo)):.1%}" + (f"({lo_d})" if lo_d else "") + "까지 내려가 ") if lo is not None else ""
            msg = (f"주식 {min(invested, 1.0):.1%} + 현금 {max(0.0, 1 - invested):.1%}로 시작했지만 {'리밸런싱 사이 ' if rebal else ''}현금은 {low}"
                   f"최소 현금 {_cap_pct(min_cash)}보다 낮았던 날이 " + (f"{nd}거래일 중 {low_days}일" if nd else f"{low_days}일")
                   + (" (리밸런싱 때 다시 맞춤)" if rebal else " (시작 뒤 리밸런싱이 없어 다시 맞추지 않음)"))  # fmt: skip
            cks.append(check("R9", "투자 비율", "info", True, invested, round(1.0 - min_cash, 6), msg))  # fmt: skip
    # 코드 자체 점검 (사용자 표 밖)
    integ = []
    rb_cps = [cp for cp in p["checkpoints"] if cp["kind"] == "rebalance"] or p["checkpoints"][:1]
    rb_max = max(max(cp["weights"]["after"].values()) for cp in rb_cps)
    integ.append(check("R4", "종목 상한(리밸런싱일)", "hard", rb_max <= crit["max_weight_per_stock"] + 1e-3, rb_max, crit["max_weight_per_stock"],
                       f"리밸런싱일 최대 종목 비중 {rb_max:.1%} vs 상한 {crit['max_weight_per_stock']:.0%}"))  # fmt: skip
    sec_rb_max = 0.0
    for cp in rb_cps:
        sums: dict[str, float] = {}
        for t, w in cp["weights"]["after"].items():
            sums[sector_of(t)] = sums.get(sector_of(t), 0.0) + w
        sec_rb_max = max(sec_rb_max, max(sums.values()))
    integ.append(check("R5", "섹터 상한(리밸런싱일)", "hard", sec_rb_max <= crit["max_weight_per_sector"] + 1e-3, sec_rb_max, crit["max_weight_per_sector"],
                       f"리밸런싱일 최대 섹터 비중 {sec_rb_max:.1%} vs 상한 {crit['max_weight_per_sector']:.0%}"))  # fmt: skip
    ok8 = all(len(v) == n_days for v in p["series"].values()) and m["trading"]["n_rebalances"] == expected_rb
    integ.append(check("R8", "자료 무결성", "hard", ok8, float(len(p["series"]["index"])), float(n_days), f"시계열 {len(p['series']['index'])}일, 리밸런싱 {m['trading']['n_rebalances']}회"))
    n_fail = sum(c["status"] == "fail" for c in cks) + sum(c["status"] == "fail" for c in integ)  # 자체 점검 실패도 안전하게 실패로 (버그 신호)
    n_warn = sum(c["status"] == "warn" for c in cks)
    n_flag = sum(c["status"] == "flag" for c in cks)
    return cks, ("fail" if n_fail else ("warn" if (n_warn or n_flag) else "pass")), n_fail, n_warn, integ, n_flag


def row_of(p, status, extra=None):
    m, h = p["metrics"], p["headline"]
    return {"id": p["id"], "name_ko": p.get("name_ko", p["id"]), "kind": p["kind"], "cagr": m["return"]["cagr"], "ann_vol": m["risk"]["ann_vol"],
            "sharpe": h["sharpe"], "max_drawdown": m["risk"]["max_drawdown"], "final_value_usd": h["final_value_usd"], "irr_annual": p["money"]["irr_annual"],
            "excess_cagr": m["vs_benchmark"]["excess_cagr"] if p["kind"] != "benchmark" else 0.0, "view_hit_ratio": h["view_hit_ratio"], "status": status,
            **(extra or {})}  # fmt: skip


def gap_pp(x: float) -> str:
    """낙폭 차이 %p — 0.05%p 아래는 소수 둘째 자리까지 (070: 0.03%p 초과를 '허용보다 0.0%p 큼' 이라고 적었다)."""
    x = max(0.0, float(x))
    return f"{x * 100:.2f}%p" if 0 < x < 0.0005 else f"{x:.1%}p"


def cautious_reason_ko(req: dict[str, Any]) -> str:
    """보수적으로 다룰 성향 조건 중 실제로 해당하는 것만 (F14: 둘 중 하나만 해당해도 '손실 시 매도·투자 경험 없음' 을 다 적었다)."""
    return " · ".join(x for x, on in (("손실 시 매도", req["risk"].get("loss_reaction") == "sell"),
                                      ("투자 경험 없음", (req.get("profile") or {}).get("investment_experience") == "none")) if on)


def dd_bucket(mdd: float, tol: float, size: float) -> int:
    """허용 낙폭 초과분을 size(5%p) 단위 구간으로. 안이면 0."""
    return int(math.ceil(max(0.0, abs(mdd) - tol) / size - 1e-9)) if size > 0 else int(abs(mdd) > tol)


def tie_levels(vals: dict[str, float], tol: float, *, higher_first: bool) -> dict[str, int]:
    """값이 tol 안으로 붙은 것끼리 같은 단계 (단계의 첫 값 기준). 소수 4자리 반올림은 경계에서 1e-6 차이를 다른 값으로 갈랐다
    (055: 14개 후보가 같은 비중·성과인데 MDD 0.300550 vs 0.300551 이 0.3005 / 0.3006 으로 갈려 사용자 기준 비중이 졌다)."""
    out: dict[str, int] = {}
    lvl, first = -1, None
    for k, v in sorted(vals.items(), key=lambda x: -x[1] if higher_first else x[1]):
        if first is None or abs(v - first) > tol:
            lvl, first = lvl + 1, v
        out[k] = lvl
    return out


def rank_key(row: dict[str, Any], st: dict[str, str], *, integrity_failed: bool, tol: float, bucket_size: float, cautious: bool,
             baseline_id: str | None = None, levels: dict[str, tuple[int, int]] | None = None) -> tuple:  # fmt: skip
    """추천 순위 키 (작을수록 좋음): 무결성 실패 → 목표수익 미달 → 비교지수 열위 → 허용 낙폭 초과 구간 → (보수 성향) 낙폭 맞춤안 우선 → Sharpe 높음 → 낙폭 작음
    → (동점) 사용자가 고른 기준 비중 쪽.
    R2/R3 는 'pass' 만 충족으로 본다 (정보로 바뀐 짧은 창은 모두 같은 등급).
    Sharpe·낙폭은 소수 4자리로 반올림해 비교한다: 종목이 1~2개라 규칙끼리 비중이 똑같으면 성과도 같은데, 예전에는 1e-6 수준의 계산 잡음이
    순위를 정해 사용자가 고르지 않은 규칙이 추천됐다 (2026-11 시나리오 002: 역변동성비중을 골랐는데 같은 성과의 동일비중이 앞)."""
    mdd = abs(row.get("max_drawdown") or 0.0)
    sharpe = row.get("sharpe")
    mine = bool(baseline_id) and (row.get("id") in (baseline_id, f"wf_{baseline_id}") or row.get("base_id") in (baseline_id, f"wf_{baseline_id}"))
    # levels(후보 전체로 센 Sharpe·낙폭 단계)가 있으면 그것으로, 없으면 예전처럼 반올림 (하나만 볼 때)
    sh_key, mdd_key = levels[row["id"]] if levels and row.get("id") in levels else (-round(sharpe if sharpe is not None else -9.0, 4), round(mdd, 4))
    return (bool(integrity_failed), st.get("R2") != "pass", st.get("R3") != "pass", dd_bucket(mdd, tol, bucket_size),
            not (cautious and row.get("kind") == "matched"), sh_key, mdd_key, not mine)  # fmt: skip


def verdict_for(*, mdd: float, tol: float, st: dict[str, str], base_invested: float, min_invested: float, name_ko: str,
                n_holdings: int | None = None, min_holdings: int | None = None, cause_ko: str | None = None, lookahead: bool = False) -> dict[str, Any]:  # fmt: skip
    cautions = []
    if lookahead:  # 시작일 재선정 없이 지금 목록으로 과거를 평가 — 초록 '추천' 만 보이면 초보자가 성과를 그대로 믿는다 (054)
        cautions.append("시작일 재선정 없이 지금 목록으로 평가(성과가 실제보다 좋게 보일 수 있음)")
    if mdd > tol + 1e-9:
        cautions.append(f"허용 낙폭 초과 ({gap_pp(mdd - tol)})")
    if st.get("R2") == "warn":
        cautions.append("목표수익 미달")
    if st.get("R3") == "warn":
        cautions.append("비교지수 하회")
    if n_holdings is not None and min_holdings and n_holdings < min_holdings:  # R6: 최소 종목 수 미달은 숨기지 않는다 (Module3)
        cautions.append(f"종목 수 부족 ({n_holdings}/{min_holdings}개)")
    if base_invested < min_invested - 1e-4:  # 반올림 잡음으로 경계(50%)에서 라벨이 뒤집히지 않게 1e-4
        # '구성 불충분' 이어도 다른 주의를 지우지 않는다 (F18: 낙폭 초과·비교지수 하회가 라벨에서 사라졌다)
        status, head = "insufficient", "구성 불충분" + (f"(주의: {' · '.join(cautions)})" if cautions else "")
    elif cautions:
        status, head = "recommended_warn", f"추천(주의: {' · '.join(cautions)})"
    else:
        status, head = "recommended", "추천"
    return {"status": status, "label_ko": f"{head}: {name_ko}", "head_ko": head, "cautions_ko": cautions, "base_invested": round(base_invested, 6),
            "cause_ko": cause_ko}  # fmt: skip


def insufficient_cause(p: dict[str, Any], crit: dict[str, Any], counts: dict[str, int]) -> str:
    """투자 비율이 낮은 이유를 사실대로 (예전 고정 문구 '후보 종목이 모자라' 는 섹터 상한·최소 현금 때문인 경우에도 나왔다, N-B1-8)."""
    w = p.get("target_weights") or {}
    inv, n = float(sum(w.values())), sum(1 for x in w.values() if x > 1e-9)
    mc = float(crit.get("min_cash_ratio") or 0.0)
    stock_cap, sector_cap = float(crit["max_weight_per_stock"]), float(crit["max_weight_per_sector"])
    lim = cap_limits(counts or {"": n}, stock_cap, sector_cap if counts else 1.0, 1 - mc)
    if lim["kind"] == "stock":
        return f"선정 종목이 {n}개뿐이라 종목당 상한 {stock_cap:.0%}로는 {min(1.0, n * stock_cap):.0%}까지만 투자됩니다"
    if lim["kind"] in ("sector", "both"):
        top = max(counts.items(), key=lambda x: x[1])
        # 두 상한이 다 걸리면 섹터 상한만 올려서는 다 담지 못한다는 것도 적는다 (002: 2종목 × 25% 인데 섹터 상한 35% 만 탓했다)
        both = f" (섹터 상한을 올려도 {n}종목 × 종목당 상한 {stock_cap:.0%}라 {lim['stock_room']:.0%}까지)" if lim["kind"] == "both" else ""
        return f"선정 종목이 {top[0]} 등 적은 섹터에 몰려 섹터당 상한 {sector_cap:.0%} 때문에 {inv:.0%}만 투자됩니다{both}"
    if mc >= 0.5:
        return f"요청한 최소 현금 비율이 {mc:.0%}입니다"
    return f"투자 비율이 {inv:.0%}입니다"


def validate(res: dict[str, Any], targets: dict[str, Any], intent: dict[str, Any], req: dict[str, Any], ctx: dict[str, Any], sector_of,
             settings: AnalysisSettings, *, max_drawdown_override: float | None = None, alternatives: bool = True) -> dict[str, Any]:  # fmt: skip
    """포트폴리오마다 규칙을 평가하고 **항상** 하나를 추천한다. `alternatives` 인자는 호환용(현금 혼합안은 더 만들지 않는다)."""
    bs = settings.backtest
    vc, cons = intent["validation_criteria"], req["constraints"]
    tol_user = float(max_drawdown_override if max_drawdown_override is not None else req["risk"]["max_drawdown_tolerance"])
    match_target = float((intent.get("risk_params") or {}).get("effective_max_drawdown") or tol_user)
    cautious = req["risk"].get("loss_reaction") == "sell" or (req.get("profile") or {}).get("investment_experience") == "none"
    # 투자기간은 확정된 요청값이 먼저 (013: 요청 10년인데 02 LLM 이 아이디어의 '약 15년' 을 적어 R2 가 '투자기간 15년' 구간으로 판정했다)
    crit = {"max_drawdown": tol_user, "input_max_drawdown": tol_user, "match_target": match_target, "cautious": cautious,
            "horizon_years": float(req["horizon"].get("target_years") or vc.get("horizon_years") or 0),
            "target_annual_return": vc["target_annual_return"], "benchmark": vc["benchmark"], "volatility_preference": intent["risk_params"]["volatility_preference"],
            "vol_band": bs.vol_bands[intent["risk_params"]["volatility_preference"]], "max_weight_per_stock": cons["max_weight_per_stock"],
            "max_weight_per_sector": cons["max_weight_per_sector"], "min_holdings": cons["num_holdings"]["min"], "drift_tolerance": bs.drift_tolerance,
            "min_cash_ratio": float(cons.get("min_cash_ratio", 0) or 0),
            "rows_per_year": _rows_per_year(res, bs.trading_days),
            "min_invested_for_recommendation": bs.min_invested_for_recommendation, "dd_excess_bucket": bs.dd_excess_bucket}  # fmt: skip
    n_days = res["period"]["trading_days"]
    expected_rb = res["portfolios"][0]["metrics"]["trading"]["n_rebalances"]
    results, table, warnings = [], [], []
    short_window = not res["period"].get("annualized_reliable", True)
    if short_window:
        warnings.append(f"window of {n_days} trading days < {bs.min_annualize_days}: R2/R7 are informational only (annualized figures unreliable)")
    integrity_failed: list[str] = []
    failed_ids: set[str] = set()
    for p in res["portfolios"]:
        cks, status, n_fail, n_warn, integ, n_flag = evaluate_checks(p, crit, n_days, expected_rb, sector_of, bs.drift_tolerance, short_window, bench=res["benchmark"], settings=settings)
        results.append({"id": p["id"], "kind": p["kind"], "status": status, "checks": cks, "integrity": integ, "n_fail": n_fail, "n_warn": n_warn, "n_flag": n_flag})
        table.append(row_of(p, status, {"n_fail": n_fail, "n_warn": n_warn, "n_flag": n_flag, "cash_ratio": p.get("cash_ratio"), "base_id": p.get("base_id")}))
        bad = [f"{p['id']}:{c['rule']}" for c in integ if c["status"] == "fail"]
        integrity_failed += bad
        if bad:
            failed_ids.add(p["id"])
    if integrity_failed:
        warnings.append(f"internal integrity checks failed (caps or data length): {integrity_failed[:6]}")
    for b in res.get("benchmarks", [res["benchmark"]]):
        table.append(row_of(b, "n/a", {"n_fail": 0, "n_warn": 0, "n_flag": 0}))

    # ── 추천 (항상 하나) ──
    ports = {p["id"]: p for p in res["portfolios"]}
    by_id = {r["id"]: {c["rule"]: c["status"] for c in r["checks"]} for r in results}
    cands = [t for t in table if t["kind"] != "benchmark"]
    base = next(t for t in table if t["id"] == targets["baseline"]["id"])

    lv_s = tie_levels({t["id"]: (t["sharpe"] if t["sharpe"] is not None else -9.0) for t in cands}, 5e-5, higher_first=True)
    lv_m = tie_levels({t["id"]: abs(t.get("max_drawdown") or 0.0) for t in cands}, 5e-5, higher_first=False)
    levels = {i: (lv_s[i], lv_m[i]) for i in lv_s}

    def key(t):
        return rank_key(t, by_id.get(t["id"], {}), integrity_failed=t["id"] in failed_ids, tol=tol_user, bucket_size=bs.dd_excess_bucket, cautious=cautious,
                        baseline_id=targets["baseline"]["id"], levels=levels)  # fmt: skip

    ranked = sorted(cands, key=key)
    best = ranked[0]
    st = by_id.get(best["id"], {})
    pb = ports[best["id"]]
    mdd_b = abs(best["max_drawdown"] or 0.0)
    base_id = pb.get("base_id") or best["id"]
    base_p = ports.get(base_id) or pb
    base_invested = float(sum(base_p["target_weights"].values()))
    n_hold = sum(1 for x in base_p["target_weights"].values() if x > 1e-9)
    counts: dict[str, int] = {}
    for t, x in base_p["target_weights"].items():
        if x > 1e-9:
            counts[sector_of(t)] = counts.get(sector_of(t), 0) + 1
    cause = insufficient_cause(base_p, crit, counts) if base_invested < bs.min_invested_for_recommendation - 1e-4 else None
    verdict = verdict_for(mdd=mdd_b, tol=tol_user, st=st, base_invested=base_invested, min_invested=bs.min_invested_for_recommendation, name_ko=best["name_ko"],
                          n_holdings=n_hold, min_holdings=int(crit.get("min_holdings") or 0), cause_ko=cause,
                          lookahead=((targets.get("backtest_spec") or {}).get("selection") or {}).get("source") == "original")  # fmt: skip
    # 사유: 사실만 (정보 규칙은 '만족'으로 세지 않고, 음수 Sharpe 에 '가장 높음'이라 쓰지 않는다)
    parts = [f"후보 {len(cands)}개 중 1위"]  # ' · ' 로 이어 붙이므로 마침표를 찍지 않는다 ('1위. ·' 문장부호 중복)
    tgt = crit["target_annual_return"]
    if st.get("R2") == "pass":
        parts.append(f"목표수익(연 {tgt:.1%}) 충족")
    elif st.get("R2") == "warn":
        parts.append(f"목표수익(연 {tgt:.1%}) 미달")
    else:
        parts.append("목표수익은 창이 짧아 참고만")
    ex = best["excess_cagr"] or 0.0
    parts.append(f"{crit['benchmark']} 대비 초과 CAGR {excess_pp_ko(best.get('cagr'), (((res.get('benchmark') or {}).get('metrics') or {}).get('return') or {}).get('cagr'), ex)}")
    parts.append(f"최대낙폭 {mdd_b:.1%} vs 허용 {tol_user:.1%}" + (f" (여유 {gap_pp(tol_user - mdd_b)})" if mdd_b <= tol_user + 1e-9 else f" ({gap_pp(mdd_b - tol_user)} 초과)"))
    sharpes = [t["sharpe"] for t in cands if t["sharpe"] is not None]
    s = best["sharpe"]
    if s is not None:
        top = s >= max(sharpes) - 1e-12
        # 순위 키와 같은 반올림(소수 4자리)으로 동점을 센다 (049: 후보 14개의 Sharpe 가 0.388246~0.388249 로 같고 사용자가 고른 기준 비중이 1위였는데
        # 'Sharpe 0.39로 가장 높음' 이라고 했다)
        same = [t for t in cands if key(t)[:-1] == key(best)[:-1]]  # 마지막 키(사용자 기준 비중)만 다른 후보
        n_sh = sum(1 for t in cands if t["sharpe"] is not None and lv_s.get(t["id"]) == lv_s.get(best["id"]))
        if len(same) > 1:
            mine = not key(best)[-1]
            parts.append(f"Sharpe {s:.2f} — 성과가 같은 후보 {len(same)}개 중 " + ("사용자가 고른 기준 비중이라 1위" if mine else "하나"))
        elif top and n_sh > 1:
            parts.append(f"Sharpe {s:.2f} — 같은 값 {n_sh}개 중 최대낙폭이 가장 작음")
        else:
            parts.append(f"Sharpe {s:.2f}로 가장 높음" if top and s > 0 else (f"Sharpe {s:.2f} (음수, 가장 덜 나쁨)" if top else f"Sharpe {s:.2f}"))
    if pb.get("kind") == "matched":
        inv = float(sum(pb["target_weights"].values()))
        base_name = (ports.get(base_id) or {}).get("name_ko") or NAMES_KO.get(base_id, base_id)
        # 주식 비중은 맞춤안 이름과 같은 자리수로 (015: 98.5% 를 '99%로 줄여' 라고 써 같은 리포트의 98.5%·1.5% 와 달랐다)
        parts.append(f"{base_name}의 주식 비중을 {share_pct(inv)}로 줄여 과거 최대낙폭을 목표 {match_target:.1%} 안에 맞춘 구성")
        if cautious:
            # 해당하는 조건만 적고, 이 규칙이 실제로 1위를 바꿨을 때만 쓴다 (F14·N-B1-1: 예전에는 둘 중 하나만 해당해도 둘 다 적고, 순위가 같아도 적었다)
            why = cautious_reason_ko(req)
            plain = min(cands, key=lambda t: rank_key(t, by_id.get(t["id"], {}), integrity_failed=t["id"] in failed_ids, tol=tol_user,
                                                       bucket_size=bs.dd_excess_bucket, cautious=False, baseline_id=targets["baseline"]["id"], levels=levels))  # fmt: skip
            if plain["id"] != best["id"]:
                parts.append(f"{why} 성향이라 같은 조건이면 낙폭 맞춤안을 우선했습니다 (이 규칙이 없으면 {plain['name_ko']})")
    parts.append(f"CAGR {best['cagr']:.1%}, 최종 평가금액 {best['final_value_usd']:,.0f} USD.")
    reason = " · ".join(parts[:-1]) + " · " + parts[-1] if len(parts) > 1 else parts[0]
    recommended = {"id": best["id"], "status": best["status"], "verdict": verdict, "rank_key": [int(x) if isinstance(x, bool) else x for x in key(best)],
                   "n_candidates": len(cands), "headroom": round(tol_user - mdd_b, 6), "reason_ko": reason,
                   "vs_baseline": {"cagr_diff": round(best["cagr"] - base["cagr"], 6), "mdd_diff": round(best["max_drawdown"] - base["max_drawdown"], 6),
                                   "sharpe_diff": round((best["sharpe"] or 0) - (base["sharpe"] or 0), 6)},
                   "ranking": [t["id"] for t in ranked]}  # fmt: skip
    infeas = targets["backtest_spec"]["selection"].get("infeasibility")
    summary = {"n_pass": sum(r["status"] == "pass" for r in results), "n_warn": sum(r["status"] == "warn" for r in results),
               "n_fail": sum(r["status"] == "fail" for r in results), "n_flag": sum(1 for r in results if r["n_flag"]),
               "n_candidates": len(cands), "n_matched": sum(1 for r in results if r["kind"] == "matched"), "alternative_note": None}  # fmt: skip
    out = Validation(request_id=res["request_id"], criteria={**crit, "selection_infeasibility": infeas}, results=results,
                     comparison_table=table, recommended=recommended, alternatives=[], chosen_id=best["id"], summary=summary, warnings=warnings)  # fmt: skip
    return out.model_dump(mode="json")

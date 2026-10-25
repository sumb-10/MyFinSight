"""M5-03 규칙 검증·추천 (라운드 5 재설계: 최대낙폭은 합격 기준이 아니라 표시·순위 신호).

사용자 규칙: R1 최대낙폭(flag — 추천 여부를 가르지 않고 순위에 반영) · R2 목표수익(권장, 투자기간 구간 비율) · R3 비교지수 대비(권장) · R7 변동성(권장)
정보: R1b 비교지수 대비 낙폭 · R4b/R5b 드리프트 · R9 투자 비율. 코드 자체 점검(integrity): R4 종목 상한 · R5 섹터 상한 · R8 자료 무결성(hard).

추천은 항상 하나다. 순위 = (무결성 실패, 목표수익 미달, 비교지수 열위, 허용 낙폭 초과 구간(5%p 단위), 보수 성향이면 낙폭 맞춤안 우선, −Sharpe, 낙폭).
허용 낙폭은 사용자 입력값 그대로 보여 준다. 손실 시 매도(×0.8)·경험 없음(×0.9) 보정은 낙폭 맞춤안(dd_match_*, 11 단계가 만드는 정식 후보)의 목표에만 쓴다.
"""

from __future__ import annotations

import math
from typing import Any

from backend.analysis.schemas.results import Validation
from backend.analysis.settings import AnalysisSettings

PREF_KO = {"low": "안정 성향", "medium": "중립 성향", "high": "적극 성향"}
NAMES_KO = {"equal_weight": "동일비중", "market_cap": "시가총액비중", "inverse_volatility": "역변동성비중", "min_variance": "최소분산"}


def check(rule, name, level, ok, value, threshold, msg):
    if level == "info":
        status = "info"
    elif level == "flag":
        status = "pass" if ok else "flag"
    else:
        status = "pass" if ok else ("fail" if level == "hard" else "warn")
    return {"rule": rule, "name_ko": name, "level": level, "status": status, "ok": bool(ok), "value": value, "threshold": threshold, "message_ko": msg}


def target_window_ratio(index, target_years: float, target: float, td: int):
    """투자기간 길이의 모든 과거 구간(하루씩 이동)에서 연환산 수익률이 목표 이상인 비율. 창이 투자기간보다 짧으면 None."""
    import numpy as np

    w = int(round(target_years * td))
    idx = np.asarray(index, dtype=float)
    if w < 5 or len(idx) - 1 < w:
        return None
    ann = (idx[w:] / idx[:-w]) ** (1.0 / target_years) - 1.0
    return {"ratio": float((ann >= target).mean()), "n": int(len(ann)), "median": float(np.median(ann)), "worst": float(ann.min())}


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
                     + ("" if ok1 else f" — 허용보다 {mdd - tol:.1%}p 큼")))  # fmt: skip
    if bench_mdd is not None:
        cks.append(check("R1b", "비교지수 대비 낙폭", "info", mdd <= bench_mdd, mdd, bench_mdd,
                         f"비교지수보다 낙폭이 {'작음' if mdd <= bench_mdd else '큼'} ({mdd:.1%} vs {bench_mdd:.1%})" + (" — 허용 낙폭은 넘었지만 시장 전체가 그만큼 빠진 구간입니다" if (not ok1 and mdd <= bench_mdd) else "")))  # fmt: skip
    # R2 목표수익 (권장) — 투자기간 길이의 과거 구간 중 목표 달성 비율
    cg = m["return"]["cagr"] or 0.0
    td = settings.backtest.trading_days if settings else 252
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
    cks.append(check("R3", "비교지수 대비", "soft", ex > 0, ex, 0.0, f"{crit['benchmark']} 대비 초과 CAGR {ex:+.1%}p"))
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
    # 정보: 드리프트 (규칙이 아니라 리밸런싱 주기의 결과)
    drift_ok = not any(b.startswith("stock_cap") for b in m["composition"]["breaches"])
    sdrift_ok = not any(b.startswith("sector_cap") for b in m["composition"]["breaches"])
    cks.append(check("R4b", "종목 비중 드리프트", "info", drift_ok, m["composition"]["max_weight_drift"], crit["max_weight_per_stock"] * (1 + drift_tol),
                     "리밸런싱 사이 종목 비중이 상한 안에 머묾" if drift_ok else f"리밸런싱 사이에 종목 비중이 상한의 {1 + drift_tol:g}배를 넘은 적 있음 ({', '.join(b.split(':', 1)[1] for b in m['composition']['breaches'] if b.startswith('stock_cap'))}) — 리밸런싱 주기를 줄이면 완화됩니다"))  # fmt: skip
    cks.append(check("R5b", "섹터 비중 드리프트", "info", sdrift_ok, m["composition"]["max_sector_drift"], crit["max_weight_per_sector"] * (1 + drift_tol),
                     "리밸런싱 사이 섹터 비중이 상한 안에 머묾" if sdrift_ok else f"리밸런싱 사이에 섹터 비중이 상한의 {1 + drift_tol:g}배를 넘은 적 있음 — 리밸런싱 주기를 줄이면 완화됩니다"))  # fmt: skip
    # 정보: 투자 비율 (상한 때문에 남은 현금). 낙폭 맞춤안의 현금은 의도된 것이라 적용하지 않는다
    invested = float(sum(p["target_weights"].values()))
    min_inv = settings.backtest.min_invested_ratio if settings else 0.9
    if p.get("kind") not in ("alternative", "matched"):
        cks.append(check("R9", "투자 비율", "info", invested >= min_inv - 1e-6, invested, min_inv,
                         f"투자 {invested:.0%}, 현금 {1 - invested:.0%}" + ("" if invested >= min_inv - 1e-6 else " — 종목·섹터 상한 때문에 돈을 다 넣지 못했습니다. 상한을 풀거나 테마를 넓히면 투자 비율이 올라갑니다")))  # fmt: skip
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


def dd_bucket(mdd: float, tol: float, size: float) -> int:
    """허용 낙폭 초과분을 size(5%p) 단위 구간으로. 안이면 0."""
    return int(math.ceil(max(0.0, abs(mdd) - tol) / size - 1e-9)) if size > 0 else int(abs(mdd) > tol)


def rank_key(row: dict[str, Any], st: dict[str, str], *, integrity_failed: bool, tol: float, bucket_size: float, cautious: bool) -> tuple:
    """추천 순위 키 (작을수록 좋음): 무결성 실패 → 목표수익 미달 → 비교지수 열위 → 허용 낙폭 초과 구간 → (보수 성향) 낙폭 맞춤안 우선 → Sharpe 높음 → 낙폭 작음.
    R2/R3 는 'pass' 만 충족으로 본다 (정보로 바뀐 짧은 창은 모두 같은 등급)."""
    mdd = abs(row.get("max_drawdown") or 0.0)
    sharpe = row.get("sharpe")
    return (bool(integrity_failed), st.get("R2") != "pass", st.get("R3") != "pass", dd_bucket(mdd, tol, bucket_size),
            not (cautious and row.get("kind") == "matched"), -(sharpe if sharpe is not None else -9.0), mdd)  # fmt: skip


def verdict_for(*, mdd: float, tol: float, st: dict[str, str], base_invested: float, min_invested: float, name_ko: str) -> dict[str, Any]:
    cautions = []
    if mdd > tol + 1e-9:
        cautions.append(f"허용 낙폭 초과 ({mdd - tol:.1%}p)")
    if st.get("R2") == "warn":
        cautions.append("목표수익 미달")
    if st.get("R3") == "warn":
        cautions.append("비교지수 하회")
    if base_invested < min_invested - 1e-9:
        status, head = "insufficient", "구성 불충분"
    elif cautions:
        status, head = "recommended_warn", f"추천(주의: {' · '.join(cautions)})"
    else:
        status, head = "recommended", "추천"
    return {"status": status, "label_ko": f"{head}: {name_ko}", "head_ko": head, "cautions_ko": cautions, "base_invested": round(base_invested, 6)}


def validate(res: dict[str, Any], targets: dict[str, Any], intent: dict[str, Any], req: dict[str, Any], ctx: dict[str, Any], sector_of,
             settings: AnalysisSettings, *, max_drawdown_override: float | None = None, alternatives: bool = True) -> dict[str, Any]:  # fmt: skip
    """포트폴리오마다 규칙을 평가하고 **항상** 하나를 추천한다. `alternatives` 인자는 호환용(현금 혼합안은 더 만들지 않는다)."""
    bs = settings.backtest
    vc, cons = intent["validation_criteria"], req["constraints"]
    tol_user = float(max_drawdown_override if max_drawdown_override is not None else req["risk"]["max_drawdown_tolerance"])
    match_target = float((intent.get("risk_params") or {}).get("effective_max_drawdown") or tol_user)
    cautious = req["risk"].get("loss_reaction") == "sell" or (req.get("profile") or {}).get("investment_experience") == "none"
    crit = {"max_drawdown": tol_user, "input_max_drawdown": tol_user, "match_target": match_target, "cautious": cautious,
            "horizon_years": float(vc.get("horizon_years") or req["horizon"].get("target_years") or 0),
            "target_annual_return": vc["target_annual_return"], "benchmark": vc["benchmark"], "volatility_preference": intent["risk_params"]["volatility_preference"],
            "vol_band": bs.vol_bands[intent["risk_params"]["volatility_preference"]], "max_weight_per_stock": cons["max_weight_per_stock"],
            "max_weight_per_sector": cons["max_weight_per_sector"], "min_holdings": cons["num_holdings"]["min"], "drift_tolerance": bs.drift_tolerance,
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

    def key(t):
        return rank_key(t, by_id.get(t["id"], {}), integrity_failed=t["id"] in failed_ids, tol=tol_user, bucket_size=bs.dd_excess_bucket, cautious=cautious)

    ranked = sorted(cands, key=key)
    best = ranked[0]
    st = by_id.get(best["id"], {})
    pb = ports[best["id"]]
    mdd_b = abs(best["max_drawdown"] or 0.0)
    base_id = pb.get("base_id") or best["id"]
    base_invested = float(sum((ports.get(base_id) or pb)["target_weights"].values()))
    verdict = verdict_for(mdd=mdd_b, tol=tol_user, st=st, base_invested=base_invested, min_invested=bs.min_invested_for_recommendation, name_ko=best["name_ko"])
    # 사유: 사실만 (정보 규칙은 '만족'으로 세지 않고, 음수 Sharpe 에 '가장 높음'이라 쓰지 않는다)
    parts = [f"후보 {len(cands)}개 중 1위."]
    tgt = crit["target_annual_return"]
    if st.get("R2") == "pass":
        parts.append(f"목표수익(연 {tgt:.1%}) 충족")
    elif st.get("R2") == "warn":
        parts.append(f"목표수익(연 {tgt:.1%}) 미달")
    else:
        parts.append("목표수익은 창이 짧아 참고만")
    ex = best["excess_cagr"] or 0.0
    parts.append(f"{crit['benchmark']} 대비 초과 CAGR {ex:+.1%}p")
    parts.append(f"최대낙폭 {mdd_b:.1%} vs 허용 {tol_user:.1%}" + (f" (여유 {tol_user - mdd_b:.1%}p)" if mdd_b <= tol_user + 1e-9 else f" ({mdd_b - tol_user:.1%}p 초과)"))
    sharpes = [t["sharpe"] for t in cands if t["sharpe"] is not None]
    s = best["sharpe"]
    if s is not None:
        top = s >= max(sharpes) - 1e-12
        parts.append(f"Sharpe {s:.2f}로 가장 높음" if top and s > 0 else (f"Sharpe {s:.2f} (음수, 가장 덜 나쁨)" if top else f"Sharpe {s:.2f}"))
    if pb.get("kind") == "matched":
        inv = float(sum(pb["target_weights"].values()))
        base_name = (ports.get(base_id) or {}).get("name_ko") or NAMES_KO.get(base_id, base_id)
        parts.append(f"{base_name}의 주식 비중을 {inv:.0%}로 줄여 과거 최대낙폭을 목표 {match_target:.1%} 안에 맞춘 구성")
        same_prefix = [t for t in ranked[1:] if key(t)[:4] == key(best)[:4]]
        if cautious and same_prefix:
            parts.append("손실 시 매도·투자 경험 없음 성향이라 같은 조건이면 낙폭 맞춤안을 우선했습니다")
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

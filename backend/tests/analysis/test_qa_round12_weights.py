"""시나리오 QA 라운드 12 (030): 시가총액비중 등 템플릿 비중의 상한 처리를 '상한 안 비례 배분(물 채우기)'으로 바꿈.

예전 apply_constraints 는 바닥 → 종목 상한 → 넘친 섹터를 통째로 축소 → 남는 몫 비례 배분을 되풀이해, 섹터 상한이 묶이면 종목 상한에
걸린 종목까지 섹터째 줄였다 (030 기준일: 시가총액 AAPL 0.84 · PLTR 0.06 인데 15.4% · 15.3%). 이제 w_i = clip(f_s·w0_i, 바닥, 종목 상한)이고
f_s 는 섹터 상한에 안 걸린 섹터면 공통 λ, 걸린 섹터면 섹터 합이 딱 상한이 되는 μ_s ≤ λ. 성질 검사는 numpy 난수 반복 (hypothesis 없음)."""

from __future__ import annotations

import re
from types import SimpleNamespace

import numpy as np
import pytest

from backend.analysis.m4_portfolio import math as P

LABEL = re.compile(r"^(min_weight|stock_cap):(\d+)$|^sector_cap:(.+)$")


def _old_apply_constraints(w, max_stock, max_sector, sectors, total=1.0, *, max_iter=50, min_weight=0.01):
    """라운드 11 까지의 apply_constraints 를 그대로 옮긴 사본 (비교용)."""
    w = np.asarray(w, float).copy()
    w = w / w.sum() * total
    sectors = np.asarray(sectors)
    applied: set[str] = set()
    for _ in range(max_iter):
        low = w < min_weight - 1e-12
        if low.any():
            applied.update(f"min_weight:{i}" for i in np.where(low)[0])
            w[low] = min_weight
        over = w > max_stock + 1e-12
        if over.any():
            applied.update(f"stock_cap:{i}" for i in np.where(over)[0])
            w[over] = max_stock
        for s in np.unique(sectors):
            m = sectors == s
            if w[m].sum() > max_sector + 1e-12:
                applied.add(f"sector_cap:{s}")
                w[m] = np.maximum(w[m] * max_sector / w[m].sum(), min_weight)
        deficit = total - w.sum()
        if abs(deficit) < 1e-10:
            break
        free = (w < max_stock - 1e-12) & (w > min_weight + 1e-12) if deficit < 0 else (w < max_stock - 1e-12)
        for s in np.unique(sectors):
            m = sectors == s
            if deficit > 0 and w[m].sum() >= max_sector - 1e-12:
                free &= ~m
        if not free.any() or w[free].sum() <= 0:
            break
        w[free] += deficit * w[free] / w[free].sum()
    return w, sorted(applied)


def _ref_fill(a, lo, hi, sec, cap, total):
    """정의를 그대로 옮긴 느린 기준: 섹터마다 합이 cap 이 되는 수준 μ_s, 그다음 합계가 total 이 되는 공통 수준 λ 를 이분법으로."""
    big = 4 * max([hi / x for x in a if x > 0], default=1.0) + 1

    def g(s, f):
        return np.clip(f * a[sec == s], lo, hi).sum()

    def tot(lam):
        return np.clip(np.minimum(lam, mu[sec]) * a, lo, hi).sum()

    mu = np.full(len(cap), np.inf)
    for s in range(len(cap)):
        if (sec == s).sum() * lo >= cap[s]:
            mu[s] = 0.0  # 바닥만으로 상한 이상
        elif g(s, big) > cap[s]:
            l_, h_ = 0.0, big
            for _ in range(100):
                m = (l_ + h_) / 2
                l_, h_ = (m, h_) if g(s, m) < cap[s] else (l_, m)
            mu[s] = h_
    lam = big  # 상한 안에서 다 못 채우면 모두 최대치
    if tot(big) > total:
        l_, h_ = 0.0, big
        for _ in range(100):
            m = (l_ + h_) / 2
            l_, h_ = (m, h_) if tot(m) < total else (l_, m)
        lam = h_
    return np.clip(np.minimum(lam, mu[sec]) * a, lo, hi)


def _reference(w0, hi, cap_sector, sectors, total, min_weight):
    w0 = np.asarray(w0, float)
    a = w0 / w0.sum() * total
    codes, sec = np.unique(np.asarray(sectors), return_inverse=True)
    lo, cap = min(min_weight, hi), np.full(len(codes), cap_sector)
    out = _ref_fill(a, lo, hi, sec, cap, total)
    zero = a <= 0
    if total - out.sum() > 1e-12 and zero.any():  # 다른 종목이 모두 최대치: 시가총액 0 종목이 남는 몫을 똑같이 (상한 안에서)
        room = cap - np.bincount(sec[~zero], weights=out[~zero], minlength=len(codes))
        out[zero] = _ref_fill(np.ones(int(zero.sum())), lo, hi, sec[zero], room, total - out[~zero].sum())
    return out


def _case(rng, *, zeros=True):
    """무작위 입력. 상한·합계·바닥은 연속값이라 '경계에 딱 붙는' 우연은 사실상 없다."""
    n = int(rng.integers(1, 25))
    sectors = [str(10 * (int(s) + 1)) for s in rng.integers(0, int(rng.integers(1, min(n, 8) + 1)), n)]  # GICS 섹터 코드 모양
    kind = int(rng.integers(0, 4))
    w0 = [rng.lognormal(0, float(rng.uniform(0.3, 2.5)), n), rng.pareto(1.2, n) + 1e-3, rng.uniform(0, 1, n), np.ones(n)][kind]
    if zeros and rng.random() < 0.3:  # 시가총액 자료가 없는 종목
        w0[rng.random(n) < 0.3] = 0.0
        w0[int(rng.integers(0, n))] = max(float(w0.max()), 1e-3)
    hi = float(rng.uniform(0.04, 0.6))
    S = float(rng.uniform(hi, 1.0))  # 요청 스키마: 섹터 상한 ≥ 종목 상한
    total = float(rng.uniform(0.4, 1.0))
    lo = 0.0 if rng.random() < 0.15 else float(rng.uniform(0.002, 0.03))
    return w0, hi, S, sectors, total, lo


def _expected_sum(sectors, hi, S, total, lo):
    """섹터마다 max(바닥 합, min(k × 종목 상한, 섹터 상한)) 의 합이 담을 수 있는 최대치. 바닥 합이 total 을 넘으면 바닥을 지킨다."""
    _, sec = np.unique(np.asarray(sectors), return_inverse=True)
    k = np.bincount(sec)
    capacity = np.maximum(k * lo, np.minimum(k * hi, S)).sum()
    return max(len(sectors) * lo, min(total, capacity))


def _state_labels(w, sectors, hi, S, lo):
    """최종 비중으로 본 라벨: 바닥에 있는 종목, 종목 상한에 있는 종목, 섹터 상한에 있는(또는 바닥만으로 넘는) 섹터."""
    codes, sec = np.unique(np.asarray(sectors), return_inverse=True)
    sums = np.bincount(sec, weights=w, minlength=len(codes))
    out = {f"min_weight:{i}" for i in np.where(w <= lo + 1e-10)[0]} if lo > 0 else set()
    out |= {f"stock_cap:{i}" for i in np.where(w >= hi - 1e-10)[0]} | {f"sector_cap:{codes[j]}" for j in np.where(sums >= S - 1e-10)[0]}
    return sorted(out)


# ───────────────────────── 030 회귀 ─────────────────────────
TK_NOW = ["AAPL", "RKLB", "APP", "PLTR", "CVNA", "HOOD", "BE", "MSTR", "TPL", "GL", "HWM", "VST"]
CAPW_NOW = [0.838817, 0.002538, 0.022963, 0.062175, 0.007923, 0.010578, 0.00111, 0.017314, 0.008461, 0.002882, 0.014149, 0.01109]
SEC_NOW = ["45", "20", "50", "45", "25", "40", "20", "45", "10", "40", "20", "55"]  # 45 정보기술 · 20 산업재 · 50 커뮤니케이션 …
TK_START = ["AAPL", "TRGP", "NVDA", "EQT", "PANW", "FTNT", "ABBV", "WMB", "BRO", "OKE", "LYV", "MAA"]
CAPW_START = [0.710123, 0.0048, 0.140288, 0.004369, 0.016046, 0.014252, 0.072119, 0.011362, 0.005218, 0.008548, 0.006558, 0.006317]
SEC_START = ["45", "10", "45", "10", "45", "45", "35", "10", "40", "10", "50", "60"]


def test_030_as_of_market_cap_keeps_order_inside_capped_it_sector():
    """030 기준일(2025-04-21), 종목 25% · 섹터 35%: 예전에는 AAPL 15.44% · PLTR 15.30% (시가총액은 13배 차이)이고 바닥에 걸린 다섯 종목이
    모두 5.98% 로 같았다. 이제 AAPL 은 종목 상한 25%, 정보기술 나머지 10% 를 PLTR · MSTR 이 시가총액 비율로, 다른 섹터는 공통 배수로."""
    old, _ = _old_apply_constraints(CAPW_NOW, 0.25, 0.35, SEC_NOW, 1.0)
    i = {t: k for k, t in enumerate(TK_NOW)}
    assert old[i["AAPL"]] == pytest.approx(0.1544, abs=1e-4) and old[i["PLTR"]] == pytest.approx(0.1530, abs=1e-4)  # 고친 버그 (기록용)
    w, applied = P.apply_constraints(CAPW_NOW, 0.25, 0.35, SEC_NOW, 1.0)
    a = np.array(CAPW_NOW) / sum(CAPW_NOW)
    assert w[i["AAPL"]] == pytest.approx(0.25, abs=1e-12)
    assert w[i["PLTR"]] == pytest.approx(0.10 * a[i["PLTR"]] / (a[i["PLTR"]] + a[i["MSTR"]]), abs=1e-12)
    assert w[i["PLTR"]] == pytest.approx(0.0782, abs=5e-5) and w[i["MSTR"]] == pytest.approx(0.0218, abs=5e-5)
    assert w[[i["AAPL"], i["PLTR"], i["MSTR"]]].sum() == pytest.approx(0.35, abs=1e-12)
    assert w[i["BE"]] == pytest.approx(0.01, abs=1e-12)  # 시가총액 비례로는 0.88% → 바닥 1%
    rest = [i[t] for t in ("RKLB", "APP", "CVNA", "HOOD", "TPL", "GL", "HWM", "VST")]
    lam = (1 - 0.35 - 0.01) / a[rest].sum()
    assert w[rest] == pytest.approx(lam * a[rest], abs=1e-12)  # 상한에 안 걸린 섹터는 모두 같은 배수
    assert w[i["APP"]] == pytest.approx(0.1824, abs=5e-5) and w[i["HWM"]] == pytest.approx(0.1124, abs=5e-5)
    assert w.sum() == pytest.approx(1.0, abs=1e-12)
    assert applied == ["min_weight:6", "sector_cap:45", "stock_cap:0"]  # 예전에는 최종 5.98% 인 종목도 min_weight 로 적었다


def test_030_start_date_apple_is_not_below_a_name_ten_times_smaller():
    """030 시작일(2022-04-21): 예전에는 AAPL(시가총액 0.710) 20.8% 인데 ABBV(0.072) 25%. 이제 둘 다 종목 상한 25%, 정보기술 나머지 10% 는
    NVDA 8% + 바닥에 걸린 PANW · FTNT 1% 씩, 다른 섹터는 공통 배수."""
    old, _ = _old_apply_constraints(CAPW_START, 0.25, 0.35, SEC_START, 1.0)
    i = {t: k for k, t in enumerate(TK_START)}
    assert old[i["AAPL"]] == pytest.approx(0.2080, abs=1e-4) and old[i["ABBV"]] == pytest.approx(0.25)  # 고친 버그 (기록용)
    w, applied = P.apply_constraints(CAPW_START, 0.25, 0.35, SEC_START, 1.0)
    assert w[i["AAPL"]] == pytest.approx(0.25, abs=1e-12) and w[i["ABBV"]] == pytest.approx(0.25, abs=1e-12)
    assert w[i["NVDA"]] == pytest.approx(0.08, abs=1e-12) and w[i["PANW"]] == w[i["FTNT"]] == pytest.approx(0.01, abs=1e-12)
    a = np.array(CAPW_START) / sum(CAPW_START)
    rest = [i[t] for t in ("TRGP", "EQT", "WMB", "OKE", "BRO", "LYV", "MAA")]
    assert w[rest] == pytest.approx(0.40 / a[rest].sum() * a[rest], abs=1e-12)
    assert applied == ["min_weight:4", "min_weight:5", "sector_cap:45", "stock_cap:0", "stock_cap:6"]


def test_bigger_name_is_no_longer_tied_with_a_smaller_one_in_a_capped_sector():
    """030 walk-forward 7개 날짜: AAPL 이 NVDA 의 2.5배인데 둘 다 종목 상한에 걸린 뒤 정보기술이 통째로 줄어 비중이 똑같았다."""
    capw = [0.65, 0.012, 0.26, 0.011, 0.025, 0.013, 0.012, 0.008, 0.006, 0.006]
    sec = ["45", "45", "45", "45", "35", "10", "10", "40", "50", "60"]
    old, _ = _old_apply_constraints(capw, 0.25, 0.35, sec, 1.0)
    assert old[0] == pytest.approx(old[2], abs=1e-12)  # 고친 버그 (기록용)
    w, applied = P.apply_constraints(capw, 0.25, 0.35, sec, 1.0)
    # 섹터 상한이 먼저 묶여 AAPL 은 종목 상한까지 못 간다: 정보기술 35% 에서 바닥 두 종목 몫을 뺀 33% 를 시가총액 비율 2.5 : 1 로
    assert w[0] / w[2] == pytest.approx(2.5, abs=1e-12) and w[0] + w[2] == pytest.approx(0.33, abs=1e-12) and w[[1, 3]] == pytest.approx([0.01, 0.01], abs=1e-12)
    assert applied[:3] == ["min_weight:1", "min_weight:3", "sector_cap:45"] and not any(x.startswith("stock_cap") for x in applied)


# ───────────────────────── 성질 (무작위 반복) ─────────────────────────
def test_matches_the_capped_proportional_definition_on_random_cases():
    """빠른 풀이(꺾이는 점 보간) = 정의를 그대로 옮긴 이분법 기준."""
    rng = np.random.default_rng(20261105)
    for _ in range(300):
        w0, hi, S, sectors, total, lo = _case(rng)
        w, _ = P.apply_constraints(w0, hi, S, sectors, total, min_weight=lo)
        assert np.allclose(w, _reference(w0, hi, S, sectors, total, lo), atol=1e-9, rtol=0), (w0, hi, S, sectors, total, lo)


def test_bounds_sector_caps_and_total_on_random_cases():
    """바닥 ≤ w_i ≤ 종목 상한, 섹터 합 ≤ 섹터 상한 (바닥만으로 넘는 섹터는 바닥 합), 합계 = min(total, 담을 수 있는 최대치)."""
    rng = np.random.default_rng(1)
    short = 0
    for _ in range(3000):
        w0, hi, S, sectors, total, lo = _case(rng)
        w, _ = P.apply_constraints(w0, hi, S, sectors, total, min_weight=lo)
        _, sec = np.unique(np.asarray(sectors), return_inverse=True)
        k = np.bincount(sec)
        assert (w >= lo - 1e-9).all() and (w <= hi + 1e-9).all()
        assert (np.bincount(sec, weights=w) <= np.maximum(S, k * lo) + 1e-9).all()
        assert (np.bincount(sec, weights=w)[k * lo <= S] <= S + 1e-9).all()
        exp = _expected_sum(sectors, hi, S, total, lo)
        assert w.sum() == pytest.approx(exp, abs=1e-9), (w0, hi, S, sectors, total, lo)
        short += exp < total - 1e-9
    assert short > 300  # 상한 때문에 현금이 남는 경우도 충분히 시험했다


def test_order_is_kept_inside_each_sector_on_random_cases():
    """같은 섹터 안에서는 입력이 큰 종목이 비중도 크거나 같다 (같은 입력이면 같은 비중)."""
    rng = np.random.default_rng(2)
    for _ in range(3000):
        w0, hi, S, sectors, total, lo = _case(rng)
        w, _ = P.apply_constraints(w0, hi, S, sectors, total, min_weight=lo)
        sec = np.asarray(sectors)
        for s in np.unique(sec):
            x0, x = w0[sec == s], w[sec == s]
            o = np.argsort(x0, kind="stable")
            assert (np.diff(x[o]) >= -1e-12).all(), (x0[o], x[o])
            assert all(abs(x[p] - x[q]) < 1e-12 for p in range(len(x0)) for q in range(len(x0)) if x0[p] == x0[q])


def test_no_binding_bound_returns_the_scaled_input_exactly():
    rng = np.random.default_rng(3)
    for _ in range(500):
        n = int(rng.integers(1, 20))
        w0 = rng.lognormal(0, 1.0, n)
        total = float(rng.uniform(0.5, 1.0))
        sectors = [str(10 * (int(s) + 1)) for s in rng.integers(0, 5, n)]
        a = w0 / w0.sum() * total
        _, sec = np.unique(np.asarray(sectors), return_inverse=True)
        hi, lo = float(a.max() + rng.uniform(0, 0.1)), float(a.min() * rng.uniform(0, 1))
        S = float(np.bincount(sec, weights=a).max() + rng.uniform(0, 0.1))
        w, applied = P.apply_constraints(w0, hi, S, sectors, total, min_weight=lo)
        assert np.array_equal(w, w0 / w0.sum() * total) and applied == []


def test_only_stock_caps_bind_gives_the_old_result():
    """섹터 상한·바닥이 안 묶이면 예전 반복도 이미 물 채우기였다: 비중과 라벨이 예전과 같다."""
    rng = np.random.default_rng(4)
    bound = 0
    for _ in range(1500):
        n = int(rng.integers(1, 25))
        total = float(rng.uniform(0.5, 1.0))
        hi = float(rng.uniform(0.04, 0.6))
        w0 = rng.lognormal(0, float(rng.uniform(0.3, 2.5)), n)
        lo = float((w0 / w0.sum() * total).min() * rng.uniform(0, 0.99))  # 바닥은 안 묶임
        if rng.random() < 0.5:
            S, sectors = float(rng.uniform(total, 1.0)), [str(10 * (int(s) + 1)) for s in rng.integers(0, 4, n)]  # 섹터 합 ≤ total ≤ 섹터 상한
        else:
            S = float(rng.uniform(hi, 1.0))
            per = max(1, int(S / hi))  # 섹터마다 종목 상한 × 종목 수 < 섹터 상한
            sectors = [str(10 * (k // per + 1)) for k in rng.permutation(n)]
        old, old_applied = _old_apply_constraints(w0, hi, S, sectors, total, min_weight=lo)
        w, applied = P.apply_constraints(w0, hi, S, sectors, total, min_weight=lo)
        assert np.allclose(w, old, atol=1e-9, rtol=0) and applied == old_applied, (w0, hi, S, sectors, total, lo)
        bound += any(x.startswith("stock_cap") for x in applied)
    assert bound > 500


def test_equal_weight_inputs_give_the_old_weights():
    """동일비중은 섹터 상한 · 바닥 · 현금이 남는 경우까지 예전과 같은 비중 (같은 섹터 종목은 늘 같은 값이라 예전 반복도 물 채우기였다)."""
    rng = np.random.default_rng(5)
    capped = 0
    for _ in range(1500):
        n = int(rng.integers(1, 30))
        sectors = [str(10 * (int(s) + 1)) for s in rng.integers(0, int(rng.integers(1, min(n, 10) + 1)), n)]
        hi = float(rng.uniform(0.03, 0.6))
        S, total, lo = float(rng.uniform(hi, 0.7)), float(rng.uniform(0.4, 1.0)), float(rng.uniform(0.0, min(0.05, hi)))
        old, _ = _old_apply_constraints(np.ones(n), hi, S, sectors, total, min_weight=lo)
        w, applied = P.apply_constraints(np.ones(n), hi, S, sectors, total, min_weight=lo)
        assert np.allclose(w, old, atol=1e-9, rtol=0), (n, sectors, hi, S, total, lo)
        capped += any(x.startswith("sector_cap") for x in applied)
    assert capped > 300


def test_missing_market_cap_names_get_only_the_floor_while_others_have_room():
    """시가총액 0(자료 없음) 종목은 바닥만 받는다 — 다른 종목이 모두 최대치라 남는 몫이 있을 때만 그 몫을 똑같이 나눠 받는다
    (경고 market_cap_missing 문구: '최소 비중(상한 때문에 남은 비중이 있으면 그 일부를 더함)만')."""
    rng = np.random.default_rng(6)
    seen = 0
    for _ in range(3000):
        w0, hi, S, sectors, total, lo = _case(rng)
        zero = w0 <= 0
        if not zero.any() or lo == 0:
            continue
        _, sec = np.unique(np.asarray(sectors), return_inverse=True)
        k, z = np.bincount(sec), np.bincount(sec, weights=zero.astype(float))
        room1 = np.maximum(k * lo, np.minimum((k - z) * hi + z * lo, S)).sum()  # 시가총액 있는 종목만 늘릴 때의 최대치
        if total > room1 - 1e-9:
            continue
        w, applied = P.apply_constraints(w0, hi, S, sectors, total, min_weight=lo)
        assert w[zero] == pytest.approx(np.full(int(zero.sum()), lo), abs=1e-12)
        assert {f"min_weight:{i}" for i in np.where(zero)[0]} <= set(applied)
        seen += 1
    assert seen > 100
    # 다른 종목이 모두 상한: 남는 20% 는 XOM 이 받는다 (예전과 같은 값)
    w, applied = P.apply_constraints([0.6, 0.4, 0.0], 0.4, 1.0, ["45", "45", "10"], 1.0)
    assert w == pytest.approx([0.4, 0.4, 0.2], abs=1e-12) and applied == ["stock_cap:0", "stock_cap:1"]
    assert _old_apply_constraints([0.6, 0.4, 0.0], 0.4, 1.0, ["45", "45", "10"], 1.0)[0] == pytest.approx(w, abs=1e-12)
    # 같은 섹터의 두 종목이 섹터에 남은 자리(0.2)를 똑같이 나누고, 그래도 남는 20% 는 현금
    w, applied = P.apply_constraints([0.7, 0.3, 0.0, 0.0], 0.3, 0.5, ["45", "30", "30", "30"], 1.0)
    assert w == pytest.approx([0.3, 0.3, 0.1, 0.1], abs=1e-12) and applied == ["sector_cap:30", "stock_cap:0", "stock_cap:1"]
    old, _ = _old_apply_constraints([0.7, 0.3, 0.0, 0.0], 0.3, 0.5, ["45", "30", "30", "30"], 1.0)
    assert old == pytest.approx([0.3, 0.3 * 5 / 7, 0.2 * 5 / 7, 0.2 * 5 / 7], abs=1e-12)  # 예전: 섹터째 줄여 시가총액이 있는 KO 가 21.4% (기록용)
    for lo in (0.0, 0.01):  # 모두 0 이면 동일비중 (예전에는 0 으로 나눠 nan)
        assert P.apply_constraints([0.0] * 4, 0.3, 1.0, ["45", "45", "10", "10"], 1.0, min_weight=lo)[0] == pytest.approx([0.25] * 4, abs=1e-12)


def test_floors_that_alone_exceed_a_sector_cap_are_kept():
    """바닥(1%) × 6종목 = 6% 가 섹터 상한 5% 보다 크면 바닥을 그대로 두고 그 섹터를 상한 라벨로 알린다 (멈추지 않고 돈다)."""
    w0 = [0.01, 0.02, 0.005, 0.03, 0.01, 0.02, 0.5, 0.405]
    sec = ["60"] * 6 + ["45", "35"]
    w, applied = P.apply_constraints(w0, 0.6, 0.05, sec, 1.0)
    assert w[:6] == pytest.approx([0.01] * 6, abs=1e-12) and w[6:] == pytest.approx([0.05, 0.05], abs=1e-12)  # 다른 섹터도 상한 5%
    assert "sector_cap:60" in applied and {f"min_weight:{i}" for i in range(6)} <= set(applied)
    # 바닥 합이 투자 총액보다 크면 모두 바닥 (예전처럼 바닥을 지킨다: 합계 > total)
    w, applied = P.apply_constraints(np.arange(1, 13, dtype=float), 0.25, 1.0, ["45"] * 12, 0.1)
    assert w == pytest.approx(np.full(12, 0.01), abs=1e-12) and applied == sorted(f"min_weight:{i}" for i in range(12))


def test_labels_keep_the_old_format_and_name_the_binding_bounds():
    """라벨 모양은 예전 그대로 ('min_weight:<i>', 'stock_cap:<i>', 'sector_cap:<섹터 코드>', 정렬) — market_model.label 이 종목·섹터 이름으로 바꾼다.
    뜻은 최종 비중 기준: 바닥에 있는 종목, 종목 상한에 있는 종목, 섹터 상한에 있는 섹터."""
    rng = np.random.default_rng(7)
    for _ in range(3000):
        w0, hi, S, sectors, total, lo = _case(rng)
        w, applied = P.apply_constraints(w0, hi, S, sectors, total, min_weight=lo)
        assert applied == sorted(applied) and len(set(applied)) == len(applied)
        for c in applied:
            m = LABEL.match(c)
            assert m, c
            assert (m.group(3) in sectors) if m.group(3) is not None else int(m.group(2)) < len(w0)
        assert applied == _state_labels(w, sectors, hi, S, lo), (w0, hi, S, sectors, total, lo)


def test_template_weights_and_min_variance_fallback_use_the_new_rule(monkeypatch):
    """호출하는 쪽(template_weights · min_variance 대체 경로)은 그대로: 시가총액 · 역변동성은 같은 함수, 최적화 실패 시 1/분산에 같은 규칙."""
    n = len(CAPW_NOW)
    vol = np.linspace(0.2, 0.9, n)
    cov = np.diag(vol**2)
    w, applied = P.template_weights("market_cap", cov, vol, np.array(CAPW_NOW), 0.25, 0.35, SEC_NOW, 1.0, max_iter=1)  # max_iter 는 받기만 한다
    assert w == pytest.approx(P.apply_constraints(CAPW_NOW, 0.25, 0.35, SEC_NOW, 1.0)[0], abs=1e-15)
    assert applied == ["min_weight:6", "sector_cap:45", "stock_cap:0"]
    wi, _ = P.template_weights("inverse_volatility", cov, vol, None, 0.25, 0.35, SEC_NOW, 1.0)
    assert wi == pytest.approx(P.apply_constraints(1 / vol, 0.25, 0.35, SEC_NOW, 1.0)[0], abs=1e-15)
    monkeypatch.setattr(P, "minimize", lambda *a, **kw: SimpleNamespace(success=False, x=np.zeros(n)))
    wm, am = P.template_weights("min_variance", cov, vol, None, 0.25, 0.35, SEC_NOW, 1.0)
    w2, a2 = P.apply_constraints(1 / np.diag(cov), 0.25, 0.35, SEC_NOW, 1.0)
    assert wm == pytest.approx(w2, abs=1e-15) and am == ["min_variance_fallback(1/var)", *a2]


def test_exact_capacity_does_not_add_a_sector_cap_label_and_bad_inputs_are_safe():
    """검토: 섹터 상한 100%·전액 투자처럼 상한이 투자 총액을 딱 담을 때 반올림 1ulp 차이로 '못 채움' 쪽에 빠져 섹터 상한 라벨이 붙었다.
    아주 작은 값(1e-310)은 경계 계산이 넘쳤고, NaN 은 모든 종목을 동일비중으로 만들었다 → 0(시가총액 자료 없음)과 같게."""
    w, lab = P.apply_constraints([2, 1, 1, 1], 0.3, 1.0, ["45"] * 4, 1.0)
    assert lab == ["stock_cap:0"] and np.allclose(w, [0.3, 0.7 / 3, 0.7 / 3, 0.7 / 3])
    _, lab = P.apply_constraints([6, 3, 1, 1, 4, 1], 0.3, 0.5, ["45", "45", "45", "20", "20", "20"], 1.0)
    assert lab == ["sector_cap:45", "stock_cap:4"]
    assert np.allclose(P.apply_constraints([1e-310, 1, 1], 0.4, 1.0, ["a", "a", "b"], 1.0)[0], [0.2, 0.4, 0.4])
    w, lab = P.apply_constraints([float("nan"), 1, 2, 3], 0.4, 1.0, ["a", "a", "b", "b"], 1.0)
    assert np.isfinite(w).all() and w[0] == pytest.approx(0.01) and "min_weight:0" in lab

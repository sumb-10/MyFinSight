"""종목·섹터 상한이 투자금을 어디까지 막는지와 그 원인 (2026-11 시나리오 QA).

R9 투자 비율 문구·현금 설명(cash_breakdown)·선정 불가 사유(infeasibility)가 원인을 따로 판단해 서로 달랐다
(011: 2종목 × 종목당 25% 인데 섹터 상한 탓 / 002: 두 상한이 다 걸리는데 섹터 상한만 탓). 같은 판단을 여기서 한다.
"""

from __future__ import annotations

from typing import Any


def cap_limits(counts: dict[str, int], stock_cap: float, sector_cap: float, investable: float) -> dict[str, Any]:
    """counts = 섹터별 종목 수. kind: 'stock'(종목 수 × 종목당 상한이 묶음) / 'sector'(섹터 상한이 묶음) / 'both' / None(상한이 안 묶음).
    stock_room = 섹터 상한이 없을 때 담을 수 있는 최대, cap_room = 두 상한을 다 지킬 때 담을 수 있는 최대 (둘 다 investable 이하)."""
    n = int(sum(counts.values()))
    stock_room = min(investable, n * stock_cap)
    cap_room = min(investable, sum(min(k * stock_cap, sector_cap) for k in counts.values()))
    stock_bind = n * stock_cap < investable - 1e-9
    sector_bind = cap_room < stock_room - 1e-9
    kind = "both" if stock_bind and sector_bind else "stock" if stock_bind else "sector" if sector_bind else None
    # 같은 지점에서 두 상한이 함께 막는 경우 (예: 한 섹터 3종목 × 25% = 섹터 75%): 원인 문장은 종목당 상한이지만 해결은 둘 다 풀어야 한다
    tie = kind == "stock" and min(investable, len(counts) * sector_cap) <= cap_room + 1e-9
    return {"n": n, "stock_room": stock_room, "cap_room": cap_room, "kind": kind, "tie": tie}


def cap_cause_ko(lim: dict[str, Any], stock_cap: float, sector_cap: float, *, clause: bool = False) -> str | None:
    """원인 문장. clause=True 면 뒤에 이어 쓰는 꼴('…까지만 담겨'), 아니면 끝맺는 꼴('…까지만 담깁니다'). 상한이 안 묶으면 None."""
    end = "담겨" if clause else "담깁니다"
    n, sr, cr = lim["n"], lim["stock_room"], lim["cap_room"]
    if lim["kind"] == "stock":
        return f"{n}종목이라 종목당 상한 {stock_cap:.0%}로는 {sr:.0%}까지만 {end}"
    if lim["kind"] == "sector":
        return f"섹터 상한 {sector_cap:.0%} 때문에 {cr:.0%}까지만 {end}"
    if lim["kind"] == "both":
        return f"{n}종목이라 종목당 상한 {stock_cap:.0%}로는 {sr:.0%}까지만 담기고, 섹터 상한 {sector_cap:.0%}에도 걸려 {cr:.0%}까지만 {end}"
    return None


def cap_fix_ko(lim: dict[str, Any]) -> str:
    """무엇을 바꾸면 투자 비율이 오르는지 (섹터 상한만 올려서는 안 되는 경우를 숨기지 않는다)."""
    if lim["kind"] == "stock" and lim.get("tie"):
        return "섹터 상한도 같은 지점에서 막고 있어, 다른 섹터 종목이 늘거나 종목당·섹터 상한을 함께 올려야 투자 비율이 올라갑니다"
    if lim["kind"] == "stock":
        return "종목 수가 늘거나 종목당 상한을 올리면 투자 비율이 올라갑니다"
    if lim["kind"] == "sector":
        return "섹터 상한을 올리거나 테마를 넓히면 투자 비율이 올라갑니다"
    if lim["kind"] == "both":
        return f"섹터 상한만 올리면 {lim['stock_room']:.0%}까지만 오르고, 종목 수가 늘거나 종목당 상한도 올려야 다 담깁니다"
    return ""

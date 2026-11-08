"""예상 매수 주문: 리포트 카드 2의 배분(분석 기준일 현재 구성)을 기준일 종가·환율로 1주 단위 주문으로 바꾼다.

프런트 제안 계약 `proposed.execution` (Front/src/api/proposed.ts) 모양 그대로 돌려준다. 새 리포트는 저장할 때 넣고,
저장 문서에 없는 예전 리포트는 조회할 때 계산해 응답에만 붙인다 (저장 문서는 불변).
계산할 수 없으면(가격·환율·수수료 없음, 현재 구성이 아닌 배분) 넣지 않는다 — 화면은 기존 안내 문구를 보여 준다. 값을 지어내지 않는다.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
from collections.abc import Iterable
from typing import Any

log = logging.getLogger(__name__)

PROPOSED_CONTRACT = "proposed-0.1"
FRACTION_DIGITS = 4  # 미국 주식 소수점 주문의 자릿수 (이 자리까지 내림). 최소 주문 금액은 두지 않는다
KR_SUFFIXES = (".KS", ".KQ")
BASIS_NOTE_KO = {
    "integer": "정수 주식 기준입니다.",
    "fractional": f"소수점 주식(소수 {FRACTION_DIGITS}째 자리까지) 기준입니다.",
    "mixed": f"미국 주식은 소수점(소수 {FRACTION_DIGITS}째 자리까지), 한국 주식은 1주 단위 기준입니다.",
}
NOTE_TAIL_KO = " 분석 기준일 종가로 계산한 추정치이며, 실제 주문 시 가격이 달라집니다."


def share_basis_of(ticker: str) -> str:
    """미국 주식은 소수점, 한국 주식은 1주 단위."""
    return "integer" if ticker.endswith(KR_SUFFIXES) else "fractional"


def _shares(target_usd: float, price: float, fee_rate: float, basis: str) -> int | float:
    """수수료까지 목표 금액 안에 들어오는 수량을 내림한다."""
    raw = target_usd / (price * (1 + fee_rate))
    if basis == "integer":
        return max(0, math.floor(raw))
    unit = 10**FRACTION_DIGITS
    return max(0.0, math.floor(raw * unit) / unit)


def estimate_orders(doc: dict[str, Any], prices_usd: dict[str, float]) -> dict[str, Any] | None:
    """문서의 배분과 종가(USD)로 주문을 계산한다. 수량은 수수료까지 목표 금액 안에 들어오도록 내림한다 (미국 소수점, 한국 1주 단위)."""
    header = doc.get("header") or {}
    alloc = (doc.get("summary") or {}).get("allocation") or {}
    items = alloc.get("items") or []
    bps = ((doc.get("parameters") or {}).get("backtest") or {}).get("commission_bps")
    as_of = header.get("data_as_of") or header.get("selection_as_of")
    capital = alloc.get("initial_amount_usd")
    fx = alloc.get("fx_rate")
    if alloc.get("basis") != "forward" or not items or bps is None or not as_of or not capital or not fx:
        return None
    fee_rate = float(bps) / 10000
    fx = float(fx)
    rows = []
    for it in items:
        price = prices_usd.get(it["ticker"])
        if not price or price <= 0:
            return None  # 한 종목이라도 가격이 없으면 합계가 틀리므로 표 전체를 만들지 않는다
        target = float(it["usd"])
        basis = share_basis_of(it["ticker"])
        shares = _shares(target, price, fee_rate, basis)
        cost = round(shares * price, 2)
        rows.append({"ticker": it["ticker"], "name": it.get("name") or it["ticker"], "price_usd": price, "target_weight": it["weight"], "target_usd": round(target, 2),
                     "target_krw": it.get("krw", round(target * fx)), "share_basis": basis, "shares": shares, "cost_usd": cost, "fee_usd": round(cost * fee_rate, 2), "cost_krw": round(cost * fx)})  # fmt: skip
    invested = round(sum(r["cost_usd"] for r in rows), 2)
    fees = round(sum(r["fee_usd"] for r in rows), 2)
    left = round(float(capital) - invested - fees, 2)
    cash_target = round(float(capital) * max(0.0, float(alloc.get("cash_weight") or 0.0)), 2)
    label = re.search(r"\((.+)\)\s*$", alloc.get("basis_ko") or "")
    bases = {r["share_basis"] for r in rows}
    overall = bases.pop() if len(bases) == 1 else "mixed"
    return {
        "as_of": str(as_of), "strategy_id": header.get("chosen_portfolio_id") or "", "strategy_label_ko": label.group(1) if label else (header.get("chosen_label_ko") or ""),
        "share_basis": overall, "commission_bps": bps, "fx": {"rate": round(fx, 2), "date": str(as_of), "source_ko": "분석 기준일 환율"},
        "capital": {"amount": round(float(capital), 2), "currency": "USD", "usd": round(float(capital), 2)}, "items": rows,
        "totals": {"invested_usd": invested, "fee_usd": fees, "cash_left_usd": left, "cash_left_krw": round(left * fx), "cash_target_usd": cash_target, "cash_target_krw": round(cash_target * fx)},
        "note_ko": BASIS_NOTE_KO[overall] + NOTE_TAIL_KO,
    }  # fmt: skip


def prices_on(md: Any, tickers: Iterable[str], as_of: dt.date) -> dict[str, float]:
    """기준일 체결용 종가(USD). 모의투자 미리보기와 같은 가격 조회를 쓴다. 그날 행이 없으면 빈 값."""
    want = list(tickers)
    frame = md.view(as_of).panel(want, as_of, as_of, required=want)[0]
    if frame.empty or frame.index[-1].date() != as_of:
        return {}
    row = frame.iloc[-1]
    return {t: round(float(row[t]), 4) for t in want if t in row.index and float(row[t]) > 0}


def compute_execution(doc: dict[str, Any], md: Any) -> dict[str, Any] | None:
    """문서에서 종목·기준일을 읽어 주문을 계산한다. 어떤 이유로든 실패하면 None (리포트 저장·조회를 막지 않는다)."""
    try:
        alloc = (doc.get("summary") or {}).get("allocation") or {}
        as_of = (doc.get("header") or {}).get("data_as_of") or (doc.get("header") or {}).get("selection_as_of")
        if alloc.get("basis") != "forward" or not alloc.get("items") or not as_of:
            return None
        return estimate_orders(doc, prices_on(md, [x["ticker"] for x in alloc["items"]], dt.date.fromisoformat(str(as_of)[:10])))
    except Exception as e:  # noqa: BLE001
        log.warning("예상 매수 주문을 계산하지 못했습니다: %r", e)
        return None


def with_execution(doc: dict[str, Any], execution: dict[str, Any] | None) -> dict[str, Any]:
    """문서 사본에 proposed.execution 을 붙인다 (원본은 그대로). execution 이 없으면 문서를 그대로 돌려준다."""
    if not execution:
        return doc
    return {**doc, "proposed": {"contract": PROPOSED_CONTRACT, **(doc.get("proposed") or {}), "execution": execution}}

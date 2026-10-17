"""SEC 재무를 고른 미국 종목만 전체 기간 다시 받는다 (수집 코드를 고친 뒤 이미 받은 종목에 반영).

python backend/scripts/refetch_sec.py                    # 기본 목록 (주식수·IFRS 수정 대상 33개)
python backend/scripts/refetch_sec.py META V BRK-B       # 직접 고른 종목
python backend/scripts/refetch_sec.py --years 12         # 기간 (기본 FIN_YEARS, 12년)

financials_source 에 upsert 하고 계약 financials 도 다시 고른다 (같은 키는 덮어씀, 지우는 것 없음).
끝나면 가치평가를 다시 계산: python backend/scripts/backfill.py --what valuation
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.adapters.factory import financial_adapter  # noqa: E402
from backend.collectors.common import JobSettings, ensure_assets, log_row  # noqa: E402
from backend.db import open_repository  # noqa: E402
from backend.pipeline.normalizer import default_asset, normalize_financials  # noqa: E402

SOURCE = "SEC_EDGAR"
DEFAULT = [
    # 주식수 없음 (종류주식 회사 등)
    "ABNB", "ACN", "BRK-B", "CMCSA", "CME", "CRWV", "DASH", "EL", "ERIE", "F", "HRL", "IBKR",
    "LEN", "MA", "META", "MKC", "MSTR", "RDDT", "REGN", "RL", "SPCX", "SPG", "STZ", "TKO", "TSN",
    "UHS", "UPS", "V", "XYZ",
    # IFRS 신고 (20-F·40-F)
    "ASML", "CCEP", "FER", "TRI",
]  # fmt: skip


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("tickers", nargs="*", help="미국 티커 (없으면 기본 목록)")
    p.add_argument("--years", type=int, default=None, help="기간 (년, 기본 FIN_YEARS)")
    a = p.parse_args(argv)
    tickers = [t.upper() for t in a.tickers] or DEFAULT
    settings = JobSettings.from_env()
    today = date.today()
    start = date(today.year - (a.years or settings.fin_years), 1, 1)
    adapter = financial_adapter(SOURCE)
    repo = open_repository()
    total = 0
    for i in range(0, len(tickers), 5):
        part = tickers[i : i + 5]
        ensure_assets(repo, {t: None for t in part})
        batch = adapter.fetch(part, start, today)
        rows, _ = normalize_financials(batch, {t: default_asset(t).asset_id for t in part})
        stored = repo.upsert_financials(rows) if rows else 0
        repo.log_fetches(SOURCE, [
            log_row(t, start, today, batch.fetched_at, batch.failed_keys.get(t),
                          len(batch.payload.get(t) or []))
            for t in part
        ])  # fmt: skip
        total += stored
        for t in part:
            n = len(batch.payload.get(t) or [])
            err = batch.failed_keys.get(t)
            print(f"{t:<6} {'실패: ' + err if err else f'{n}행'}", flush=True)
    print(f"\n저장 {total:,}행. 이제 가치평가 다시 계산:")
    print("python backend/scripts/backfill.py --what valuation")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

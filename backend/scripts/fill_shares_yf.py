"""yfinance 유통주식수 이력을 지금 바로 받아 넣는다 (SEC 에 최근 주식 수가 없는 종목 보충).

python backend/scripts/fill_shares_yf.py         # 기본: .env YF_SHARES_TICKERS (없으면 BRK-B,V,STZ,ERIE)
python backend/scripts/fill_shares_yf.py V STZ           # 직접 고른 종목

매일 수집의 주식 분할 단계도 같은 종목을 FIN_REFRESH_DAYS 마다 다시 받는다. 이 스크립트는 그걸
기다리지 않고 한 번 채울 때 쓴다. 끝나면: python backend/scripts/backfill.py --what valuation
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.adapters.crawlers import yfinance_client  # noqa: E402
from backend.collectors.common import JobSettings, ensure_assets  # noqa: E402
from backend.collectors.financials.supplements import yf_share_rows  # noqa: E402
from backend.db import open_repository  # noqa: E402


def main(argv: list[str]) -> int:
    settings = JobSettings.from_env()
    tickers = [t.upper() for t in argv] or settings.yf_shares
    start = date(date.today().year - settings.fin_years, 1, 1)
    repo = open_repository()
    ensure_assets(repo, {t: None for t in tickers})
    for t in tickers:
        hist = yfinance_client.shares_rows(t, start)
        rows = yf_share_rows(t, hist, datetime.now(UTC))
        n = repo.upsert_financials(rows) if rows else 0
        last = f"{hist[-1]['date']} {hist[-1]['shares']:,.0f}주" if hist else "없음"
        print(f"{t:<6} {len(hist)}개월, 저장 {n}행, 마지막 {last}", flush=True)
    print("\n이제 가치평가 다시 계산: python backend/scripts/backfill.py --what valuation")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

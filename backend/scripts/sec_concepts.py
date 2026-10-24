"""SEC companyfacts 에 어떤 개념이 있는지 본다 (DB 안 씀, 진단용).

python backend/scripts/sec_concepts.py ASML             # 분류별 개념 수 + 손익·자본·주식 관련 개념
python backend/scripts/sec_concepts.py ACN BRK-B CMCSA      # 여러 종목
python backend/scripts/sec_concepts.py ASML --all           # 개념 전부
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.adapters.crawlers import edgar_client  # noqa: E402

KEYS = ("share", "revenue", "profit", "income", "equity", "earningspershare")


def show(ticker: str, everything: bool) -> None:
    facts = edgar_client.fetch_company_facts(edgar_client.resolve_cik(ticker))
    print(f"\n===== {ticker} ({facts.get('entityName', '')})")
    for tax, concepts in facts.get("facts", {}).items():
        print(f"[{tax}] 개념 {len(concepts)}개")
        for name in sorted(concepts):
            if not everything and not any(k in name.lower() for k in KEYS):
                continue
            units = concepts[name].get("units", {})
            parts = []
            for u, es in units.items():
                ends = sorted(e["end"] for e in es)
                forms = sorted({e.get("form", "") for e in es})
                parts.append(f"{u} {len(es)}개 {ends[0]}~{ends[-1]} {','.join(forms)}")
            print(f"  {name}: {' | '.join(parts)}")


def main(argv: list[str]) -> int:
    tickers = [a for a in argv if not a.startswith("--")]
    if not tickers:
        print(__doc__)
        return 1
    for t in tickers:
        show(t, "--all" in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

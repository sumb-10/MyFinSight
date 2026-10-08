"""고정 구성종목 파일 만들기: 내려받은 표 → config/kospi200.csv 또는 config/ndx.csv.

KOSPI200 과 Nasdaq-100 은 정기 변경이 12월이라 프로젝트 기간(~11월) 동안 목록이 그대로임.
무료로 구성종목을 주는 공식 API 가 없어 한 번 내려받은 표를 고정 파일로 쓴다.

KOSPI200
1. data.krx.co.kr → 지수 → 주가지수 → 지수구성종목 → "코스피 200" 조회 → CSV 내려받기
   → config/kospi200_krx.csv (2026-10-05 내려받은 파일이 이미 들어 있음)
2. python scripts/make_constituents_csv.py --index KOSPI200 --as-of 2026-10-05

Nasdaq-100 (위키백과 Nasdaq-100 문서에서 구성종목 표가 빠짐)
1. https://stockanalysis.com/list/nasdaq-100-stocks/ 의 표 (Download 는 유료라 표를 복사)
   (티커·종목명 칸이 있으면 다른 표도 됨: QQQ 보유종목 등) → config/ndx_holdings.csv 로 저장
2. python scripts/make_constituents_csv.py --index NDX --as-of 2026-10-05

섹터·산업: NDX 는 위키백과 S&P 500 표의 GICS → config/gics_overrides.csv → yfinance 순서로 찾고,
KOSPI200 은 gics_overrides.csv → yfinance. yfinance 섹터는 GICS 11개 이름으로 바꿈. 인터넷 필요.
못 찾은 종목이 출력되면 config/gics_overrides.csv 에 붙여 넣고 섹터·산업을 고친 뒤 다시 실행.

python scripts/make_constituents_csv.py --index NDX 다른파일.csv     # 입력 파일 직접 지정
python scripts/make_constituents_csv.py --index NDX --no-sector      # 섹터 찾기 없이 (확인용)
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from myfinsight.data.constituent_source import (  # noqa: E402
    CODE_COLS,
    constituent_rows_from_table,
    load_gics_overrides,
)
from myfinsight.data.constituents import GICS_SECTORS, ROW_BOUNDS  # noqa: E402
from myfinsight.data.normalizer import normalize_ticker  # noqa: E402
from myfinsight.schemas.market import IndexCode  # noqa: E402

INPUTS = {
    IndexCode.KOSPI200: ("kospi200_krx.csv", "kospi200.csv", "KRX 지수구성종목 코스피 200"),
    IndexCode.NDX: ("ndx_holdings.csv", "ndx.csv", "Nasdaq-100 보유종목 표"),
}


def _frame(path: Path, header: int | None) -> pd.DataFrame:
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str, header=header)
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc, header=header)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"{path} 인코딩을 읽지 못함 (UTF-8·EUC-KR 아님)")


def read_table(path: Path) -> list[dict[str, str]]:
    """내려받은 표 읽기 (CSV 는 UTF-8 또는 EUC-KR, 또는 Excel).

    머리글 위에 설명 줄이 있는 파일(ETF 보유종목 표 등)은 티커 칸 이름이 나오는 줄을 머리글로 씀.
    """
    try:
        frame = _frame(path, 0)
        if any(c in frame.columns for c in CODE_COLS):
            return frame.fillna("").to_dict(orient="records")
    except pd.errors.ParserError:
        pass
    with path.open("rb") as f:
        raw = f.read()
    text = next((raw.decode(e) for e in ("utf-8-sig", "cp949") if _decodes(raw, e)), "")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        cells = [c.strip().strip('"') for c in next(csv.reader([line]), [])]
        if any(c in cells for c in CODE_COLS):
            rows = list(csv.DictReader(lines[i:]))
            return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in rows]
    raise SystemExit(f"{path} 에서 티커 칸({', '.join(CODE_COLS)})을 찾지 못함")


def _decodes(raw: bytes, enc: str) -> bool:
    try:
        raw.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


def make_lookup(index: IndexCode, no_sector: bool) -> Callable[[str], tuple[str, str]]:
    overrides = load_gics_overrides()
    if no_sector:
        return lambda t: overrides.get(t, ("", ""))
    sp: dict[str, tuple[str, str]] = {}
    if index == IndexCode.NDX:  # S&P 500 표의 GICS 를 먼저 (미국 종목은 대부분 여기 있음)
        from myfinsight.data.crawlers import wikipedia_client

        for r in wikipedia_client.sp500_rows():
            sp[normalize_ticker(r["ticker"])] = (r["sector"], r["sub_industry"])
    from myfinsight.data.crawlers.yfinance_client import sector_of

    return lambda t: sp.get(t) or overrides.get(t) or sector_of(t)


def main(argv: list[str] | None = None, *, default_index: str | None = None) -> int:
    p = argparse.ArgumentParser(description="내려받은 구성종목 표 → config/ 고정 파일")
    p.add_argument("input", type=Path, nargs="?", help="내려받은 CSV·Excel (기본: 지수별 파일)")
    p.add_argument(
        "--index", default=default_index, choices=["KOSPI200", "NDX"], required=not default_index
    )
    p.add_argument("--as-of", default=None, help="구성종목 기준일 (예: 2026-10-05)")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--no-sector", action="store_true", help="섹터를 찾지 않음 (확인용)")
    a = p.parse_args(argv)
    index = IndexCode(a.index)
    raw_name, out_name, what = INPUTS[index]
    src = a.input or ROOT / "config" / raw_name
    out = a.out or ROOT / "config" / out_name
    if not src.exists():
        raise SystemExit(f"{src} 없음 (파일 맨 위 설명대로 내려받아 저장)")

    rows = constituent_rows_from_table(
        read_table(src), make_lookup(index, a.no_sector), index=index
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    as_of = a.as_of or "기준일 미기재"
    with out.open("w", encoding="utf-8", newline="") as f:
        made = date.today()
        f.write(f"# {what}, {as_of}, 원본 {src.name}, 만든 날 {made}\n")
        w = csv.DictWriter(f, fieldnames=["ticker", "name", "sector", "industry"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)}종목 → {out}")
    lo, hi = ROW_BOUNDS[index]
    if not lo <= len(rows) <= hi:
        print(f"주의: 종목 수 {len(rows)} ({index.value} 는 {lo}~{hi} 여야 저장됨)")
    bad = [r for r in rows if r["sector"] not in GICS_SECTORS or not r["industry"]]
    if bad:
        print(f"섹터·산업을 못 찾은 종목 {len(bad)}개 (config/gics_overrides.csv 에 추가):")
        print("  (형식: 티커,GICS섹터,산업. 끝의 종목명 칸은 읽을 때 무시됨)")
        for r in bad:
            sector, industry = r["sector"] or "섹터", r["industry"] or "산업"
            print(f"{r['ticker']},{sector},{industry},{r['name']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

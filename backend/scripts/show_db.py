"""DB 내용 보기: 저장된 데이터를 요약하거나 종목별로 출력한다 (데이터는 안 바꿈, .env 의 DB).

python backend/scripts/show_db.py                      # 테이블별 행 수, 출처별 가격 범위, 교차검증 결과
python backend/scripts/show_db.py price MSFT           # 한 종목 최근 5거래일 가격 (출처별 원본 + CONSENSUS)
python backend/scripts/show_db.py price 005930.KS 10   # 최근 10거래일
python backend/scripts/show_db.py fin 005930.KS        # 한 종목 재무 (최근 공시 20개)
python backend/scripts/show_db.py news AAPL            # 한 종목 최근 뉴스 10개
python backend/scripts/show_db.py sql "SELECT source, COUNT(*) FROM news GROUP BY source"   # 직접 조회
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import func, select, text  # noqa: E402

from backend.pipeline.normalizer import asset_id_for, normalize_ticker  # noqa: E402
from backend.db import open_repository  # noqa: E402
from backend.db import tables as T  # noqa: E402

SUMMARY_TABLES = (
    "index_constituent",
    "assets",
    "price_daily",
    "price_daily_source",
    "fx_daily",
    "financials",
    "financials_source",
    "news",
)


def _print_rows(header: list[str], rows: list) -> None:
    rows = [["" if v is None else str(v) for v in r] for r in rows]
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(header)]
    print("  ".join(h.ljust(w) for h, w in zip(header, widths, strict=True)))
    for r in rows:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths, strict=True)))
    if not rows:
        print("(없음)")


def summary(c) -> None:  # noqa: ANN001
    print("[테이블별 행 수]")
    for name in SUMMARY_TABLES:
        t = T.metadata.tables[name]
        print(f"  {name:<18} {c.execute(select(func.count()).select_from(t)).scalar_one():>10,}")
    p = T.price_daily_source
    print("\n[가격 원본: 출처별]")
    q = (
        select(p.c.source, func.count(func.distinct(p.c.ticker)), func.count(), func.min(p.c.date),
               func.max(p.c.date))
        .group_by(p.c.source)
        .order_by(p.c.source)
    )  # fmt: skip
    _print_rows(["출처", "종목", "행", "처음", "마지막"], list(c.execute(q)))
    print("\n[교차검증: CONSENSUS 행]")
    q = (
        select(p.c.verify_status, func.count())
        .where(p.c.source == "CONSENSUS")
        .group_by(p.c.verify_status)
    )
    _print_rows(["상태", "행"], list(c.execute(q)))
    n = T.news
    print("\n[뉴스: 출처별]")
    q = select(n.c.source, func.count(), func.max(n.c.published_at)).group_by(n.c.source)
    _print_rows(["출처", "기사", "최근 기사"], list(c.execute(q)))


def price(c, ticker: str, days: int) -> None:  # noqa: ANN001
    p = T.price_daily_source
    t = normalize_ticker(ticker)
    dates = select(p.c.date).where(p.c.ticker == t).distinct().order_by(p.c.date.desc()).limit(days)
    q = (
        select(p.c.date, p.c.source, p.c.close, p.c.adj_close, p.c.volume, p.c.verify_status)
        .where(p.c.ticker == t, p.c.date.in_(dates.scalar_subquery()))
        .order_by(p.c.date.desc(), p.c.source)
    )
    _print_rows(["날짜", "출처", "종가", "수정종가", "거래량", "검증"], list(c.execute(q)))


def fin(c, ticker: str) -> None:  # noqa: ANN001
    f = T.financials_source
    q = (
        select(f.c.period, f.c.metric, f.c.value, f.c.unit, f.c.disclosed_at, f.c.source)
        .where(f.c.asset_id == asset_id_for(normalize_ticker(ticker)))
        .order_by(f.c.disclosed_at.desc(), f.c.metric)
        .limit(20)
    )
    _print_rows(["기간", "항목", "값", "단위", "공시일", "출처"], list(c.execute(q)))


def news(c, ticker: str) -> None:  # noqa: ANN001
    n = T.news
    q = (
        select(n.c.published_at, n.c.source, n.c.title)
        .where(n.c.asset_id == asset_id_for(normalize_ticker(ticker)))
        .order_by(n.c.published_at.desc())
        .limit(10)
    )
    _print_rows(["게시", "출처", "제목"], list(c.execute(q)))


def main(argv: list[str]) -> int:
    repo = open_repository()
    with repo.engine.connect() as c:
        if not argv:
            summary(c)
        elif argv[0] == "price" and len(argv) >= 2:
            price(c, argv[1], int(argv[2]) if len(argv) > 2 else 5)
        elif argv[0] == "fin" and len(argv) >= 2:
            fin(c, argv[1])
        elif argv[0] == "news" and len(argv) >= 2:
            news(c, argv[1])
        elif argv[0] == "sql" and len(argv) >= 2:
            if not argv[1].lstrip().lower().startswith("select"):
                print("SELECT 문만 실행함 (데이터를 바꾸지 않게)")
                return 1
            res = c.execute(text(argv[1]))
            _print_rows(list(res.keys()), res.fetchmany(50))
        else:
            print(__doc__)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

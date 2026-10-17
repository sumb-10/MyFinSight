"""DB 결측 점검: 가격·재무에 빠진 값이 있는지 센다 (읽기만 함, 데이터는 안 바꿈, .env 의 DB).

python backend/scripts/check_missing.py                 # 가격 + 재무 전체 점검, 종목 목록은 상위 20개
python backend/scripts/check_missing.py price           # 가격만
python backend/scripts/check_missing.py fin             # 재무만
python backend/scripts/check_missing.py --top 50        # 목록을 50개까지
python backend/scripts/check_missing.py --csv logs      # 전체 목록을 logs/missing_*.csv 로 저장

[가격] price_daily 기준
  거래일 달력: 시장(US/KR)마다 "그날 가격이 있는 종목 수가 가장 많은 날의 20% 이상"인 날
  빠진 날: 종목의 첫날~마지막날 사이 달력 날짜 중 행이 없는 날 (상장 전·상장폐지 후는 안 셈)
  최장 연속: 빠진 날이 연속으로 이어진 최대 길이 (M02-03 기준: 1일은 FILLED, 2일 이상은 EXCLUDED)
  멈춤: 마지막 날이 시장 마지막 거래일보다 이른 종목
[재무] financials 기준 (STOCK 만, ETF·INDEX 는 재무가 없는 게 정상)
  핵심 항목: 매출·순이익·자본총계·주식수 중 한 번도 없는 것
  빠진 연도: 최근 12년 안에서 손익(IS)·재무상태(BS) 항목의 period_end 가 하나도 없는 해
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

from backend.db import open_repository  # noqa: E402

FIN_SPAN = 12  # 재무 연도 점검 범위: 올해 포함 최근 12년 (FIN_YEARS 와 같게)
CAL_RATIO = 0.2  # 그날 종목 수가 최대치의 20% 이상이면 거래일로 봄
KEY_ITEMS = {  # 핵심 항목 묶음: 묶음 안 이름 중 하나만 있어도 있음 (띄어쓰기·(분기)·(누적) 무시)
    "매출": ("매출액", "수익(매출액)", "영업수익"),
    "순이익": ("당기순이익", "당기순이익(손실)", "지배주주순이익", "순이익(TTM)"),
    "자본총계": ("자본총계", "자본총계(최근)"),
    "주식수": ("유통주식수", "발행주식수"),
}


def _print_rows(header: list[str], rows: list) -> None:
    rows = [["" if v is None else str(v) for v in r] for r in rows]
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(header)]
    print("  ".join(h.ljust(w) for h, w in zip(header, widths, strict=True)))
    for r in rows:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths, strict=True)))
    if not rows:
        print("(없음)")


def _save(csv_dir: Path | None, name: str, header: list[str], rows: list) -> None:
    if csv_dir is None:
        return
    csv_dir.mkdir(parents=True, exist_ok=True)
    path = csv_dir / f"missing_{name}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  → 전체 목록 저장: {path}")


def check_price(c, top: int, csv_dir: Path | None) -> None:  # noqa: ANN001
    print("=" * 70 + "\n[가격] price_daily\n" + "=" * 70)

    # 1) 가격이 아예 없는 종목
    rows = list(
        c.execute(
            text("""
        SELECT a.market, a.asset_type, a.yfinance_symbol, a.name
        FROM assets a
        WHERE NOT EXISTS (SELECT 1 FROM price_daily p WHERE p.asset_id = a.asset_id)
        ORDER BY a.market, a.asset_type, a.yfinance_symbol
    """)
        )
    )
    print(f"\n1) 가격이 하나도 없는 종목: {len(rows)}개")
    _print_rows(["시장", "종류", "티커", "이름"], rows[:top])
    _save(csv_dir, "price_no_rows", ["market", "asset_type", "ticker", "name"], rows)

    # 2) 값이 비어 있거나 이상한 칸
    r = c.execute(
        text("""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE open IS NULL), COUNT(*) FILTER (WHERE high IS NULL),
               COUNT(*) FILTER (WHERE low IS NULL), COUNT(*) FILTER (WHERE close IS NULL),
               COUNT(*) FILTER (WHERE adj_close IS NULL), COUNT(*) FILTER (WHERE volume IS NULL),
               COUNT(*) FILTER (WHERE close <= 0 OR adj_close <= 0),
               COUNT(*) FILTER (WHERE volume = 0)
        FROM price_daily
    """)
    ).one()
    print(f"\n2) 칸별 빈 값 (전체 {r[0]:,}행)")
    _print_rows(
        ["open", "high", "low", "close", "adj_close", "volume", "종가<=0", "거래량=0"],
        [[f"{v:,}" for v in r[1:]]],
    )
    print("  (CONSENSUS 로 실린 날은 OHLC 가 비는 게 정상: "
          "교차검증 행은 adj_close·close·volume 만 가짐)")  # fmt: skip

    # 3) 거래일 달력 대비 빠진 날
    cal_sql = f"""
        WITH daily AS (
            SELECT a.market, p.date, COUNT(*) AS n
            FROM price_daily p JOIN assets a ON a.asset_id = p.asset_id
            GROUP BY a.market, p.date
        )
        SELECT market, date FROM daily d
        WHERE n >= {CAL_RATIO} * (SELECT MAX(n) FROM daily x WHERE x.market = d.market)
        ORDER BY market, date
    """
    cal: dict[str, list] = defaultdict(list)
    for m, d in c.execute(text(cal_sql)):
        cal[m].append(d)
    idx = {m: {d: i for i, d in enumerate(ds)} for m, ds in cal.items()}
    print("\n3) 거래일 달력 (시장별)")
    _print_rows(
        ["시장", "거래일 수", "처음", "마지막"],
        [[m, len(ds), ds[0], ds[-1]] for m, ds in sorted(cal.items())],
    )

    miss_sql = f"""
        WITH cal AS ({cal_sql}),
        rng AS (
            SELECT p.asset_id, a.market, a.yfinance_symbol AS ticker, MIN(p.date) AS d0,
                   MAX(p.date) AS d1
            FROM price_daily p JOIN assets a ON a.asset_id = p.asset_id
            GROUP BY p.asset_id, a.market, a.yfinance_symbol
        )
        SELECT r.market, r.ticker, c.date
        FROM rng r JOIN cal c ON c.market = r.market AND c.date BETWEEN r.d0 AND r.d1
        WHERE NOT EXISTS (
            SELECT 1 FROM price_daily p WHERE p.asset_id = r.asset_id AND p.date = c.date)
    """
    missing: dict[tuple[str, str], list] = defaultdict(list)
    for m, t, d in c.execute(text(miss_sql)):
        missing[(m, t)].append(d)
    out = []
    for (m, t), ds in missing.items():
        pos = sorted(idx[m][d] for d in ds)
        longest = run = 1
        for a, b in zip(pos, pos[1:], strict=False):
            run = run + 1 if b == a + 1 else 1
            longest = max(longest, run)
        out.append([m, t, len(ds), longest, min(ds), max(ds)])
    out.sort(key=lambda x: (-x[3], -x[2]))
    n_excl = sum(1 for x in out if x[3] >= 2)
    print(f"\n4) 중간에 빠진 날이 있는 종목: {len(out)}개 (그중 2일 이상 연속 빠짐 {n_excl}개)")
    head = ["시장", "티커", "빠진 날", "최장 연속", "처음 빠진 날", "마지막 빠진 날"]
    _print_rows(head, out[:top])
    _save(csv_dir, "price_gaps", ["market", "ticker", "missing_days", "longest_run", "first",
                                  "last"], out)  # fmt: skip

    # 4) 업데이트가 멈춘 종목
    rows = list(
        c.execute(
            text("""
        WITH last AS (
            SELECT a.market, a.yfinance_symbol AS ticker, a.asset_type, MAX(p.date) AS d1
            FROM price_daily p JOIN assets a ON a.asset_id = p.asset_id
            GROUP BY a.market, a.yfinance_symbol, a.asset_type
        )
        SELECT l.market, l.ticker, l.asset_type, l.d1, m.d1 AS market_last
        FROM last l JOIN (SELECT market, MAX(d1) AS d1 FROM last GROUP BY market) m
             ON m.market = l.market
        WHERE l.d1 < m.d1
        ORDER BY l.d1, l.ticker
    """)
        )
    )
    print(f"\n5) 마지막 가격이 시장 최신일보다 이른 종목: {len(rows)}개 (상장폐지·티커 변경 의심)")
    _print_rows(["시장", "티커", "종류", "마지막 날", "시장 최신일"], rows[:top])
    _save(csv_dir, "price_stale", ["market", "ticker", "asset_type", "last", "market_last"], rows)


def check_fin(c, top: int, csv_dir: Path | None) -> None:  # noqa: ANN001
    print("\n" + "=" * 70 + "\n[재무] financials (STOCK 만)\n" + "=" * 70)

    # 1) 재무가 아예 없는 종목
    rows = list(
        c.execute(
            text("""
        SELECT a.market, a.yfinance_symbol, a.name,
               EXISTS (SELECT 1 FROM financials_source s WHERE s.asset_id = a.asset_id) AS in_src
        FROM assets a
        WHERE a.asset_type = 'STOCK'
          AND NOT EXISTS (SELECT 1 FROM financials f WHERE f.asset_id = a.asset_id)
        ORDER BY a.market, a.yfinance_symbol
    """)
        )
    )
    print(f"\n1) 재무가 하나도 없는 주식: {len(rows)}개 "
          "(원본에 있음=True 면 financials 발행 단계 문제)")  # fmt: skip
    _print_rows(["시장", "티커", "이름", "원본에 있음"], rows[:top])
    _save(csv_dir, "fin_no_rows", ["market", "ticker", "name", "in_financials_source"], rows)

    # 2) 핵심 항목이 한 번도 없는 종목
    norm = "regexp_replace(replace(f.item, ' ', ''), '\\((분기|누적)\\)$', '')"
    have: dict[str, set[str]] = defaultdict(set)
    q = f"""
        SELECT a.market, a.yfinance_symbol, {norm}
        FROM financials f JOIN assets a ON a.asset_id = f.asset_id
        WHERE a.asset_type = 'STOCK'
        GROUP BY a.market, a.yfinance_symbol, {norm}
    """
    market_of = {}
    for m, t, item in c.execute(text(q)):
        have[t].add(item)
        market_of[t] = m
    groups = {g: {n.replace(" ", "") for n in names} for g, names in KEY_ITEMS.items()}
    out = []
    for t, items in have.items():
        lack = [g for g, names in groups.items() if not items & names]
        if lack:
            out.append([market_of[t], t, ", ".join(lack)])
    out.sort()
    print(f"\n2) 핵심 항목(매출·순이익·자본총계·주식수) 중 빠진 게 있는 주식: {len(out)}개")
    by_group = {g: sum(1 for x in out if g in x[2].split(", ")) for g in KEY_ITEMS}
    print("  항목별: " + ", ".join(f"{g} {n}개" for g, n in by_group.items()))
    _print_rows(["시장", "티커", "빠진 항목"], out[:top])
    _save(csv_dir, "fin_key_items", ["market", "ticker", "missing_items"], out)

    # 3) 회계연도 사이 빠진 해, 최신 기간 (손익·재무상태 항목만, 최근 FIN_SPAN 년 안에서)
    #    주식분할·배당 같은 ETC 항목은 수십 년 전 날짜가 섞여 있어 빼고 봄
    rows = list(
        c.execute(
            text("""
        WITH y AS (
            SELECT a.market, a.yfinance_symbol AS ticker,
                   EXTRACT(YEAR FROM f.period_end)::int AS yr, MAX(f.period_end) AS last_end
            FROM financials f JOIN assets a ON a.asset_id = f.asset_id
            WHERE a.asset_type = 'STOCK' AND f.statement IN ('IS', 'BS')
              AND f.period_end >= make_date(EXTRACT(YEAR FROM CURRENT_DATE)::int - :span + 1, 1, 1)
            GROUP BY a.market, a.yfinance_symbol, EXTRACT(YEAR FROM f.period_end)
        )
        SELECT market, ticker, MIN(yr), MAX(yr), COUNT(*), MAX(yr) - MIN(yr) + 1 - COUNT(*),
               MAX(last_end)
        FROM y GROUP BY market, ticker
        ORDER BY market, ticker
    """),
            {"span": FIN_SPAN},
        )
    )
    gaps = sorted([r for r in rows if r[5] > 0], key=lambda r: -r[5])
    print(f"\n3) 최근 {FIN_SPAN}년 안 첫해~마지막해 사이에 빠진 회계연도가 있는 주식: "
          f"{len(gaps)}개 (재무 있는 주식 {len(rows)}개 중)")  # fmt: skip
    head = ["시장", "티커", "첫해", "마지막해", "있는 해", "빠진 해", "최근 기간 끝"]
    _print_rows(head, gaps[:top])
    _save(csv_dir, "fin_year_gaps", ["market", "ticker", "first_year", "last_year", "years",
                                     "missing_years", "last_period_end"], rows)  # fmt: skip

    hist = defaultdict(int)
    for r in rows:
        hist[(r[0], r[3] - r[2] + 1)] += 1
    print("\n4) 재무 기간 길이 분포 (몇 년치가 있는지, 시장별 종목 수)")
    _print_rows(["시장", "연수", "종목"], [[m, y, n] for (m, y), n in sorted(hist.items())])

    newest = {m: max(r[6] for r in rows if r[0] == m) for m in {r[0] for r in rows}}
    stale = [r for r in rows if (newest[r[0]] - r[6]).days > 400]
    stale.sort(key=lambda r: r[6])
    print(f"\n5) 최근 재무가 시장 최신 기간보다 400일 넘게 오래된 주식: {len(stale)}개")
    _print_rows(["시장", "티커", "최근 기간 끝"], [[r[0], r[1], r[6]] for r in stale[:top]])


def main(argv: list[str]) -> int:
    top, csv_dir, what = 20, None, {"price", "fin"}
    args = list(argv)
    if "--top" in args:
        i = args.index("--top")
        top = int(args[i + 1])
        del args[i : i + 2]
    if "--csv" in args:
        i = args.index("--csv")
        csv_dir = Path(args[i + 1])
        del args[i : i + 2]
    if args:
        if args[0] not in what:
            print(__doc__)
            return 1
        what = {args[0]}
    repo = open_repository()
    with repo.engine.connect() as c:
        if "price" in what:
            check_price(c, top, csv_dir)
        if "fin" in what:
            check_fin(c, top, csv_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

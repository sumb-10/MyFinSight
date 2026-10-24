"""DB 에 쌓인 재무·가치평가·뉴스를 보는 읽기 전용 보고서. 결과를 그대로 붙여 보내면 됨.

python backend/scripts/coverage_report.py                 # .env 의 DATABASE_URL
python backend/scripts/coverage_report.py "postgres://..."  # 주소를 직접 줘서
python backend/scripts/coverage_report.py --since 2016    # 뉴스·가치평가 표를 2016년부터 (기본 2000)

- 읽기만 한다: PostgreSQL 은 세션을 읽기 전용(default_transaction_read_only)으로 열고, SQLite 는
  query_only. 테이블을 만들거나 바꾸지 않는다.
- 출력 (표마다 시장 KR·US 로 나눔)
  0. 가격 price_daily: 시장별 행·종목·기간, 출처별 원본(price_daily_source), 교차검증 상태
     (시장 × 기간 묶음별 VERIFIED·MISMATCH·SINGLE, MISMATCH 에서 혼자 벗어난 출처)
  0-1. 환율: fx_daily 에 실린 출처, 출처별 원본(fx_daily_source)
  1. 재무 financials: 출처 × 묶음(분기 손익·재무상태·주식수·배당·분할·연간 등)별 기간과 종목 수
  2. 가치평가 valuation_daily: 첫·마지막 날짜, 종목 수, 연도별 PER·PBR 이 있는 비율
  3. 뉴스 news: 출처 × 연도별 기사 수, 그리고 균형 보기 = 달마다 기사가 1건 이상 있는 종목 수의
     평균·최소 (지수 구성종목 수 대비 %)
  4. GICS 섹터별 (v4): 섹터마다 종목 수와 재무·가치평가·뉴스가 있는 종목 수. 금융 섹터(은행·보험·
     증권)는 DART·EDGAR 에 매출액·영업이익 줄이 없어 "해당 없음"으로 세고 결측으로 보지 않는다.
     GICS 출처별 종목 수, 세부산업이 없는 종목 목록도 보여 준다.
  5. 공시 disclosures: 출처별 건수·종목·기간, 출처 × 유형(event_type) 상위
  6. 재무 공시일 지연: 기간 끝에서 disclosed_at 까지 150일·365일이 넘는 보고서 수 (정정 공시로 공시일이
     늦게 잡힌 경우, 그만큼 가치평가에 늦게 쓰임)
  7. 테이블 크기 (PostgreSQL)
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import extract, func, inspect, select  # noqa: E402

from backend.pipeline.gics import REVENUE_ITEMS, expects_revenue  # noqa: E402
from backend.db import default_db_url  # noqa: E402
from backend.db import tables as T  # noqa: E402
from backend.db.readers import mask_url as _mask  # noqa: E402
from backend.db.readers import readonly_engine  # noqa: E402


def item_group(item: str) -> str:
    """financials.item → 보고서 묶음 이름."""
    if item == "주식분할":
        return "주식분할(yfinance)"
    if item in ("유통주식수", "발행주식수", "자기주식수"):
        return "주식수"
    if item.startswith("주당배당금") or item == "배당금총액":
        return "배당"
    if item.endswith("(분기)"):
        return "분기 손익(3개월)"
    if item.endswith("(누적)"):
        return "누적 손익"
    if item in ("자산총계", "부채총계", "자본총계"):
        return "재무상태(자산·부채·자본)"
    if "TTM" in item or item in ("자본총계(최근)", "BPS"):
        return "스냅샷(TTM 등)"
    return "기타 손익·재무 항목"


def table(rows: list[list[Any]], header: list[str]) -> str:
    cells = [header] + [[("" if c is None else str(c)) for c in r] for r in rows]
    width = [max(len(r[i]) for r in cells) for i in range(len(header))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, width, strict=True)).rstrip() for r in cells]
    lines.insert(1, "  ".join("-" * w for w in width))
    return "\n".join("  " + x for x in lines)


def universe(conn: Any) -> dict[str, int]:
    """시장별 지수 구성종목 수 (최근 스냅샷, STOCK)."""
    ic, a = T.index_constituent, T.assets
    latest = (
        select(ic.c.index_code, func.max(ic.c.snapshot_date).label("d"))
        .group_by(ic.c.index_code)
        .subquery()
    )
    q = (
        select(a.c.market, func.count(func.distinct(ic.c.asset_id)))
        .select_from(
            ic.join(
                latest,
                (latest.c.index_code == ic.c.index_code) & (latest.c.d == ic.c.snapshot_date),
            ).join(a, a.c.asset_id == ic.c.asset_id)
        )
        .where(a.c.asset_type == "STOCK")
        .group_by(a.c.market)
    )
    return {m: n for m, n in conn.execute(q)}


def _period(year: int) -> str:
    return "~2009" if year < 2010 else "2010~2015" if year < 2016 else "2016~"


def price_section(conn: Any) -> str:
    p, s, a = T.price_daily, T.price_daily_source, T.assets
    q = (
        select(a.c.market, func.count(), func.count(func.distinct(p.c.asset_id)),
               func.min(p.c.date), func.max(p.c.date))
        .select_from(p.join(a, a.c.asset_id == p.c.asset_id))
        .group_by(a.c.market).order_by(a.c.market)
    )  # fmt: skip
    head = [[m, f"{n:,}", k, lo, hi] for m, n, k, lo, hi in conn.execute(q)]
    q2 = (
        select(s.c.source, func.count(), func.count(func.distinct(s.c.ticker)),
               func.min(s.c.date), func.max(s.c.date))
        .group_by(s.c.source).order_by(func.count().desc())
    )  # fmt: skip
    src = [[x, f"{n:,}", k, lo, hi] for x, n, k, lo, hi in conn.execute(q2)]
    y = extract("year", p.c.date).label("y")
    q3 = (
        select(a.c.market, y, p.c.verify_status, func.count())
        .select_from(p.join(a, a.c.asset_id == p.c.asset_id))
        .group_by(a.c.market, y, p.c.verify_status)
    )
    ver: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for m, yr, st, n in conn.execute(q3):
        ver[(m, _period(int(yr)))][st or "검증 전"] += n
    order = {"~2009": 0, "2010~2015": 1, "2016~": 2}
    vrows = []
    for (m, per), c in sorted(ver.items(), key=lambda kv: (kv[0][0], order[kv[0][1]])):
        tot = sum(c.values())
        mm = c.get("MISMATCH", 0)
        vrows.append([m, per, f"{c.get('VERIFIED', 0):,}", f"{mm:,} ({100 * mm / tot:.0f}%)",
                      f"{c.get('SINGLE', 0):,}", f"{c.get('검증 전', 0):,}"])  # fmt: skip
    q4 = (
        select(s.c.outlier_sources, func.count())
        .where(s.c.source == "CONSENSUS", s.c.verify_status == "MISMATCH")
        .group_by(s.c.outlier_sources)
    )
    outl: dict[str, int] = defaultdict(int)
    for o, n in conn.execute(q4):
        key = ",".join(o) if isinstance(o, list) else str(o or "-")
        outl[key] += n
    orows = [[k, f"{n:,}"] for k, n in sorted(outl.items(), key=lambda kv: -kv[1])[:8]]
    return (
        "0. 가격 price_daily (계약 테이블)\n"
        + table(head, ["시장", "행 수", "종목", "첫 날짜", "마지막 날짜"])
        + "\n\n   출처별 원본 price_daily_source (CONSENSUS = 교차검증 기록)\n"
        + table(src, ["출처", "행 수", "종목", "첫 날짜", "마지막 날짜"])
        + "\n\n   교차검증 상태 (시장 × 기간). SINGLE = 출처가 하나뿐\n"
        + table(vrows, ["시장", "기간", "VERIFIED", "MISMATCH", "SINGLE", "검증 전"])
        + "\n\n   MISMATCH 에서 혼자 벗어난 출처\n"
        + table(orows, ["출처", "(종목, 날짜) 수"])
    )


def fx_section(conn: Any) -> str:
    out = []
    for name in ("fx_daily", "fx_daily_source"):
        if not inspect(conn).has_table(name):
            out.append(f"   {name}: 테이블 없음")
            continue
        f = T.metadata.tables[name]
        q = (
            select(f.c.source, func.count(), func.min(f.c.date), func.max(f.c.date))
            .group_by(f.c.source).order_by(f.c.source)
        )  # fmt: skip
        rows = [[s, f"{n:,}", lo, hi] for s, n, lo, hi in conn.execute(q)]
        label = (
            "계약 fx_daily 에 실린 출처" if name == "fx_daily" else "출처별 원본 fx_daily_source"
        )
        out.append(f"   {label}\n" + table(rows, ["출처", "일수", "첫 날짜", "마지막 날짜"]))
    return "0-1. 환율 USDKRW\n" + "\n\n".join(out)


def disclosure_section(conn: Any, top: int = 10) -> str:
    if not inspect(conn).has_table("disclosures"):
        return "5. 공시 disclosures: 테이블 없음 (python backend/scripts/migrate_v2.py --apply)"
    d = T.disclosures
    q = (
        select(d.c.source, func.count(), func.count(func.distinct(d.c.asset_id)),
               func.min(d.c.filed_at), func.max(d.c.filed_at))
        .group_by(d.c.source).order_by(d.c.source)
    )  # fmt: skip
    head = [
        [s, f"{n:,}", k, f"{lo:%Y-%m-%d}", f"{hi:%Y-%m-%d}"] for s, n, k, lo, hi in conn.execute(q)
    ]
    q2 = select(
        d.c.source, d.c.event_type, func.count(), func.count(func.distinct(d.c.asset_id))
    ).group_by(d.c.source, d.c.event_type)
    by: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
    for s, ev, n, k in conn.execute(q2):
        by[s].append((n, ev or "-", k))
    rows = []
    for s in sorted(by):
        for n, ev, k in sorted(by[s], reverse=True)[:top]:
            rows.append([s, ev, f"{n:,}", k])
    return (
        "5. 공시 disclosures\n"
        + table(head, ["출처", "건수", "종목", "첫 접수", "마지막 접수"])
        + f"\n\n   출처 × 유형(event_type) 상위 {top}\n"
        + table(rows, ["출처", "유형", "건수", "종목"])
    )


def lag_section(conn: Any) -> str:
    """기간 끝 → 공시일(disclosed_at) 지연. 정정 공시로 늦게 잡힌 보고서는 가치평가에 늦게 쓰인다."""
    f = T.financials_source
    q = (
        select(f.c.source, f.c.report_code, f.c.asset_id, f.c.period, f.c.period_end,
               func.min(f.c.disclosed_at))
        .where(f.c.period_end.is_not(None), f.c.source.in_(("DART", "SEC_EDGAR")))
        .group_by(f.c.source, f.c.report_code, f.c.asset_id, f.c.period, f.c.period_end)
    )  # fmt: skip
    agg: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for s, rc, _aid, _per, pend, disc in conn.execute(q):
        days = (disc - pend).days
        c = agg[(s, rc or "-")]
        c[0] += 1
        c[1] += days > 150
        c[2] += days > 365
    rows = [[s, rc, f"{n:,}", f"{a1:,} ({100 * a1 / n:.0f}%)", f"{a2:,}"]
            for (s, rc), (n, a1, a2) in sorted(agg.items()) if n]  # fmt: skip
    return "6. 재무 공시일 지연 (원본 financials_source, 보고서 = 종목 × 기간)\n" + table(
        rows, ["출처", "보고서 코드", "보고서", "150일 넘음", "365일 넘음"]
    )


def size_section(conn: Any) -> str:
    if conn.dialect.name != "postgresql":
        return "7. 테이블 크기: PostgreSQL 에서만"
    from sqlalchemy import text

    rows = [
        [r[0], r[1]]
        for r in conn.execute(text(
            "SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) "
            "FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC"))
    ]  # fmt: skip
    total = conn.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))"))
    return f"7. 테이블 크기 (DB 전체 {total.scalar_one()})\n" + table(rows, ["테이블", "크기"])


def financial_section(conn: Any) -> str:
    f, a = T.financials, T.assets
    q = (
        select(
            a.c.market,
            f.c.source,
            f.c.item,
            func.min(f.c.period_end),
            func.max(f.c.period_end),
            func.count(func.distinct(f.c.asset_id)),
            func.count(),
        )
        .select_from(f.join(a, a.c.asset_id == f.c.asset_id))
        .group_by(a.c.market, f.c.source, f.c.item)
    )
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for market, source, item, lo, hi, stocks, n in conn.execute(q):
        g = groups.setdefault(
            (market, source, item_group(item)), {"lo": lo, "hi": hi, "stocks": 0, "rows": 0}
        )
        g["lo"], g["hi"] = min(g["lo"], lo), max(g["hi"], hi)
        g["stocks"] = max(g["stocks"], stocks)
        g["rows"] += n
    rows = [
        [m, s, grp, f"{v['lo']:%Y}~{v['hi']:%Y}", v["stocks"], f"{v['rows']:,}"]
        for (m, s, grp), v in sorted(groups.items())
    ]
    # 시장 × 연도: 분기 순이익이 4개 분기 모두 있는 종목 수
    q2 = (
        select(
            a.c.market,
            extract("year", f.c.period_end).label("y"),
            f.c.asset_id,
            func.count(func.distinct(f.c.period_end)),
        )
        .select_from(f.join(a, a.c.asset_id == f.c.asset_id))
        .where(f.c.item.in_(("당기순이익(분기)", "지배주주순이익(분기)")))
        .group_by(a.c.market, "y", f.c.asset_id)
    )
    per_year: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    for market, y, _aid, nq in conn.execute(q2):
        c = per_year[(market, int(y))]
        c[0] += 1
        c[1] += nq >= 4
    rows2 = [[m, y, v[0], v[1]] for (m, y), v in sorted(per_year.items())]
    return (
        "1. 재무 financials (계약 테이블, 출처 × 묶음)\n"
        + table(rows, ["시장", "출처", "묶음", "기간끝 연도", "종목 수(항목별 최대)", "행 수"])
        + "\n\n   분기 순이익(3개월) 연도별: 1개 분기 이상 있는 종목 / 4개 분기 모두 있는 종목\n"
        + table(rows2, ["시장", "연도", "종목(≥1분기)", "종목(4분기)"])
    )


def valuation_section(conn: Any, since: int) -> str:
    if not inspect(conn).has_table("valuation_daily"):
        return "2. 가치평가 valuation_daily: 테이블 없음 (python backend/scripts/migrate_v2.py --apply)"
    v, a = T.valuation_daily, T.assets
    q = (
        select(
            a.c.market,
            func.min(v.c.date),
            func.max(v.c.date),
            func.count(func.distinct(v.c.asset_id)),
            func.count(),
        )
        .select_from(v.join(a, a.c.asset_id == v.c.asset_id))
        .group_by(a.c.market)
    )
    head = [[m, lo, hi, n, f"{rows:,}"] for m, lo, hi, n, rows in conn.execute(q)]
    y = extract("year", v.c.date).label("y")
    q2 = (
        select(
            a.c.market,
            y,
            func.count(func.distinct(v.c.asset_id)),
            func.count(),
            func.count(v.c.per),
            func.count(v.c.pbr),
            func.count(v.c.dividend_yield),
        )
        .select_from(v.join(a, a.c.asset_id == v.c.asset_id))
        .where(v.c.date >= date(since, 1, 1))
        .group_by(a.c.market, y)
        .order_by(a.c.market, y)
    )

    def pct(x: int, n: int) -> str:
        return f"{100 * x / n:.0f}%" if n else "-"

    body = [
        [m, int(yr), stocks, f"{n:,}", pct(per, n), pct(pbr, n), pct(dy, n)]
        for m, yr, stocks, n, per, pbr, dy in conn.execute(q2)
    ]
    return (
        "2. 가치평가 valuation_daily\n"
        + table(head, ["시장", "첫 날짜", "마지막 날짜", "종목 수", "행 수"])
        + "\n\n   연도별 (거래일×종목 행 중 값이 있는 비율. PER 은 적자면 비어 있는 게 정상)\n"
        + table(body, ["시장", "연도", "종목", "행", "PER 있음", "PBR 있음", "배당수익률 있음"])
    )


def news_section(conn: Any, since: int, uni: dict[str, int]) -> str:
    n, a = T.news, T.assets
    y = extract("year", n.c.published_at).label("y")
    mth = extract("month", n.c.published_at).label("m")
    q = (
        select(n.c.source, a.c.market, y, func.count())
        .select_from(n.join(a, a.c.asset_id == n.c.asset_id))
        .where(n.c.published_at >= datetime(since, 1, 1, tzinfo=UTC))
        .group_by(n.c.source, a.c.market, y)
        .order_by(n.c.source, a.c.market, y)
    )
    counts = [[s, m, int(yr), f"{c:,}"] for s, m, yr, c in conn.execute(q)]
    q2 = (
        select(n.c.source, a.c.market, y, mth, func.count(func.distinct(n.c.asset_id)))
        .select_from(n.join(a, a.c.asset_id == n.c.asset_id))
        .where(n.c.published_at >= datetime(since, 1, 1, tzinfo=UTC))
        .group_by(n.c.source, a.c.market, y, mth)
    )
    months: dict[tuple[str, str, int], list[int]] = defaultdict(list)
    for s, m, yr, _mo, stocks in conn.execute(q2):
        months[(s, m, int(yr))].append(stocks)
    q3 = (
        select(a.c.market, y, mth, func.count(func.distinct(n.c.asset_id)))
        .select_from(n.join(a, a.c.asset_id == n.c.asset_id))
        .where(n.c.published_at >= datetime(since, 1, 1, tzinfo=UTC))
        .group_by(a.c.market, y, mth)
    )
    for m, yr, _mo, stocks in conn.execute(q3):
        months[("(모든 출처)", m, int(yr))].append(stocks)
    bal = []
    for (s, m, yr), xs in sorted(months.items()):
        avg = sum(xs) / len(xs)
        total = uni.get(m, 0)
        share = f"{100 * avg / total:.0f}%" if total else "-"
        bal.append([s, m, yr, len(xs), f"{avg:.0f}", min(xs), share])
    return (
        "3. 뉴스 news: 출처 × 시장 × 연도 기사 수\n"
        + table(counts, ["출처", "시장", "연도", "기사 수"])
        + "\n\n   균형 보기: 달마다 기사가 1건 이상 있는 종목 수 "
        + f"(구성종목 KR {uni.get('KR', 0)}, US {uni.get('US', 0)})\n"
        + table(bal, ["출처", "시장", "연도", "달 수", "평균 종목", "최소 종목", "평균/구성종목"])
    )


def _latest_members(conn: Any) -> dict[str, set[str]]:
    """asset_id → 최근 스냅샷에서 속한 지수들 (STOCK 만)."""
    ic, a = T.index_constituent, T.assets
    latest = (
        select(ic.c.index_code, func.max(ic.c.snapshot_date).label("d"))
        .group_by(ic.c.index_code)
        .subquery()
    )
    q = (
        select(ic.c.asset_id, ic.c.index_code)
        .select_from(
            ic.join(
                latest,
                (latest.c.index_code == ic.c.index_code) & (latest.c.d == ic.c.snapshot_date),
            ).join(a, a.c.asset_id == ic.c.asset_id)
        )
        .where(a.c.asset_type == "STOCK")
    )
    out: dict[str, set[str]] = defaultdict(set)
    for aid, index in conn.execute(q):
        out[aid].add(index)
    return out


def gics_section(conn: Any, today: date | None = None) -> str:
    """4. GICS 섹터별 커버리지와 GICS 없는 종목."""
    cols = {c["name"] for c in inspect(conn).get_columns("assets")}
    if "gics_sector_code" not in cols:
        return "4. GICS: assets 에 GICS 칸 없음 (python backend/scripts/migrate_v2.py --apply)"
    a, f, n = T.assets, T.financials, T.news
    members = _latest_members(conn)
    if not members:
        return "4. GICS: 구성종목 스냅샷 없음"
    ids = sorted(members)
    info = {
        r.asset_id: r
        for r in conn.execute(
            select(
                a.c.asset_id,
                a.c.yfinance_symbol,
                a.c.name,
                a.c.market,
                a.c.gics_sector_code,
                a.c.gics_sub_industry_code,
                a.c.gics_source,
            )
        )
        if r.asset_id in members
    }
    sectors = {}
    if inspect(conn).has_table("gics_taxonomy"):
        g = T.gics_taxonomy
        sectors = dict(conn.execute(select(g.c.code, g.c.name_en).where(g.c.level == 1)).all())

    def having(q: Any) -> set[str]:
        return {x for x in conn.execute(q).scalars() if x in members}

    ni = having(
        select(f.c.asset_id)
        .where(f.c.item.in_(("당기순이익(분기)", "지배주주순이익(분기)", "당기순이익")))
        .distinct()
    )
    rev = having(select(f.c.asset_id).where(f.c.item.in_(REVENUE_ITEMS)).distinct())
    val: set[str] = set()
    if inspect(conn).has_table("valuation_daily"):
        v = T.valuation_daily
        val = having(select(v.c.asset_id).where(v.c.per.is_not(None)).distinct())
    since = datetime.combine(today or date.today(), datetime.min.time(), UTC) - timedelta(days=365)
    news = having(select(n.c.asset_id).where(n.c.published_at >= since).distinct())
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for aid in ids:
        r = info.get(aid)
        sec = (r.gics_sector_code if r else None) or "-"
        groups[(r.market if r else "?", sec)].append(aid)

    def pct(x: int, total: int) -> str:
        return f"{x} ({100 * x / total:.0f}%)" if total else "-"

    rows = []
    for (market, sec), xs in sorted(groups.items()):
        t = len(xs)
        name = f"{sec} {sectors.get(sec, '(GICS 없음)' if sec == '-' else '')}".strip()
        rev_cell = pct(sum(x in rev for x in xs), t) if expects_revenue(sec) else "해당 없음"
        rows.append(
            [
                market,
                name,
                t,
                pct(sum(x in ni for x in xs), t),
                rev_cell,
                pct(sum(x in val for x in xs), t),
                pct(sum(x in news for x in xs), t),
            ]
        )
    src: dict[tuple[str, str], int] = defaultdict(int)
    for aid in ids:
        r = info.get(aid)
        src[(r.market if r else "?", (r.gics_source if r else None) or "(없음)")] += 1
    no_sub = [
        [
            (r.market if r else "?"),
            (r.yfinance_symbol if r else aid),
            (r.name if r else ""),
            ",".join(sorted(members[aid])),
            (r.gics_source if r else None) or "-",
            (r.gics_sector_code if r else None) or "-",
        ]
        for aid in ids
        if not (r := info.get(aid)) or not r.gics_sub_industry_code
    ]
    out = (
        "4. GICS 섹터별 (최근 스냅샷 구성종목, STOCK). 금융 섹터는 매출액·영업이익 줄이 없어 "
        "'해당 없음'\n"
        + table(
            rows,
            ["시장", "섹터", "종목", "분기 순이익", "매출액", "PER 있음", "뉴스(최근 1년)"],
        )
        + "\n\n   GICS 출처별 종목 수\n"
        + table([[m, s, c] for (m, s), c in sorted(src.items())], ["시장", "gics_source", "종목"])
    )
    if no_sub:
        out += (
            f"\n\n   GICS 세부산업이 없는 종목 {len(no_sub)}개 "
            "(python backend/scripts/backfill.py --what gics, 안 되면 "
            "backend/data/config/kr_gics.csv·gics_overrides.csv)\n"
            + table(no_sub, ["시장", "티커", "이름", "지수", "gics_source", "섹터"])
        )
    else:
        out += "\n\n   모든 구성종목에 GICS 세부산업이 있음"
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("url", nargs="?", help="DB 주소 (없으면 .env 의 DATABASE_URL)")
    p.add_argument("--since", type=int, default=2000, help="뉴스·가치평가 연도별 표의 시작 연도")
    a = p.parse_args(argv)
    url = a.url or default_db_url()
    print(f"DB: {_mask(url)} (읽기 전용)")
    engine = readonly_engine(url)
    try:
        with engine.connect() as conn:
            have = set(inspect(conn).get_table_names())
            missing = {"assets", "index_constituent", "financials", "news"} - have
            if missing:
                print(
                    f"v2 테이블이 없음: {sorted(missing)} (python backend/scripts/migrate_v2.py 먼저)"
                )
                return 1
            uni = universe(conn)
            print(f"지수 구성종목 (최근 스냅샷, STOCK): {uni}\n")
            if "price_daily" in have:
                print(price_section(conn) + "\n")
            if "fx_daily" in have:
                print(fx_section(conn) + "\n")
            print(financial_section(conn) + "\n")
            print(valuation_section(conn, a.since) + "\n")
            print(news_section(conn, a.since, uni) + "\n")
            print(gics_section(conn) + "\n")
            print(disclosure_section(conn) + "\n")
            if "financials_source" in have:
                print(lag_section(conn) + "\n")
            print(size_section(conn))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

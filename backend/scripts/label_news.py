"""뉴스 사실 표시를 이미 저장된 기사에 채운다 (pipeline/news_labels.py 규칙, .env 의 DB).

python backend/scripts/label_news.py                       # 미리보기: 표본 종목만 계산해 통계·예시 (DB 안 바꿈)
python backend/scripts/label_news.py --tickers 005930 AAPL # 미리보기 종목 고르기
python backend/scripts/label_news.py --apply               # 표시가 빈 기사만 채움 (전 종목)
python backend/scripts/label_news.py --apply --all         # 규칙을 바꾼 뒤: 전부 다시 계산

새로 저장하는 기사는 upsert_news 가 알아서 채우므로 이 스크립트는 처음 한 번(또는 규칙 변경 뒤)만.
--apply 는 (asset_id, story_id) 인덱스가 없으면 먼저 만든다. 종목 단위로 저장해서 끊겨도 다시 돌리면 이어서 함.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import bindparam, case, select, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from backend.db import open_repository  # noqa: E402
from backend.db import tables as T  # noqa: E402
from backend.db.sql import news_asset_names  # noqa: E402
from backend.pipeline import news_labels as L  # noqa: E402

PREVIEW = ["005930", "000660", "035420", "AAPL", "NVDA", "T", "A", "BRK-B"]
LABELS = ("is_press_release", "title_has_name", "story_id", "available_on", "is_first_report")
BATCH = 2000
RETRIES = 5


def compute(rows: list[Any], names: L.AssetNames) -> dict[int, dict[str, Any]]:
    """기사들 → {news_id: 표시} (is_first_report 포함: 묶음마다 발행 시각이 가장 이른 기사)."""
    out: dict[int, dict[str, Any]] = {}
    groups: dict[str, list[tuple[Any, int]]] = defaultdict(list)
    for r in rows:
        lab = L.labels(names, title=r.title, url=r.url, publisher=r.publisher,
                       published_at=r.published_at, query=r.query, source=r.source)  # fmt: skip
        out[r.news_id] = lab
        groups[lab["story_id"]].append((r.published_at, r.news_id))
    for items in groups.values():
        first = min(items)[1]
        for _, nid in items:
            out[nid]["is_first_report"] = nid == first
    return out


def read_asset(conn: Any, asset_id: str, only_missing: bool) -> list[Any]:
    n = T.news  # Google RSS 주소는 news.google.com 넘김 주소라 쓸모없고 길어서 안 읽음
    q = select(
        n.c.news_id, n.c.source, n.c.title, n.c.publisher, n.c.published_at, n.c.query,
        n.c.is_press_release, n.c.title_has_name, n.c.story_id, n.c.available_on,
        n.c.is_first_report,
        case((n.c.source == "GOOGLE_RSS", None), else_=n.c.url).label("url"),
    ).where(n.c.asset_id == asset_id)  # fmt: skip
    rows = list(conn.execute(q))
    if only_missing and all(r.story_id is not None for r in rows):
        return []
    return rows


def changed(rows: list[Any], labs: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        new = labs[r.news_id]
        if any(getattr(r, k) != new[k] for k in LABELS):
            out.append({"nid": r.news_id, **new})
    return out


def write(conn: Any, rows: list[dict[str, Any]]) -> None:
    n = T.news
    if conn.dialect.name == "postgresql":
        for i in range(0, len(rows), BATCH):
            part = rows[i : i + BATCH]
            vals, params = [], {}
            for j, r in enumerate(part):
                vals.append(f"(:i{j}, :p{j}, :t{j}, :s{j}, CAST(:a{j} AS DATE), :f{j})")
                params.update({f"i{j}": r["nid"], f"p{j}": r["is_press_release"],
                               f"t{j}": r["title_has_name"], f"s{j}": r["story_id"],
                               f"a{j}": r["available_on"], f"f{j}": r["is_first_report"]})  # fmt: skip
            conn.execute(text(f"""
                UPDATE news SET is_press_release = v.p, title_has_name = v.t, story_id = v.s,
                       available_on = v.a, is_first_report = v.f
                FROM (VALUES {", ".join(vals)}) AS v(id, p, t, s, a, f)
                WHERE news.news_id = v.id
            """), params)  # fmt: skip
        return
    conn.execute(
        n.update().where(n.c.news_id == bindparam("nid")).values(
            {k: bindparam(k) for k in LABELS}
        ),
        rows,
    )


def preview(repo: Any, tickers: list[str]) -> None:
    a = T.assets
    with repo.engine.connect() as c:
        ids = list(c.execute(select(a.c.asset_id).where(a.c.ticker.in_(tickers))).scalars())
        names = news_asset_names(c, ids)
        total: Counter[str] = Counter()
        for aid in ids:
            rows = read_asset(c, aid, only_missing=False)
            if not rows:
                continue
            labs = compute(rows, names[aid])
            st: Counter[str] = Counter()
            pubs_pr: Counter[str] = Counter()
            by_src: dict[str, Counter[str]] = defaultdict(Counter)
            for r in rows:
                lab = labs[r.news_id]
                st["기사"] += 1
                st["보도자료"] += lab["is_press_release"]
                st["제목에 종목명"] += lab["title_has_name"]
                st["첫 보도"] += lab["is_first_report"]
                by_src[r.source]["기사"] += 1
                by_src[r.source]["제목에 종목명"] += lab["title_has_name"]
                if lab["is_press_release"]:
                    pubs_pr[r.publisher or "(주소로 판단)"] += 1
            total.update(st)
            n = st["기사"]
            print(f"\n== {names[aid].ticker} {names[aid].name} ({n:,}건)")
            print("  " + ", ".join(f"{k} {v:,} ({v / n:.0%})" for k, v in st.items() if k != "기사"))
            print(f"  묶음 {n - st['첫 보도']:,}건이 다른 기사의 중복 (같은 날·같은 제목)")
            print("  출처별 제목에 종목명: " + ", ".join(
                f"{s} {c['제목에 종목명'] / c['기사']:.0%}" for s, c in sorted(by_src.items())))  # fmt: skip
            print("  보도자료로 본 언론사: " + ", ".join(f"{p} {k}" for p, k in pubs_pr.most_common(6)))
            sample = sorted(rows, key=lambda r: r.published_at)[-400:]
            for want, label in ((True, "제목에 종목명 O"), (False, "제목에 종목명 X")):
                ex = [r for r in sample if labs[r.news_id]["title_has_name"] is want][:3]
                for r in ex:
                    lab = labs[r.news_id]
                    print(f"   [{label}] {r.published_at:%Y-%m-%d %H:%M}Z → 반영 {lab['available_on']}"
                          f" | {r.title[:70]} | {r.publisher}")  # fmt: skip
        if total["기사"]:
            n = total["기사"]
            print(f"\n== 표본 합계 {n:,}건: " + ", ".join(
                f"{k} {v / n:.0%}" for k, v in total.items() if k != "기사"))  # fmt: skip
    print("\n(미리보기만 함. 채우려면 --apply)")


def apply(repo: Any, redo_all: bool) -> None:
    with repo.engine.begin() as c:
        c.execute(text("CREATE INDEX IF NOT EXISTS idx_news_asset_story ON news (asset_id, story_id)"))
        ids = list(c.execute(text("SELECT DISTINCT asset_id FROM news ORDER BY asset_id")).scalars())
    t0, done, written = time.time(), 0, 0
    for aid in ids:
        for attempt in range(1, RETRIES + 1):
            try:
                with repo.engine.begin() as c:
                    rows = read_asset(c, aid, only_missing=not redo_all)
                    if rows:
                        labs = compute(rows, news_asset_names(c, [aid])[aid])
                        diff = changed(rows, labs)
                        write(c, diff)
                        written += len(diff)
                break
            except OperationalError as exc:  # 네트워크가 끊기면 연결을 새로 열고 그 종목부터 다시
                if attempt == RETRIES:
                    raise
                print(f"  {aid} 연결 끊김 ({attempt}/{RETRIES}), {attempt * 15}초 뒤 다시: "
                      f"{str(exc).splitlines()[0][:80]}", flush=True)  # fmt: skip
                repo.engine.dispose()
                time.sleep(attempt * 15)
        done += 1
        if done % 20 == 0 or done == len(ids):
            print(f"[{time.time() - t0:6.0f}s] {done}/{len(ids)}종목, 바꾼 기사 {written:,}", flush=True)
    print(f"끝. 바꾼 기사 {written:,}건 (규칙 {L.RULE_VERSION})")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--apply", action="store_true", help="DB 에 채움 (없으면 미리보기)")
    p.add_argument("--all", action="store_true", help="이미 채운 기사도 다시 계산")
    p.add_argument("--tickers", nargs="*", default=PREVIEW, help="미리보기 종목 (시장 안 코드)")
    a = p.parse_args(argv)
    repo = open_repository()
    if a.apply:
        apply(repo, a.all)
    else:
        preview(repo, a.tickers)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

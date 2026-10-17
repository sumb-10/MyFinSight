"""어댑터 직접 돌려 보기 (실제 API 호출).

python backend/scripts/try_adapters.py env      # .env 에 어떤 키가 있는지 (값은 가림)
python backend/scripts/try_adapters.py smoke    # 진짜 API 9곳을 조금씩 불러 보기
python backend/scripts/try_adapters.py price  --source TIINGO --keys MSFT BRK-B
python backend/scripts/try_adapters.py price  --keys 005930.KS KRW=X
python backend/scripts/try_adapters.py financial --source DART --keys 005930 --start 2025-01-01
python backend/scripts/try_adapters.py news --source NAVER_NEWS --keys 삼성전자
python backend/scripts/try_adapters.py constituents --index NDX   # 구성종목 (NDX·KOSPI200 은 config/ 파일)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.adapters.crawlers import config  # noqa: E402
from backend.adapters.crawlers.config import MissingApiKeyError  # noqa: E402
from backend.adapters.factory import (  # noqa: E402
    financial_adapter,
    news_adapter,
    price_adapter,
)
from backend.collectors.constituents.collector import validate_constituents  # noqa: E402
from backend.collectors.constituents.source import (  # noqa: E402
    default_constituent_source,
)

# smoke: 출처마다 (종류, 출처, 키, 필요한 .env 키, 추가 인자)
SMOKE = [
    ("price", "YFINANCE", ["MSFT", "005930.KS", "KRW=X"], [], {}),
    ("price", "KIS", ["005930"], ["KIS_APP_KEY", "KIS_APP_SECRET"], {}),
    ("price", "TIINGO", ["MSFT"], ["TIINGO_API_KEY"], {}),
    ("price", "ALPACA", ["MSFT"], ["ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"], {}),
    ("financial", "DART", ["005930"], ["DART_API_KEY"], {}),
    ("financial", "SEC_EDGAR", ["MSFT"], ["SEC_USER_AGENT"], {}),
    ("news", "NAVER_NEWS", ["삼성전자"], ["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"], {}),
    ("news", "NEWSAPI", ["NVIDIA"], ["NEWSAPI_KEY"], {}),
    ("news", "GOOGLE_RSS", ["삼성전자"], [], {}),
]
MAKERS = {"price": price_adapter, "financial": financial_adapter, "news": news_adapter}


def _mask(v: str) -> str:
    return "(비어 있음)" if not v else (v[:3] + "…" + f" ({len(v)}자)")


def cmd_env(_: argparse.Namespace) -> int:
    print(f".env 위치: {config.env_file().resolve()} (있음: {config.env_file().exists()})")
    for k in config._KEYS:
        print(f"  {k:<22} {_mask(config.get(k))}")
    return 0


def _show(batch: object) -> None:
    payload = batch.payload  # type: ignore[attr-defined]
    failed = getattr(batch, "failed_tickers", None) or getattr(batch, "failed_keys", {})
    print(f"  출처={batch.source}  받은 시각={batch.fetched_at:%Y-%m-%d %H:%M:%S}")  # type: ignore[attr-defined]
    for key, rows in payload.items():
        print(f"  [{key}] {len(rows)}행")
        print(f"     처음: {rows[0]}")
        if len(rows) > 1:
            print(f"     끝  : {rows[-1]}")
    for key, why in failed.items():
        print(f"  [{key}] 실패: {why}")


def cmd_fetch(a: argparse.Namespace) -> int:
    kw = {} if a.kind == "price" and a.source is None else {"source": a.source}
    if a.kind != "price" and a.source is None:
        print("--source 가 필요함")
        return 2
    ad = MAKERS[a.kind](**kw)
    print(type(ad).__name__)
    try:
        _show(ad.fetch(a.keys, a.start, a.end))
    except MissingApiKeyError as e:
        print(f"  설정 오류: {e.message}")
        return 1
    return 0


def cmd_smoke(a: argparse.Namespace) -> int:
    end = date.today() - timedelta(days=1)
    bad = 0
    for kind, source, keys, need, extra in SMOKE:
        missing = [k for k in need if not config.get(k)]
        if missing:
            print(f"- {source:<11} 건너뜀: .env 에 {', '.join(missing)} 없음")
            continue
        start = date(end.year - 1, 1, 1) if kind == "financial" else end - timedelta(days=20)
        ad = MAKERS[kind](source, retry_max=1, **extra)
        try:
            b = ad.fetch(keys, start, end)
        except Exception as e:  # noqa: BLE001
            print(f"- {source:<11} 오류: {type(e).__name__}: {e}")
            bad += 1
            continue
        failed = getattr(b, "failed_tickers", None) or getattr(b, "failed_keys", {})
        counts = ", ".join(f"{k} {len(v)}행" for k, v in b.payload.items())
        mark = "성공" if not failed else "일부 실패"
        print(f"- {source:<11} {mark}: {counts or '받은 것 없음'}")
        for k, why in failed.items():
            print(f"      {k}: {why[:160]}")
        bad += bool(failed)
    for index in ("SP500", "NDX", "KOSPI200"):  # S&P 500 은 위키백과, 나머지는 config/ 고정 파일
        try:
            rows = default_constituent_source().fetch(index)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            print(f"- 구성종목 {index:<8} 오류: {type(e).__name__}: {e}")
            bad += 1
            continue
        problems = validate_constituents(index, rows)  # type: ignore[arg-type]
        print(f"- 구성종목 {index:<8} {'성공' if not problems else '검사 불통과'}: {len(rows)}행")
        for p in problems:
            print(f"      {p[:200]}")
        bad += bool(problems)
    print("\n전부 성공" if not bad else f"\n{bad}곳에 문제 있음 (위 사유 확인)")
    return 1 if bad else 0


def cmd_constituents(a: argparse.Namespace) -> int:
    src = default_constituent_source()
    try:
        rows = src.fetch(a.index)
    except Exception as e:  # noqa: BLE001 - 파일 없음 등은 사유만 보여 줌
        print(f"{a.index} 오류: {type(e).__name__}: {e}")
        return 1
    print(f"{src.source_name}: {a.index} {len(rows)}행")
    for r in rows[:5]:
        print(f"  {r.ticker:<8} {r.sector:<24} {r.industry}")
    problems = validate_constituents(a.index, rows)
    for p in problems:
        print(f"  검사: {p}")
    if rows:
        print(f"  출처: {rows[0].source}")
    elif (
        a.index == "SP500"
    ):  # 표를 못 찾음: 페이지에 있는 표 모양을 보여 줌 (보내 주면 고칠 수 있음)
        from backend.adapters.crawlers import wikipedia_client as w

        print(f"  {w.SP500_URL} 의 표 (행 6개 넘는 것만):")
        for line in w.describe_tables(w.SP500_URL):
            print(f"    {line}")
    return 1 if problems else 0


def main() -> int:
    p = argparse.ArgumentParser(description="역할 A 어댑터 직접 돌려 보기")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("env", help=".env 키 확인").set_defaults(func=cmd_env)
    sub.add_parser("smoke", help="진짜 API 9곳 간단 확인").set_defaults(func=cmd_smoke)
    for kind in ("price", "financial", "news"):
        s = sub.add_parser(kind, help=f"{kind} 어댑터 한 번 부르기")
        s.add_argument("--source", default=None)
        s.add_argument("--keys", nargs="+", required=True)
        s.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 1))
        s.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 30))
        s.set_defaults(func=cmd_fetch, kind=kind)
    c = sub.add_parser("constituents", help="지수 구성종목 한 번 읽기")
    c.add_argument("--index", choices=["SP500", "NDX", "KOSPI200"], default="SP500")
    c.set_defaults(func=cmd_constituents)
    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())

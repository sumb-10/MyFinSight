"""M02-05 구성종목 출처: 인터페이스, 위키백과 구현, KOSPI200 고정 파일.

출처 기록 (명세 M02-05 출처 기록란)
- 출처: 위키백과 영문판 구성종목 표. S&P 500 은 GICS 분류 포함. Nasdaq-100 은 ICB 분류라
  GICS 는 S&P 500 표에서 같은 티커를 찾아 붙이고, 없으면 backend/data/config/gics_overrides.csv 에서 찾음
- URL: https://en.wikipedia.org/wiki/List_of_S%26P_500_companies ,
       https://en.wikipedia.org/wiki/Nasdaq-100
- 갱신 방법: 정기 변경일(3·6·9·12월 셋째 금요일) 이후 처음 실행할 때 표를 다시 읽음
  (constituents.py)
- industry 칸: GICS Sub-Industry 이름 (위키백과 표가 주는 단계)
  예: Semiconductors, Application Software

KOSPI200 (추가)
- 출처: 한국거래소 정보데이터시스템 지수구성종목 화면에서 내려받은 표를
  backend/scripts/make_constituents_csv.py --index KOSPI200 로 바꾼 backend/data/config/kospi200.csv (KOSPI200 을 주는 무료 공식 API 가 없음)
- sector·industry (v4): 종목별 GICS 표 backend/data/config/kr_gics.csv (사람이 정하고 검수 표시, K17) 의 GICS
  섹터·세부산업 영문 이름을 덮어 씀. 표에 없는 종목만 파일 값(yfinance 섹터를 GICS 섹터 이름으로
  바꾼 값, Yahoo 산업 이름)이 남고, 그 이름은 수집기 결과 검사에서 "GICS 세부산업 못 찾음"으로 알림
- backend/data/config/kospi200.csv 가 없으면 KRX 원본 backend/data/config/kospi200_krx.csv(EUC-KR) 를 바로 읽는다
  (섹터·산업은 kr_gics.csv 로만 채우므로 인터넷이 필요 없음)
- 갱신 방법: 정기 변경(6·12월) 뒤 KRX 원본을 바꾸고, 새 종목은 kr_gics.csv 에 한 줄씩 추가
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from backend.adapters.crawlers import wikipedia_client
from backend.core.paths import DATA_DIR
from backend.pipeline.normalizer import normalize_ticker
from backend.schemas.errors import DataSourceError
from backend.schemas.market import IndexCode, IndexConstituent


@runtime_checkable
class ConstituentSource(Protocol):
    """지수 구성종목 출처 (명세 M02-05)."""

    def fetch(self, index: IndexCode) -> list[IndexConstituent]:
        """해당 지수의 현재 구성종목을 가져온다."""
        ...


def config_file(name: str) -> Path:
    """backend/data/config/ 파일 위치."""
    return DATA_DIR / "config" / name


def gics_overrides_csv() -> Path:
    """GICS 보충표 위치 (backend/data/config/gics_overrides.csv)."""
    return config_file("gics_overrides.csv")


def load_gics_overrides(path: Path | str | None = None) -> dict[str, tuple[str, str]]:
    """티커 → (sector, industry). 파일이 없으면 빈 dict."""
    p = Path(path) if path else gics_overrides_csv()
    if not p.exists():
        return {}
    with p.open(encoding="utf-8", newline="") as f:
        return {
            normalize_ticker(r["ticker"]): (r["sector"].strip(), r["industry"].strip())
            for r in csv.DictReader(f)
            if r.get("ticker")
        }


class WikipediaConstituentSource:
    """위키백과 표 기반 진짜 출처. 네트워크를 쓴다 (테스트에서는 session 에 테스트용 세션을 넣음).

    티커는 yfinance 표기로 바꿔 저장한다 (BRK.B → BRK-B). GICS 를 못 찾은 Nasdaq-100 종목은
    sector·industry 가 빈 칸으로 나가고, constituents.py 결과 검사에서 걸려 저장되지 않는다
    (경고에 티커가 나오면 backend/data/config/gics_overrides.csv 에 한 줄 추가).
    """

    source_name = "wikipedia"

    def __init__(
        self,
        *,
        session: Any | None = None,
        overrides_csv: Path | str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.session = session
        self.overrides_csv = overrides_csv
        self._clock = clock

    def fetch(self, index: IndexCode) -> list[IndexConstituent]:
        """지수 구성종목을 읽는다. snapshot_date 는 오늘(UTC) 로 두고, 저장할 때 다시 정한다."""
        code = IndexCode(index)
        if code == IndexCode.KOSPI200:
            raise DataSourceError(
                "위키백과 출처는 KOSPI200 을 지원하지 않음 (KRX 출처 필요)",
                details={"index": code.value},
            )
        now = self._clock()
        sp = wikipedia_client.sp500_rows(self.session)
        gics = {normalize_ticker(r["ticker"]): (r["sector"], r["sub_industry"]) for r in sp}
        if code == IndexCode.SP500:
            src = f"wikipedia:S&P 500 {wikipedia_client.SP500_URL}"
            rows = [(r["ticker"], r["name"]) for r in sp]
        else:
            src = (
                f"wikipedia:Nasdaq-100 {wikipedia_client.NDX_URL} "
                f"(GICS: {wikipedia_client.SP500_URL})"
            )
            rows = [(r["ticker"], r["name"]) for r in wikipedia_client.ndx_rows(self.session)]
            gics = {**load_gics_overrides(self.overrides_csv), **gics}
        out = []
        for raw, name in rows:
            ticker = normalize_ticker(raw)
            sector, industry = gics.get(ticker, ("", ""))
            out.append(
                IndexConstituent(
                    index_code=code,
                    ticker=ticker,
                    name=name,
                    sector=sector,
                    industry=industry,
                    snapshot_date=now.date(),
                    source=src,
                    fetched_at=now.astimezone(UTC),
                )
            )
        return sorted(out, key=lambda r: r.ticker)


# ---------------------------------------------------------------- KOSPI200 고정 파일 (추가)
YAHOO_TO_GICS = {
    "Technology": "Information Technology",
    "Communication Services": "Communication Services",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Financial Services": "Financials",
    "Healthcare": "Health Care",
    "Industrials": "Industrials",
    "Basic Materials": "Materials",
    "Energy": "Energy",
    "Real Estate": "Real Estate",
    "Utilities": "Utilities",
}
"""Yahoo(yfinance) 섹터 이름 → GICS 섹터 이름 (11개가 1:1 로 맞음)."""

KOSPI200_CSV = "kospi200.csv"
KOSPI200_KRX_CSV = "kospi200_krx.csv"
NDX_CSV = "ndx.csv"
_FILES = {IndexCode.KOSPI200: KOSPI200_CSV, IndexCode.NDX: NDX_CSV}
CODE_COLS = (
    "종목코드",
    "단축코드",
    "code",
    "ticker",
    "Holding Ticker",
    "Ticker",
    "Symbol",
    "symbol",
)
_NAME_COLS = (
    "종목명",
    "한글 종목약명",
    "name",
    "Name",
    "Company",
    "Company Name",
    "Security Name",
    "companyName",
)
_US_TICKER = re.compile(r"^[A-Z][A-Z0-9]{0,5}([.-][A-Z])?$")


def kr_symbol(code: str) -> str:
    """6자리 코드(앞 0 빠진 것 포함) 또는 005930.KS → 005930.KS (KOSPI 상장)."""
    text = str(code).strip().upper().removesuffix(".KS")
    digits = text.zfill(6) if text.isdigit() else text
    return f"{digits}.KS"


def kospi200_rows_from_table(
    table: list[dict[str, str]],
    sector_of: Callable[[str], tuple[str, str]],
) -> list[dict[str, str]]:
    """KRX 지수구성종목 표(행 dict) → kospi200.csv 행 (ticker, name, sector, industry).

    sector_of(티커) 는 (Yahoo 섹터 또는 GICS 섹터, 산업) 을 준다. 모르면 ("", "").
    """
    return constituent_rows_from_table(table, sector_of, index=IndexCode.KOSPI200)


def _symbol(code: str, index: IndexCode) -> str | None:
    """표의 코드 → 저장 티커. 미국 지수는 주식 티커 모양이 아니면(현금·선물 행 등) None."""
    if index == IndexCode.KOSPI200:
        return kr_symbol(code)
    t = normalize_ticker(code)
    return t if _US_TICKER.match(t) else None


def constituent_rows_from_table(
    table: list[dict[str, str]],
    sector_of: Callable[[str], tuple[str, str]],
    *,
    index: IndexCode,
) -> list[dict[str, str]]:
    """내려받은 구성종목 표(행 dict) → config CSV 행 (ticker, name, sector, industry).

    KOSPI200: KRX 지수구성종목 표.
    NDX: stockanalysis.com Nasdaq-100 목록이나 ETF(QQQ 등) 보유종목 표.
    sector_of(티커) 는 (Yahoo 섹터 또는 GICS 섹터, 산업) 을 준다. 모르면 ("", "").
    """
    if not table:
        return []
    cols = list(table[0])
    code_col = next((c for c in CODE_COLS if c in cols), None)
    name_col = next((c for c in _NAME_COLS if c in cols), None)
    if code_col is None or name_col is None:
        raise DataSourceError(
            f"표에 종목코드(티커)·종목명 칸이 없음: {cols}", details={"columns": cols}
        )
    out: dict[str, dict[str, str]] = {}
    for r in table:
        code = (r.get(code_col) or "").strip()
        if not code:
            continue
        ticker = _symbol(code, index)
        if ticker is None:
            continue
        sector, industry = sector_of(ticker)
        out[ticker] = {
            "ticker": ticker,
            "name": (r.get(name_col) or "").strip(),
            "sector": YAHOO_TO_GICS.get(sector, sector),
            "industry": industry,
        }
    return [out[t] for t in sorted(out)]


class FileConstituentSource:
    """config/ 의 고정 CSV 로 구성종목을 주는 출처 (KOSPI200, NDX). 네트워크를 쓰지 않는다.

    CSV 칸: ticker,name,sector,industry. '#' 으로 시작하는 줄은 설명 (첫 줄에 기준일·원본을 적음).
    """

    def __init__(
        self,
        files: dict[IndexCode, Path | str] | None = None,
        *,
        name: str = "krx_file",
        kr_gics_csv: Path | str | None = None,
        use_kr_gics: bool = True,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.files = files
        self.source_name = name
        self.kr_gics_csv = kr_gics_csv
        self.use_kr_gics = use_kr_gics
        self._clock = clock

    def _path(self, code: IndexCode) -> Path:
        if self.files is not None:
            if code not in self.files:
                raise DataSourceError(f"{code.value} 파일이 정해지지 않음", details={})
            return Path(self.files[code])
        if code not in _FILES:
            raise DataSourceError(f"파일 출처는 KOSPI200·NDX 만 지원: {code.value}", details={})
        return config_file(_FILES[code])

    def fetch(self, index: IndexCode) -> list[IndexConstituent]:
        code = IndexCode(index)
        path = self._path(code)
        krx = config_file(KOSPI200_KRX_CSV)
        if not path.exists() and code == IndexCode.KOSPI200 and self.files is None and krx.exists():
            table, notes = _krx_table(krx), ["KRX 지수구성종목 코스피 200 원본, 분류 kr_gics.csv"]
            path = krx
            rows = constituent_rows_from_table(table, lambda _t: ("", ""), index=code)
        elif not path.exists():
            raise DataSourceError(
                f"{path.name} 없음: backend/scripts/make_constituents_csv.py --index {code.value} 로 만듦",
                details={"path": str(path)},
            )
        else:
            with path.open(encoding="utf-8-sig", newline="") as f:
                lines = f.read().splitlines()
            notes = [x.lstrip("# ").strip() for x in lines if x.startswith("#")]
            body = [x for x in lines if x.strip() and not x.startswith("#")]
            rows = [r for r in csv.DictReader(body) if r.get("ticker")]
        now = self._clock()
        src = f"file:config/{path.name}" + (f" ({notes[0]})" if notes else "")
        out = [
            IndexConstituent(
                index_code=code,
                ticker=_symbol(r["ticker"], code) or r["ticker"],
                name=(r.get("name") or "").strip(),
                sector=(r.get("sector") or "").strip(),
                industry=(r.get("industry") or "").strip(),
                snapshot_date=now.date(),
                source=src,
                fetched_at=now.astimezone(UTC),
            )
            for r in rows
        ]
        if code == IndexCode.KOSPI200 and self.use_kr_gics:
            out = apply_kr_gics(out, self.kr_gics_csv)
        return sorted(out, key=lambda r: r.ticker)


def _krx_table(path: Path) -> list[dict[str, str]]:
    """KRX 내려받기 CSV (EUC-KR 또는 UTF-8) → 행 dict."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise DataSourceError(f"{path.name} 인코딩을 읽지 못함", details={"path": str(path)})
    return [dict(r) for r in csv.DictReader(text.splitlines())]


def apply_kr_gics(
    rows: list[IndexConstituent], kr_gics_csv: Path | str | None = None
) -> list[IndexConstituent]:
    """KOSPI200 행의 sector·industry 를 backend/data/config/kr_gics.csv 의 GICS 섹터·세부산업 이름으로 바꿈.

    표에 없는 종목은 그대로 (이름이 GICS 가 아니면 수집기가 경고). 코드도 함께 붙인다.
    """
    from backend.pipeline.classification import kr_code, load_kr_gics
    from backend.pipeline.gics import load_taxonomy

    table = load_kr_gics(kr_gics_csv)
    if not table:
        return rows
    tax = load_taxonomy()
    out = []
    for r in rows:
        hit = table.get(kr_code(r.ticker))
        levels = tax.four_levels(hit.code) if hit else None
        if levels is None:
            out.append(r)
            continue
        out.append(
            r.model_copy(
                update={
                    "sector": levels["sector"].name_en,
                    "industry": levels["sub_industry"].name_en,
                    "gics_sub_industry_code": hit.code,
                }
            )
        )
    return out


class RoutedConstituentSource:
    """지수마다 다른 출처를 쓴다. 기본: KOSPI200 → 고정 파일, 나머지 → 위키백과."""

    def __init__(self, routes: dict[IndexCode, Any], default: Any) -> None:
        self.routes = routes
        self.default = default
        self._last = default

    @property
    def source_name(self) -> str:
        """직전에 쓴 출처 이름 (수집 기록 fetch_log 에 남김)."""
        return str(getattr(self._last, "source_name", type(self._last).__name__))

    def fetch(self, index: IndexCode) -> list[IndexConstituent]:
        self._last = self.routes.get(IndexCode(index), self.default)
        return self._last.fetch(index)


def default_constituent_source() -> RoutedConstituentSource:
    """수집 작업이 쓰는 구성종목 출처: S&P 500 → 위키백과, KOSPI200·NDX → config/ 고정 파일.

    위키백과 Nasdaq-100 문서에서 구성종목 표가 빠져(2026-10 확인) NDX 도 파일로 읽는다.
    """
    return RoutedConstituentSource(
        {
            IndexCode.KOSPI200: FileConstituentSource(),
            IndexCode.NDX: FileConstituentSource(name="ndx_file"),
        },
        WikipediaConstituentSource(),
    )

"""종목별 GICS 분류 정하기 (Module2 §5 종목 검색용 사전, 부록 F K17).

assets 의 gics_* 칸과 index_constituent.gics_sub_industry_code 를 채운다. 종목마다 아래 순서로 처음
찾은 것을 쓰고, 어디서 정했는지 assets.gics_source 에 남긴다.

미국 종목
1. WIKIPEDIA_SP500 : 최신 S&P 500 스냅샷의 GICS Sub-Industry 이름 (위키백과 표, GICS 그대로)
2. OVERRIDE        : backend/data/config/gics_overrides.csv (S&P 500 밖 Nasdaq-100 종목 등, 사람이 적음)
3. NDX_FILE        : 최신 Nasdaq-100 스냅샷 (backend/data/config/ndx.csv, 만들 때 S&P 500 표·보충표로 채운 이름)
4. YAHOO_FALLBACK  : Yahoo 섹터만 (세부산업 모름)

한국 종목
1. KR_MAP_REVIEWED / KR_MAP_DRAFT : backend/data/config/kr_gics.csv (종목별로 사람이 정한 표,
   reviewed=false 는 DRAFT)
2. OVERRIDE        : backend/data/config/gics_overrides.csv 의 .KS 종목
3. KR_MAP_KSIC_AUTO: DART 기업개황 induty_code(KSIC) → backend/data/config/ksic_to_gics.csv (앞자리 매핑, 자동)
4. CONSTITUENT_KOSPI200 : 구성종목 파일의 industry 이름이 GICS 세부산업이면 그것
5. YAHOO_FALLBACK  : Yahoo 프로필의 섹터만 (세부산업 모름)

둘 다 마지막에는 구성종목 행의 sector 이름만 쓴다 (CONSTITUENT_<지수>, 섹터만.
KOSPI200 파일의 sector 는 Yahoo 섹터를 GICS 섹터 이름으로 바꾼 값).

정하지 못한 종목은 결과(JobResult.failed)·fetch_log(PARTIAL)·coverage_report 에 이름이 나온다.
이미 저장된 분류는 이번에 못 정했다고 지우지 않는다. ETF·지수는 대상이 아니다.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backend.pipeline.gics import GicsTaxonomy, load_taxonomy
from backend.schemas.errors import DataSourceError
from backend.schemas.market import IndexCode, IndexConstituent

KR_GICS_CSV = "kr_gics.csv"
KSIC_TO_GICS_CSV = "ksic_to_gics.csv"
SOURCE_NAME = "GICS"
"""fetch_log·data_sources 의 출처 이름."""


class Src:
    """assets.gics_source 값."""

    WIKIPEDIA_SP500 = "WIKIPEDIA_SP500"
    OVERRIDE = "OVERRIDE"
    NDX_FILE = "NDX_FILE"
    KR_MAP_REVIEWED = "KR_MAP_REVIEWED"
    KR_MAP_DRAFT = "KR_MAP_DRAFT"
    KR_MAP_KSIC_AUTO = "KR_MAP_KSIC_AUTO"
    YAHOO_FALLBACK = "YAHOO_FALLBACK"

    @staticmethod
    def constituent(index: IndexCode | str) -> str:
        return f"CONSTITUENT_{IndexCode(index).value}"


def _config(name: str) -> Path:
    from backend.collectors.constituents.source import config_file

    return config_file(name)


def _rows(path: Path) -> list[dict[str, str]]:
    """'#' 으로 시작하는 줄(설명)을 뺀 CSV 행."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        body = [x for x in f.read().splitlines() if x.strip() and not x.startswith("#")]
    return list(csv.DictReader(body))


# ---------------------------------------------------------------- 한국: 종목별 표
@dataclass(frozen=True)
class KrGics:
    """backend/data/config/kr_gics.csv 한 줄."""

    ticker: str  # 6자리 종목코드 (영문 포함 코드 0126Z0 도 있음)
    name: str
    code: str  # GICS 세부산업 8자리
    reviewed: bool
    basis: str


def kr_code(symbol: str) -> str:
    """005930.KS · 005930 → 005930."""
    t = str(symbol).strip().upper()
    for suffix in (".KS", ".KQ"):
        t = t.removesuffix(suffix)
    return t.zfill(6) if t.isdigit() else t


def load_kr_gics(path: Path | str | None = None) -> dict[str, KrGics]:
    """종목코드 → KrGics. 파일이 없으면 빈 dict."""
    p = Path(path) if path else _config(KR_GICS_CSV)
    if not p.exists():
        return {}
    out = {}
    for r in _rows(p):
        if not (r.get("ticker") or "").strip():
            continue
        t = kr_code(r["ticker"])
        out[t] = KrGics(
            ticker=t,
            name=(r.get("name") or "").strip(),
            code=(r.get("gics_sub_industry_code") or "").strip(),
            reviewed=(r.get("reviewed") or "").strip().lower() in ("true", "1", "y", "yes"),
            basis=(r.get("basis") or "").strip(),
        )
    return out


# ---------------------------------------------------------------- 한국: KSIC 앞자리 매핑
def load_ksic_map(path: Path | str | None = None) -> list[tuple[str, str | None, str]]:
    """[(KSIC 앞자리, GICS 세부산업 코드 또는 None, 메모)] 긴 앞자리부터."""
    p = Path(path) if path else _config(KSIC_TO_GICS_CSV)
    if not p.exists():
        return []
    out = [
        (
            (r.get("ksic_prefix") or "").strip(),
            (r.get("gics_sub_industry_code") or "").strip() or None,
            (r.get("note") or "").strip(),
        )
        for r in _rows(p)
        if (r.get("ksic_prefix") or "").strip()
    ]
    return sorted(out, key=lambda x: (-len(x[0]), x[0]))


def ksic_to_gics(
    ksic: str | None, table: Sequence[tuple[str, str | None, str]]
) -> tuple[str | None, str | None]:
    """KSIC 코드 → (GICS 세부산업 코드, 맞은 앞자리). 가장 긴 앞자리가 이긴다.

    맞은 앞자리의 코드가 비어 있으면(예: 64992 지주회사) (None, 앞자리): 자동으로 정하지 않음.
    """
    code = "".join(ch for ch in str(ksic or "") if ch.isdigit())
    if not code:
        return None, None
    for prefix, gics, _note in table:
        if code.startswith(prefix):
            return gics, prefix
    return None, None


# ---------------------------------------------------------------- 종목 하나 정하기
@dataclass(frozen=True)
class Assignment:
    """한 종목의 결과. sub_code 가 없으면 sector_code 만 (YAHOO_FALLBACK)."""

    asset_id: str
    sub_code: str | None
    sector_code: str | None
    source: str
    detail: str = ""

    def columns(self, tax: GicsTaxonomy) -> dict[str, Any]:
        return {
            **tax.asset_columns(self.sub_code, sector_code=self.sector_code),
            "gics_source": self.source,
        }


def resolve_row(tax: GicsTaxonomy, sector: str, industry: str) -> tuple[str | None, str]:
    """구성종목 행의 (sector, industry 이름) → (세부산업 코드, 못 찾은 이유)."""
    node = tax.resolve(industry, 4)
    if node is None:
        return None, f"세부산업 이름을 분류표에서 못 찾음: {industry!r}"
    sector_node = tax.chain(node.code)[0]
    if sector.strip() and tax.sector_name_to_code(sector) != sector_node.code:
        return None, (
            f"섹터가 맞지 않음: {sector!r} 인데 {industry!r} 는 {sector_node.name_en} 섹터"
        )
    return node.code, ""


def assign_gics(
    profiles: Iterable[Mapping[str, Any]],
    constituents: Mapping[IndexCode, Sequence[IndexConstituent]],
    *,
    tax: GicsTaxonomy,
    kr_map: Mapping[str, KrGics],
    ksic_map: Sequence[tuple[str, str | None, str]],
    overrides: Mapping[str, tuple[str, str]],
    yahoo_sectors: Mapping[str, str] | None = None,
) -> tuple[dict[str, Assignment], dict[str, str]]:
    """종목들의 GICS. ({asset_id: Assignment}, {asset_id: 못 정한 이유}).

    profiles: SqlRepository.asset_profiles() 행 (asset_id, yfinance_symbol, market, asset_type,
    ksic_code ...). yahoo_sectors: yfinance 표기 → Yahoo 섹터 또는 GICS 섹터 이름.
    """
    by_index: dict[IndexCode, dict[str, IndexConstituent]] = {
        IndexCode(k): {r.ticker: r for r in rows} for k, rows in constituents.items()
    }
    yahoo = dict(yahoo_sectors or {})
    out: dict[str, Assignment] = {}
    problems: dict[str, str] = {}

    def from_row(index: IndexCode, sym: str) -> tuple[str | None, str]:
        r = by_index.get(index, {}).get(sym)
        if r is None:
            return None, ""
        if r.gics_sub_industry_code and tax.get(r.gics_sub_industry_code):
            return r.gics_sub_industry_code, ""
        return resolve_row(tax, r.sector, r.industry)

    def from_override(sym: str) -> tuple[str | None, str]:
        if sym not in overrides:
            return None, ""
        sector, industry = overrides[sym]
        code, why = resolve_row(tax, sector, industry)
        return code, (f"gics_overrides.csv: {why}" if why else "")

    for p in profiles:
        if p.get("asset_type", "STOCK") != "STOCK":
            continue
        aid, sym = p["asset_id"], p["yfinance_symbol"]
        notes: list[str] = []
        got: Assignment | None = None
        if p["market"] == "KR":
            row = kr_map.get(kr_code(sym))
            if row and tax.get(row.code) and tax.get(row.code).level == 4:
                src = Src.KR_MAP_REVIEWED if row.reviewed else Src.KR_MAP_DRAFT
                got = Assignment(aid, row.code, None, src, row.basis)
            elif row:
                notes.append(f"kr_gics.csv 코드가 분류표에 없음: {row.code!r}")
            if got is None:
                code, why = from_override(sym)
                if code:
                    got = Assignment(aid, code, None, Src.OVERRIDE)
                elif why:
                    notes.append(why)
            if got is None and p.get("ksic_code"):
                code, prefix = ksic_to_gics(p["ksic_code"], ksic_map)
                if code and tax.get(code):
                    got = Assignment(
                        aid, code, None, Src.KR_MAP_KSIC_AUTO, f"KSIC {p['ksic_code']}"
                    )
                else:
                    notes.append(f"KSIC {p['ksic_code']} 자동 매핑 없음 (앞자리 {prefix})")
            if got is None:
                code, why = from_row(IndexCode.KOSPI200, sym)
                if code:
                    got = Assignment(aid, code, None, Src.constituent(IndexCode.KOSPI200))
                elif why:
                    notes.append(f"KOSPI200 스냅샷: {why}")
        else:
            code, why = from_row(IndexCode.SP500, sym)
            if code:
                r = by_index[IndexCode.SP500][sym]
                src = (
                    Src.WIKIPEDIA_SP500
                    if r.source.lower().startswith("wikipedia")
                    else Src.constituent(IndexCode.SP500)
                )
                got = Assignment(aid, code, None, src)
            elif why:
                notes.append(f"SP500 스냅샷: {why}")
            if got is None:
                code, why = from_override(sym)
                if code:
                    got = Assignment(aid, code, None, Src.OVERRIDE)
                elif why:
                    notes.append(why)
            if got is None:
                code, why = from_row(IndexCode.NDX, sym)
                if code:
                    r = by_index[IndexCode.NDX][sym]
                    src = (
                        Src.NDX_FILE
                        if r.source.lower().startswith("file")
                        else Src.constituent(IndexCode.NDX)
                    )
                    got = Assignment(aid, code, None, src)
                elif why:
                    notes.append(f"NDX 스냅샷: {why}")
        if got is None and yahoo.get(sym):
            from backend.collectors.constituents.source import YAHOO_TO_GICS

            name = YAHOO_TO_GICS.get(yahoo[sym], yahoo[sym])
            sector = tax.sector_name_to_code(name)
            if sector:
                got = Assignment(aid, None, sector, Src.YAHOO_FALLBACK, f"Yahoo 섹터 {yahoo[sym]}")
            else:
                notes.append(f"Yahoo 섹터를 GICS 섹터로 못 바꿈: {yahoo[sym]!r}")
        if got is None:  # 마지막: 구성종목 행의 섹터 이름만 (세부산업 모름)
            for index in (IndexCode.SP500, IndexCode.NDX, IndexCode.KOSPI200):
                r = by_index.get(index, {}).get(sym)
                sector = tax.sector_name_to_code(r.sector) if r and r.sector.strip() else None
                if sector:
                    got = Assignment(aid, None, sector, Src.constituent(index), "섹터만")
                    break
        if got is None:
            problems[aid] = "; ".join(notes) or "어느 출처에도 분류가 없음"
            continue
        out[aid] = got
        if got.sub_code is None:
            problems[aid] = "세부산업 모름 (섹터만): " + ("; ".join(notes) or got.detail)
    return out, problems


# ---------------------------------------------------------------- 수집 단계
def gics_step(
    repo: Any,
    settings: Any,
    *,
    today: date,
    ksic_fetch: Callable[[str], str | None] | None = None,
    profile_fetch: Callable[[str], Mapping[str, Any]] | None = None,
    ksic_limit: int = 10**6,
    profile_limit: int = 10**6,
    deadline: Any = None,
    progress: Callable[[str], None] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Any:
    """GICS 채우기 한 단계 (jobs meta 끝, backend/scripts/backfill.py --what gics).

    1. gics_taxonomy 를 backend/data/reference/gics_taxonomy.json 과 같게 (바뀐 행만)
    2. (ksic_fetch 가 있으면) KSIC 코드가 없는 한국 종목의 DART induty_code 를 받아 assets.ksic_code
    3. (profile_fetch 가 있으면) 사업 설명이 없는 종목의 yfinance 프로필 → business_summary,
       Yahoo 섹터 (분류를 못 정한 종목의 대체)
    4. 종목마다 GICS 를 정해 assets 에 (값이 바뀐 행만, gics_updated_at)
    5. index_constituent 에서 gics_sub_industry_code 가 빈 행을 채움 (이름 → 코드, 못 찾으면 그
       종목의 assets 분류. 한국 예전 스냅샷의 Yahoo 산업 이름은 GICS 이름으로 바꿈)
    못 정한 종목은 failed 와 fetch_log(GICS, PARTIAL) 에 남긴다.
    """
    from backend.collectors.common import Deadline, JobResult, ensure_assets, universe
    from backend.collectors.constituents.source import load_gics_overrides

    res = JobResult("gics")
    deadline = deadline or Deadline(10**9)
    say = progress or (lambda _m: None)
    tax = load_taxonomy()
    res.counts["taxonomy_changed"] = repo.sync_gics_taxonomy(tax.rows())

    names = universe(repo, settings)
    ensure_assets(repo, names)
    etfs = set(settings.etfs)
    profiles = {
        p["yfinance_symbol"]: p
        for p in repo.asset_profiles(list(names))
        if p["asset_type"] == "STOCK" and p["yfinance_symbol"] not in etfs
    }
    kr_map = load_kr_gics()

    # 2. KSIC (한국): 아직 없는 종목만, 한 종목 한 번 (DART 요청 하나)
    if ksic_fetch is not None:
        todo = [s for s, p in profiles.items() if p["market"] == "KR" and not p.get("ksic_code")]
        res.counts["ksic_pending"] = len(todo)
        updates = []
        for s in todo[:ksic_limit]:
            if deadline.over():
                res.done = False
                break
            try:
                code = ksic_fetch(kr_code(s))
            except DataSourceError as exc:  # 한도·키 오류: 다음 실행에
                res.notes.append(f"KSIC 멈춤: {exc}")
                res.done = False
                break
            except Exception as exc:  # noqa: BLE001 - 한 종목 실패는 기록하고 계속
                res.failed[f"ksic:{s}"] = f"{type(exc).__name__}: {exc}"
                continue
            if code:
                updates.append({"asset_id": profiles[s]["asset_id"], "ksic_code": code})
                profiles[s]["ksic_code"] = code
        res.counts["ksic_saved"] = repo.update_asset_profiles(updates)
        if len(todo) > ksic_limit:
            res.done = False
        say(f"[gics] KSIC {len(updates)}/{len(todo)}종목")

    # 3. 사업 설명·Yahoo 섹터
    yahoo: dict[str, str] = {}
    if profile_fetch is not None:
        todo = [s for s, p in profiles.items() if not p.get("business_summary")]
        res.counts["profile_pending"] = len(todo)
        updates = []
        for i, s in enumerate(todo[:profile_limit], start=1):
            if deadline.over():
                res.done = False
                break
            try:
                info = dict(profile_fetch(s) or {})
            except Exception as exc:  # noqa: BLE001 - 프로필이 없어도 분류·사전은 만들 수 있음
                res.failed[f"profile:{s}"] = f"{type(exc).__name__}: {exc}"
                continue
            if info.get("sector"):
                yahoo[s] = str(info["sector"])
            text = str(info.get("summary") or "").strip()
            if text:
                updates.append(
                    {
                        "asset_id": profiles[s]["asset_id"],
                        "business_summary": text,
                        "business_summary_source": str(info.get("source") or "YFINANCE"),
                    }
                )
            if i % 50 == 0:
                say(f"[gics] 사업 설명 {i}/{len(todo)}종목")
        res.counts["profile_saved"] = repo.update_asset_profiles(updates)
        if len(todo) > profile_limit:
            res.done = False

    # 4. 종목별 GICS
    cons = {i: repo.latest_constituents(i) for i in IndexCode}
    found, problems = assign_gics(
        profiles.values(),
        cons,
        tax=tax,
        kr_map=kr_map,
        ksic_map=load_ksic_map(),
        overrides=load_gics_overrides(),
        yahoo_sectors=yahoo,
    )
    rows = [{"asset_id": a.asset_id, **a.columns(tax)} for a in found.values()]
    res.counts["assets_changed"] = repo.update_asset_profiles(rows)
    res.counts["assets_with_sub_industry"] = sum(a.sub_code is not None for a in found.values())
    res.counts["assets_sector_only"] = sum(a.sub_code is None for a in found.values())
    by_source: dict[str, int] = {}
    for a in found.values():
        by_source[a.source] = by_source.get(a.source, 0) + 1
    res.notes.append(
        "출처별 종목 수: " + ", ".join(f"{k} {v}" for k, v in sorted(by_source.items()))
    )
    stored = {p["asset_id"]: p for p in profiles.values()}
    for aid, why in sorted(problems.items()):
        if aid not in found and stored[aid].get("gics_sub_industry_code"):
            why += " (저장된 분류는 그대로 둠)"
        res.failed[stored[aid]["yfinance_symbol"]] = why

    # 5. 구성종목 행의 코드
    current = {a.asset_id: a.sub_code for a in found.values() if a.sub_code}
    current.update(
        {
            aid: p["gics_sub_industry_code"]
            for aid, p in ((p["asset_id"], p) for p in repo.asset_profiles())
            if aid not in current and p.get("gics_sub_industry_code")
        }
    )
    fixes = []
    left = 0
    for r in repo.constituent_gics_gaps():
        code, _why = resolve_row(tax, r["sector"], r["industry"])
        fix: dict[str, Any] = {k: r[k] for k in ("index_code", "snapshot_date", "ticker")}
        if code is None:
            code = current.get(r["asset_id"])
            levels = tax.four_levels(code)
            if levels is None:
                left += 1
                continue
            fix["sector"] = levels["sector"].name_en
            fix["industry"] = levels["sub_industry"].name_en
        fix["gics_sub_industry_code"] = code
        fixes.append(fix)
    res.counts["constituent_rows_filled"] = repo.update_constituent_gics(fixes)
    res.counts["constituent_rows_without_gics"] = left

    status = "SUCCESS" if not res.failed else "PARTIAL"
    error = None
    if res.failed:
        error = f"분류 못 정함·실패 {len(res.failed)}건: " + "; ".join(
            f"{k}: {v}" for k, v in list(res.failed.items())[:20]
        )
    repo.log_fetch(SOURCE_NAME, "gics:assets", None, today, status, clock(), error)
    say(
        f"[gics] 분류 {len(found)}종목 (세부산업 {res.counts['assets_with_sub_industry']}), "
        f"바뀜 {res.counts['assets_changed']}, 못 정함 {len(problems)}, "
        f"구성종목 행 채움 {res.counts['constituent_rows_filled']}"
    )
    return res


def default_fetchers(
    notes: list[str], *, ksic: bool = True, profiles: bool = True
) -> tuple[Callable[[str], str | None] | None, Callable[[str], Mapping[str, Any]] | None]:
    """실제 수집용 (KSIC, 프로필) 함수. 키·패키지가 없으면 None 과 notes 에 이유."""
    from backend.adapters.crawlers import config

    ksic_fetch = profile_fetch = None
    if ksic:
        if config.get("DART_API_KEY"):
            from backend.adapters.crawlers import dart_client

            ksic_fetch = dart_client.industry_code
        else:
            notes.append("KSIC(DART 기업개황) 건너뜀: .env 에 DART_API_KEY 없음")
    if profiles:
        try:
            import yfinance  # noqa: F401

            from backend.adapters.crawlers import yfinance_client

            profile_fetch = yfinance_client.profile
        except ImportError:
            notes.append("사업 설명(yfinance) 건너뜀: yfinance 미설치 (pip install -e .[real])")
    return ksic_fetch, profile_fetch

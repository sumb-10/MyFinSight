"""종목 검색용 사전 (Module2 §5, module_prototype2 M2-03 "유니버스 디스크립터").

종목마다 GICS 4단계 코드·이름, 키워드, 한 줄 소개와 그 출처를 담은 사전을 구성종목 스냅샷 날짜별로
만들고 (build_descriptors), 검색 함수를 준다 (Descriptor). 만들기는 backend/scripts/build_descriptor.py.

- 재료는 DB 만 (assets, index_constituent, gics_taxonomy: repository.readers.descriptor_inputs).
  외부 사이트·LLM 을 부르지 않는다 (K3). 같은 DB 면 같은 결과 (generated_at 만 다름).
- 버전: 유니버스(SP500·NDX·KOSPI200·ALL)의 스냅샷 날짜마다 하나. 날짜 D 버전은 지수마다 D 이전(포함)
  가장 최근 스냅샷을 쓰고, D 이전 스냅샷이 없는 지수는 가장 오래된 스냅샷을 쓰되
  "당시 구성종목 미확보" 를 남긴다 (K4). 과거 기준일에 쓸 버전은 select_version.
- GICS: 그 스냅샷 행의 gics_sub_industry_code (당시 분류). 없으면 assets 의 현재 분류를 쓰고
  gics_asof = "current" 로 표시한다 (분류 시점이 보장되지 않는 한계).
- 소개 문장 우선순위: (LLM 한국어 요약은 이 수집기에서 만들지 않음) → DB 사업 설명
  (assets.business_summary) 첫 문장 → "<회사명>은(는) <세부산업 한국어> 기업이다." 기본 문장.
  intro_source 에 무엇으로 만들었는지 남긴다.
- 키워드 (결정적, LLM 없음): GICS 4단계 영문·한국어 이름과 그 단어, 회사명 단어, 티커.
- 검색: 산업 접두 코드(filter_by_gics), 단어 경계 키워드(search_keywords), 섹터 이름 → 코드
  (sector_name_to_code), 상위 분류(parents_of).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backend.pipeline.gics import LEVELS, GicsTaxonomy
from backend.schemas.market import IndexCode

SCHEMA_VERSION = 1
NOT_AVAILABLE = "당시 구성종목 미확보"
UNIVERSES: Mapping[str, tuple[IndexCode, ...]] = {
    "SP500": (IndexCode.SP500,),
    "NDX": (IndexCode.NDX,),
    "KOSPI200": (IndexCode.KOSPI200,),
    "ALL": (IndexCode.SP500, IndexCode.NDX, IndexCode.KOSPI200),
}
_FILE = re.compile(r"^(?P<u>[a-z0-9]+)_descriptor_(?P<d>\d{4}-\d{2}-\d{2})\.json$")
_STOP = frozenset({"and", "of", "the", "other", "&"})
_CORP = frozenset(
    {
        "inc",
        "inc.",
        "corp",
        "corp.",
        "corporation",
        "co",
        "co.",
        "company",
        "ltd",
        "ltd.",
        "limited",
        "plc",
        "holdings",
        "holding",
        "group",
        "the",
        "n.v.",
        "nv",
        "s.a.",
        "sa",
        "ag",
        "se",
        "class",
        "a",
        "b",
        "c",
        "&",
    }
)
_ABBREV = frozenset(
    {
        "inc",
        "corp",
        "co",
        "ltd",
        "no",
        "st",
        "mr",
        "ms",
        "dr",
        "jr",
        "sr",
        "vs",
        "etc",
        "e.g",
        "i.e",
        "u.s",
        "u.k",
        "s.a",
        "n.v",
        "l.p",
        "plc",
        "approx",
    }
)
INTRO_MAX = 400


# ---------------------------------------------------------------- 문장·키워드
def first_sentence(text: str | None) -> str:
    """사업 설명의 첫 문장. 약어(Inc. Co. U.S. 등) 뒤의 점은 문장 끝으로 보지 않는다."""
    t = " ".join(str(text or "").split())
    if not t:
        return ""
    for m in re.finditer(r"[.!?。](?=\s|$)", t):
        before = t[: m.start()].split(" ")[-1].lower().rstrip(".")
        if before in _ABBREV or (len(before) == 1 and before.isalpha()):
            continue
        t = t[: m.end()]
        break
    return t if len(t) <= INTRO_MAX else t[: INTRO_MAX - 1].rsplit(" ", 1)[0] + "…"


def josa_eun(name: str) -> str:
    """이름 뒤 조사 은/는 (한글 받침 기준, 한글로 안 끝나면 "은(는)")."""
    last = name.strip()[-1:] if name.strip() else ""
    if "가" <= last <= "힣":
        return "은" if (ord(last) - 0xAC00) % 28 else "는"
    return "은(는)"


def default_intro(
    name: str, levels: Mapping[str, Mapping[str, str]] | None, market: str
) -> tuple[str, str]:
    """기본 소개 문장과 출처 (DEFAULT_GICS / DEFAULT_SECTOR / DEFAULT_NAME)."""
    who = f"{name}{josa_eun(name)}"
    if levels and levels.get("sub_industry"):
        return f"{who} {levels['sub_industry']['name_ko']} 기업이다.", "DEFAULT_GICS"
    if levels and levels.get("sector"):
        return f"{who} {levels['sector']['name_ko']} 섹터 기업이다.", "DEFAULT_SECTOR"
    where = {"US": "미국", "KR": "한국"}.get(market, market)
    return f"{who} {where} 상장 기업이다.", "DEFAULT_NAME"


def _ascii_words(text: str) -> list[str]:
    return [w for w in re.split(r"[^0-9a-z]+", text.lower()) if w]


def keywords_for(
    name: str, tickers: Iterable[str], levels: Mapping[str, Mapping[str, str]] | None
) -> list[str]:
    """결정적 키워드: GICS 이름(영문 전체·단어, 한국어 전체·조각), 회사명 단어, 티커."""
    out: list[str] = []

    def add(x: str) -> None:
        x = x.strip()
        if x and x not in out:
            out.append(x)

    for lvl in ("sub_industry", "industry", "industry_group", "sector"):
        node = (levels or {}).get(lvl)
        if not node:
            continue
        add(node["name_en"].lower())
        add(node["name_ko"])
        for w in _ascii_words(node["name_en"]):
            if w not in _STOP and len(w) > 1:
                add(w)
        for part in re.split(r"[·,]", node["name_ko"]):
            add(part)
    nm = str(name or "").strip()
    if re.search(r"[가-힣]", nm):
        add(nm)
    for w in re.split(r"[\s,]+", nm.lower()):
        w = w.strip("()").rstrip(",")
        if w and w not in _CORP and len(w) > 1:
            add(w)
    for t in tickers:
        add(str(t).lower())
    return out


# ---------------------------------------------------------------- 버전 만들기
def _snapshot_for(dates: Sequence[date], d: date) -> tuple[date | None, str | None]:
    """d 에 쓸 스냅샷 날짜: d 이전(포함) 가장 최근, 없으면 가장 오래된 것 + 미확보 표시."""
    if not dates:
        return None, None
    before = [x for x in dates if x <= d]
    if before:
        return max(before), None
    return min(dates), NOT_AVAILABLE


def _levels_dict(tax: GicsTaxonomy, code: str | None) -> dict[str, dict[str, str]] | None:
    levels = tax.four_levels(code)
    if levels is None:
        return None
    return {
        k: {"code": n.code, "name_en": n.name_en, "name_ko": n.name_ko} for k, n in levels.items()
    }


def build_version(inputs: Mapping[str, Any], universe: str, d: date, tax: GicsTaxonomy) -> dict:
    """유니버스의 날짜 d 버전 (사전 문서 하나)."""
    indices = UNIVERSES[universe.upper()]
    used: dict[str, dict[str, Any]] = {}
    stocks: dict[str, dict[str, Any]] = {}
    limitations: list[str] = []
    for index in indices:
        code = index.value
        snap, flag = _snapshot_for(inputs["snapshots"].get(code, []), d)
        used[code] = {"snapshot_date": snap.isoformat() if snap else None, "note": flag}
        if snap is None:
            limitations.append(f"{code}: 저장된 구성종목 스냅샷 없음")
            continue
        if flag:
            limitations.append(
                f"{code}: {d} 이전 스냅샷이 없어 가장 오래된 {snap} 스냅샷을 씀 "
                f"({flag}, 생존 편향 가능)"
            )
        for m in inputs["members"][(code, snap)]:
            aid = m["asset_id"]
            e = stocks.setdefault(aid, {"members": [], "rows": []})
            e["members"].append((code, flag))
            e["rows"].append(m)
    out = []
    missing: list[str] = []
    for aid in sorted(stocks):
        e = stocks[aid]
        a = inputs["assets"].get(aid, {})
        row = e["rows"][0]
        snap_code = next(
            (r["gics_sub_industry_code"] for r in e["rows"] if r.get("gics_sub_industry_code")),
            None,
        )
        levels = _levels_dict(tax, snap_code)
        asof = "snapshot"
        if levels is None:
            levels = _levels_dict(tax, a.get("gics_sub_industry_code"))
            asof = "current" if levels else None
        sector_only = None
        if levels is None and a.get("gics_sector_code") and tax.get(a["gics_sector_code"]):
            n = tax.get(a["gics_sector_code"])
            sector_only = {"sector": {"code": n.code, "name_en": n.name_en, "name_ko": n.name_ko}}
            asof = "current"
        name = a.get("name") or row["name"] or row["ticker"]
        market = a.get("market") or ("KR" if aid.startswith("KR-") else "US")
        summary = first_sentence(a.get("business_summary"))
        if summary:
            intro, intro_src = (
                summary,
                f"BUSINESS_SUMMARY:{a.get('business_summary_source') or 'DB'}",
            )
        else:
            intro, intro_src = default_intro(name, levels or sector_only, market)
        gics = {lvl: (levels or sector_only or {}).get(lvl) for lvl in LEVELS.values()}
        if not levels:
            missing.append(row["ticker"])
        tickers = [row["ticker"]]
        if a.get("yfinance_symbol") and a["yfinance_symbol"] != row["ticker"]:
            tickers.append(a["yfinance_symbol"])
        flags = [NOT_AVAILABLE] if all(f for _c, f in e["members"]) else []
        out.append(
            {
                "asset_id": aid,
                "ticker": row["ticker"],
                "yfinance_symbol": a.get("yfinance_symbol") or row["ticker"],
                "name": name,
                "market": market,
                "currency": a.get("currency") or ("KRW" if market == "KR" else "USD"),
                "indices": sorted(c for c, _f in e["members"]),
                "gics": gics,
                "gics_source": a.get("gics_source"),
                "gics_asof": asof,
                "keywords": keywords_for(name, tickers, levels or sector_only),
                "intro": intro,
                "intro_source": intro_src,
                "flags": flags,
            }
        )
    if missing:
        limitations.append(f"GICS 세부산업이 없는 종목 {len(missing)}개: {', '.join(missing[:30])}")
    if any(s["gics_asof"] == "current" for s in out):
        n = sum(s["gics_asof"] == "current" for s in out)
        limitations.append(
            f"{n}개 종목은 스냅샷 당시 분류가 없어 현재 분류를 씀 (분류 시점 미보장)"
        )
    counts: dict[str, int] = {}
    for s in out:
        for lvl in LEVELS.values():
            node = s["gics"].get(lvl)
            if node:
                counts[node["code"]] = counts.get(node["code"], 0) + 1
    tree = [{**r, "count": counts.get(r["code"], 0)} for r in tax.rows()]
    return {
        "schema_version": SCHEMA_VERSION,
        "universe": universe.upper(),
        "snapshot_date": d.isoformat(),
        "taxonomy_version": tax.version,
        "indices": used,
        "limitations": limitations,
        "count": len(out),
        "missing_gics": missing,
        "stocks": out,
        "gics_tree": tree,
    }


def version_dates(inputs: Mapping[str, Any], universe: str) -> list[date]:
    """유니버스의 버전 날짜 = 그 지수들의 스냅샷 날짜 합집합."""
    out: set[date] = set()
    for index in UNIVERSES[universe.upper()]:
        out.update(inputs["snapshots"].get(index.value, []))
    return sorted(out)


def build_descriptors(
    inputs: Mapping[str, Any], universe: str, *, only_latest: bool = False
) -> list[dict]:
    """유니버스의 버전들 (날짜 순). 분류표는 DB gics_taxonomy 행으로 만든다."""
    tax = GicsTaxonomy(inputs["taxonomy"], version=_taxonomy_version(inputs["taxonomy"]))
    dates = version_dates(inputs, universe)
    if only_latest:
        dates = dates[-1:]
    return [build_version(inputs, universe, d, tax) for d in dates]


def _taxonomy_version(rows: Sequence[Mapping[str, Any]]) -> str:
    """DB 분류표 행의 지문 (같은 분류표면 같은 값)."""
    blob = json.dumps([dict(r) for r in rows], ensure_ascii=False, sort_keys=True, default=str)
    return "db-" + hashlib.sha256(blob.encode()).hexdigest()[:12]


# ---------------------------------------------------------------- 파일
def file_name(universe: str, d: date | str) -> str:
    return f"{universe.lower()}_descriptor_{d if isinstance(d, str) else d.isoformat()}.json"


def write_descriptors(
    docs: Sequence[dict], out_dir: Path | str, universe: str
) -> list[tuple[Path, bool]]:
    """버전 파일 backend/data/processed/<universe>_descriptor_<날짜>.json 을 쓰고 (내용이 같으면 그대로),
    가장 최근 버전을 <universe>_descriptor.json 으로,
    목록을 <universe>_descriptor_versions.json 으로.

    [(경로, 바뀜 여부)].
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    result: list[tuple[Path, bool]] = []
    index = []
    for doc in docs:
        path = out / file_name(universe, doc["snapshot_date"])
        body = {k: v for k, v in doc.items() if k != "generated_at"}
        changed = True
        if path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                changed = {k: v for k, v in old.items() if k != "generated_at"} != body
                gen = old.get("generated_at", now)
            except (ValueError, OSError):
                gen = now
        else:
            gen = now
        full = {"generated_at": now if changed else gen, **body}
        if changed:
            _atomic_write(path, full)
        result.append((path, changed))
        index.append(
            {
                "snapshot_date": doc["snapshot_date"],
                "file": path.name,
                "count": doc["count"],
                "generated_at": full["generated_at"],
                "limitations": doc["limitations"],
            }
        )
    if docs:
        latest = out / f"{universe.lower()}_descriptor.json"
        _atomic_write(latest, json.loads((out / index[-1]["file"]).read_text(encoding="utf-8")))
        _atomic_write(
            out / f"{universe.lower()}_descriptor_versions.json",
            {"universe": universe.upper(), "versions": index},
        )
    return result


def _atomic_write(path: Path, doc: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def select_version(out_dir: Path | str, universe: str, as_of: date) -> tuple[Path, list[str]]:
    """기준일 as_of 에 쓸 버전: as_of 이전(포함) 가장 최근 날짜 파일. 없으면 가장 오래된 것 +
    "당시 구성종목 미확보" 경고. 버전이 하나도 없으면 FileNotFoundError.

    한 실행은 시작할 때 이것으로 버전을 고정하고 끝까지 바꾸지 않는다 (Module2 §5).
    """
    found: list[tuple[date, Path]] = []
    for p in Path(out_dir).glob(f"{universe.lower()}_descriptor_*.json"):
        m = _FILE.match(p.name)
        if m and m["u"] == universe.lower():
            found.append((date.fromisoformat(m["d"]), p))
    if not found:
        raise FileNotFoundError(
            f"{universe} 사전 버전이 없음: {out_dir} (backend/scripts/build_descriptor.py)"
        )
    found.sort()
    before = [x for x in found if x[0] <= as_of]
    if before:
        return before[-1][1], []
    d, p = found[0]
    return p, [f"{as_of} 이전 사전 버전이 없어 {d} 버전을 씀 ({NOT_AVAILABLE}, 생존 편향 가능)"]


# ---------------------------------------------------------------- 검색
def _word_pattern(word: str) -> re.Pattern[str]:
    """단어 경계: 앞은 영문·숫자·한글이 아니어야 하고, 영문·숫자로 끝나는 말은 뒤도 그래야 한다.
    한글로 끝나는 말은 뒤에 조사가 붙어도 맞음 ("반도체" → "반도체를")."""
    w = word.strip().lower()
    tail = r"(?![0-9a-z])" if re.search(r"[0-9a-z]$", w) else ""
    return re.compile(r"(?<![0-9a-z가-힣])" + re.escape(w) + tail)


@dataclass
class Match:
    entry: dict[str, Any]
    matched: list[str]


class Descriptor:
    """사전 한 버전과 검색 함수. Descriptor.load(path) 또는 Descriptor(doc)."""

    def __init__(self, doc: Mapping[str, Any]) -> None:
        self.doc = dict(doc)
        self.stocks: list[dict[str, Any]] = list(doc.get("stocks", []))
        self.tax = GicsTaxonomy(
            [
                {k: r[k] for k in ("code", "level", "name_en", "name_ko", "parent_code")}
                for r in doc.get("gics_tree", [])
            ],
            version=str(doc.get("taxonomy_version", "")),
        )

    @classmethod
    def load(cls, path: Path | str) -> Descriptor:
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @staticmethod
    def _code(entry: Mapping[str, Any]) -> str:
        g = entry.get("gics") or {}
        for lvl in ("sub_industry", "industry", "industry_group", "sector"):
            if g.get(lvl):
                return g[lvl]["code"]
        return ""

    def filter_by_gics(self, codes: Iterable[str]) -> list[dict[str, Any]]:
        """GICS 코드(2/4/6/8자리) 중 하나로 시작하는 종목 (접두 일치)."""
        prefixes = [str(c).strip() for c in codes if str(c).strip()]
        return [e for e in self.stocks if any(self._code(e).startswith(p) for p in prefixes)]

    def search_keywords(self, words: Iterable[str], *, min_distinct: int = 1) -> list[Match]:
        """이름·키워드·소개에서 단어 경계로 맞는 종목. 서로 다른 단어가 min_distinct 개 이상."""
        pats = [(w, _word_pattern(w)) for w in dict.fromkeys(x for x in words if x.strip())]
        out = []
        for e in self.stocks:
            text = " | ".join(
                [str(e.get("name", "")), *e.get("keywords", []), str(e.get("intro", ""))]
            ).lower()
            hit = [w for w, p in pats if p.search(text)]
            if len(hit) >= min_distinct and hit:
                out.append(Match(e, hit))
        return out

    def sector_name_to_code(self, name: str) -> str | None:
        return self.tax.sector_name_to_code(name)

    def parents_of(self, code: str) -> list[dict[str, Any]]:
        return [n.as_dict() for n in self.tax.parents_of(code)]

    def by_ticker(self, ticker: str) -> dict[str, Any] | None:
        t = str(ticker).upper()
        return next(
            (e for e in self.stocks if t in (e["ticker"].upper(), e["yfinance_symbol"].upper())),
            None,
        )

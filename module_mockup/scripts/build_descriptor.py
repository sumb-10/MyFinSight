"""
Stage D (run once, re-run to refresh): build the universe descriptor.

  data/reference/gics_taxonomy.json                  163 sub-industries x 4 GICS levels (from Wikipedia)
  data/processed/sp500_nasdaq100_descriptor.json     per-ticker GICS tags + keywords + one-line summary

Summary / keyword priority:  LLM batch overrides (data/processed/descriptor_llm_overrides.json, optional)
                           > yfinance longBusinessSummary first sentence (RAW/info_snapshot.json, optional)
                           > rule: "{name} — {sub_industry}" / phrases from GICS names

Usage: python scripts/build_descriptor.py [--refresh-taxonomy]
"""
import argparse, io, re, datetime as dt
from collections import Counter
import pandas as pd
import requests
from common import RAW, REFERENCE, PROCESSED, DESCRIPTOR_PATH, TAXONOMY_PATH, UNIVERSE_NAME, dump_json, load_json
from schemas import Descriptor

GICS_URL = "https://en.wikipedia.org/wiki/Global_Industry_Classification_Standard"
EXPECTED = {"sector": 11, "industry_group": 25, "industry": 74, "sub_industry": 163}

# NASDAQ-100-only names come from Wikipedia with ICB labels, not GICS -> manual GICS sub-industry codes.
MANUAL_GICS = {
    "ALAB": "45301020",  # Astera Labs            Semiconductors
    "ALNY": "35201010",  # Alnylam                Biotechnology
    "ARM":  "45301020",  # Arm Holdings           Semiconductors
    "ASML": "45301010",  # ASML                   Semiconductor Materials & Equipment
    "CCEP": "30201030",  # Coca-Cola Europacific  Soft Drinks & Non-alcoholic Beverages
    "CRWV": "45102030",  # CoreWeave              Internet Services & Infrastructure
    "FER":  "20103010",  # Ferrovial              Construction & Engineering
    "MELI": "25503030",  # MercadoLibre           Broadline Retail
    "MSTR": "45103010",  # Strategy (MicroStrategy) Application Software
    "NBIS": "45102030",  # Nebius                 Internet Services & Infrastructure
    "PDD":  "25503030",  # PDD Holdings           Broadline Retail
    "RKLB": "20101010",  # Rocket Lab             Aerospace & Defense
    "SHOP": "45102030",  # Shopify                Internet Services & Infrastructure
    "SPCX": "50101020",  # (ICB: Telecommunications Services) -> Integrated Telecommunication Services [guess]
    "TRI":  "20202020",  # Thomson Reuters        Research & Consulting Services
}

STOP = {"and", "&", "other", "services", "service", "products", "equipment", "n", "a"}


def fetch_taxonomy() -> list[dict]:
    html = requests.get(GICS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    tables = [t for t in pd.read_html(io.StringIO(html)) if "Sub-Industry" in map(str, t.columns)]
    if not tables:
        raise RuntimeError("GICS table not found on Wikipedia page")
    t = tables[0].dropna(subset=["Sub-Industry"])
    rows = []
    for r in t.itertuples(index=False):
        rows.append({
            "sector": {"code": f"{int(r[0]):02d}", "name": str(r[1]).strip()},
            "industry_group": {"code": f"{int(r[2]):04d}", "name": str(r[3]).strip()},
            "industry": {"code": f"{int(r[4]):06d}", "name": str(r[5]).strip()},
            "sub_industry": {"code": f"{int(r[6]):08d}", "name": re.sub(r"\[.*?\]", "", str(r[7])).strip()},
        })
    counts = {lvl: len({r[lvl]["code"] for r in rows}) for lvl in EXPECTED}
    if counts != EXPECTED:
        raise RuntimeError(f"GICS taxonomy counts {counts} != expected {EXPECTED}")
    return rows


def phrases(name: str) -> list[str]:
    parts = re.split(r"\s*(?:&|,|/)\s*", name)
    out = []
    for p in parts:
        p = p.strip().lower()
        if p and p not in STOP:
            out.append(p)
    return out


def first_sentence(text: str, limit=300) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.+?\.)(\s|$)", text)
    s = m.group(1) if m else text
    return s[:limit].rstrip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-taxonomy", action="store_true")
    args = ap.parse_args()

    # 1. taxonomy
    if TAXONOMY_PATH.exists() and not args.refresh_taxonomy:
        rows = load_json(TAXONOMY_PATH)["sub_industries"]
    else:
        rows = fetch_taxonomy()
        dump_json({"source": GICS_URL, "fetched_at": str(dt.date.today()), "sub_industries": rows}, TAXONOMY_PATH)
    by_code = {r["sub_industry"]["code"]: r for r in rows}
    by_name = {r["sub_industry"]["name"]: r for r in rows}
    print(f"[taxonomy] {len(rows)} sub-industries")

    # 2. universe -> GICS
    uni = load_json(RAW / "universe.json")
    info = {}
    p = RAW / "info_snapshot.json"
    if p.exists():
        info = {r["ticker"]: r for r in load_json(p)}
        print(f"[info] business summaries available for {sum(1 for v in info.values() if v.get('longBusinessSummary'))} tickers")
    overrides = {}
    p = PROCESSED / "descriptor_llm_overrides.json"
    if p.exists():
        overrides = {r["ticker"]: r for r in load_json(p)["results"]}
        print(f"[llm] overrides for {len(overrides)} tickers")

    companies, unmapped = {}, []
    for r in uni:
        t = r["ticker"]
        if t in MANUAL_GICS:
            node, src = by_code[MANUAL_GICS[t]], "manual_icb_to_gics"
        elif r["industry"] in by_name:
            node, src = by_name[r["industry"]], "wikipedia_sp500"
        else:
            unmapped.append((t, r["industry"])); continue
        sub, ind = node["sub_industry"]["name"], node["industry"]["name"]
        kw = list(dict.fromkeys(phrases(sub) + phrases(ind)))
        summary, s_src, k_src = f"{r['name']} — {sub}", "rule", "rule"
        lbs = (info.get(t) or {}).get("longBusinessSummary")
        if lbs:
            summary, s_src = first_sentence(lbs), "yfinance_first_sentence"
        if t in overrides:
            o = overrides[t]
            if o.get("company_summary_ko"): summary, s_src = o["company_summary_ko"], "llm"
            if o.get("keywords"): kw, k_src = list(dict.fromkeys(kw + [k.lower() for k in o["keywords"]])), "llm+rule"
        companies[t] = {
            "name": r["name"], "indices": r["indices"],
            "gics": {lvl: dict(node[lvl]) for lvl in ("sector", "industry_group", "industry", "sub_industry")},
            "keywords": kw, "company_summary": summary,
            "sources": {"gics": src, "summary": s_src, "keywords": k_src},
        }
    if unmapped:
        raise RuntimeError(f"{len(unmapped)} tickers without GICS mapping: {unmapped}")

    counts = {lvl: dict(Counter(c["gics"][lvl]["code"] for c in companies.values()))
              for lvl in ("sector", "industry_group", "industry", "sub_industry")}
    desc = {
        "meta": {"universe": UNIVERSE_NAME, "built_at": str(dt.date.today()), "gics_version": "2023",
                 "n_companies": len(companies), "summary_sources": dict(Counter(c["sources"]["summary"] for c in companies.values()))},
        "taxonomy_counts": counts,
        "companies": dict(sorted(companies.items())),
    }
    Descriptor.model_validate(desc)
    dump_json(desc, DESCRIPTOR_PATH)
    print(f"[descriptor] {len(companies)} companies -> {DESCRIPTOR_PATH}")
    print(f"             sectors={len(counts['sector'])} groups={len(counts['industry_group'])} "
          f"industries={len(counts['industry'])} sub={len(counts['sub_industry'])}  summary sources={desc['meta']['summary_sources']}")


if __name__ == "__main__":
    main()

"""Universe descriptor helpers shared by stage 2 (prompt tree) and stage 3 (retrieval)."""
from collections import defaultdict
from common import DESCRIPTOR_PATH, TAXONOMY_PATH, load_json

LEVELS = ["sector", "industry_group", "industry", "sub_industry"]
LEVEL_LEN = {"sector": 2, "industry_group": 4, "industry": 6, "sub_industry": 8}


def load_descriptor(path=DESCRIPTOR_PATH) -> dict:
    return load_json(path)


def load_taxonomy(path=TAXONOMY_PATH) -> list[dict]:
    return load_json(path)["sub_industries"]


def code8(company: dict) -> str:
    return company["gics"]["sub_industry"]["code"]


def level_of(code: str) -> str:
    return {2: "sector", 4: "industry_group", 6: "industry", 8: "sub_industry"}[len(code)]


def filter_by_gics(desc: dict, codes: list[str]) -> dict[str, list[str]]:
    """ticker -> list of selected codes it falls under (prefix match on the 8-digit code)."""
    hits = {}
    for t, c in desc["companies"].items():
        c8 = code8(c)
        m = [k for k in codes if c8.startswith(k)]
        if m:
            hits[t] = m
    return hits


def search_keywords(desc: dict, words: list[str]) -> dict[str, list[str]]:
    """ticker -> keywords found (case-insensitive) in name / keywords / company_summary."""
    hits = {}
    lw = [w.lower() for w in words if w.strip()]
    for t, c in desc["companies"].items():
        hay = " ".join([c["name"], " ".join(c.get("keywords", [])), c.get("company_summary", "")]).lower()
        m = [w for w in lw if w in hay]
        if m:
            hits[t] = m
    return hits


def sector_name_to_code(desc: dict) -> dict[str, str]:
    out = {}
    for c in desc["companies"].values():
        out[c["gics"]["sector"]["name"]] = c["gics"]["sector"]["code"]
    return out


def render_tree(desc: dict, max_level: str = "sub_industry") -> str:
    """Indented GICS tree with company counts, for the stage-2 LLM prompt (~3K chars)."""
    names = {lvl: {} for lvl in LEVELS}
    counts = desc["taxonomy_counts"]
    for c in desc["companies"].values():
        for lvl in LEVELS:
            names[lvl][c["gics"][lvl]["code"]] = c["gics"][lvl]["name"]
    depth = LEVELS.index(max_level)
    lines = []
    for s in sorted(names["sector"]):
        lines.append(f"{s} {names['sector'][s]} ({counts['sector'][s]})")
        if depth < 1: continue
        for g in sorted(k for k in names["industry_group"] if k.startswith(s)):
            lines.append(f"  {g} {names['industry_group'][g]} ({counts['industry_group'][g]})")
            if depth < 2: continue
            for i in sorted(k for k in names["industry"] if k.startswith(g)):
                lines.append(f"    {i} {names['industry'][i]} ({counts['industry'][i]})")
                if depth < 3: continue
                for u in sorted(k for k in names["sub_industry"] if k.startswith(i)):
                    lines.append(f"      {u} {names['sub_industry'][u]} ({counts['sub_industry'][u]})")
    return "\n".join(lines)


def parents_of(code: str) -> list[str]:
    """Broader codes of a code, nearest first: 45301020 -> ['453010', '4530', '45']."""
    return [code[:n] for n in (6, 4, 2) if n < len(code)]

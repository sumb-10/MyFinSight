"""선정 지표가 비어 뽑히지 못한 종목(metric_missing)이 '자료가 없어서'인지 '정의가 안 돼서'(적자·자본 음수)인지 DB 값으로 나눈다."""
import json, sys, datetime as dt, collections
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path.cwd()))
from backend.analysis.common.dbconn import open_analysis_repository
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.settings import AnalysisSettings
s = AnalysisSettings.load(); repo = open_analysis_repository(None)
rows = []
for ln in open(sys.argv[1]):
    name, rid = ln.split()
    sel = json.load(open(f"output/{rid}/05_selection.json"))
    miss = [r["ticker"] for r in sel.get("rejected", []) if str(r.get("reason", "")).startswith("metric_missing")]
    if not miss:
        continue
    metric = sel["summary"]["metric"]
    as_of = dt.date.fromisoformat(str(sel["as_of"])[:10])
    v = MarketData(repo, s).view(as_of).valuation(miss)
    for t in miss:
        r = v.loc[t] if t in v.index else None
        if r is None:
            kind = "가치평가 행 없음"
        else:
            eps, pbr = r.get("eps_ttm"), r.get("pbr")
            if metric == "pe_ttm":
                kind = "적자(EPS≤0, 정의 안 됨)" if eps is not None and not pd.isna(eps) and float(eps) <= 0 else "자료 없음"
            elif metric == "roe_ttm":
                if pbr is not None and not pd.isna(pbr) and float(pbr) <= 0:
                    kind = "자본 음수(정의 안 됨)"
                elif (pbr is None or pd.isna(pbr)) and eps is not None and not pd.isna(eps):
                    kind = "자본 음수 추정(PBR 없음·EPS 있음)"
                else:
                    kind = "자료 없음"
            else:
                kind = "자료 없음"
        stale = None
        if r is not None and r.get("date") is not None and not pd.isna(r.get("date")):
            stale = (as_of - pd.Timestamp(r["date"]).date()).days
        rows.append({"name": name, "ticker": t, "metric": metric, "kind": kind, "valuation_age_days": stale})
df = pd.DataFrame(rows)
print(df.groupby(["metric", "kind"]).size().to_string())
print("total missing:", len(df))
print(df[df.kind.str.startswith("자료")].groupby("ticker").size().sort_values(ascending=False).head(15).to_string())
df.to_csv(sys.argv[2], index=False)

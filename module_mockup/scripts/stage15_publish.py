"""
Stage 15: publish the report document for the Front app.

in : output/14_report.json
out: Front/public/pipeline/report.json  (+ reports.json index)  -> rendered at http://localhost:5173/#/pipeline
"""
import argparse, datetime as dt, json, shutil
from common import ROOT, OUTPUT, load_json, dump_json

FRONT_PUBLIC = ROOT.parent / "Front" / "public" / "pipeline"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=str(OUTPUT / "14_report.json"))
    ap.add_argument("--dest", default=str(FRONT_PUBLIC))
    a = ap.parse_args()
    doc = load_json(a.report)
    dest = __import__("pathlib").Path(a.dest); dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(a.report, dest / "report.json")
    idx_p = dest / "reports.json"
    idx = load_json(idx_p) if idx_p.exists() else {"reports": []}
    idx["reports"] = [r for r in idx["reports"] if r["request_id"] != doc["request_id"]] + [
        {"request_id": doc["request_id"], "title_ko": doc["header"]["title_ko"], "generated_at": doc["generated_at"], "file": "report.json"}]
    dump_json(idx, idx_p)
    print(f"[stage15] ok -> {dest / 'report.json'} ({(dest / 'report.json').stat().st_size / 1e6:.2f} MB); open http://localhost:5173/#/pipeline")


if __name__ == "__main__":
    main()

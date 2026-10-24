"""
Run the request pipeline stage by stage (each stage reads the previous stage's JSON).

  python scripts/run_pipeline.py --request input/01_user_request.example.jsonc [--stop-at 5] [--fx-rate 1400] [--explain]

Stages: 1 normalize -> 2 intent (LLM#1) -> 3 retrieve -> 4 classify (LLM#2) -> 5 screen [-> 6 explain (LLM#3)]
        -> 7 confirm/backtest spec -> 8 market model + baselines -> 9 views (LLM#4) -> 10 Black-Litterman targets
        -> 11 bt backtest -> 12 rule validation + recommendation
        -> 13 consolidated results -> 14 report document (LLM#5a interpret + #5b narrate) -> 15 publish to Front/public/pipeline
Stages 7-10 need --backtest-request (default input/02_backtest_request.jsonc) and run when --stop-at >= 7.
Prerequisite (once): scripts/build_descriptor.py
"""
import argparse, os, shutil, subprocess, sys, datetime as dt
from pathlib import Path
from common import INPUT, OUTPUT_ROOT, DESCRIPTOR_PATH, load_jsonc, dump_json

HERE = Path(__file__).resolve().parent
STAGE_NO = {"stage1_normalize.py": 1, "stage2_intent.py": 2, "stage3_retrieve.py": 3, "stage4_classify.py": 4, "stage5_screen.py": 5, "stage6_explain.py": 6,
            "stage7_confirm.py": 7, "stage8_baseline.py": 8, "stage9_views.py": 9, "stage10_black_litterman.py": 10, "stage9a_news.py": 10, "stage10w_walkforward.py": 10,
            "stage10f_forward.py": 10, "stage11_backtest.py": 11, "stage12_validate.py": 12, "stage13_collect.py": 13, "stage14_report.py": 14, "stage15_publish.py": 15}


def run(script, *args):
    cmd = [sys.executable, str(HERE / script), *map(str, args)]
    print("\n$", " ".join(Path(c).name if i < 2 else c for i, c in enumerate(cmd)))
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", default=str(INPUT / "01_user_request.example.jsonc"))
    ap.add_argument("--stop-at", type=int, default=5, help="last stage to run (1-15)")
    ap.add_argument("--from", dest="from_stage", type=int, default=1, help="first stage to run (reuse earlier outputs)")
    ap.add_argument("--backtest-request", default=str(INPUT / "02_backtest_request.jsonc"))
    ap.add_argument("--news", action="store_true", help="run news stages (9a evidence, 10w walk-forward, 10f forward) — needs NEWS_DB_* in .env")
    ap.add_argument("--web-evidence", default=None, help="json of web-search evidence for windows the DB lacks")
    ap.add_argument("--fx-rate", type=float, default=None)
    ap.add_argument("--explain", action="store_true", help="also run stage 6 (LLM #3)")
    ap.add_argument("--run-id", default=None, help="output/<run_id>/ (default run_<scenario>_<YYYYMMDD_HHMM>)")
    a = ap.parse_args()
    if not DESCRIPTOR_PATH.exists():
        raise SystemExit("descriptor missing: run scripts/build_descriptor.py first")

    parts = Path(a.request).name.split("."); scenario = parts[1] if len(parts) == 3 else None
    run_id = a.run_id or os.environ.get("MYFINSIGHT_RUN_ID") or dt.datetime.now().strftime(f"run_{scenario or 'adhoc'}_%Y%m%d_%H%M")
    os.environ["MYFINSIGHT_RUN_ID"] = run_id
    run_dir = OUTPUT_ROOT / run_id; (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
    for f in (a.request, a.backtest_request, a.web_evidence):
        if f and Path(f).exists(): shutil.copy(f, run_dir / "inputs" / Path(f).name)
    latest = OUTPUT_ROOT / "latest"
    if latest.is_symlink() or latest.exists(): latest.unlink()
    os.symlink(run_id, latest)
    meta = {"run_id": run_id, "scenario": scenario, "request_id": load_jsonc(a.request)["request_id"], "request_file": a.request, "backtest_file": a.backtest_request,
            "web_evidence": a.web_evidence, "news": bool(a.news), "stop_at": a.stop_at, "from_stage": a.from_stage, "llm_mode": os.environ.get("MYFINSIGHT_LLM", "stub"),
            "data_dir": os.environ.get("MYFINSIGHT_DATA"), "started_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "finished_at": None, "status": "running",
            "git_commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=HERE).stdout.strip() or None}
    dump_json(meta, run_dir / "run_meta.json")
    try:
        import store
        store.update_run_index({"run_id": run_id, "request_id": meta["request_id"], "status": "running", "queued_at": meta["started_at"], "started_at": meta["started_at"],
                                "output_dir": str(run_dir), "llm_mode": "api" if meta["llm_mode"] == "api" else "stub", "scenario": scenario, "request_file": a.request,
                                "backtest_file": a.backtest_request, "data_dir": meta["data_dir"], "stop_at": a.stop_at, "news": bool(a.news)})
    except Exception as e:                       # the index must never block an analysis
        print(f"[pipeline] run index not updated: {e!r}")
    print(f"[pipeline] LLM mode={meta['llm_mode']} run_id={run_id} -> {run_dir}")
    fx = ["--fx-rate", a.fx_rate] if a.fx_rate else []
    steps = [
        ("stage1_normalize.py", ["--request", a.request, *fx]),
        ("stage2_intent.py", ["--request", a.request]),
        ("stage3_retrieve.py", []),
        ("stage4_classify.py", []),
        ("stage5_screen.py", []),
    ]
    steps.append(("stage6_explain.py", []) if a.explain else None)
    steps += [
        ("stage7_confirm.py", ["--backtest-request", a.backtest_request]),
        ("stage8_baseline.py", []),
        ("stage9_views.py", ["--backtest-request", a.backtest_request]),
        ("stage10_black_litterman.py", []),
        ("stage9a_news.py", ["--backtest-request", a.backtest_request, *(["--web-evidence", a.web_evidence] if a.web_evidence else [])]) if a.news else None,
        ("stage10w_walkforward.py", ["--backtest-request", a.backtest_request]) if a.news else None,
        ("stage10f_forward.py", ["--backtest-request", a.backtest_request]) if a.news else None,
        ("stage11_backtest.py", []),
        ("stage12_validate.py", []),
        ("stage13_collect.py", []),
        ("stage14_report.py", []),
        ("stage15_publish.py", []),
    ]
    def finish(status, err=None):
        meta.update(status=status, finished_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"), error=err)
        dump_json(meta, run_dir / "run_meta.json")
        try:
            import store
            store.update_run_index({"run_id": run_id, "request_id": meta["request_id"], "status": status, "queued_at": meta["started_at"], "finished_at": meta["finished_at"],
                                    "output_dir": str(run_dir), "report_id": run_id if (run_dir / "14_report.json").exists() else None, "error_message": err})
        except Exception as e:
            print(f"[pipeline] run index not updated: {e!r}")

    try:
        for step in steps:
            if step is None:
                continue
            no = STAGE_NO[step[0]]
            if no > a.stop_at or no < a.from_stage:
                continue
            run(step[0], *step[1])
    except subprocess.CalledProcessError as e:
        finish("failed", f"{Path(e.cmd[1]).name} exited {e.returncode}"); raise
    finish("success")
    print(f"\n[pipeline] done. outputs in {run_dir}")
    if os.environ.get("MYFINSIGHT_LLM") == "api":
        run("llm_cost_report.py", "--run-id", os.environ["MYFINSIGHT_RUN_ID"])


if __name__ == "__main__":
    main()

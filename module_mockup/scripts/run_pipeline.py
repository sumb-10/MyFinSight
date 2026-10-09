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
import argparse, os, subprocess, sys, datetime as dt
from pathlib import Path
from common import INPUT, OUTPUT, DESCRIPTOR_PATH

HERE = Path(__file__).resolve().parent


def run(script, *args):
    cmd = [sys.executable, str(HERE / script), *map(str, args)]
    print("\n$", " ".join(Path(c).name if i < 2 else c for i, c in enumerate(cmd)))
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", default=str(INPUT / "01_user_request.example.jsonc"))
    ap.add_argument("--stop-at", type=int, default=5, help="last stage to run (1-15)")
    ap.add_argument("--backtest-request", default=str(INPUT / "02_backtest_request.jsonc"))
    ap.add_argument("--fx-rate", type=float, default=None)
    ap.add_argument("--explain", action="store_true", help="also run stage 6 (LLM #3)")
    a = ap.parse_args()
    if not DESCRIPTOR_PATH.exists():
        raise SystemExit("descriptor missing: run scripts/build_descriptor.py first")

    os.environ.setdefault("MYFINSIGHT_RUN_ID", dt.datetime.now().strftime("run_%Y%m%d_%H%M%S"))
    print(f"[pipeline] LLM mode={os.environ.get('MYFINSIGHT_LLM', 'stub (default)')} run_id={os.environ['MYFINSIGHT_RUN_ID']}")
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
        ("stage11_backtest.py", []),
        ("stage12_validate.py", []),
        ("stage13_collect.py", []),
        ("stage14_report.py", []),
        ("stage15_publish.py", []),
    ]
    for i, step in enumerate(steps, 1):
        if step is None or i > a.stop_at:
            continue
        run(step[0], *step[1])
    print(f"\n[pipeline] done. outputs in {OUTPUT}")
    if os.environ.get("MYFINSIGHT_LLM") == "api":
        run("llm_cost_report.py", "--run-id", os.environ["MYFINSIGHT_RUN_ID"])


if __name__ == "__main__":
    main()

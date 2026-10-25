"""시나리오를 실제 서비스 경로(API → 보충 질문 → 확정 → 큐 → 일꾼 → 리포트)로 돌린다 (E2).

  python -m backend.analysis.eval.run_scenarios --scenarios ai,kr --llm api
  python -m backend.analysis.eval.run_scenarios --list
  python -m backend.analysis.eval.run_scenarios --collect          # 돌리지 않고 저장된 run_id 의 결과만 다시 모음

- 시나리오 = module_mockup/input/01_user_request.<이름>.jsonc 의 프로필·조건 + 아이디어. kr 은 backend/analysis/examples/request_kr_us_semis.json.
- 서버를 --port 로 띄우고(이미 떠 있으면 그대로 사용), 시나리오마다 프로필을 저장하고 요청을 만든다.
- 보충 질문 답: 첫 질문은 첫 번째 보기(보기가 없으면 자유 입력 한 줄), 그 뒤는 "답하지 않음". --answer skip 이면 모두 답하지 않음.
- 확정 뒤 `worker --once` 로 한 건을 계산하고 리포트를 받아 요약 표(markdown)를 적는다.
- 저장 위치는 서비스 기본값(data/analysis_store, data/analysis_results.db) → 화면(Front)에서 바로 볼 수 있다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
MOCK_INPUT = ROOT / "module_mockup" / "input"
EXAMPLES = ROOT / "backend" / "analysis" / "examples"
PROFILE_KEYS = ("profile", "capital", "horizon", "risk", "constraints", "strategy_preference")

SCENARIOS: dict[str, dict[str, Any]] = {
    "ai": {"file": MOCK_INPUT / "01_user_request.ai.jsonc", "title_ko": "AI 반도체·클라우드 모멘텀"},
    "defensive": {"file": MOCK_INPUT / "01_user_request.defensive.jsonc", "title_ko": "은퇴 대비 경기방어"},
    "broad": {"file": MOCK_INPUT / "01_user_request.broad.jsonc", "title_ko": "대형 우량주 전반 장기 보유"},
    "energy": {"file": MOCK_INPUT / "01_user_request.energy.jsonc", "title_ko": "에너지 전환·전력 인프라"},
    "travel": {"file": MOCK_INPUT / "01_user_request.travel.jsonc", "title_ko": "여행·외식·레저 소비 회복"},
    "healthcare": {"file": MOCK_INPUT / "01_user_request.healthcare.jsonc", "title_ko": "헬스케어 (비만·의료기기·서비스)"},
    "kr": {"file": EXAMPLES / "request_kr_us_semis.json", "title_ko": "미국·한국 반도체·메모리"},
    "lowper": {"file": EXAMPLES / "request_us_lowper_2005.json", "title_ko": "대형주 저PER (2005년부터 12년: 과거 구간 공시 근거 확인)"},
}


def load_request(path: Path) -> dict[str, Any]:
    from backend.analysis.common.jsonio import load_json, load_jsonc

    return load_jsonc(str(path)) if path.suffix == ".jsonc" else load_json(str(path))


class Api:
    def __init__(self, base: str) -> None:
        self.base = base

    def call(self, method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})  # fmt: skip
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def ok(self, method: str, path: str, body: Any | None = None) -> Any:
        st, out = self.call(method, path, body)
        if st >= 400:
            raise RuntimeError(f"{method} {path} → {st}: {json.dumps(out, ensure_ascii=False)[:300]}")
        return out


def ensure_server(api: Api, port: int, env: dict[str, str], log: Path) -> subprocess.Popen | None:
    try:
        api.call("GET", "/health")
        return None
    except Exception:  # noqa: BLE001
        pass
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.analysis.api.app:app", "--port", str(port), "--log-level", "warning"],
                            cwd=ROOT, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT)  # fmt: skip
    for _ in range(90):
        try:
            api.call("GET", "/health")
            return proc
        except Exception:  # noqa: BLE001
            time.sleep(1)
    proc.terminate()
    raise SystemExit("서버가 켜지지 않았습니다. 로그: " + str(log))


def answer_questions(api: Api, rid: str, state: dict[str, Any], policy: str, log: list[dict[str, Any]]) -> dict[str, Any]:
    """policy: first = 첫 질문만 첫 보기, all = 모든 질문에 첫 보기(협조적인 사용자 흉내), skip = 전부 건너뜀."""
    first = True
    while state.get("state") == "asking" and state.get("question"):
        q = state["question"]
        t_q = time.time()
        if (policy == "first" and first) or policy == "all":
            if q.get("options"):
                opt = q["options"][0]
                state = api.ok("POST", f"/requests/{rid}/answer", {"seq": q["seq"], "option_value": opt["value"]})
                log.append({"seq": q["seq"], "field": q["field"], "question_ko": q["question_ko"], "answer": opt.get("label_ko")})
            else:
                text = "지금 적은 조건과 아이디어 그대로 진행해 주세요."
                state = api.ok("POST", f"/requests/{rid}/answer", {"seq": q["seq"], "free_text": text})
                log.append({"seq": q["seq"], "field": q["field"], "question_ko": q["question_ko"], "answer": text})
        else:
            state = api.ok("POST", f"/requests/{rid}/skip", {"seq": q["seq"]})  # skip 도 seq 본문이 필요하다 (두 번째 질문부터 422 나던 버그)
            log.append({"seq": q["seq"], "field": q["field"], "question_ko": q["question_ko"], "answer": "(답하지 않음)"})
        log[-1].update({"kind": q.get("kind"), "options": [o.get("label_ko") for o in q.get("options", [])], "why_ko": q.get("why_ko"), "turn_seconds": round(time.time() - t_q, 1)})
        first = False
    return state


TERMINAL = ("success", "partial", "failed", "cancelled")


def wait_for_run(api: Api, run_id: str, timeout_s: float, poll_s: float = 10.0) -> dict[str, Any]:
    """다른 일꾼이 잠금을 쥐고 있어 `worker --once` 가 바로 끝났을 때, 실행이 끝날 때까지 상태를 본다."""
    t0 = time.time()
    run = api.ok("GET", f"/runs/{run_id}")
    while run.get("status") not in TERMINAL and time.time() - t0 < timeout_s:
        time.sleep(poll_s)
        run = api.ok("GET", f"/runs/{run_id}")
    return run


def collect(name: str, api: Api, prev: dict[str, Any]) -> dict[str, Any]:
    """저장된 시나리오 JSON 의 run_id 로 지금 상태·리포트를 다시 읽어 요약을 채운다."""
    run_id = prev.get("run_id")
    if not run_id:
        return prev
    run = api.ok("GET", f"/runs/{run_id}")
    out = {**prev, "status": run.get("status"), "error": run.get("error"), "buckets": [(b["id"], b["status"]) for b in run.get("buckets", [])]}
    steps = run.get("steps") or []
    if steps and steps[0].get("started_at") and steps[-1].get("ended_at"):
        out["run_seconds"] = round((dt.datetime.fromisoformat(steps[-1]["ended_at"]) - dt.datetime.fromisoformat(steps[0]["started_at"])).total_seconds(), 1)
    st, doc = api.call("GET", f"/reports/{run_id}")
    if st == 200:
        hdr = doc.get("header", {})
        out.update({"report": True, "report_error": None, "chosen_label_ko": hdr.get("chosen_label_ko"), "verdict_ko": hdr.get("subtitle_ko"), "as_of": hdr.get("data_as_of"),
                    "kpis": {k["id"]: k.get("value") for k in doc.get("kpis", []) if isinstance(k, dict) and "id" in k}, "n_evidence": len(doc.get("evidence", [])), "warnings": len(doc.get("warnings", []))})  # fmt: skip
        st2, res = api.call("GET", f"/reports/{run_id}/results")
        if st2 == 200:
            v = res.get("validation", {})
            out.update({"validation": v.get("summary"), "recommended": (v.get("recommended") or {}).get("id"), "chosen_id": v.get("chosen_id"), "llm_usage": res.get("llm_usage")})
    else:
        out.update({"report": False, "report_error": doc})
    return out


def normalize_request(req: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """시나리오 파일의 표기 차이를 서비스 입력에 맞춘다. 바뀐 것은 기록한다 (채점 근거).

    - capital.trading_currency: 서비스는 USD 로만 계산하고 표시는 KRW 로도 한다 → "KRW" 는 "USD" 로. (계산값은 바뀌지 않는다)"""
    req = json.loads(json.dumps(req))
    notes: list[str] = []
    tc = req.get("capital", {}).get("trading_currency")
    if tc and tc != "USD":
        notes.append(f"capital.trading_currency {tc} → USD (서비스는 USD 로 계산, 표시만 KRW)")
        req["capital"]["trading_currency"] = "USD"
    return req, notes


def run_scenario(name: str, api: Api, env: dict[str, str], policy: str, wait_s: float) -> dict[str, Any]:
    sc = SCENARIOS[name]
    req, normalized = normalize_request(load_request(sc["file"]))
    profile = {k: req[k] for k in PROFILE_KEYS}
    profile["risk_type_computed"] = req["risk"]["risk_tolerance"]
    profile["risk_type_overridden"] = False
    profile["note"] = f"시나리오 {name}"
    api.ok("PUT", "/profile", profile)
    overrides: dict[str, Any] = {}
    start_date = (req.get("horizon") or {}).get("start_date")
    if start_date:  # 프로필은 기준일을 지우므로(요청마다 정함) 시나리오의 기준일은 이번 요청의 덮어쓰기로 넣는다
        overrides["horizon.start_date"] = str(start_date)[:10]
    t0 = time.time()
    state = api.ok("POST", "/requests", {"idea": req["natural_language"]["idea"], "overrides": overrides})
    rid = state["request_id"]
    qa: list[dict[str, Any]] = []
    state = answer_questions(api, rid, state, policy, qa)
    if state.get("state") != "ready":
        return {"name": name, "title_ko": sc["title_ko"], "scenario_file": str(sc["file"]), "normalized": normalized, "overrides": overrides, "request_id": rid,
                "dialog_state": state.get("state"), "qa": qa, "blocked_reason_ko": state.get("blocked_reason_ko"), "hard_errors": state.get("hard_errors"), "status": "not_confirmed"}  # fmt: skip
    conf = api.ok("POST", f"/requests/{rid}/confirm")
    run_id = conf["run_id"]
    dialog_s = round(time.time() - t0, 1)
    t1 = time.time()
    w = subprocess.run([sys.executable, "-m", "backend.analysis.executor.worker", "--once"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=3600)
    run = api.ok("GET", f"/runs/{run_id}")
    if run.get("status") not in TERMINAL and wait_s > 0:  # 다른 일꾼이 돌고 있으면 (rc 2) 그 일꾼이 끝내 줄 때까지 기다린다
        run = wait_for_run(api, run_id, wait_s)
    run_s = round(time.time() - t1, 1)
    out: dict[str, Any] = {"name": name, "title_ko": sc["title_ko"], "scenario_file": str(sc["file"]), "normalized": normalized, "overrides": overrides,
                           "request_id": rid, "run_id": run_id, "qa": qa, "dialog_seconds": dialog_s,
                           "run_seconds": run_s, "status": run.get("status"), "error": run.get("error"), "worker_rc": w.returncode,
                           "buckets": [(b["id"], b["status"]) for b in run.get("buckets", [])],
                           "steps": [{k: st.get(k) for k in ("step", "status", "started_at", "ended_at", "summary", "error_message")} for st in run.get("steps", [])]}  # fmt: skip
    st, doc = api.call("GET", f"/reports/{run_id}")
    if st == 200:
        kp = {k["id"]: k.get("value") for k in doc.get("kpis", []) if isinstance(k, dict) and "id" in k}
        hdr = doc.get("header", {})
        out.update({"report": True, "chosen_label_ko": hdr.get("chosen_label_ko"), "verdict_ko": hdr.get("verdict_ko") or hdr.get("subtitle_ko"), "kpis": kp,
                    "as_of": hdr.get("as_of"), "n_evidence": len(doc.get("evidence", {})), "warnings": len(doc.get("warnings", []))})  # fmt: skip
        st2, res = api.call("GET", f"/reports/{run_id}/results")
        if st2 == 200:
            v = res.get("validation", {})
            out["validation"] = v.get("summary")
            out["recommended"] = (v.get("recommended") or {}).get("id")
            out["chosen_id"] = v.get("chosen_id")
            out["llm_usage"] = res.get("llm_usage") or (res.get("params") or {}).get("llm_usage")
    else:
        out.update({"report": False, "report_error": doc})
    return out


def to_markdown(rows: list[dict[str, Any]], llm: str) -> str:
    lines = [f"# 시나리오 실행 결과 ({dt.date.today()}, LLM {llm})", "",
             "| 시나리오 | 상태 | 보충 질문 | 추천 | 선택안 | 통과/주의/미통과 | 근거 수 | 대화 s | 실행 s | run_id |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for r in rows:
        v = r.get("validation") or {}
        vs = f"{v.get('n_pass', '-')}/{v.get('n_warn', '-')}/{v.get('n_fail', '-')}" if v else "-"
        qa = "; ".join(f"Q{q['seq']} {q['field'].split('.')[-1]} → {q['answer']}" for q in r.get("qa", [])) or "없음"
        lines.append(f"| {r['title_ko']} | {r.get('status')} | {qa} | {r.get('recommended') or '없음'} | {r.get('chosen_id') or '-'} | {vs} | {r.get('n_evidence', '-')} | {r.get('dialog_seconds', '-')} | {r.get('run_seconds', '-')} | `{r.get('run_id', '-')}` |")  # fmt: skip
    lines.append("")
    for r in rows:
        if r.get("error") or r.get("report_error") or r.get("blocked_reason_ko"):
            lines.append(f"- {r['title_ko']}: {json.dumps(r.get('error') or r.get('report_error') or r.get('blocked_reason_ko'), ensure_ascii=False)[:300]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="backend.analysis.eval.run_scenarios")
    ap.add_argument("--scenarios", default=",".join(SCENARIOS), help="쉼표로 구분 (기본: 전부)")
    ap.add_argument("--llm", default=None, choices=["stub", "api"], help="MYFINSIGHT_LLM (기본: .env)")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--answer", default="first", choices=["first", "all", "skip"], help="보충 질문 답 정책: first=첫 질문만 첫 보기, all=모든 질문 첫 보기, skip=전부 건너뜀")
    ap.add_argument("--files", default="", help="임의 시나리오 요청 JSON 경로(쉼표). 이름은 파일 이름(확장자 제외). 예: backend/test_scenarios/scenario_000.json")
    ap.add_argument("--out", default=str(ROOT / "docs" / "mvp" / "scenario_runs"), help="결과 JSON·markdown 폴더")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--collect", action="store_true", help="새로 돌리지 않고 저장된 JSON 의 run_id 로 상태·리포트만 다시 모아 표를 만든다")
    ap.add_argument("--wait-sec", type=float, default=3600, help="다른 일꾼이 돌고 있을 때 실행 완료를 기다리는 최대 시간")
    a = ap.parse_args(argv)
    if a.files:
        names = []
        for f in [x.strip() for x in a.files.split(",") if x.strip()]:
            path = Path(f) if Path(f).is_absolute() else ROOT / f
            if not path.exists():
                raise SystemExit(f"시나리오 파일이 없습니다: {path}")
            idea = str((load_request(path).get("natural_language") or {}).get("idea") or "")
            SCENARIOS[path.stem] = {"file": path, "title_ko": idea[:40] + ("…" if len(idea) > 40 else "")}
            names.append(path.stem)
        a.scenarios = ",".join(names)
    if a.list:
        for k, v in SCENARIOS.items():
            print(f"{k:<12} {v['title_ko']}  ({v['file'].relative_to(ROOT)})")
        return 0
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    if a.llm:
        env["MYFINSIGHT_LLM"] = a.llm
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    api = Api(f"http://127.0.0.1:{a.port}/api/v1")
    proc = ensure_server(api, a.port, env, out_dir / "uvicorn.log")
    rows: list[dict[str, Any]] = []
    saved_profile: dict[str, Any] | None = None  # 시나리오는 프로필을 덮어쓰므로(PUT /profile) 끝나면 사용자의 프로필을 되돌린다
    if not a.collect:
        try:
            cur = api.ok("GET", "/profile")["profile"]
            saved_profile = {k: cur[k] for k in (*PROFILE_KEYS, "diagnosis", "risk_type_computed", "risk_type_overridden") if k in cur and cur[k] is not None}
        except Exception:  # noqa: BLE001 — 프로필이 아직 없으면 되돌릴 것도 없다
            saved_profile = None
    try:
        for name in [s.strip() for s in a.scenarios.split(",") if s.strip()]:
            print(f"── {name} ({SCENARIOS[name]['title_ko']})", flush=True)
            try:
                if a.collect:
                    prev_p = out_dir / f"{name}.json"
                    r = collect(name, api, json.loads(prev_p.read_text(encoding="utf-8"))) if prev_p.exists() else {"name": name, "title_ko": SCENARIOS[name]["title_ko"], "status": "missing"}
                else:
                    r = run_scenario(name, api, env, a.answer, a.wait_sec)
            except Exception as e:  # noqa: BLE001
                r = {"name": name, "title_ko": SCENARIOS[name]["title_ko"], "status": "error", "error": f"{type(e).__name__}: {e}"[:400]}
            rows.append(r)
            print(json.dumps({k: r.get(k) for k in ("status", "run_id", "recommended", "chosen_id", "validation", "dialog_seconds", "run_seconds", "error")}, ensure_ascii=False), flush=True)
            (out_dir / f"{name}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        if saved_profile is not None:
            try:
                api.ok("PUT", "/profile", {**saved_profile, "note": "시나리오 실행 전 프로필로 복원"})
                print("프로필을 시나리오 실행 전 값으로 되돌렸습니다 (새 버전).", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"프로필 복원 실패: {e}", flush=True)
        if proc:
            proc.terminate()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    md = to_markdown(rows, env.get("MYFINSIGHT_LLM", "(.env)"))
    (out_dir / f"summary_{stamp}.md").write_text(md, encoding="utf-8")
    (out_dir / "summary_latest.md").write_text(md, encoding="utf-8")
    print(md)
    return 0 if all(r.get("status") in ("success", "partial") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

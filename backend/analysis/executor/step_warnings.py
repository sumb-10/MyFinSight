"""단계별 사용자 경고 전체 (분석 진행 화면의 「확인할 점」, GET /runs/{id}/warnings).

단계 요약(run_step.summary)은 「확인 필요 N건: a; b」 로 2건까지만 적는다. 러너가 단계 하나가 끝날 때마다 그 단계의
사용자 경고를 step_warnings.json 에 써 두어, 실행 중에도 끝난 단계의 경고 전체를 볼 수 있다.
세는 규칙은 요약과 같다: 같은 경고는 merge 로 하나로 묶고(count 합산) level 이 user 인 것만 → 단계별 줄 수 = 요약의 N.
이 파일이 없는 예전 실행은 끝난 뒤의 run_meta.json(warnings·steps)에서 같은 규칙으로 다시 만든다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backend.analysis.common.jsonio import dump_json
from backend.analysis.common.warnings import Warning, merge

FILE = "step_warnings.json"
DONE = ("SUCCESS", "PARTIAL")  # 끝난 단계 (실패·취소된 단계의 경고는 요약에도 없다)


def user_warnings(ws: Sequence[Warning]) -> list[Warning]:
    """한 단계의 경고 → 화면에 보일 것 (요약의 「확인 필요 N건」 과 같은 규칙)."""
    return [w for w in merge(list(ws)) if w.level == "user"]


def save(run_dir: Path, by_stage: dict[str, list[Warning]]) -> None:
    dump_json({stage: [w.to_dict() for w in ws] for stage, ws in by_stage.items()}, run_dir / FILE)


def load(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """단계 → 경고(dict) 목록. 아직 끝난 단계가 없으면 빈 dict."""
    f = run_dir / FILE
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    meta = run_dir / "run_meta.json"
    if not meta.exists():
        return {}
    m = json.loads(meta.read_text(encoding="utf-8"))
    ws = [Warning(**w) for w in m.get("warnings") or []]
    done = [s["name"] for s in m.get("steps") or [] if s.get("status") in DONE]
    return {stage: [w.to_dict() for w in user_warnings([w for w in ws if w.stage == stage])] for stage in done}


def api_rows(by_stage: dict[str, list[dict[str, Any]]], labels: dict[str, str], order: Sequence[str]) -> list[dict[str, Any]]:
    """API 모양 (프런트 제안 계약 ProposedRunWarning): 단계 순서대로 {step, step_label_ko, message_ko, count}."""
    rank = {name: i for i, name in enumerate(order)}
    rows = []
    for stage in sorted(by_stage, key=lambda s: rank.get(s, len(rank))):
        for w in by_stage[stage]:
            rows.append({"step": stage, "step_label_ko": labels.get(stage, stage), "message_ko": w["message_ko"], "count": int(w.get("count") or 1)})
    return rows

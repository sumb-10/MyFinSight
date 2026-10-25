"""프롬프트 템플릿 로딩. prompts/<stage>/system_prompt.md + user_prompt.md ({{name}} 치환은 user 만)."""

from __future__ import annotations

from pathlib import Path

from backend.analysis.paths import PROMPTS


def render_template(template: str, **vars_: object) -> str:
    """{{name}} 자리 표시자를 바꾼다. 모르는 자리 표시자는 그대로 둔다."""
    for k, v in vars_.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def load_prompts(stage_dir: str, *, root: Path | None = None, **vars_: object) -> tuple[str, str]:
    d = (root or PROMPTS) / stage_dir
    system = (d / "system_prompt.md").read_text(encoding="utf-8")
    user = render_template((d / "user_prompt.md").read_text(encoding="utf-8"), **vars_)
    return system, user

"""프롬프트 템플릿 로딩. prompts/<stage>/system_prompt.md + user_prompt.md ({{name}} 치환은 user 만).

여러 단계가 같은 지침을 나눠 쓸 때는 system_prompt.md 에 `{{include:_파일.md}}` 한 줄을 둔다 (prompts/ 바로 아래 파일).
예: 리포트 14a·14b·14c·14d 가 같이 쓰는 문체 지침 `_report_style.md` (2026-11-18: 리포트 글이 AI 처럼 읽힌다는 사용자 의견).
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.analysis.paths import PROMPTS

INCLUDE_RE = re.compile(r"\{\{include:([\w.-]+\.md)\}\}")


def render_template(template: str, **vars_: object) -> str:
    """{{name}} 자리 표시자를 바꾼다. 모르는 자리 표시자는 그대로 둔다."""
    for k, v in vars_.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def expand_includes(text: str, root: Path) -> str:
    """`{{include:_x.md}}` 를 prompts/ 바로 아래 그 파일 내용으로 바꾼다 (한 단계만, 경로 구분자는 받지 않는다)."""
    return INCLUDE_RE.sub(lambda m: (root / m.group(1)).read_text(encoding="utf-8").strip(), text)


def load_prompts(stage_dir: str, *, root: Path | None = None, **vars_: object) -> tuple[str, str]:
    base = root or PROMPTS
    d = base / stage_dir
    system = expand_includes((d / "system_prompt.md").read_text(encoding="utf-8"), base)
    user = render_template((d / "user_prompt.md").read_text(encoding="utf-8"), **vars_)
    return system, user

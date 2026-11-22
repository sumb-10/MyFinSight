"""비밀 값 보관함: 화면에서 넣은 팀 DB 주소·API 키를 운영체제에 맡긴다.

- Windows 는 자격 증명 관리자, macOS 는 키체인, Linux 데스크톱은 시스템 키링. `keyring` 라이브러리가 같은 방식으로 쓰게 해 준다.
  암호화와 접근 제한은 운영체제가 한다 (로그인한 그 계정만 꺼낼 수 있다). 앱은 파일에 비밀 값을 쓰지 않는다.
- 보관함을 쓸 수 없는 곳(Docker 컨테이너·화면 없는 서버, keyring 을 설치하지 않은 환경)에서는 available() 이 False 다.
  그런 곳에서는 화면에서 저장할 수 없고, 값은 환경변수(.env · Compose)로만 넣는다.
- MYFINSIGHT_SECRET_STORE=none 이면 보관함을 쓰지 않는다 (테스트, 보관함을 건드리고 싶지 않을 때).
- MYFINSIGHT_SECRET_SERVICE 로 보관함에 넣는 이름을 바꿀 수 있다 (한 PC 에서 설치본과 개발본을 따로 쓸 때, 시험할 때).
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

SERVICE = "MyFinSight"  # 보관함에 이 이름으로 들어간다 (운영체제의 보관함 화면에서 보이는 이름)


def service() -> str:
    return os.environ.get("MYFINSIGHT_SECRET_SERVICE", "").strip() or SERVICE


class SecretStoreError(Exception):
    """보관함에 쓰지 못했다."""


def _backend() -> Any | None:
    """쓸 수 있는 보관함. 없으면 None."""
    if os.environ.get("MYFINSIGHT_SECRET_STORE", "").strip().lower() == "none":
        return None
    try:
        import keyring
    except ImportError:
        return None
    try:
        k = keyring.get_keyring()
    except Exception:  # noqa: BLE001 — 보관함을 찾다 실패해도 서버는 떠야 한다
        log.info("[secret_store] no keyring", exc_info=True)
        return None
    return k if float(getattr(k, "priority", 0) or 0) > 0 else None  # 쓸 것이 없으면 keyring 은 우선순위 0 인 「실패」 보관함을 준다


def available() -> bool:
    return _backend() is not None


def label() -> str | None:
    """화면에 적을 보관함 이름 (「…에 저장되고」처럼 뒤에 '에'를 붙여 쓴다). 쓸 수 없으면 None."""
    k = _backend()
    if k is None:
        return None
    module = type(k).__module__
    if module.endswith(".Windows"):
        return "Windows 자격 증명 관리자"
    if module.endswith(".macOS"):
        return "macOS 키체인"
    return "시스템 키링"


def get(name: str) -> str | None:
    k = _backend()
    if k is None:
        return None
    try:
        return k.get_password(service(), name) or None
    except Exception:  # noqa: BLE001 — 못 읽으면 없는 것으로 본다 (연습 모드로 뜬다)
        log.warning("[secret_store] read failed: %s", name, exc_info=True)
        return None


def put(name: str, value: str) -> None:
    k = _backend()
    if k is None:
        raise SecretStoreError("보관함을 쓸 수 없는 환경입니다")
    try:
        k.set_password(service(), name, value)
    except Exception as exc:  # noqa: BLE001
        raise SecretStoreError(f"{type(exc).__name__}: 보관함에 저장하지 못했습니다") from exc


def delete(name: str) -> None:
    """없던 값이면 조용히 넘어간다."""
    k = _backend()
    if k is None:
        return
    try:
        k.delete_password(service(), name)
    except Exception:  # noqa: BLE001
        log.info("[secret_store] delete skipped: %s", name, exc_info=True)

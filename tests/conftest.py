"""모든 테스트 공통: 네트워크 차단, 내 .env·환경변수와 분리."""

from __future__ import annotations

import pytest
import requests

from myfinsight.data.crawlers import config


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    # 테스트가 실제 .env 의 키를 읽지 않게 (내 PC 에 진짜 키가 있어도 테스트 결과는 같아야 함)
    monkeypatch.setattr(config, "_loaded", True)
    for key in (*config._KEYS, "MYFINSIGHT_ENV_FILE", "MYFINSIGHT_ENV"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MYFINSIGHT_CACHE_DIR", str(tmp_path / "cache"))

    # 명세 C-11: 테스트에서 실제 네트워크 금지. 실수로 부르면 바로 실패한다.
    def _no_network(self, method, url, *a, **k):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError(f"테스트에서 실제 네트워크 호출: {method} {url}")

    monkeypatch.setattr(requests.Session, "request", _no_network)

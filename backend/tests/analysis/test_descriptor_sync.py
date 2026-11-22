"""종목 사전을 팀 DB 에서 스스로 맞추기 (m2_data/descriptor.sync).

예전에는 backend/scripts/build_descriptor.py 를 손으로 돌려 파일을 만들어 두어야 했다.
지금은 화면 서버가 팀 DB 를 열 때 맞춘다 — 저장소를 받지 않은 사람(실행 파일)도 사전을 갖게.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from backend.analysis.api import services as services_module
from backend.analysis.api.services import Services
from backend.analysis.common.dbconn import SplitRepository
from backend.analysis.common.store import JsonStore
from backend.analysis.errors import DataMissing
from backend.analysis.m2_data import descriptor as D
from backend.analysis.settings import AnalysisSettings, replace_settings

AS_OF = dt.date(2025, 12, 31)
UNIVERSES = ["SP500", "NASDAQ100", "KOSPI200"]


def market_for(folder, **changes):
    s = AnalysisSettings()
    return replace_settings(s.market, descriptor_dir=str(folder), **changes)


def version_files(folder) -> list[str]:
    return sorted(p.name for p in folder.glob("all_descriptor_*.json") if "versions" not in p.name)


def test_sync_builds_the_descriptor_from_the_database(seeded_repo, descriptor_dir, tmp_path):
    changed = D.sync(seeded_repo, market_for(tmp_path))
    assert changed and version_files(tmp_path) == version_files(descriptor_dir)  # 손으로 만든 것(테스트 픽스처)과 같은 버전들
    desc, info, _warns = D.load_for(AS_OF, UNIVERSES, processed_dir=tmp_path)
    by_hand, _info, _w = D.load_for(AS_OF, UNIVERSES, processed_dir=descriptor_dir)
    assert D.tickers(desc) == D.tickers(by_hand) and info["n_stocks"] > 0


def test_sync_again_leaves_the_version_files_alone_when_the_database_is_the_same(seeded_repo, tmp_path):
    D.sync(seeded_repo, market_for(tmp_path))
    first = {name: json.loads((tmp_path / name).read_text(encoding="utf-8"))["generated_at"] for name in version_files(tmp_path)}
    assert D.sync(seeded_repo, market_for(tmp_path)) == []  # 바뀐 버전 없음 → 예전 실행이 고른 버전 파일이 그대로다
    again = {name: json.loads((tmp_path / name).read_text(encoding="utf-8"))["generated_at"] for name in version_files(tmp_path)}
    assert again == first


def test_sync_reads_the_market_side_of_a_split_repository(seeded_repo, tmp_path):
    """팀 DB 는 읽기만, 결과는 내 컴퓨터에 쓰는 구성(SplitRepository)에서도 팀 DB 쪽을 읽는다."""
    assert D.sync(SplitRepository(seeded_repo, object()), market_for(tmp_path))
    assert version_files(tmp_path)


def test_sync_keeps_what_is_there_when_the_database_cannot_be_read(seeded_repo, tmp_path):
    D.sync(seeded_repo, market_for(tmp_path))
    before = version_files(tmp_path)

    class Broken:
        @property
        def engine(self):
            raise OSError("db is down")

    assert D.sync(Broken(), market_for(tmp_path)) == []  # 오류를 올리지 않는다 (사전을 못 맞춘 것이 서버를 멈출 일은 아니다)
    assert version_files(tmp_path) == before


def test_sync_can_be_switched_off(seeded_repo, tmp_path, monkeypatch):
    assert D.sync(seeded_repo, market_for(tmp_path, descriptor_sync=False)) == [] and not version_files(tmp_path)
    assert AnalysisSettings.load().market.descriptor_sync is True
    monkeypatch.setenv("ANALYSIS_DESCRIPTOR_SYNC", "0")  # 사전을 고정해 두고 여러 번 돌리는 점검용
    assert AnalysisSettings.load().market.descriptor_sync is False


def test_load_says_what_to_do_when_there_is_no_descriptor_yet(tmp_path):
    with pytest.raises(DataMissing, match="팀 DB 에 연결하면 자동으로 만들어집니다"):
        D.load_for(AS_OF, UNIVERSES, processed_dir=tmp_path)


def test_the_server_syncs_when_it_opens_the_market_data(seeded_repo, tmp_path, monkeypatch):
    settings = AnalysisSettings()
    settings = replace_settings(settings, market=market_for(tmp_path / "descriptor"))

    def real_repo():
        return seeded_repo

    # 테스트가 꽂은 저장소: 사전 파일을 건드리지 않는다 (다른 테스트가 개발자의 backend/data/processed 를 덮어쓰지 않게)
    injected = Services(repo_factory=lambda: seeded_repo, store=JsonStore(tmp_path / "a"), settings=settings)
    injected.market_data()
    assert not (tmp_path / "descriptor").exists()

    # 실제 저장소(default_repo)로 켠 서버: 시장 자료를 여는 순간 맞춘다
    monkeypatch.setattr(services_module, "default_repo", real_repo)
    real = Services(repo_factory=real_repo, store=JsonStore(tmp_path / "b"), settings=settings)
    real.market_data()
    assert version_files(tmp_path / "descriptor")

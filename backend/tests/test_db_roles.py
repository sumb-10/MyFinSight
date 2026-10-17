"""backend/scripts/make_db_roles.py: 읽기·쓰기 계정 권한 (데이터 계약). SQL 출력은 DB 없이,
실제 적용은 MYFINSIGHT_TEST_PG_URL 이 있을 때만 (테스트 전용 DB, 계정 2개를 만듦)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from backend.db import open_repository
from backend.db import tables as T

_spec = importlib.util.spec_from_file_location(
    "make_db_roles", Path(__file__).resolve().parents[1] / "scripts" / "make_db_roles.py"
)
roles = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(roles)

PG_URL = os.environ.get("MYFINSIGHT_TEST_PG_URL", "")
SECRET = "Test_password_1234"


def test_print_sql_by_default_without_password(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYFINSIGHT_READ_PASSWORD", SECRET)
    monkeypatch.setenv("MYFINSIGHT_WRITE_PASSWORD", SECRET)
    assert roles.main([]) == 0
    out = capsys.readouterr().out
    assert SECRET not in out and "'***'" in out
    read_part, write_part = out.split("-- write 계정")
    tables = (
        "assets, index_constituent, price_daily, fx_daily, financials, news, fetch_log, "
        "valuation_daily, gics_taxonomy, disclosures"
    )
    assert f"GRANT SELECT ON {tables} TO myfinsight_read;" in read_part
    assert "INSERT" not in read_part and "DELETE" not in out
    grant = "GRANT SELECT, INSERT, UPDATE ON run_step, run_artifact, report TO myfinsight_write;"
    assert grant in write_part
    assert "price_daily_source" not in out and "financials_source" not in out


def test_read_tables_are_the_contract_tables() -> None:
    contract_read = {"assets", "index_constituent", "price_daily", "fx_daily", "financials", "news"}
    # + valuation_daily: 계약 밖이지만 분석 쪽이 읽는 수집기 발행 테이블 (읽기만)
    # + gics_taxonomy: GICS 분류표 참조 테이블 (종목 검색용 사전, 읽기만)
    assert set(roles.READ_TABLES) == contract_read | {
        "fetch_log",
        "valuation_daily",
        "gics_taxonomy",
        "disclosures",  # SEC EDGAR·DART 공시 목록 (읽기만)
    }
    assert set(roles.WRITE_TABLES) == {"run_step", "run_artifact", "report"}
    assert set(roles.READ_TABLES) | set(roles.WRITE_TABLES) <= set(T.metadata.tables)


@pytest.mark.skipif(not PG_URL, reason="MYFINSIGHT_TEST_PG_URL 없음")
def test_apply_on_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    eng = create_engine(PG_URL)
    T.metadata.drop_all(eng)
    eng.dispose()
    open_repository(PG_URL).engine.dispose()
    monkeypatch.setenv("MYFINSIGHT_READ_PASSWORD", SECRET)
    monkeypatch.setenv("MYFINSIGHT_WRITE_PASSWORD", SECRET)
    names = ["--reader", "test_contract_read", "--writer", "test_contract_write"]
    assert roles.main([PG_URL, "--apply", *names]) == 0
    assert roles.main([PG_URL, "--apply", *names]) == 0  # 다시 돌려도 같음
    url = create_engine(PG_URL).url
    writer = create_engine(url.set(username="test_contract_write", password=SECRET))
    with writer.begin() as c:
        c.execute(text("SELECT COUNT(*) FROM price_daily")).scalar_one()
        c.execute(
            text(
                "INSERT INTO run_artifact (run_id, request_id, created_at, results_json, "
                "params_json) VALUES ('r1', 'q1', now(), '{}', '{}')"
            )
        )
    for sql in ("DELETE FROM run_artifact", "SELECT COUNT(*) FROM price_daily_source"):
        with pytest.raises(DBAPIError), writer.begin() as c:
            c.execute(text(sql))
    writer.dispose()
    reader = create_engine(url.set(username="test_contract_read", password=SECRET))
    with pytest.raises(DBAPIError), reader.begin() as c:
        c.execute(text("SELECT COUNT(*) FROM run_artifact"))
    with reader.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM fetch_log")).scalar_one() >= 0
        # 분류표는 저장소가 열 때 채워 둠 (읽기 계정은 DB 만으로 GICS 코드·이름을 찾음, K3)
        assert c.execute(text("SELECT COUNT(*) FROM gics_taxonomy")).scalar_one() == 273
    reader.dispose()

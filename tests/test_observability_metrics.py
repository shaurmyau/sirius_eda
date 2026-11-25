from sqlalchemy import create_engine

from app.core.metrics import (
    DB_QUERY_DURATION,
    MENU_CACHE_OPERATIONS,
    classify_sql_operation,
    instrument_sqlalchemy_engine,
)


def _select_histogram_count() -> float:
    for family in DB_QUERY_DURATION.collect():
        for sample in family.samples:
            if sample.name.endswith("_count") and sample.labels == {"operation": "SELECT"}:
                return sample.value
    return 0.0


def test_classify_sql_operation_uses_bounded_labels():
    assert classify_sql_operation("SELECT * FROM menu_items") == "SELECT"
    assert classify_sql_operation("INSERT INTO orders VALUES (1)") == "INSERT"
    assert classify_sql_operation("WITH items AS (SELECT 1) SELECT * FROM items") == "OTHER"
    assert classify_sql_operation("") == "OTHER"


def test_sqlalchemy_engine_records_query_duration():
    engine = create_engine("sqlite:///:memory:")
    instrument_sqlalchemy_engine(engine)

    before = _select_histogram_count()
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        after = _select_histogram_count()
    finally:
        engine.dispose()

    assert after == before + 1


def _menu_cache_operation_count(result: str) -> float:
    for family in MENU_CACHE_OPERATIONS.collect():
        for sample in family.samples:
            if sample.name.endswith("_total") and sample.labels == {
                "operation": "read",
                "result": result,
            }:
                return sample.value
    return 0.0


def test_json_cache_fast_paths_record_hits_and_misses(monkeypatch):
    from app.modules.menu import repository as menu_repository

    repo = menu_repository.SqlMenuRepository(db=None)

    before_hits = _menu_cache_operation_count("hit")
    monkeypatch.setattr(menu_repository.redis_client, "get", lambda key: '{"items":[]}')
    assert repo.get_all_json() == '{"items":[]}'
    assert repo.get_category_json("food") == '{"items":[]}'
    assert _menu_cache_operation_count("hit") == before_hits + 2

    before_misses = _menu_cache_operation_count("miss")
    monkeypatch.setattr(menu_repository.redis_client, "get", lambda key: None)
    assert repo.get_all_json() is None
    assert repo.get_category_json("drink") is None
    assert _menu_cache_operation_count("miss") == before_misses + 2


def test_json_cache_fast_path_records_redis_errors(monkeypatch):
    from app.modules.menu import repository as menu_repository

    repo = menu_repository.SqlMenuRepository(db=None)
    before_errors = _menu_cache_operation_count("error")

    def fail_get(key):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(menu_repository.redis_client, "get", fail_get)
    assert repo.get_all_json() is None
    assert _menu_cache_operation_count("error") == before_errors + 1

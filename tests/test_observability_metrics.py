from sqlalchemy import create_engine

from app.core.metrics import (
    DB_QUERY_DURATION,
    classify_sql_operation,
    instrument_sqlalchemy_engine,
)


def test_classify_sql_operation_uses_bounded_labels():
    assert classify_sql_operation("SELECT * FROM menu_items") == "SELECT"
    assert classify_sql_operation("INSERT INTO orders VALUES (1)") == "INSERT"
    assert classify_sql_operation("WITH items AS (SELECT 1) SELECT * FROM items") == "OTHER"
    assert classify_sql_operation("") == "OTHER"


def test_sqlalchemy_engine_records_query_duration():
    engine = create_engine("sqlite:///:memory:")
    instrument_sqlalchemy_engine(engine)

    before = DB_QUERY_DURATION.labels(operation="SELECT")._count.get()
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        after = DB_QUERY_DURATION.labels(operation="SELECT")._count.get()
    finally:
        engine.dispose()

    assert after == before + 1

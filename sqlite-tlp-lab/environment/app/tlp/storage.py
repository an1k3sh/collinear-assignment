from __future__ import annotations

import sqlite3

from .model import Case, Query, Rows, validate_case


def open_database(case: Case) -> sqlite3.Connection:
    validate_case(case)
    connection = sqlite3.connect(":memory:")
    try:
        for table in ("t", "u"):
            connection.execute(
                f"CREATE TABLE {table}(id INTEGER, k INTEGER, v INTEGER, tag TEXT)"
            )
            connection.executemany(
                f"INSERT INTO {table} VALUES (?, ?, ?, ?)", case["tables"][table]
            )
        connection.commit()
        return connection
    except Exception:
        connection.close()
        raise


def execute(connection: sqlite3.Connection, query: Query) -> Rows:
    return [list(row) for row in connection.execute(query.sql, query.params)]

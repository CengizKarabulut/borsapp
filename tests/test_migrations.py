from __future__ import annotations

import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path

from market_intelligence.persistence.postgres.migrations import (
    MigrationChecksumError,
    apply_migrations,
    discover,
)


class FakeCursor:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.row = None
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, params=None) -> None:
        normalized = " ".join(query.split()).casefold()
        if "select to_regclass" in normalized:
            self.row = ("schema_migrations" if self.connection.table_exists else None,)
        elif normalized.startswith("select version, checksum"):
            self.rows = sorted(self.connection.applied.items())
        elif "create table if not exists schema_migrations" in normalized:
            self.connection.table_exists = True
            self.connection.executed.append("bootstrap")
        elif normalized.startswith("insert into schema_migrations"):
            assert params is not None
            version, _name, checksum, *_duration = params
            self.connection.applied.setdefault(str(version), str(checksum))
        else:
            self.connection.executed.append(query.strip())

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self) -> None:
        self.table_exists = False
        self.applied: dict[str, str] = {}
        self.executed: list[str] = []

    def cursor(self):
        return FakeCursor(self)

    def transaction(self):
        return nullcontext()


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        (self.directory / "000_migrations.sql").write_text(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version text);",
            encoding="utf-8",
        )
        (self.directory / "002_second.sql").write_text(
            "CREATE TABLE second_table (id int);",
            encoding="utf-8",
        )
        (self.directory / "001_first.sql").write_text(
            "CREATE TABLE first_table (id int);",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_discover_uses_numeric_version_order(self) -> None:
        self.assertEqual(
            [migration.version for migration in discover(self.directory)],
            ["000", "001", "002"],
        )

    def test_second_apply_is_noop(self) -> None:
        connection = FakeConnection()
        first = apply_migrations(connection, self.directory)
        second = apply_migrations(connection, self.directory)

        self.assertEqual(first.applied, ("000", "001", "002"))
        self.assertEqual(second.applied, ())
        self.assertEqual(second.skipped, ("000", "001", "002"))

    def test_changed_applied_migration_fails_closed(self) -> None:
        connection = FakeConnection()
        apply_migrations(connection, self.directory)
        path = self.directory / "001_first.sql"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

        with self.assertRaises(MigrationChecksumError):
            apply_migrations(connection, self.directory)

    def test_crlf_checkout_to_lf_preserves_applied_sql(self):
        path = self.directory / "001_first.sql"
        path.write_bytes(b"CREATE TABLE first_table (id int);\r\n")
        connection = FakeConnection()
        apply_migrations(connection, self.directory)
        recorded = dict(connection.applied)
        path.write_bytes(b"CREATE TABLE first_table (id int);\n")
        self.assertEqual(apply_migrations(connection, self.directory).applied, ())
        self.assertEqual(recorded, connection.applied)
        path.write_bytes(b"CREATE TABLE different_table (id int);\n")
        with self.assertRaises(MigrationChecksumError):
            apply_migrations(connection, self.directory)

    def test_dry_run_does_not_create_schema_objects(self) -> None:
        connection = FakeConnection()
        result = apply_migrations(connection, self.directory, dry_run=True)

        self.assertEqual(result.pending, ("000", "001", "002"))
        self.assertFalse(connection.table_exists)
        self.assertEqual(connection.executed, [])


if __name__ == "__main__":
    unittest.main()

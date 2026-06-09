#!/usr/bin/env python3
"""Apply qqq_test PostgreSQL schema migrations."""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = BASE_DIR / "db" / "migrations"

sys.path.insert(0, str(BASE_DIR))

from database import connect, get_database_url  # noqa: E402


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str
    checksum: str


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_migrations() -> list[Migration]:
    """Load ordered migration files from db/migrations."""
    migrations: list[Migration] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        sql = path.read_text(encoding="utf-8")
        if not sql.strip():
            raise RuntimeError(f"Empty migration file: {path}")
        migrations.append(Migration(version=version, path=path, sql=sql, checksum=_checksum(sql)))
    if not migrations:
        raise RuntimeError(f"No migration files found in {MIGRATIONS_DIR}")
    return migrations


def ensure_migration_table(conn) -> None:
    """Create the migration tracking table before applying project migrations."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def load_applied_migrations(conn) -> dict[str, str]:
    """Return already-applied migrations as version -> checksum."""
    rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    return {version: checksum for version, checksum in rows}


def apply_migrations(database_url: str | None = None) -> list[str]:
    """Apply pending migrations and return the versions applied in this run."""
    migrations = load_migrations()
    applied_versions: list[str] = []
    with connect(database_url, autocommit=False) as conn:
        ensure_migration_table(conn)
        applied = load_applied_migrations(conn)
        for migration in migrations:
            current_checksum = applied.get(migration.version)
            if current_checksum == migration.checksum:
                continue
            if current_checksum and current_checksum != migration.checksum:
                raise RuntimeError(
                    f"Migration {migration.version} was already applied with checksum {current_checksum}, "
                    f"but file now has checksum {migration.checksum}"
                )
            print(f"[db_migrate] applying {migration.version}")
            conn.execute(migration.sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (migration.version, migration.checksum),
            )
            applied_versions.append(migration.version)
        conn.commit()
    return applied_versions


def dry_run() -> None:
    """Print migration files and whether DATABASE_URL is configured without connecting."""
    migrations = load_migrations()
    database_url = get_database_url(required=False)
    print(f"[db_migrate] migrations_dir={MIGRATIONS_DIR}")
    print(f"[db_migrate] database_url_configured={bool(database_url)}")
    for migration in migrations:
        rel_path = migration.path.relative_to(BASE_DIR)
        print(f"[db_migrate] found {migration.version} {rel_path} sha256={migration.checksum[:12]}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply qqq_test PostgreSQL migrations.")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL for this run.")
    parser.add_argument("--dry-run", action="store_true", help="Validate migration files without connecting to PostgreSQL.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        dry_run()
        return 0
    applied = apply_migrations(args.database_url)
    if applied:
        print(f"[db_migrate] applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        print("[db_migrate] database already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

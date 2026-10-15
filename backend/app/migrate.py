"""Pinned AQ adapter: one PostgreSQL transaction including migration history."""
import re
from pathlib import Path
import psycopg2
from aq_dbmigration import DBMigration, DBConstant, MigrationConfig
from .config import ROOT, settings

DIRECTORY = ROOT / 'backend' / 'resource' / 'db_migration'
LOCK = 7367281301


def validate_files(directory: Path):
    files = list(directory.glob('*.sql'))
    versions = []
    if not (directory / 'V1__init.sql').is_file():
        raise RuntimeError('Missing V1__init.sql')
    for path in files:
        match = re.fullmatch(r'V([1-9][0-9]*)__[a-z0-9_]+\.sql', path.name)
        if not match:
            raise RuntimeError(f'Invalid migration name: {path.name}')
        versions.append(int(match[1]))
        if "'" in str(path):
            raise RuntimeError('Migration path cannot contain single quotes')
        content = path.read_text(encoding='utf-8')
        if re.search(r'^\s*(BEGIN|COMMIT|ROLLBACK|END)\s*;', content, re.M | re.I):
            raise RuntimeError('Migration transaction control belongs to the runner')
    if len(set(versions)) != len(versions):
        raise RuntimeError('Duplicate migration versions')
    return files


class AtomicMigration(DBMigration):
    # AQ 1.0.2 has private hooks; tests cover these overrides. Upgrade deliberately.
    def _DBMigration__init_conn(self):
        url = settings().database
        self.conn = psycopg2.connect(dbname=url.database, user=url.username, password=url.password,
                                     host=url.host, port=url.port or 5432,
                                     **{'connect_timeout': 10, **dict(url.query)})
        with self.conn.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '60s'")
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))

    def _DBMigration__execute_sql(self, sql, params=None):
        with self.conn.cursor() as cursor:
            cursor.execute(sql, params)

    def _DBMigration__close_conn(self):
        pass  # outer runner owns commit / rollback / close


def migrate(directory=DIRECTORY):
    directory = Path(directory).resolve()
    files = validate_files(directory)
    url = settings().database
    config = MigrationConfig(url.database, url.username, url.password, url.host,
                             url.port or 5432, DBConstant.Type.PostgreSQL, str(directory), base_line=0)
    migration = AtomicMigration.__new__(AtomicMigration)
    migration.conn = None
    try:
        migration.__init__(config)
        with migration.conn.cursor() as cursor:
            cursor.execute("SELECT file_path, sequence FROM migration.aq_db_migration WHERE file_path <> %s", (DBConstant.BASE_LINE,))
            history = cursor.fetchall()
        paths = {str(p) for p in files}
        if any(path not in paths for path, _ in history):
            raise RuntimeError('Migration path changed or historical SQL is missing; refusing replay')
        installed = {path for path, _ in history}
        maximum = max((int(version) for _, version in history), default=0)
        if any(int(p.name.split('__')[0][1:]) <= maximum and str(p) not in installed for p in files):
            raise RuntimeError('Out-of-order migration; add a higher version')
        migration.migration()
        migration.conn.commit()
    except Exception:
        if migration.conn is not None:
            migration.conn.rollback()
        raise
    finally:
        if migration.conn is not None:
            migration.conn.close()


if __name__ == '__main__':
    migrate()

import shutil
import pytest
from app.migrate import migrate, DIRECTORY, validate_files
from app.db import engine, one, run


def test_migration_repeat_does_not_reapply(system):
    migrate()
    with engine().begin() as db:
        assert one(db,'SELECT count(*) AS n FROM migration.aq_db_migration')['n']==1+len(list(DIRECTORY.glob('*.sql')))


def test_path_change_rejected(system,tmp_path):
    for path in DIRECTORY.glob('*.sql'):
        shutil.copy(path,tmp_path/path.name)
    with pytest.raises(RuntimeError,match='path changed'):
        migrate(tmp_path)


def test_migration_sql_and_history_rollback_together(system,tmp_path):
    with engine().begin() as db:
        run(db,'DROP SCHEMA migration CASCADE')
        run(db,'DROP SCHEMA public CASCADE')
        run(db,'CREATE SCHEMA public')
    (tmp_path/'V1__init.sql').write_text('CREATE TABLE should_rollback(id integer);',encoding='utf-8')
    (tmp_path/'V2__failure.sql').write_text('SELECT missing_column FROM should_rollback;',encoding='utf-8')
    with pytest.raises(Exception): migrate(tmp_path)
    with engine().begin() as db:
        assert one(db,"SELECT to_regclass('public.should_rollback') AS name")['name'] is None
        assert one(db,"SELECT to_regnamespace('migration') AS name")['name'] is None


def test_duplicate_version_preflight(tmp_path):
    (tmp_path/'V1__init.sql').write_text('SELECT 1;',encoding='utf-8')
    (tmp_path/'V1__other.sql').write_text('SELECT 2;',encoding='utf-8')
    with pytest.raises(RuntimeError,match='Duplicate'): validate_files(tmp_path)


def test_incremental_sql_and_checksum(system,tmp_path):
    with engine().begin() as db:
        run(db,'DROP SCHEMA migration CASCADE')
        run(db,'DROP SCHEMA public CASCADE')
        run(db,'CREATE SCHEMA public')
    initial=tmp_path/'V1__init.sql'
    initial.write_text('CREATE TABLE example(id integer);',encoding='utf-8')
    migrate(tmp_path)
    (tmp_path/'V2__add_value.sql').write_text('ALTER TABLE example ADD COLUMN name text; INSERT INTO example VALUES (1, \'ok\');',encoding='utf-8')
    migrate(tmp_path)
    migrate(tmp_path)
    with engine().begin() as db:
        assert one(db,'SELECT count(*) AS n FROM example')['n']==1
        assert one(db,'SELECT name FROM example')['name']=='ok'
    initial.write_text('CREATE TABLE example(id bigint);',encoding='utf-8')
    with pytest.raises(Exception,match='check value error'): migrate(tmp_path)

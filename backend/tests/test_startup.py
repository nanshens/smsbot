import pytest
from fastapi.testclient import TestClient
from app import main
from app.db import engine, run, one


def test_startup_migrates_empty_database_before_scheduler(system, monkeypatch):
    with engine().begin() as db:
        run(db, 'DROP SCHEMA migration CASCADE')
        run(db, 'DROP SCHEMA public CASCADE')
        run(db, 'CREATE SCHEMA public')
    starts, stops = [], []
    class Scheduler:
        def shutdown(self, wait=True):
            stops.append(wait)
    def start():
        with engine().begin() as db:
            assert one(db, "SELECT to_regclass('public.sim_api_keys') AS name")['name']
        starts.append(True)
        return Scheduler()
    monkeypatch.setattr(main, 'start_scheduler', start)
    for _ in range(2):
        with TestClient(main.app) as client:
            assert client.get('/api/health').status_code == 200
    assert starts == [True, True]
    assert stops == [True, True]


def test_failed_migration_prevents_scheduler_and_startup(monkeypatch):
    def fail():
        raise RuntimeError('migration failed')
    def forbidden():
        pytest.fail('Scheduler must not start after migration failure')
    monkeypatch.setattr(main, 'migrate', fail)
    monkeypatch.setattr(main, 'start_scheduler', forbidden)
    with pytest.raises(RuntimeError, match='migration failed'):
        with TestClient(main.app):
            pytest.fail('Application must not become ready')

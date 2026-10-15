import threading
from fastapi.testclient import TestClient
from app import main, worker
from app.scheduler import guarded


def test_lifespan_jobs_run_without_blocking_api_and_stop(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    maintained = threading.Event()

    def forwarding():
        entered.set()
        assert release.wait(5)
        finished.set()

    monkeypatch.setattr(worker, 'forward_once', forwarding)
    monkeypatch.setattr(worker, 'maintenance', maintained.set)
    with TestClient(main.app) as client:
        scheduler = main.app.state.scheduler
        assert scheduler.running
        assert scheduler.get_job('forwarding').max_instances == 1
        assert scheduler.get_job('maintenance').trigger.interval.total_seconds() == 30
        scheduler.reschedule_job('forwarding', trigger='interval', seconds=0.05)
        scheduler.reschedule_job('maintenance', trigger='interval', seconds=0.05)
        try:
            assert entered.wait(3)
            assert client.get('/not-an-endpoint').status_code == 404
            assert maintained.wait(3)  # Cleanup isn't blocked by notification I/O.
        finally:
            release.set()
    assert finished.is_set()
    assert not scheduler.running
    # A fresh lifespan creates a fresh scheduler, including during reload.
    with TestClient(main.app):
        assert main.app.state.scheduler is not scheduler
        assert main.app.state.scheduler.running
    assert not main.app.state.scheduler.running


def test_scheduler_failure_is_sanitized_and_next_call_can_run(caplog):
    def fail():
        raise RuntimeError('secret-provider-token')
    guarded(fail)
    assert 'RuntimeError' in caplog.text
    assert 'secret-provider-token' not in caplog.text
    ran = []
    guarded(lambda: ran.append(True))
    assert ran == [True]

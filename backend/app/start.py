"""Container entry point: bounded DB readiness, atomic migrations, supervisor."""
import os
import time
from .config import settings
from .db import engine
from .migrate import migrate


def main():
    settings()
    for attempt in range(12):
        try:
            with engine().connect() as db:
                db.exec_driver_sql('SELECT 1')
            break
        except Exception:
            if attempt == 11:
                raise SystemExit('Database unavailable after bounded retries') from None
            time.sleep(5)
    try:
        migrate()
    except Exception as exc:
        raise SystemExit('Migration failed (' + type(exc).__name__ + '); application not started') from None
    os.execvp('supervisord', ['supervisord', '-n', '-c', '/app/deploy/supervisord.conf'])


if __name__ == '__main__':
    main()

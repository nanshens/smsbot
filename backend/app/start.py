"""Container entry point: DB readiness and supervisor; FastAPI owns migrations."""
import os
import time
from .config import settings
from .db import engine


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
    os.execvp('supervisord', ['supervisord', '-n', '-c', '/app/deploy/supervisord.conf'])


if __name__ == '__main__':
    main()

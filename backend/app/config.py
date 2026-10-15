from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

from cryptography.fernet import Fernet
from dotenv import dotenv_values
from sqlalchemy.engine import make_url, URL

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database: URL
    app_secret: str
    encryption_key: str
    origin: str
    cookie_secure: bool
    poll_ms: int
    heartbeat_ms: int
    allow_private_notifications: bool


@lru_cache
def settings() -> Settings:
    values = {**dotenv_values(ROOT / '.env', interpolate=False), **os.environ}

    def required(name):
        value = values.get(name, '')
        if not value or value.startswith('REPLACE_'):
            raise RuntimeError(f'{name} must be configured')
        return value

    url = make_url(required('DATABASE_URL'))
    if url.get_backend_name() != 'postgresql' or url.username or url.password:
        raise RuntimeError('DATABASE_URL must be PostgreSQL without credentials')
    if not url.host or not url.database:
        raise RuntimeError('DATABASE_URL needs a host and database')
    allowed = {'sslmode', 'sslrootcert', 'sslcert', 'sslkey', 'connect_timeout', 'application_name'}
    if set(url.query) - allowed:
        raise RuntimeError('Unsupported DATABASE_URL parameters')
    url = url.set(drivername='postgresql+psycopg', username=required('DATABASE_USER'), password=required('DATABASE_PASSWORD'))
    key = required('CREDENTIAL_ENCRYPTION_KEY')
    Fernet(key.encode())
    secret = required('APP_SECRET')
    if len(secret) < 32:
        raise RuntimeError('APP_SECRET must contain at least 32 characters')
    origin = values.get('APP_ORIGIN', 'http://localhost:5173').rstrip('/')
    secure = values.get('COOKIE_SECURE', 'true').lower() == 'true'
    if not origin.startswith(('https://', 'http://')):
        raise RuntimeError('APP_ORIGIN must be an HTTP(S) origin')
    return Settings(url, secret, key, origin, secure,
                    max(1000, int(values.get('DEVICE_POLL_MS', '1000'))),
                    max(10000, int(values.get('DEVICE_HEARTBEAT_MS', '30000'))),
                    values.get('ALLOW_PRIVATE_NOTIFICATIONS', 'false').lower() == 'true')

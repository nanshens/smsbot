import os
from uuid import uuid4
import pytest
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url


@pytest.fixture
def system(monkeypatch):
    url = os.environ.get('SMSBOT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set SMSBOT_TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test')
    parsed = make_url(url)
    if not parsed.database or not parsed.database.endswith('_test'):
        pytest.fail('Refusing to clear a database whose name does not end in _test')
    monkeypatch.setenv('DATABASE_URL', parsed.set(username=None, password=None).render_as_string(hide_password=False))
    # URL.set(None) keeps existing credentials; require a credential-free test URL.
    if parsed.username or parsed.password:
        pytest.fail('Use credential-free SMSBOT_TEST_DATABASE_URL and separate SMSBOT_TEST_DATABASE_USER/PASSWORD')
    monkeypatch.setenv('DATABASE_USER', os.environ.get('SMSBOT_TEST_DATABASE_USER', 'smsbot_test'))
    monkeypatch.setenv('DATABASE_PASSWORD', os.environ.get('SMSBOT_TEST_DATABASE_PASSWORD', 'test-only'))
    monkeypatch.setenv('APP_SECRET', 'test-only-secret-that-is-not-used-outside-tests-0000')
    monkeypatch.setenv('CREDENTIAL_ENCRYPTION_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('APP_ORIGIN', 'http://testserver')
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    from app.config import settings
    from app.db import engine, run
    settings.cache_clear()
    if engine.cache_info().currsize:
        engine().dispose()
    engine.cache_clear()
    with engine().begin() as db:
        run(db, 'DROP SCHEMA IF EXISTS migration CASCADE')
        run(db, 'DROP SCHEMA public CASCADE')
        run(db, 'CREATE SCHEMA public')
    from app.migrate import migrate
    migrate()
    yield
    engine().dispose()
    engine.cache_clear()
    settings.cache_clear()


@pytest.fixture
def client(system):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        client.headers['origin'] = 'http://testserver'
        yield client


@pytest.fixture
def admin(client):
    import pyotp
    from app.db import engine, run
    from app.security import hasher, encrypt
    secret = pyotp.random_base32()
    with engine().begin() as db:
        run(db, '''INSERT INTO users(id,username,password_hash,totp_secret_encrypted,totp_enabled)
            VALUES (:id,'tester',:password,:secret,true)''', id=uuid4(),
            password=hasher.hash('test-password-12345'), secret=encrypt(secret))
    response = client.post('/api/auth/login', json={'username':'tester','password':'test-password-12345','code':pyotp.TOTP(secret).now()})
    assert response.status_code == 200, response.text
    client.headers['x-csrf-token'] = response.json()['csrf']
    return client


@pytest.fixture
def paired(admin):
    code = admin.post('/api/pairing-codes').json()['code']
    payload = {'request_id':str(uuid4()),'pairing_code':code,'hardware_id':'AA:BB:CC:DD:EE:FF','iccid':'8986001234567890123','name':'Test card'}
    response = admin.post('/api/device/register',json=payload)
    assert response.status_code == 200, response.text
    return admin, response.json(), payload

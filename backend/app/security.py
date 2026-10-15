import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from uuid import uuid4
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
import pyotp
from .config import settings
from .db import one, run, engine

hasher = PasswordHasher()
DUMMY = hasher.hash('not-a-user-password')


def digest(value):
    return hmac.new(settings().app_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def encrypt(value):
    return Fernet(settings().encryption_key.encode()).encrypt(value.encode()).decode()


def decrypt(value):
    return Fernet(settings().encryption_key.encode()).decrypt(value.encode()).decode()


def password_ok(encoded, password):
    try:
        return hasher.verify(encoded or DUMMY, password)
    except (VerificationError, InvalidHashError):
        return False


def consume_totp(db, user, code):
    if not user['totp_secret_encrypted'] or not code:
        return False
    otp = pyotp.TOTP(decrypt(user['totp_secret_encrypted']))
    step = int(time.time()) // 30
    for candidate in (step, step - 1, step + 1):
        if hmac.compare_digest(otp.at(candidate * 30), code) and candidate > (user['last_totp_step'] or -1):
            run(db, 'UPDATE users SET last_totp_step=:step WHERE id=:id', step=candidate, id=user['id'])
            return True
    return False


def consume_factor(db, user, code):
    if consume_totp(db, user, code):
        return True
    result = run(db, '''UPDATE recovery_codes SET used_at=now()
        WHERE user_id=:id AND code_hash=:hash AND used_at IS NULL''', id=user['id'], hash=digest(code))
    return result.rowcount == 1


def throttle(bucket, limit=10, seconds=300):
    # Separate committed transaction: failed auth requests must not roll back counters.
    with engine().begin() as db:
        result = one(db, '''INSERT INTO auth_limits(bucket, failures, reset_at)
            VALUES (:bucket, 1, now() + make_interval(secs => :seconds))
            ON CONFLICT (bucket) DO UPDATE SET
              failures=CASE WHEN auth_limits.reset_at < now() THEN 1 ELSE auth_limits.failures+1 END,
              reset_at=CASE WHEN auth_limits.reset_at < now() THEN EXCLUDED.reset_at ELSE auth_limits.reset_at END
            RETURNING failures''', bucket=digest(bucket), seconds=seconds)
    if result['failures'] > limit:
        raise HTTPException(429, '尝试过于频繁，请稍后再试')


def csrf(token):
    return digest('csrf:' + token)


def new_session(db, response, user_id, scope):
    token = secrets.token_urlsafe(32)
    seconds = 43200 if scope == 'authenticated' else 600
    run(db, '''INSERT INTO sessions(id,user_id,token_hash,scope,expires_at)
        VALUES (:id,:user,:hash,:scope,now()+make_interval(secs => :seconds))''',
        id=uuid4(), user=user_id, hash=digest(token), scope=scope, seconds=seconds)
    response.set_cookie('smsbot_session', token, max_age=seconds, httponly=True,
                        secure=settings().cookie_secure, samesite='strict', path='/')
    return csrf(token)


def current(db, request: Request, setup=False):
    token = request.cookies.get('smsbot_session', '')
    record = one(db, '''SELECT s.id AS session_id,s.scope,u.* FROM sessions s
        JOIN users u ON u.id=s.user_id WHERE s.token_hash=:hash
        AND s.revoked_at IS NULL AND s.expires_at>now()''', hash=digest(token))
    if not record or (record['scope'] != 'authenticated' and not setup):
        raise HTTPException(401, '请重新登录')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if request.headers.get('origin') != settings().origin or not hmac.compare_digest(request.headers.get('x-csrf-token', ''), csrf(token)):
            raise HTTPException(403, '请求校验失败，请刷新后重试')
    return record


def device(db, request):
    header = request.headers.get('authorization', '')
    if not header.startswith('Bearer '):
        raise HTTPException(401, 'Invalid device key')
    if header.startswith('Bearer sms_sim_'):
        from .sim_api import authenticate
        key = authenticate(db, request)
        row = one(db, '''SELECT d.*,s.id AS sim_id FROM sim_cards s JOIN devices d ON d.id=s.device_id
            WHERE s.id=:id AND d.enabled AND d.key_revoked_at IS NULL''', id=key['sim_id'])
        if not row:
            raise HTTPException(401, 'Device not activated or disabled')
        return row
    row = one(db, '''SELECT d.*,s.id AS sim_id FROM devices d JOIN sim_cards s ON s.device_id=d.id
        WHERE d.api_key_hash=:hash AND d.key_revoked_at IS NULL AND d.enabled=true''', hash=digest(header[7:]))
    if not row:
        raise HTTPException(401, 'Invalid device key')
    return row


def audit(db, action, user=None, device_id=None, resource=None):
    run(db, '''INSERT INTO audit_events(id,user_id,device_id,action,resource_id)
        VALUES (:id,:user,:device,:action,:resource)''', id=uuid4(), user=user, device=device_id,
        action=action, resource=resource)

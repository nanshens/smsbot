import secrets
from uuid import uuid4
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from .db import connection, one, run
from .config import settings
from .schemas import Login, Factor, SecurityChange
from .security import (current, throttle, password_ok, consume_factor, consume_totp,
                       new_session, csrf, encrypt, decrypt, digest, audit, hasher)

router = APIRouter(prefix='/api/auth', tags=['auth'])


@router.post('/login')
def login(body: Login, request: Request, response: Response, db=Depends(connection, scope="function")):
    if request.headers.get('origin') != settings().origin:
        raise HTTPException(403, '登录来源无效')
    throttle('login-user:' + body.username, 15)
    throttle('login-ip:' + (request.client.host if request.client else 'unknown'), 60)
    user = one(db, 'SELECT * FROM users WHERE username=:name FOR UPDATE', name=body.username)
    if not password_ok(user['password_hash'] if user else None, body.password) or not user:
        raise HTTPException(401, '用户名、密码或验证码错误')
    if user['totp_enabled'] and not consume_factor(db, user, body.code):
        raise HTTPException(401, '用户名、密码或验证码错误')
    scope = 'authenticated' if user['totp_enabled'] else 'totp_setup'
    token = new_session(db, response, user['id'], scope)
    audit(db, 'login.' + scope, user=user['id'])
    return {'username': user['username'], 'scope': scope, 'csrf': token}


@router.get('/me')
def me(request: Request, db=Depends(connection, scope="function")):
    user = current(db, request, setup=True)
    return {'username': user['username'], 'scope': user['scope'],
            'csrf': csrf(request.cookies['smsbot_session'])}


@router.post('/logout')
def logout(request: Request, response: Response, db=Depends(connection, scope="function")):
    user = current(db, request, setup=True)
    run(db, 'UPDATE sessions SET revoked_at=now() WHERE id=:id', id=user['session_id'])
    response.delete_cookie('smsbot_session', path='/')
    return {'ok': True}


@router.post('/totp/setup')
def setup(request: Request, db=Depends(connection, scope="function")):
    auth = current(db, request, setup=True)
    user = one(db, 'SELECT * FROM users WHERE id=:id FOR UPDATE', id=auth['id'])
    if user['totp_enabled'] or auth['scope'] != 'totp_setup':
        raise HTTPException(409, '请先完成身份校验后重置二次验证')
    secret = decrypt(user['totp_secret_encrypted']) if user['totp_secret_encrypted'] else pyotp.random_base32()
    run(db, 'UPDATE users SET totp_secret_encrypted=:secret WHERE id=:id', secret=encrypt(secret), id=user['id'])
    return {'secret': secret, 'uri': pyotp.TOTP(secret).provisioning_uri(user['username'], issuer_name='SMSBot')}


def recovery_codes(db, user_id):
    run(db, 'DELETE FROM recovery_codes WHERE user_id=:id', id=user_id)
    codes = [secrets.token_hex(8) for _ in range(10)]
    for code in codes:
        run(db, 'INSERT INTO recovery_codes(id,user_id,code_hash) VALUES (:id,:user,:hash)',
            id=uuid4(), user=user_id, hash=digest(code))
    return codes


@router.post('/totp/confirm')
def confirm(body: Factor, request: Request, response: Response, db=Depends(connection, scope="function")):
    auth = current(db, request, setup=True)
    throttle('totp:' + str(auth['id']))
    user = one(db, 'SELECT * FROM users WHERE id=:id FOR UPDATE', id=auth['id'])
    if user['totp_enabled'] or auth['scope'] != 'totp_setup':
        raise HTTPException(409, '二次验证已经启用')
    if not consume_totp(db, user, body.code):
        raise HTTPException(400, '验证码错误或已使用')
    run(db, 'UPDATE users SET totp_enabled=true WHERE id=:id', id=user['id'])
    run(db, 'UPDATE sessions SET revoked_at=now() WHERE user_id=:id', id=user['id'])
    token = new_session(db, response, user['id'], 'authenticated')
    audit(db, 'totp.enabled', user=user['id'])
    return {'csrf': token, 'recovery_codes': recovery_codes(db, user['id'])}


@router.post('/security')
def security(body: SecurityChange, request: Request, response: Response, db=Depends(connection, scope="function")):
    auth = current(db, request)
    throttle('security:' + str(auth['id']))
    user = one(db, 'SELECT * FROM users WHERE id=:id FOR UPDATE', id=auth['id'])
    if not password_ok(user['password_hash'], body.password) or not consume_factor(db, user, body.code):
        raise HTTPException(400, '密码或验证码错误')
    run(db, 'UPDATE sessions SET revoked_at=now() WHERE user_id=:id', id=user['id'])
    if body.new_password:
        run(db, 'UPDATE users SET password_hash=:hash WHERE id=:id', id=user['id'], hash=hasher.hash(body.new_password))
        scope = 'authenticated'
        audit(db, 'password.changed', user=user['id'])
    else:
        run(db, 'UPDATE users SET totp_enabled=false,totp_secret_encrypted=NULL,last_totp_step=NULL WHERE id=:id', id=user['id'])
        run(db, 'DELETE FROM recovery_codes WHERE user_id=:id', id=user['id'])
        scope = 'totp_setup'
        audit(db, 'totp.reset', user=user['id'])
    return {'scope': scope, 'csrf': new_session(db, response, user['id'], scope)}

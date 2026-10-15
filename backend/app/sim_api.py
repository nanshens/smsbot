"""Manually issued SIM-scoped integration credentials, separate from modem keys."""
import secrets
from datetime import datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from .db import connection, one, run
from .security import current, digest, audit
from .schemas import Outgoing
from .admin import enqueue, list_messages, cancel_message, remove_incoming, remove_outgoing

management = APIRouter(prefix='/api/sims', tags=['SIM API key management'])
router = APIRouter(prefix='/api/v1/sim', tags=['SIM integration'])


def lock_sim(db, sim_id):
    if not one(db, 'SELECT id FROM sim_cards WHERE id=:id FOR NO KEY UPDATE', id=sim_id):
        raise HTTPException(404, '电话卡不存在')


@management.get('/{sim_id}/api-key')
def key_info(sim_id: UUID, request: Request, db=Depends(connection, scope='function')):
    current(db, request)
    if not one(db, 'SELECT id FROM sim_cards WHERE id=:id', id=sim_id):
        raise HTTPException(404, '电话卡不存在')
    key = one(db, 'SELECT key_hint,created_at,last_used_at FROM sim_api_keys WHERE sim_id=:id', id=sim_id)
    return {'active': bool(key), 'key': key}


def issue(db, sim_id, user, reset=False):
    lock_sim(db, sim_id)
    existing = one(db, 'SELECT sim_id FROM sim_api_keys WHERE sim_id=:id', id=sim_id)
    if bool(existing) != reset:
        raise HTTPException(409, '请先签发 Key' if reset else 'Key 已存在，请使用重置')
    key = 'sms_sim_' + secrets.token_urlsafe(32)
    run(db, '''INSERT INTO sim_api_keys(sim_id,key_hash,key_hint,created_by)
        VALUES (:id,:hash,:hint,:user) ON CONFLICT (sim_id) DO UPDATE SET
        key_hash=EXCLUDED.key_hash,key_hint=EXCLUDED.key_hint,created_by=EXCLUDED.created_by,
        created_at=now(),last_used_at=NULL''', id=sim_id, hash=digest(key), hint=key[:12]+'…'+key[-4:], user=user['id'])
    audit(db, 'sim.api_key.reset' if reset else 'sim.api_key.issued', user=user['id'], resource=sim_id)
    return {'sim_id': sim_id, 'api_key': key}


@management.post('/{sim_id}/api-key')
def create_key(sim_id: UUID, request: Request, db=Depends(connection, scope='function')):
    return issue(db, sim_id, current(db, request))


@management.post('/{sim_id}/api-key/reset')
def reset_key(sim_id: UUID, request: Request, db=Depends(connection, scope='function')):
    return issue(db, sim_id, current(db, request), reset=True)


@management.delete('/{sim_id}/api-key')
def delete_key(sim_id: UUID, request: Request, db=Depends(connection, scope='function')):
    user = current(db, request)
    lock_sim(db, sim_id)
    run(db, 'DELETE FROM sim_api_keys WHERE sim_id=:id', id=sim_id)
    audit(db, 'sim.api_key.deleted', user=user['id'], resource=sim_id)
    return {'ok': True}


def authenticate(db, request):
    header = request.headers.get('authorization', '')
    if not header.startswith('Bearer sms_sim_') or len(header) > 128:
        raise HTTPException(401, 'Invalid SIM API key', headers={'WWW-Authenticate': 'Bearer'})
    # Hold a row lock until request commit. Reset/delete waits for in-flight calls.
    key = one(db, '''SELECT sim_id,created_by FROM sim_api_keys
        WHERE key_hash=:hash FOR UPDATE''', hash=digest(header[7:]))
    if not key:
        raise HTTPException(401, 'Invalid SIM API key', headers={'WWW-Authenticate': 'Bearer'})
    run(db, 'UPDATE sim_api_keys SET last_used_at=now() WHERE sim_id=:id', id=key['sim_id'])
    return key


@router.get('')
def status(request: Request, db=Depends(connection, scope='function')):
    key = authenticate(db, request)
    return one(db, '''SELECT s.id,s.name,s.phone_number,s.iccid,s.operator_name,s.sim_status,
        s.network_status,s.signal_dbm,s.status_sampled_at,d.last_seen_at,
        coalesce(d.enabled AND d.key_revoked_at IS NULL AND d.last_seen_at>now()-interval '90 seconds',false) AS online
        FROM sim_cards s LEFT JOIN devices d ON d.id=s.device_id WHERE s.id=:id''', id=key['sim_id'])


@router.get('/messages/{kind}')
def messages(kind: Literal['incoming', 'outgoing'], request: Request,
             q: str = Query('', max_length=200), status: str = '',
             start: datetime | None = None, end: datetime | None = None,
             page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
             db=Depends(connection, scope='function')):
    key = authenticate(db, request)
    return list_messages(db, kind, key['sim_id'], q, status, start, end, page, size)


def scoped_message(db, key, kind, message_id):
    table = 'incoming_sms' if kind == 'incoming' else 'outgoing_sms'
    row = one(db, f'SELECT * FROM {table} WHERE id=:id AND sim_id=:sim AND deleted_at IS NULL',
              id=message_id, sim=key['sim_id'])
    if not row:
        raise HTTPException(404, '短信不存在')
    return row


@router.get('/messages/{kind}/{message_id}')
def detail(kind: Literal['incoming', 'outgoing'], message_id: UUID, request: Request,
           db=Depends(connection, scope='function')):
    return scoped_message(db, authenticate(db, request), kind, message_id)


class Send(Outgoing):
    # The credential selects the SIM; clients cannot override it.
    sim_id: None = None


@router.post('/messages/outgoing')
def send(body: Send, request: Request, db=Depends(connection, scope='function')):
    key = authenticate(db, request)
    payload = Outgoing(**body.model_dump(exclude={'sim_id'}), sim_id=key['sim_id'])
    return enqueue(db, payload, key['created_by'], key_namespace='api:'+str(key['sim_id'])+':')


@router.post('/messages/outgoing/{message_id}/cancel')
def cancel(message_id: UUID, request: Request, db=Depends(connection, scope='function')):
    key = authenticate(db, request)
    scoped_message(db, key, 'outgoing', message_id)
    return cancel_message(db, message_id)


@router.delete('/messages/{kind}/{message_id}')
def delete(kind: Literal['incoming', 'outgoing'], message_id: UUID, request: Request,
           db=Depends(connection, scope='function')):
    key = authenticate(db, request)
    scoped_message(db, key, kind, message_id)
    return (remove_incoming if kind == 'incoming' else remove_outgoing)(db, message_id, key['created_by'])

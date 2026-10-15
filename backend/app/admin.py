import json
import secrets
from datetime import datetime
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from .db import connection, one, rows, run
from .security import current, digest, fingerprint, encrypt, decrypt, audit, throttle
from .schemas import SimEdit, Bindings, Outgoing, Channel
from .channels import validate_channel, deliver, DeliveryError

router = APIRouter(prefix='/api', tags=['management'])


@router.get('/dashboard')
def dashboard(request: Request, db=Depends(connection, scope="function")):
    current(db, request)
    return one(db, '''SELECT
        (SELECT count(*) FROM sim_cards) AS sims,
        (SELECT count(*) FROM devices WHERE enabled AND key_revoked_at IS NULL AND last_seen_at>now()-interval '90 seconds') AS online,
        (SELECT count(*) FROM incoming_sms WHERE deleted_at IS NULL AND received_at>now()-interval '24 hours') AS incoming_today,
        (SELECT count(*) FROM outgoing_sms WHERE deleted_at IS NULL AND status IN ('pending','leased')) AS pending,
        (SELECT count(*) FROM forwarding_jobs WHERE status='failed') AS forwarding_failed''')


@router.get('/sims')
def sims(request: Request, db=Depends(connection, scope="function")):
    current(db, request)
    return rows(db, '''SELECT s.*,d.last_seen_at,d.firmware_version,d.queue_depth,d.last_error,
        coalesce(d.enabled AND d.key_revoked_at IS NULL AND d.last_seen_at>now()-interval '90 seconds',false) AS online,
        coalesce((SELECT json_agg(channel_id) FROM sim_channel_bindings WHERE sim_id=s.id),'[]'::json) AS channel_ids
        FROM sim_cards s LEFT JOIN devices d ON d.id=s.device_id ORDER BY s.created_at''')


@router.patch('/sims/{sim_id}')
def edit_sim(sim_id: UUID, body: SimEdit, request: Request, db=Depends(connection, scope="function")):
    user = current(db, request)
    if not run(db, 'UPDATE sim_cards SET name=:name,phone_number=:phone_number,notes=:notes WHERE id=:id', id=sim_id, **body.model_dump()).rowcount:
        raise HTTPException(404, '电话卡不存在')
    audit(db, 'sim.updated', user=user['id'], resource=sim_id)
    return {'ok': True}


@router.put('/sims/{sim_id}/channels')
def bindings(sim_id: UUID, body: Bindings, request: Request, db=Depends(connection, scope="function")):
    current(db, request)
    if not one(db, 'SELECT id FROM sim_cards WHERE id=:id FOR UPDATE', id=sim_id):
        raise HTTPException(404, '电话卡不存在')
    for cid in set(body.channel_ids):
        if not one(db, 'SELECT id FROM notification_channels WHERE id=:id AND deleted_at IS NULL', id=cid):
            raise HTTPException(400, '通道不存在')
    run(db, 'DELETE FROM sim_channel_bindings WHERE sim_id=:id', id=sim_id)
    for cid in set(body.channel_ids):
        run(db, 'INSERT INTO sim_channel_bindings(sim_id,channel_id) VALUES (:sim,:channel)', sim=sim_id, channel=cid)
    return {'ok': True}


@router.post('/pairing-codes')
def pairing(request: Request, db=Depends(connection, scope="function")):
    user = current(db, request)
    code = secrets.token_urlsafe(24)
    run(db, '''INSERT INTO pairing_codes(id,code_hash,created_by,expires_at)
        VALUES (:id,:hash,:user,now()+interval '30 minutes')''', id=uuid4(), hash=digest(code), user=user['id'])
    audit(db, 'pairing.created', user=user['id'])
    return {'code': code, 'expires_in': 1800}


@router.post('/devices/{device_id}/revoke')
def revoke(device_id: UUID, request: Request, db=Depends(connection, scope="function")):
    user = current(db, request)
    if not one(db, 'SELECT id FROM devices WHERE id=:id FOR UPDATE', id=device_id):
        raise HTTPException(404, '设备不存在')
    run(db, 'UPDATE devices SET enabled=false,key_revoked_at=now(),api_key_hash=NULL WHERE id=:id', id=device_id)
    run(db, "UPDATE outgoing_sms SET status='unknown' WHERE status='leased' AND sim_id IN (SELECT id FROM sim_cards WHERE device_id=:id)", id=device_id)
    run(db, "UPDATE send_attempts SET phase='unknown' WHERE device_id=:id AND phase IN ('claimed','submitting')", id=device_id)
    run(db, 'UPDATE sim_cards SET device_id=NULL WHERE device_id=:id', id=device_id)
    run(db, 'UPDATE device_registrations SET response_encrypted=NULL WHERE device_id=:id', id=device_id)
    audit(db, 'device.revoked', user=user['id'], resource=device_id)
    return {'ok': True}


def list_messages(db, kind, sim_id, q, status, start, end, page, size):
    table = 'incoming_sms' if kind == 'incoming' else 'outgoing_sms'
    time = 'received_at' if kind == 'incoming' else 'created_at'
    number = 'sender' if kind == 'incoming' else 'recipient'
    where = 'm.deleted_at IS NULL'
    params = {'limit': size, 'offset': (page-1)*size}
    if sim_id:
        where += ' AND m.sim_id=:sim'
        params['sim'] = sim_id
    if q:
        where += f' AND (m.body ILIKE :q OR m.{number} ILIKE :q)'
        params['q'] = '%' + q + '%'
    if start:
        where += f' AND m.{time}>=:start'
        params['start'] = start
    if end:
        where += f' AND m.{time}<=:end'
        params['end'] = end
    if status:
        if kind == 'incoming':
            where += ' AND EXISTS (SELECT 1 FROM forwarding_jobs f WHERE f.incoming_id=m.id AND f.status=:status)'
        else:
            where += ' AND m.status=:status'
        params['status'] = status
    count = one(db, f'SELECT count(*) AS n FROM {table} m WHERE {where}', **params)['n']
    items = rows(db, f'''SELECT m.*,s.name AS sim_name,s.phone_number AS sim_phone FROM {table} m
        JOIN sim_cards s ON s.id=m.sim_id WHERE {where} ORDER BY m.{time} DESC LIMIT :limit OFFSET :offset''', **params)
    result = []
    for item in items:
        entry = dict(item)
        if kind == 'incoming':
            entry['forwarding'] = rows(db, '''SELECT f.id,f.status,f.attempts,f.last_error,c.name AS channel_name
                FROM forwarding_jobs f JOIN notification_channels c ON c.id=f.channel_id WHERE f.incoming_id=:id''', id=item['id'])
        else:
            entry['attempts'] = rows(db, '''SELECT id,phase,claimed_at,reported_at,error_message,segment_results
                FROM send_attempts WHERE outgoing_id=:id ORDER BY claimed_at''', id=item['id'])
        result.append(entry)
    return {'items': result, 'total': count, 'page': page, 'size': size}


@router.get('/incoming')
def inbox(request: Request, sim_id: UUID | None = None, q: str = Query('', max_length=200),
          status: str = '', start: datetime | None = None, end: datetime | None = None,
          page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), db=Depends(connection, scope="function")):
    current(db, request)
    return list_messages(db, 'incoming', sim_id, q, status, start, end, page, size)


@router.get('/outgoing')
def outbox(request: Request, sim_id: UUID | None = None, q: str = Query('', max_length=200),
           status: str = '', start: datetime | None = None, end: datetime | None = None,
           page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), db=Depends(connection, scope="function")):
    current(db, request)
    return list_messages(db, 'outgoing', sim_id, q, status, start, end, page, size)


@router.post('/outgoing')
def create_outgoing(body: Outgoing, request: Request, db=Depends(connection, scope="function")):
    user = current(db, request)
    return enqueue(db, body, user['id'])


def enqueue(db, body, user_id, key_namespace=''):
    if not one(db, 'SELECT id FROM sim_cards WHERE id=:id', id=body.sim_id):
        raise HTTPException(404, '电话卡不存在')
    if body.retry_of and not one(db, "SELECT id FROM outgoing_sms WHERE id=:id AND sim_id=:sim AND status IN ('unknown','failed')", id=body.retry_of, sim=body.sim_id):
        raise HTTPException(400, '只能关联同一卡片的失败或结果未知记录')
    signature = fingerprint(body.model_dump(exclude={'idempotency_key'}))
    record = one(db, '''INSERT INTO outgoing_sms(id,sim_id,created_by,idempotency_key,request_fingerprint,recipient,body,retry_of)
        VALUES (:id,:sim,:user,:key,:fingerprint,:recipient,:body,:retry)
        ON CONFLICT DO NOTHING RETURNING id''', id=uuid4(), sim=body.sim_id,
        user=user_id, key=key_namespace + str(body.idempotency_key), fingerprint=signature, recipient=body.recipient, body=body.body, retry=body.retry_of)
    if not record:
        scope = 'sim_id=:sim' if key_namespace else 'created_by=:user'
        record = one(db, f'SELECT id,request_fingerprint FROM outgoing_sms WHERE {scope} AND idempotency_key=:key',
                     sim=body.sim_id, user=user_id, key=key_namespace + str(body.idempotency_key))
        if record['request_fingerprint'] != signature:
            raise HTTPException(409, '重复请求的内容不同')
    audit(db, 'outgoing.created', user=user_id, resource=record['id'])
    return {'id': record['id']}


@router.post('/outgoing/{message_id}/cancel')
def cancel(message_id: UUID, request: Request, db=Depends(connection, scope="function")):
    current(db, request)
    return cancel_message(db, message_id)


def cancel_message(db, message_id):
    if not run(db, "UPDATE outgoing_sms SET status='cancelled',completed_at=now() WHERE id=:id AND status='pending' AND deleted_at IS NULL", id=message_id).rowcount:
        raise HTTPException(409, '只能取消尚未领取的任务')
    return {'ok': True}


@router.delete('/incoming/{message_id}')
def delete_incoming(message_id: UUID, request: Request, db=Depends(connection, scope="function")):
    user = current(db, request)
    return remove_incoming(db, message_id, user['id'])


def remove_incoming(db, message_id, user_id):
    locked = one(db, 'SELECT pg_try_advisory_xact_lock(hashtextextended(:id,0)) AS ok', id=str(message_id))
    if not locked['ok']:
        raise HTTPException(409, '短信正在转发，请稍后删除')
    if not run(db, 'UPDATE incoming_sms SET deleted_at=now(),body=NULL,sender=NULL WHERE id=:id AND deleted_at IS NULL', id=message_id).rowcount:
        raise HTTPException(404, '短信不存在')
    run(db, "UPDATE forwarding_jobs SET status='cancelled',lease_token=NULL,lease_expires_at=NULL WHERE incoming_id=:id AND status IN ('pending','processing','failed')", id=message_id)
    audit(db, 'incoming.deleted', user=user_id, resource=message_id)
    return {'ok': True}


@router.delete('/outgoing/{message_id}')
def delete_outgoing(message_id: UUID, request: Request, db=Depends(connection, scope="function")):
    user = current(db, request)
    return remove_outgoing(db, message_id, user['id'])


def remove_outgoing(db, message_id, user_id):
    if not run(db, '''UPDATE outgoing_sms SET deleted_at=now(),body=NULL,recipient=NULL,last_error=NULL
        WHERE id=:id AND status IN ('sent','failed','cancelled') AND deleted_at IS NULL''', id=message_id).rowcount:
        raise HTTPException(409, '请先取消待发送任务；执行中或结果未知的记录不可删除')
    run(db, "UPDATE send_attempts SET error_message=NULL,segment_results='[]'::jsonb WHERE outgoing_id=:id", id=message_id)
    audit(db, 'outgoing.deleted', user=user_id, resource=message_id)
    return {'ok': True}


@router.get('/channels')
def channels(request: Request, db=Depends(connection, scope="function")):
    current(db, request)
    return rows(db, '''SELECT id,name,type,config,enabled,true AS has_credentials
        FROM notification_channels WHERE deleted_at IS NULL ORDER BY created_at''')


def save_channel(db, body, cid=None):
    old = one(db, 'SELECT * FROM notification_channels WHERE id=:id AND deleted_at IS NULL FOR UPDATE', id=cid) if cid else None
    if cid and not old:
        raise HTTPException(404, '通道不存在')
    if old and old['type'] != body.type:
        raise HTTPException(400, '通道类型不能更改，请新建通道')
    credentials = body.credentials or (json.loads(decrypt(old['credentials_encrypted'])) if old else None)
    try:
        config = validate_channel(body.type, body.config, credentials)
    except ValueError:
        raise HTTPException(400, '通道配置无效，请检查地址、邮箱和凭据') from None
    cid = cid or uuid4()
    run(db, '''INSERT INTO notification_channels(id,name,type,config,credentials_encrypted,enabled)
        VALUES (:id,:name,:type,CAST(:config AS jsonb),:credentials,:enabled)
        ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,config=EXCLUDED.config,
        credentials_encrypted=EXCLUDED.credentials_encrypted,enabled=EXCLUDED.enabled''', id=cid,
        name=body.name, type=body.type, config=json.dumps(config), credentials=encrypt(json.dumps(credentials)), enabled=body.enabled)
    if not body.enabled:
        run(db, "UPDATE forwarding_jobs SET status='cancelled' WHERE channel_id=:id AND status IN ('pending','failed')", id=cid)
    return {'id': cid}


@router.post('/channels')
def create_channel(body: Channel, request: Request, db=Depends(connection, scope="function")):
    user = current(db, request)
    result = save_channel(db, body)
    audit(db, 'channel.created', user=user['id'], resource=result['id'])
    return result


@router.patch('/channels/{channel_id}')
def edit_channel(channel_id: UUID, body: Channel, request: Request, db=Depends(connection, scope="function")):
    user = current(db, request)
    result = save_channel(db, body, channel_id)
    audit(db, 'channel.updated', user=user['id'], resource=channel_id)
    return result


@router.delete('/channels/{channel_id}')
def delete_channel(channel_id: UUID, request: Request, db=Depends(connection, scope="function")):
    user = current(db, request)
    if one(db, "SELECT id FROM forwarding_jobs WHERE channel_id=:id AND status='processing'", id=channel_id):
        raise HTTPException(409, '通道有转发任务正在执行，请稍后删除')
    run(db, 'UPDATE notification_channels SET deleted_at=now(),enabled=false,credentials_encrypted=:empty WHERE id=:id', id=channel_id, empty=encrypt('{}'))
    run(db, 'DELETE FROM sim_channel_bindings WHERE channel_id=:id', id=channel_id)
    run(db, "UPDATE forwarding_jobs SET status='cancelled' WHERE channel_id=:id AND status IN ('pending','failed')", id=channel_id)
    audit(db, 'channel.deleted', user=user['id'], resource=channel_id)
    return {'ok': True}


@router.post('/channels/{channel_id}/test')
def test_channel(channel_id: UUID, request: Request, db=Depends(connection, scope="function")):
    user = current(db, request)
    throttle('channel-test:' + str(user['id']), 10, 60)
    channel = one(db, 'SELECT * FROM notification_channels WHERE id=:id AND deleted_at IS NULL', id=channel_id)
    if not channel:
        raise HTTPException(404, '通道不存在')
    try:
        deliver(channel['type'], channel['config'], json.loads(decrypt(channel['credentials_encrypted'])),
                'SMSBot 测试通知', '通知通道已成功连接。')
    except DeliveryError as exc:
        raise HTTPException(400, str(exc)) from None
    return {'ok': True}


@router.post('/forwarding/{job_id}/retry')
def retry(job_id: UUID, request: Request, db=Depends(connection, scope="function")):
    current(db, request)
    result = run(db, '''UPDATE forwarding_jobs f SET status='pending',attempts=0,next_attempt_at=now(),last_error=NULL
        FROM notification_channels c,incoming_sms m WHERE f.id=:id AND f.channel_id=c.id AND f.incoming_id=m.id
        AND f.status='failed' AND c.enabled AND c.deleted_at IS NULL AND m.deleted_at IS NULL''', id=job_id)
    if not result.rowcount:
        raise HTTPException(409, '任务不可重试，请检查短信与通道状态')
    return {'ok': True}

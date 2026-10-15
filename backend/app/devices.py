import json
import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from .db import connection, one, rows, run
from .config import settings
from .schemas import Registration, Heartbeat, Incoming, Result, Activation
from .security import device, throttle, digest, fingerprint, encrypt, decrypt, audit

router = APIRouter(prefix='/api/device', tags=['device'])


@router.post('/activate')
def activate(body: Activation, request: Request, db=Depends(connection, scope='function')):
    from .sim_api import authenticate
    key = authenticate(db, request)
    run(db, 'SELECT pg_advisory_xact_lock(7367281302)')
    sim = one(db, 'SELECT * FROM sim_cards WHERE id=:id', id=key['sim_id'])
    dev = one(db, 'SELECT * FROM devices WHERE hardware_id=:hardware FOR UPDATE', hardware=body.hardware_id)
    if sim['iccid'] and sim['iccid'] != body.iccid:
        raise HTTPException(409, 'ICCID does not match this phone')
    if sim['device_id'] and (not dev or sim['device_id'] != dev['id']):
        raise HTTPException(409, 'Unbind the old device before moving this SIM')
    other = one(db, 'SELECT id FROM sim_cards WHERE iccid=:iccid AND id<>:id', iccid=body.iccid, id=sim['id'])
    if other:
        raise HTTPException(409, 'ICCID already belongs to another phone')
    if dev and one(db, 'SELECT id FROM sim_cards WHERE device_id=:device AND id<>:id', device=dev['id'], id=sim['id']):
        raise HTTPException(409, 'Device already belongs to another phone')
    did = dev['id'] if dev else uuid4()
    if dev:
        run(db, '''UPDATE devices SET api_key_hash=NULL,key_revoked_at=NULL,enabled=true,iccid=:iccid,
            firmware_version=:fw,modem_version=:modem,last_seen_at=now() WHERE id=:id''',
            id=did, iccid=body.iccid, fw=body.firmware_version, modem=body.modem_version)
        run(db, 'UPDATE device_registrations SET response_encrypted=NULL WHERE device_id=:id', id=did)
    else:
        run(db, '''INSERT INTO devices(id,hardware_id,name,iccid,firmware_version,modem_version,last_seen_at)
            VALUES (:id,:hardware,:name,:iccid,:fw,:modem,now())''', id=did, hardware=body.hardware_id,
            name=sim['name'], iccid=body.iccid, fw=body.firmware_version, modem=body.modem_version)
    run(db, 'UPDATE sim_cards SET device_id=:device,iccid=:iccid WHERE id=:id', id=sim['id'], device=did, iccid=body.iccid)
    audit(db, 'device.activated', device_id=did, resource=sim['id'])
    return {'device_id': did, 'sim_id': sim['id'], 'poll_interval_ms': settings().poll_ms,
            'heartbeat_interval_ms': settings().heartbeat_ms}


def card_check(dev, iccid):
    if dev['iccid'] != iccid:
        raise HTTPException(409, 'SIM changed; pair again')


@router.post('/register')
def register(body: Registration, request: Request, db=Depends(connection, scope="function")):
    throttle('register:' + (request.client.host if request.client else 'unknown'), 30)
    code = one(db, 'SELECT * FROM pairing_codes WHERE code_hash=:hash FOR UPDATE', hash=digest(body.pairing_code))
    if not code:
        raise HTTPException(401, 'Invalid pairing code')
    signature = fingerprint(body.model_dump(exclude={'pairing_code'}))
    old = one(db, 'SELECT * FROM device_registrations WHERE request_id=:id', id=body.request_id)
    if old:
        dev = one(db, 'SELECT * FROM devices WHERE id=:id', id=old['device_id'])
        if (old['pairing_code_id'] != code['id'] or old['request_fingerprint'] != signature
                or old['response_expires_at'] <= datetime.now(timezone.utc) or not old['response_encrypted']
                or dev['key_revoked_at'] or not dev['enabled'] or dev['iccid'] != body.iccid):
            raise HTTPException(409, 'Registration recovery expired or conflicting; use new pairing code')
        recovered = json.loads(decrypt(old['response_encrypted']))
        if digest(recovered['api_key']) != dev['api_key_hash']:
            raise HTTPException(409, 'Registration key was rotated; use the latest pairing')
        return recovered
    if code['consumed_at'] or code['expires_at'] <= datetime.now(timezone.utc):
        raise HTTPException(401, 'Pairing code used or expired')
    # Pairing is rare; a transaction lock avoids races on new hardware / ICCID rows.
    run(db, 'SELECT pg_advisory_xact_lock(7367281302)')
    dev = one(db, 'SELECT * FROM devices WHERE hardware_id=:hardware FOR UPDATE', hardware=body.hardware_id)
    sim = one(db, 'SELECT * FROM sim_cards WHERE iccid=:iccid FOR UPDATE', iccid=body.iccid)
    if sim and sim['device_id'] and (not dev or sim['device_id'] != dev['id']):
        raise HTTPException(409, 'Revoke the old device before moving this SIM')
    did = dev['id'] if dev else uuid4()
    sid = sim['id'] if sim else uuid4()
    key = secrets.token_urlsafe(32)
    if dev:
        run(db, "UPDATE outgoing_sms SET status='unknown' WHERE sim_id IN (SELECT id FROM sim_cards WHERE device_id=:id) AND status='leased'", id=did)
        run(db, "UPDATE send_attempts SET phase='unknown' WHERE device_id=:id AND phase IN ('claimed','submitting')", id=did)
        run(db, 'UPDATE sim_cards SET device_id=NULL WHERE device_id=:id', id=did)
        run(db, '''UPDATE devices SET api_key_hash=:key,key_revoked_at=NULL,enabled=true,iccid=:iccid,
            firmware_version=:fw,modem_version=:modem,last_seen_at=now() WHERE id=:id''',
            id=did, key=digest(key), iccid=body.iccid, fw=body.firmware_version, modem=body.modem_version)
    else:
        run(db, '''INSERT INTO devices(id,hardware_id,name,api_key_hash,iccid,firmware_version,modem_version,last_seen_at)
            VALUES (:id,:hardware,:name,:key,:iccid,:fw,:modem,now())''', id=did, hardware=body.hardware_id,
            name=body.name, key=digest(key), iccid=body.iccid, fw=body.firmware_version, modem=body.modem_version)
    if sim:
        run(db, 'UPDATE sim_cards SET device_id=:device WHERE id=:id', id=sid, device=did)
    else:
        run(db, 'INSERT INTO sim_cards(id,iccid,name,device_id) VALUES (:id,:iccid,:name,:device)',
            id=sid, iccid=body.iccid, name=body.name, device=did)
    payload = {'device_id': str(did), 'sim_id': str(sid), 'api_key': key,
               'poll_interval_ms': settings().poll_ms, 'heartbeat_interval_ms': settings().heartbeat_ms}
    run(db, 'UPDATE pairing_codes SET consumed_at=now(),consumed_by=:device WHERE id=:id', id=code['id'], device=did)
    run(db, '''INSERT INTO device_registrations(id,request_id,pairing_code_id,device_id,sim_id,
        request_fingerprint,response_encrypted,response_expires_at)
        VALUES (:id,:request,:pair,:device,:sim,:fingerprint,:response,now()+interval '24 hours')''',
        id=uuid4(), request=body.request_id, pair=code['id'], device=did, sim=sid,
        fingerprint=signature, response=encrypt(json.dumps(payload)))
    audit(db, 'device.paired', device_id=did, resource=sid)
    return payload


@router.post('/heartbeat')
def heartbeat(body: Heartbeat, request: Request, db=Depends(connection, scope="function")):
    dev = device(db, request)
    card_check(dev, body.iccid)
    run(db, 'UPDATE devices SET last_seen_at=now(),queue_depth=:depth,last_error=:error WHERE id=:id',
        id=dev['id'], depth=body.queue_depth, error=body.last_error)
    run(db, '''UPDATE sim_cards SET operator_name=:operator,sim_status=:sim,network_status=:network,
        signal_dbm=:signal,status_sampled_at=now() WHERE id=:id''', id=dev['sim_id'],
        operator=body.operator_name, sim=body.sim_status, network=body.network_status, signal=body.signal_dbm)
    return {'poll_interval_ms': settings().poll_ms, 'heartbeat_interval_ms': settings().heartbeat_ms}


@router.post('/incoming')
def incoming(body: Incoming, request: Request, db=Depends(connection, scope="function")):
    dev = device(db, request)
    card_check(dev, body.iccid)
    record = one(db, '''INSERT INTO incoming_sms(id,device_id,sim_id,event_id,sender,body,modem_received_at)
        VALUES (:id,:device,:sim,:event,:sender,:body,:received)
        ON CONFLICT (device_id,event_id) DO NOTHING RETURNING id''', id=uuid4(), device=dev['id'],
        sim=dev['sim_id'], event=body.event_id, sender=body.sender, body=body.body, received=body.modem_received_at)
    if not record:
        old = one(db, 'SELECT id FROM incoming_sms WHERE device_id=:device AND event_id=:event', device=dev['id'], event=body.event_id)
        return {'id': old['id'], 'duplicate': True}
    channels = rows(db, '''SELECT c.id FROM notification_channels c JOIN sim_channel_bindings b ON b.channel_id=c.id
        WHERE b.sim_id=:sim AND c.enabled AND c.deleted_at IS NULL''', sim=dev['sim_id'])
    for channel in channels:
        run(db, 'INSERT INTO forwarding_jobs(id,incoming_id,channel_id) VALUES (:id,:incoming,:channel)',
            id=uuid4(), incoming=record['id'], channel=channel['id'])
    return {'id': record['id'], 'duplicate': False}


@router.post('/outgoing/claim')
def claim(request: Request, response: Response, iccid: str, db=Depends(connection, scope="function")):
    dev = device(db, request)
    card_check(dev, iccid)
    # Serialize claims for one device, not the whole queue.
    run(db, 'SELECT id FROM devices WHERE id=:id FOR UPDATE', id=dev['id'])
    if one(db, "SELECT id FROM send_attempts WHERE device_id=:id AND phase IN ('claimed','submitting')", id=dev['id']):
        response.status_code = 204
        return
    message = one(db, '''SELECT * FROM outgoing_sms WHERE sim_id=:sim AND status='pending'
        AND deleted_at IS NULL ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1''', sim=dev['sim_id'])
    if not message:
        response.status_code = 204
        return
    attempt = uuid4()
    token = secrets.token_urlsafe(32)
    run(db, "UPDATE outgoing_sms SET status='leased' WHERE id=:id", id=message['id'])
    run(db, '''INSERT INTO send_attempts(id,outgoing_id,device_id,lease_token_hash,phase,lease_expires_at)
        VALUES (:id,:outgoing,:device,:hash,'claimed',now()+interval '15 minutes')''',
        id=attempt, outgoing=message['id'], device=dev['id'], hash=digest(token))
    return {'id': message['id'], 'attempt_id': attempt, 'lease_token': token,
            'recipient': message['recipient'], 'body': message['body'], 'iccid': iccid}


@router.post('/outgoing/{message_id}/result')
def result(message_id: UUID, body: Result, request: Request, db=Depends(connection, scope="function")):
    dev = device(db, request)
    card_check(dev, body.iccid)
    message = one(db, 'SELECT * FROM outgoing_sms WHERE id=:id AND sim_id=:sim FOR UPDATE', id=message_id, sim=dev['sim_id'])
    attempt = one(db, '''SELECT * FROM send_attempts WHERE id=:attempt AND outgoing_id=:message
        AND device_id=:device AND lease_token_hash=:hash FOR UPDATE''', attempt=body.attempt_id,
        message=message_id, device=dev['id'], hash=digest(body.lease_token))
    if not message or not attempt:
        raise HTTPException(404, 'Attempt not found')
    signature = fingerprint(body.model_dump(exclude={'lease_token'}))
    if attempt['result_fingerprint']:
        if attempt['result_fingerprint'] != signature:
            raise HTTPException(409, 'Conflicting result')
        return {'ok': True, 'duplicate': True}
    if message['status'] not in ('leased', 'unknown'):
        raise HTTPException(409, 'Message already finalized')
    status = 'pending' if body.status == 'not_sent' else body.status
    run(db, '''UPDATE send_attempts SET phase=:phase,reported_at=now(),result_fingerprint=:fingerprint,
        error_code=:code,error_message=:error,modem_reference=:reference,segment_results=CAST(:segments AS jsonb)
        WHERE id=:id''', id=body.attempt_id, phase=body.status, fingerprint=signature,
        code=body.error_code, error=body.error_message, reference=body.modem_reference,
        segments=json.dumps(body.segment_results))
    run(db, '''UPDATE outgoing_sms SET status=:status,last_error=:error,
        completed_at=CASE WHEN :completed THEN now() ELSE NULL END WHERE id=:id''',
        id=message_id, status=status, error=body.error_message, completed=status in ('sent','failed'))
    return {'ok': True, 'duplicate': False}

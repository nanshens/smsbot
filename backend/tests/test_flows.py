from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from app.db import engine, one, run
from app.security import digest


def headers(identity):
    return {'Authorization': 'Bearer ' + identity['api_key']}


def message(identity, iccid, event=None):
    return {'iccid':iccid,'event_id':event or str(uuid4()),'sender':'+8613800000000','body':'您的验证码是 123456。'}


def create_outgoing(client, identity):
    body = {'sim_id':identity['sim_id'],'recipient':'+8613800000000','body':'Hello 你好','idempotency_key':str(uuid4())}
    response = client.post('/api/outgoing',json=body)
    assert response.status_code == 200, response.text
    return response.json()['id'],body


def add_channel(client, sid):
    response = client.post('/api/channels',json={'name':'Test','type':'bark','config':{'server':'https://api.day.app'},'credentials':{'key':'test-provider-secret'}})
    assert response.status_code==200,response.text
    cid=response.json()['id']
    assert client.put(f'/api/sims/{sid}/channels',json={'channel_ids':[cid]}).status_code==200
    return cid


def test_auth_required(client):
    assert client.get('/api/sims').status_code == 401
    assert client.get('/api/openapi.json').status_code == 401


def test_setup_cannot_access_management(client):
    import pyotp
    from app.security import hasher
    with engine().begin() as db:
        run(db,'INSERT INTO users(id,username,password_hash) VALUES (:id,:name,:password)',id=uuid4(),name='new',password=hasher.hash('new-password-12345'))
    response=client.post('/api/auth/login',json={'username':'new','password':'new-password-12345'})
    assert response.status_code==200
    client.headers['x-csrf-token']=response.json()['csrf']
    assert client.get('/api/sims').status_code==401
    setup=client.post('/api/auth/totp/setup').json()
    result=client.post('/api/auth/totp/confirm',json={'code':pyotp.TOTP(setup['secret']).now()})
    assert result.status_code==200,result.text
    assert len(result.json()['recovery_codes'])==10
    code=result.json()['recovery_codes'][0]
    assert client.get('/api/sims').status_code==200
    client.cookies.clear()
    assert client.post('/api/auth/login',json={'username':'new','password':'new-password-12345','code':code}).status_code==200
    client.cookies.clear()
    assert client.post('/api/auth/login',json={'username':'new','password':'new-password-12345','code':code}).status_code==401


def test_csrf_and_origin(admin):
    assert admin.post('/api/pairing-codes',headers={'x-csrf-token':'bad'}).status_code==403
    assert admin.post('/api/pairing-codes',headers={'origin':'https://evil.example'}).status_code==403
    assert admin.post('/api/auth/logout').status_code==200
    assert admin.get('/api/sims').status_code==401


def test_invalid_login_throttled(client):
    for _ in range(15):
        assert client.post('/api/auth/login',json={'username':'none','password':'wrong'}).status_code==401
    assert client.post('/api/auth/login',json={'username':'none','password':'wrong'}).status_code==429


def test_registration_response_recovery(paired):
    client,identity,payload=paired
    assert client.post('/api/device/register',json=payload).json()['api_key']==identity['api_key']
    changed={**payload,'hardware_id':'another-device'}
    assert client.post('/api/device/register',json=changed).status_code==409
    with engine().begin() as db:
        key=one(db,'SELECT api_key_hash FROM devices')['api_key_hash']
        assert key != identity['api_key']


def test_incoming_idempotency_and_deletion(paired):
    client,identity,payload=paired
    add_channel(client,identity['sim_id'])
    data=message(identity,payload['iccid'])
    first=client.post('/api/device/incoming',json=data,headers=headers(identity))
    second=client.post('/api/device/incoming',json=data,headers=headers(identity))
    assert first.status_code==second.status_code==200
    assert second.json()['duplicate']
    with engine().begin() as db:
        assert one(db,'SELECT count(*) AS n FROM forwarding_jobs')['n']==1
    mid=first.json()['id']
    assert client.delete(f'/api/incoming/{mid}').status_code==200
    assert client.post('/api/device/incoming',json=data,headers=headers(identity)).json()['id']==mid
    assert client.get('/api/incoming').json()['total']==0
    with engine().begin() as db:
        assert one(db,'SELECT status FROM forwarding_jobs')['status']=='cancelled'
        assert one(db,'SELECT body FROM incoming_sms')['body'] is None


def test_same_body_different_events_are_preserved(paired):
    client,identity,payload=paired
    for _ in range(2):
        assert client.post('/api/device/incoming',json=message(identity,payload['iccid']),headers=headers(identity)).status_code==200
    assert client.get('/api/incoming').json()['total']==2


def test_sim_scope_and_revocation(paired):
    client,identity,payload=paired
    data=message(identity,'8986000000000000000')
    assert client.post('/api/device/incoming',json=data,headers=headers(identity)).status_code==409
    assert client.post(f"/api/devices/{identity['device_id']}/revoke").status_code==200
    assert client.post('/api/device/incoming',json=message(identity,payload['iccid']),headers=headers(identity)).status_code==401
    assert client.post('/api/device/register',json=payload).status_code==409


def test_send_and_idempotent_receipt(paired):
    client,identity,payload=paired
    mid,body=create_outgoing(client,identity)
    assert client.post('/api/outgoing',json=body).json()['id']==mid
    assert client.post('/api/outgoing',json={**body,'body':'different'}).status_code==409
    route='/api/device/outgoing/claim?iccid='+payload['iccid']
    claimed=client.post(route,headers=headers(identity)).json()
    assert claimed['id']==mid
    assert client.post(route,headers=headers(identity)).status_code==204
    assert client.post(f'/api/outgoing/{mid}/cancel').status_code==409
    receipt={'iccid':payload['iccid'],'attempt_id':claimed['attempt_id'],'lease_token':claimed['lease_token'],'status':'sent'}
    assert client.post(f'/api/device/outgoing/{mid}/result',json=receipt,headers=headers(identity)).status_code==200
    assert client.post(f'/api/device/outgoing/{mid}/result',json=receipt,headers=headers(identity)).json()['duplicate']
    assert client.post(f'/api/device/outgoing/{mid}/result',json={**receipt,'status':'failed'},headers=headers(identity)).status_code==409
    assert client.get('/api/outgoing').json()['items'][0]['status']=='sent'
    assert client.delete(f'/api/outgoing/{mid}').status_code==200


def test_concurrent_claim_and_timeout(paired):
    from app.worker import maintenance
    client,identity,payload=paired
    mid,_=create_outgoing(client,identity)
    route='/api/device/outgoing/claim?iccid='+payload['iccid']
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(client.post,route,headers=headers(identity)) for _ in range(2)]
        assert sorted(f.result().status_code for f in futures)==[200,204]
    with engine().begin() as db:
        run(db,"UPDATE send_attempts SET lease_expires_at=now()-interval '1 second'")
    maintenance()
    assert client.get('/api/outgoing').json()['items'][0]['status']=='unknown'
    assert client.post(route,headers=headers(identity)).status_code==204
    assert client.delete(f'/api/outgoing/{mid}').status_code==409


def test_cancel_before_claim(paired):
    client,identity,payload=paired
    mid,_=create_outgoing(client,identity)
    assert client.post(f'/api/outgoing/{mid}/cancel').status_code==200
    assert client.post('/api/device/outgoing/claim?iccid='+payload['iccid'],headers=headers(identity)).status_code==204
    assert client.delete(f'/api/outgoing/{mid}').status_code==200


def test_forward_worker_retries_and_finishes(paired,monkeypatch):
    from app import worker
    from app.channels import DeliveryError
    client,identity,payload=paired
    add_channel(client,identity['sim_id'])
    client.post('/api/device/incoming',json=message(identity,payload['iccid']),headers=headers(identity))
    def fail(*args): raise DeliveryError('test failure')
    monkeypatch.setattr(worker,'deliver',fail)
    job=worker.claim_job(); worker.process(job)
    with engine().begin() as db:
        row=one(db,'SELECT * FROM forwarding_jobs')
        assert row['status']=='pending' and row['attempts']==1
        run(db,'UPDATE forwarding_jobs SET next_attempt_at=now()')
    monkeypatch.setattr(worker,'deliver',lambda *args:None)
    worker.process(worker.claim_job())
    assert worker.claim_job() is None
    with engine().begin() as db:
        assert one(db,'SELECT status FROM forwarding_jobs')['status']=='sent'


def test_channel_secret_redaction(paired):
    client,identity,_=paired
    add_channel(client,identity['sim_id'])
    assert 'test-provider-secret' not in client.get('/api/channels').text
    with engine().begin() as db:
        assert 'test-provider-secret' not in one(db,'SELECT credentials_encrypted FROM notification_channels')['credentials_encrypted']


def test_validation_does_not_echo_password(client):
    secret='sensitive-value-in-invalid-body'
    result=client.post('/api/auth/login',json={'username':'a','password':secret,'unexpected':True})
    assert result.status_code==422 and secret not in result.text

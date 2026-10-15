from uuid import uuid4
from app.db import engine, run, one
from app.security import digest


def issue(client, sim):
    response = client.post(f'/api/sims/{sim}/api-key')
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['api_key']}


def test_key_lifecycle_and_auth_separation(paired):
    client, device, payload = paired
    sim = device['sim_id']
    path = f'/api/sims/{sim}/api-key'
    assert client.get(path).json() == {'active': False, 'key': None}
    headers = issue(client, sim)
    assert client.post(path).status_code == 409
    info = client.get(path).json()
    assert info['active'] and 'key_hash' not in str(info)
    assert headers['Authorization'][7:] not in str(info)
    assert client.get('/api/v1/sim').status_code == 401  # Login does not substitute for Key.
    assert client.get('/api/v1/sim', headers={'Authorization':'Bearer '+device['api_key']}).status_code == 401
    assert client.get('/api/v1/sim', headers=headers).json()['id'] == sim
    assert client.get(path).json()['key']['last_used_at']
    with engine().begin() as db:
        stored = one(db, 'SELECT key_hash FROM sim_api_keys WHERE sim_id=:id', id=sim)
        assert stored['key_hash'] == digest(headers['Authorization'][7:])
    replacement = client.post(path+'/reset').json()['api_key']
    assert client.get('/api/v1/sim', headers=headers).status_code == 401
    new = {'Authorization':'Bearer '+replacement}
    assert client.get('/api/v1/sim', headers=new).status_code == 200
    assert client.post('/api/device/heartbeat', headers=new, json={'iccid':payload['iccid']}).status_code == 200
    assert client.delete(path).status_code == 200
    assert client.get('/api/v1/sim', headers=new).status_code == 401
    assert client.post('/api/device/heartbeat', headers={'Authorization':'Bearer '+device['api_key']}, json={'iccid':payload['iccid']}).status_code == 200
    client.cookies.clear()
    assert client.post(path, headers=new).status_code == 401


def test_card_isolation_send_idempotency_and_delete(paired):
    client, dev, payload = paired
    sim = dev['sim_id']
    headers = issue(client, sim)
    other = uuid4()
    with engine().begin() as db:
        run(db, "INSERT INTO sim_cards(id,iccid,name) VALUES (:id,'8986009999999999999','other')", id=other)
    other_headers = issue(client, other)
    body = {'recipient':'+8613800000000','body':'API test','idempotency_key':str(uuid4())}
    path = '/api/v1/sim/messages/outgoing'
    sent = client.post(path, headers=headers, json=body)
    assert sent.status_code == 200, sent.text
    mid = sent.json()['id']
    assert client.post(path, headers=headers, json=body).json()['id'] == mid
    assert client.post(path, headers=headers, json={**body,'body':'changed'}).status_code == 409
    assert client.post(path, headers=headers, json={**body,'sim_id':str(other)}).status_code == 422
    assert client.get(path, headers=other_headers).json()['total'] == 0
    assert client.get(path+'/'+mid, headers=other_headers).status_code == 404
    assert client.delete(path+'/'+mid, headers=other_headers).status_code == 404
    assert client.post(path+'/'+mid+'/cancel', headers=other_headers).status_code == 404
    assert client.get(path+'/'+mid, headers=headers).json()['status'] == 'pending'
    assert client.delete(path+'/'+mid, headers=headers).status_code == 409
    assert client.post(path+'/'+mid+'/cancel', headers=headers).status_code == 200
    assert client.delete(path+'/'+mid, headers=headers).status_code == 200
    assert client.get(path+'/'+mid, headers=headers).status_code == 404
    rotated = client.post(f'/api/sims/{sim}/api-key/reset').json()['api_key']
    assert client.post(path, headers={'Authorization':'Bearer '+rotated}, json=body).json()['id'] == mid
    message = client.post('/api/device/incoming', headers={'Authorization':'Bearer '+dev['api_key']},
                          json={'iccid':payload['iccid'],'event_id':'external-test','sender':'10086','body':'hello'}).json()['id']
    inbox = '/api/v1/sim/messages/incoming'
    headers = {'Authorization':'Bearer '+rotated}
    assert client.get(inbox, headers=headers).json()['total'] == 1
    assert client.get(inbox, headers=other_headers).json()['total'] == 0
    assert client.delete(inbox+'/'+message, headers=other_headers).status_code == 404
    assert client.delete(inbox+'/'+message, headers=headers).status_code == 200
    assert client.get(inbox, headers=headers).json()['total'] == 0


def test_key_management_requires_csrf(paired):
    client, dev, _ = paired
    del client.headers['x-csrf-token']
    assert client.post(f"/api/sims/{dev['sim_id']}/api-key").status_code == 403


def test_api_without_session_and_reissue_by_other_admin(paired):
    client, dev, _ = paired
    sim = dev['sim_id']
    headers = issue(client, sim)
    body = {'recipient':'10086','body':'test','idempotency_key':str(uuid4())}
    path = '/api/v1/sim/messages/outgoing'
    mid = client.post(path, headers=headers, json=body).json()['id']
    # Simulate another administrator reissuing this card's credential.
    with engine().begin() as db:
        uid = uuid4()
        run(db, "INSERT INTO users(id,username,password_hash) VALUES (:id,'second-admin','unused')", id=uid)
        run(db, 'UPDATE sim_api_keys SET created_by=:user WHERE sim_id=:id', user=uid, id=sim)
    client.cookies.clear()
    client.headers.pop('x-csrf-token', None)
    client.headers.pop('origin', None)
    assert client.get('/api/v1/sim', headers=headers).status_code == 200
    assert client.post(path, headers=headers, json=body).json()['id'] == mid
    assert client.get('/api/sims', headers=headers).status_code == 401
    assert client.delete(f'/api/sims/{sim}/api-key', headers=headers).status_code == 401

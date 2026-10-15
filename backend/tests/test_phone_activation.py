from app.db import engine, run
from uuid import uuid4


def test_phone_key_without_pairing_and_activation_lifecycle(admin):
    response = admin.post('/api/sims', json={'name':'My phone','phone_number':'+8613800000000'})
    assert response.status_code == 200, response.text
    phone = response.json()
    sid, token = phone['sim_id'], phone['api_key']
    headers = {'Authorization':'Bearer '+token}
    assert admin.post('/api/sims', json={'name':'duplicate','phone_number':'8613800000000'}).status_code == 409
    assert admin.post(f'/api/sims/{sid}/api-key').status_code == 409
    with engine().begin() as db:
        run(db, "UPDATE sim_api_keys SET created_at=now()-interval '365 days' WHERE sim_id=:id", id=sid)
    assert admin.get('/api/v1/sim', headers=headers).status_code == 200
    task = {'recipient':'10086','body':'hello','idempotency_key':str(uuid4())}
    assert admin.post('/api/v1/sim/messages/outgoing', headers=headers, json=task).status_code == 200
    payload = {'hardware_id':'ESP32-PHONE-1','iccid':'8986001234567890123'}
    response = admin.post('/api/device/activate', headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert admin.post('/api/device/activate', headers=headers, json=payload).json() == response.json()
    assert admin.post('/api/device/activate', headers=headers, json={**payload,'iccid':'8986009999999999999'}).status_code == 409
    assert admin.post('/api/device/activate', headers=headers, json={**payload,'hardware_id':'OTHER-BOARD'}).status_code == 409
    assert admin.post('/api/device/heartbeat', headers=headers, json={'iccid':payload['iccid']}).status_code == 200
    claim = admin.post('/api/device/outgoing/claim', params={'iccid':payload['iccid']}, headers=headers)
    assert claim.status_code == 200
    replacement = admin.post(f'/api/sims/{sid}/api-key/reset').json()['api_key']
    assert admin.post('/api/device/heartbeat', headers=headers, json={'iccid':payload['iccid']}).status_code == 401
    assert admin.get('/api/v1/sim', headers=headers).status_code == 401
    new = {'Authorization':'Bearer '+replacement}
    assert admin.post('/api/device/activate', headers=new, json=payload).status_code == 200
    job = claim.json()
    receipt = {'iccid':payload['iccid'],'attempt_id':job['attempt_id'],'lease_token':job['lease_token'],'status':'sent'}
    assert admin.post(f"/api/device/outgoing/{job['id']}/result", headers=new, json=receipt).status_code == 200
    assert admin.delete(f'/api/sims/{sid}/api-key').status_code == 200
    assert admin.get('/api/v1/sim', headers=new).status_code == 401
    assert admin.post('/api/device/heartbeat', headers=new, json={'iccid':payload['iccid']}).status_code == 401
    assert admin.post(f'/api/sims/{sid}/api-key').status_code == 200


def test_activation_cannot_steal_existing_iccid(admin):
    def phone(number):
        data = admin.post('/api/sims', json={'name':'phone','phone_number':number}).json()
        return {'Authorization':'Bearer '+data['api_key']}
    first, second = phone('13800000001'), phone('13800000002')
    payload = {'hardware_id':'ESP32-FIRST','iccid':'8986001234567890123'}
    assert admin.post('/api/device/activate', headers=first, json=payload).status_code == 200
    assert admin.post('/api/device/activate', headers=second, json={**payload,'hardware_id':'ESP32-SECOND'}).status_code == 409

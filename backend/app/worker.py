import json
import logging
from uuid import uuid4
from .db import engine, one, rows, run
from .security import decrypt
from .channels import deliver, delivery_content, DeliveryError

log = logging.getLogger('smsbot.worker')
DELAYS = [10, 30, 120, 600, 1800]


def maintenance():
    with engine().begin() as db:
        if not one(db, 'SELECT pg_try_advisory_xact_lock(7367281303) AS ok')['ok']:
            return
        run(db, '''UPDATE outgoing_sms SET status='unknown',last_error='设备回执超时，未自动重发'
            WHERE status='leased' AND id IN (SELECT outgoing_id FROM send_attempts
            WHERE phase IN ('claimed','submitting') AND lease_expires_at<now())''')
        run(db, "UPDATE send_attempts SET phase='unknown' WHERE phase IN ('claimed','submitting') AND lease_expires_at<now()")
        run(db, '''UPDATE forwarding_jobs SET status=CASE WHEN attempts>=6 THEN 'failed' ELSE 'pending' END,
            lease_token=NULL,lease_expires_at=NULL,next_attempt_at=now(),last_error='转发进程中断，等待重试'
            WHERE status='processing' AND lease_expires_at<now()''')
        run(db, 'UPDATE device_registrations SET response_encrypted=NULL WHERE response_expires_at<now() AND response_encrypted IS NOT NULL')
        run(db, 'DELETE FROM sessions WHERE expires_at<now()')
        run(db, 'DELETE FROM auth_limits WHERE reset_at<now()')


def claim_job():
    with engine().begin() as db:
        job = one(db, '''SELECT f.* FROM forwarding_jobs f JOIN incoming_sms m ON m.id=f.incoming_id
            JOIN notification_channels c ON c.id=f.channel_id
            WHERE f.status='pending' AND f.next_attempt_at<=now() AND m.deleted_at IS NULL
            AND c.enabled AND c.deleted_at IS NULL ORDER BY f.next_attempt_at FOR UPDATE OF f SKIP LOCKED LIMIT 1''')
        if not job:
            return None
        token = uuid4()
        run(db, '''UPDATE forwarding_jobs SET status='processing',attempts=attempts+1,
            lease_token=:token,lease_expires_at=now()+interval '5 minutes' WHERE id=:id''', token=token, id=job['id'])
        return {**job, 'lease_token': token, 'attempts': job['attempts'] + 1}


def process(job):
    # Session lock spans network I/O without holding a database transaction.
    with engine().connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
        acquired = one(lock, 'SELECT pg_try_advisory_lock(hashtextextended(:id,0)) AS ok', id=str(job['incoming_id']))['ok']
        if not acquired:
            with engine().begin() as db:
                run(db, "UPDATE forwarding_jobs SET status='pending',next_attempt_at=now()+interval '5 seconds',lease_token=NULL,lease_expires_at=NULL WHERE id=:id AND lease_token=:token", id=job['id'], token=job['lease_token'])
            return
        try:
            with engine().begin() as db:
                data = one(db, '''SELECT c.type,c.config,c.credentials_encrypted,m.sender,m.body,m.received_at,
                    s.name,s.phone_number FROM forwarding_jobs f JOIN incoming_sms m ON m.id=f.incoming_id
                    JOIN sim_cards s ON s.id=m.sim_id JOIN notification_channels c ON c.id=f.channel_id
                    WHERE f.id=:id AND f.lease_token=:token AND f.status='processing'
                    AND m.deleted_at IS NULL AND c.enabled AND c.deleted_at IS NULL''', id=job['id'], token=job['lease_token'])
            if not data:
                finish(job, 'cancelled', None)
                return
            title = f"{data['name']} · 新短信"
            content = f"电话卡：{data['name']} {data['phone_number'] or ''}\n发件人：{data['sender']}\n接收时间：{data['received_at'].isoformat()}\n\n{data['body']}"
            content = delivery_content(data['config'], data['body'], content)
            if content is None:
                finish(job, 'cancelled', '短信未匹配截取规则')
                return
            try:
                deliver(data['type'], data['config'], json.loads(decrypt(data['credentials_encrypted'])), title, content)
            except DeliveryError as exc:
                finish(job, 'failed' if job['attempts'] >= 6 else 'pending', str(exc))
            else:
                finish(job, 'sent', None)
        finally:
            run(lock, 'SELECT pg_advisory_unlock(hashtextextended(:id,0))', id=str(job['incoming_id']))


def finish(job, status, error):
    with engine().begin() as db:
        run(db, '''UPDATE forwarding_jobs SET status=:status,last_error=:error,
            next_attempt_at=now()+make_interval(secs => :delay),
            completed_at=CASE WHEN :completed THEN now() ELSE NULL END,
            lease_token=NULL,lease_expires_at=NULL WHERE id=:id AND lease_token=:token AND status='processing' ''',
            status=status, completed=status=='sent', error=error, delay=DELAYS[min(job['attempts']-1, len(DELAYS)-1)],
            id=job['id'], token=job['lease_token'])


def forward_once():
    """One bounded unit of work; scheduling is owned by FastAPI."""
    job = claim_job()
    if job:
        process(job)


def offline_alert_once():
    """Create and deliver one durable alert for a still-offline device."""
    with engine().begin() as db:
        candidates = rows(db, '''SELECT s.id AS sim_id,d.id AS device_id,c.id AS channel_id,
                   d.last_seen_at AS offline_since,s.offline_alert_generation AS generation
            FROM sim_cards s JOIN devices d ON d.id=s.device_id
            JOIN notification_channels c ON c.id=s.offline_channel_id
            WHERE d.enabled AND d.key_revoked_at IS NULL AND d.last_seen_at IS NOT NULL
              AND d.last_seen_at <= now()-make_interval(hours => s.offline_after_hours)
              AND c.enabled AND c.deleted_at IS NULL''')
        for candidate in candidates:
            run(db, '''INSERT INTO device_offline_notifications
                (id,sim_id,device_id,channel_id,offline_since,generation)
                VALUES (:id,:sim_id,:device_id,:channel_id,:offline_since,:generation)
                ON CONFLICT (sim_id,offline_since,generation) DO NOTHING''',
                id=uuid4(), **candidate)
        run(db, '''UPDATE device_offline_notifications a SET status='cancelled',lease_token=NULL,
            lease_expires_at=NULL WHERE a.status='pending' AND NOT EXISTS (
              SELECT 1 FROM sim_cards s JOIN devices d ON d.id=s.device_id
              JOIN notification_channels c ON c.id=s.offline_channel_id
              WHERE s.id=a.sim_id AND d.id=a.device_id AND c.id=a.channel_id
                AND s.offline_alert_generation=a.generation AND d.last_seen_at=a.offline_since
                AND d.enabled AND d.key_revoked_at IS NULL AND c.enabled AND c.deleted_at IS NULL
                AND d.last_seen_at <= now()-make_interval(hours => s.offline_after_hours))''')
        run(db, '''UPDATE device_offline_notifications SET status='pending',lease_token=NULL,
            lease_expires_at=NULL,next_attempt_at=now()
            WHERE status='processing' AND lease_expires_at<now()''')
        alert = one(db, '''SELECT a.id,a.sim_id,a.device_id,a.channel_id,a.offline_since,a.generation,
            a.attempts FROM device_offline_notifications a WHERE a.status='pending'
            AND a.next_attempt_at<=now() ORDER BY a.next_attempt_at
            FOR UPDATE SKIP LOCKED LIMIT 1''')
        if not alert:
            return
        token = uuid4()
        run(db, '''UPDATE device_offline_notifications SET status='processing',attempts=attempts+1,
            lease_token=:token,lease_expires_at=now()+interval '2 minutes'
            WHERE id=:id''', token=token, id=alert['id'])
    with engine().begin() as db:
        data = one(db, '''SELECT s.name,s.phone_number,s.offline_after_hours,
            c.type,c.config,c.credentials_encrypted FROM device_offline_notifications a
            JOIN sim_cards s ON s.id=a.sim_id JOIN devices d ON d.id=s.device_id
            JOIN notification_channels c ON c.id=s.offline_channel_id
            WHERE a.id=:id AND a.lease_token=:token AND a.status='processing'
              AND d.id=a.device_id AND c.id=a.channel_id
              AND s.offline_alert_generation=a.generation AND d.last_seen_at=a.offline_since
              AND d.enabled AND d.key_revoked_at IS NULL AND c.enabled AND c.deleted_at IS NULL
              AND d.last_seen_at <= now()-make_interval(hours => s.offline_after_hours)''',
            id=alert['id'], token=token)
    if not data:
        with engine().begin() as db:
            run(db, "UPDATE device_offline_notifications SET status='cancelled',lease_token=NULL,lease_expires_at=NULL WHERE id=:id AND lease_token=:token",
                id=alert['id'], token=token)
        return
    title = f"{data['name']} · 设备离线"
    content = (f"电话卡：{data['name']} {data['phone_number'] or ''}\n"
               f"设备自 {alert['offline_since'].isoformat()} 起未连接平台，"
               f"已超过设置的 {data['offline_after_hours']} 小时。")
    try:
        # Channel SMS keywords and extraction rules do not apply to system alerts.
        deliver(data['type'], data['config'], json.loads(decrypt(data['credentials_encrypted'])), title, content)
    except DeliveryError as exc:
        with engine().begin() as db:
            run(db, '''UPDATE device_offline_notifications SET status='pending',last_error=:error,
                next_attempt_at=now()+make_interval(secs => :delay),lease_token=NULL,
                lease_expires_at=NULL WHERE id=:id AND lease_token=:token AND status='processing' ''',
                error=str(exc), delay=DELAYS[min(alert['attempts'], len(DELAYS)-1)],
                id=alert['id'], token=token)
    else:
        with engine().begin() as db:
            run(db, '''UPDATE device_offline_notifications SET status='sent',sent_at=now(),
                last_error=NULL,lease_token=NULL,lease_expires_at=NULL
                WHERE id=:id AND lease_token=:token AND status='processing' ''', id=alert['id'], token=token)

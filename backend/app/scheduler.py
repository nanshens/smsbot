"""In-process scheduling; PostgreSQL remains the durable business job queue."""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from . import worker

log = logging.getLogger('smsbot.scheduler')


def guarded(function):
    # Keep secrets / provider response bodies out of scheduler traceback logs.
    try:
        function()
    except Exception as exc:
        log.error('Scheduled job %s failed (%s)', function.__name__, type(exc).__name__)


def start_scheduler():
    scheduler = BackgroundScheduler(
        timezone='UTC', executors={'default': ThreadPoolExecutor(2)},
        job_defaults={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 30},
    )
    scheduler.add_job(guarded, 'interval', seconds=1, args=[worker.forward_once], id='forwarding')
    scheduler.add_job(guarded, 'interval', seconds=30, args=[worker.maintenance], id='maintenance')
    scheduler.start()
    return scheduler

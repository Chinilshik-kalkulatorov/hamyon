import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("hamyon")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "expire-stale-payment-and-transfer-requests": {
        "task": "apps.payments.tasks.expire_stale_requests",
        "schedule": 60.0,
    },
}

"""Single shared Redis client (raw redis-py, used by OTP). Tests replace
``_client`` with a fakeredis instance."""

import redis
from django.conf import settings

_client = None


def get_redis():
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client

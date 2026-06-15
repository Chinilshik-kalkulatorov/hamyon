#!/bin/sh
# Web entrypoint: prepare the app, then exec the given command (gunicorn).
# Only the web service uses this; worker/beat run celery directly.
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

if [ "$SEED_DEMO" = "1" ]; then
    echo "SEED_DEMO=1 -> seeding demo users (alice / bob / admin)"
    python manage.py seed_demo || true
fi

exec "$@"

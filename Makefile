PY := .venv/bin/python
CELERY := .venv/bin/celery

up:
	docker compose up -d

down:
	docker compose down

migrate:
	$(PY) manage.py migrate

seed:
	$(PY) manage.py seed_demo

run:
	$(PY) manage.py runserver

worker:
	$(CELERY) -A config worker -l info

beat:
	$(CELERY) -A config beat -l info

test:
	.venv/bin/pytest

# ---- production (docker) ----
COMPOSE_PROD := docker compose --env-file .env.prod -f docker-compose.prod.yml

deploy:
	$(COMPOSE_PROD) up -d --build

deploy-down:
	$(COMPOSE_PROD) down

deploy-logs:
	$(COMPOSE_PROD) logs -f

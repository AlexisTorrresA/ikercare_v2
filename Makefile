.PHONY: up down logs test backup

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f app

test:
	pytest -q

backup:
	./scripts/backup.sh

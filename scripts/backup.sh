#!/usr/bin/env sh
set -eu

mkdir -p backups
STAMP=$(date +%Y%m%d_%H%M%S)
DB_NAME=${POSTGRES_DB:-iker_care}
DB_USER=${POSTGRES_USER:-iker_care}

docker compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > "backups/iker_care_${STAMP}.sql.gz"
echo "Respaldo creado: backups/iker_care_${STAMP}.sql.gz"

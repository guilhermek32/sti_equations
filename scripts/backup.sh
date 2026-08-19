#!/bin/sh
set -eu

destination=${1:?usage: scripts/backup.sh BACKUP_FILE}
docker compose exec -T db pg_dump -U sti -d sti --format=custom > "$destination"

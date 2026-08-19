#!/bin/sh
set -eu

source_file=${1:?usage: scripts/restore.sh BACKUP_FILE}
test -f "$source_file"
docker compose exec -T db pg_restore -U sti -d sti --clean --if-exists < "$source_file"

#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/vm-common.sh"

if (( $# > 0 )); then
    printf 'Uso: bash scripts/vm-stop.sh\n' >&2
    exit 2
fi
vm_init
printf 'Encerrando somente a pagina de resultados e o dashboard deste projeto...\n'
docker compose --profile demo stop results dashboard
printf 'Interfaces encerradas. Experimentos, dados e volumes foram preservados.\n'

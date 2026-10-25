#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/vm-common.sh"

if (( $# > 0 )); then
    printf 'Uso: bash scripts/vm-prepare.sh\n' >&2
    exit 2
fi
vm_init
LOG="$EXPORTS_HOST_DIR/setup/prepare.log"
trap vm_on_error ERR

printf '\n[1/3] Encerrando somente as interfaces deste projeto...\n'
docker compose --profile demo stop results dashboard
docker compose config > "$EXPORTS_HOST_DIR/setup/compose-effective.yaml"
docker info > "$EXPORTS_HOST_DIR/setup/docker-info.txt"

printf '\n[2/3] Construindo a imagem Linux...\n'
docker compose build experiment 2>&1 | tee -a "$LOG"
docker image inspect grupo05-dask:cp3 > "$EXPORTS_HOST_DIR/setup/image-inspect.json"

printf '\n[3/3] Executando testes e registrando o ambiente...\n'
docker compose run --rm --no-deps --entrypoint python experiment \
    -m unittest discover -s tests -v 2>&1 | tee -a "$LOG"
docker compose run --rm --no-deps experiment environment \
    --output "/exports/setup/prepare-environment.json" 2>&1 | tee -a "$LOG"

printf '\nPreparacao concluida. Para executar: bash scripts/vm-run.sh smoke\n'

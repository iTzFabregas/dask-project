#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/vm-common.sh"

usage() {
    printf 'Uso: bash scripts/vm-run.sh [smoke|pilot] [ID] [--workers N] [--partitions N] [--memory 256m|512m|1g|2g]\n'
}

MODE="${1:-smoke}"
if [[ "$MODE" != smoke && "$MODE" != pilot ]]; then
    usage >&2
    exit 2
fi
if (( $# > 0 )); then shift; fi
EXPERIMENT_ID=""
if (( $# > 0 )) && [[ "$1" != --* ]]; then
    EXPERIMENT_ID="$1"
    shift
fi
WORKERS=""
PARTITIONS=""
MEMORY=""
while (( $# > 0 )); do
    case "$1" in
        --workers)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            WORKERS="$2"; shift 2 ;;
        --partitions)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            PARTITIONS="$2"; shift 2 ;;
        --memory)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            MEMORY="${2,,}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Opcao desconhecida: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done
if [[ -n "$WORKERS" && ! "$WORKERS" =~ ^(1|2|4|8|16)$ ]]; then
    printf 'Workers aceitos: 1, 2, 4, 8 ou 16.\n' >&2
    exit 2
fi
if [[ -n "$PARTITIONS" && ! "$PARTITIONS" =~ ^(1|2|4|8|16|32|64)$ ]]; then
    printf 'Particoes aceitas: 1, 2, 4, 8, 16, 32 ou 64.\n' >&2
    exit 2
fi
if [[ -n "$MEMORY" && ! "$MEMORY" =~ ^([1-9][0-9]*)(m|g)$ ]]; then
    printf 'Memoria deve usar M ou G, por exemplo: 256m, 512m, 1g ou 2g.\n' >&2
    exit 2
fi

vm_init
REVISION="${SOURCE_COMMIT:0:10}"
if [[ -z "$EXPERIMENT_ID" ]]; then
    EXPERIMENT_ID="vm-${MODE}-${REVISION}"
    [[ -z "$WORKERS" ]] || EXPERIMENT_ID+="-w${WORKERS}"
    [[ -z "$PARTITIONS" ]] || EXPERIMENT_ID+="-p${PARTITIONS}"
    [[ -z "$MEMORY" ]] || EXPERIMENT_ID+="-m${MEMORY}"
fi
if [[ ! "$EXPERIMENT_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    printf 'O identificador so pode conter letras, numeros, _ e -.\n' >&2
    exit 2
fi
LOG="$EXPORTS_HOST_DIR/setup/${EXPERIMENT_ID}.log"
trap vm_on_error ERR

if ! docker image inspect grupo05-dask:cp3 >/dev/null 2>&1; then
    printf 'Imagem ainda nao preparada. Execute primeiro: bash scripts/vm-prepare.sh\n' >&2
    exit 1
fi

RUN_ARGS=("$MODE" --experiment "$EXPERIMENT_ID")
[[ -z "$WORKERS" ]] || RUN_ARGS+=(--workers "$WORKERS")
[[ -z "$PARTITIONS" ]] || RUN_ARGS+=(--partitions "$PARTITIONS")
if [[ -n "$MEMORY" ]]; then
    MEMORY_MIB="${MEMORY%[mg]}"
    if [[ "$MEMORY" == *g ]]; then MEMORY_MIB=$((MEMORY_MIB * 1024)); fi
    WORKER_COUNT="${WORKERS:-2}"
    WORKER_MEMORY_MIB=$((MEMORY_MIB * 80 / 100 / WORKER_COUNT))
    if (( WORKER_MEMORY_MIB < 64 )); then
        printf 'Esse limite nao deixa 64 MiB por worker. Reduza workers ou aumente memoria.\n' >&2
        exit 2
    fi
    export EXPERIMENT_MEMORY="$MEMORY" EXPECTED_MEMORY="$MEMORY" WORKER_MEMORY_MIB
    printf 'Memoria total: %s; limite por worker Dask: %s MiB.\n' "$MEMORY" "$WORKER_MEMORY_MIB"
fi

printf '\n[1/3] Parando somente as interfaces deste projeto antes da medicao...\n'
docker compose --profile demo stop results dashboard
printf '\n[2/3] Executando %s (%s)...\n' "$MODE" "$EXPERIMENT_ID"
docker compose run --rm --no-deps --service-ports experiment "${RUN_ARGS[@]}" 2>&1 | tee -a "$LOG"

printf '\n[3/3] Iniciando a pagina de resultados e o dashboard...\n'
docker compose --profile demo up -d results dashboard 2>&1 | tee -a "$LOG"
vm_check_http results http://127.0.0.1:8080/
vm_check_http dashboard http://127.0.0.1:8787/status

RESULTS_MAPPING="$(docker compose port results 8080)"
DASHBOARD_MAPPING="$(docker compose port dashboard 8787)"
RESULTS_PORT="${RESULTS_MAPPING##*:}"
DASHBOARD_PORT="${DASHBOARD_MAPPING##*:}"
if command -v curl >/dev/null 2>&1; then
    curl --noproxy '*' --fail --silent --show-error --max-time 10 \
        "http://127.0.0.1:${RESULTS_PORT}/" > /dev/null
    curl --noproxy '*' --fail --silent --show-error --max-time 10 \
        "http://127.0.0.1:${DASHBOARD_PORT}/status" > /dev/null
fi
printf '\nExecucao concluida. Experimento: %s\n' "$EXPERIMENT_ID"
printf 'Resultados: http://localhost:%s/\n' "$RESULTS_PORT"
printf 'Dashboard: http://localhost:%s/status\n' "$DASHBOARD_PORT"
printf 'Dados e logs: %s\n' "$EXPORTS_HOST_DIR"
printf 'Para encerrar as interfaces sem apagar resultados: bash scripts/vm-stop.sh\n'

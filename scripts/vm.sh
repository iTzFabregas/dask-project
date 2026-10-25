#!/usr/bin/env bash
# Run from any directory: bash /path/to/project/scripts/vm.sh [smoke|pilot] [ID]
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

MODE="${1:-smoke}"
if [[ "$MODE" != smoke && "$MODE" != pilot ]] || (( $# > 2 )); then
    printf 'Uso: bash scripts/vm.sh [smoke|pilot] [identificador]\n' >&2
    exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
    printf 'Docker nao encontrado. A VM precisa de Docker e Docker Compose v2.\n' >&2
    exit 1
fi
docker compose version
if [[ "$(docker info --format '{{.OSType}}')" != linux ]]; then
    printf 'O Docker precisa estar acessivel e executar containers Linux.\n' >&2
    exit 1
fi

if [[ ! -f .env ]]; then
    cp .env.vm.example .env
    printf 'Configuracao VM criada em .env (portas 5185 e 5285).\n'
fi
SOURCE_COMMIT=unavailable
if command -v git >/dev/null 2>&1; then
    SOURCE_COMMIT="$(git rev-parse HEAD 2>/dev/null || printf unavailable)"
    if [[ "$SOURCE_COMMIT" != unavailable ]] && [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
        printf 'Aviso: ha alteracoes locais; os hashes das fontes tambem serao registrados.\n' >&2
    fi
fi
export SOURCE_COMMIT
REVISION="${SOURCE_COMMIT:0:10}"
EXPERIMENT_ID="${2:-vm-${MODE}-${REVISION}}"
if [[ ! "$EXPERIMENT_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    printf 'O identificador so pode conter letras, numeros, _ e -.\n' >&2
    exit 2
fi
EXPORTS_HOST_DIR="${EXPORTS_HOST_DIR:-/tmp/grupo05-dask-exports-${UID}}"
export EXPORTS_HOST_DIR
mkdir -p "$EXPORTS_HOST_DIR/setup"
LOG="$EXPORTS_HOST_DIR/setup/${EXPERIMENT_ID}.log"

on_error() {
    local status=$?
    printf '\nA execucao parou (codigo %s). Nao houve exclusao de dados.\n' "$status" >&2
    printf 'Consulte %s e os logs acima. A interface nao sera anunciada como pronta.\n' "$LOG" >&2
    printf 'Diagnostico dos servicos: docker compose --profile demo logs --tail 80\n' >&2
    exit "$status"
}
trap on_error ERR

# Stop only this Compose project's auxiliaries before collecting measurements.
printf '\n[1/6] Preparando o projeto e encerrando suas interfaces anteriores...\n'
docker compose --profile demo stop results dashboard
docker compose config > "$EXPORTS_HOST_DIR/setup/compose-effective.yaml"
docker info > "$EXPORTS_HOST_DIR/setup/docker-info.txt"

printf '\n[2/6] Construindo a imagem Linux...\n'
docker compose build experiment 2>&1 | tee -a "$LOG"
docker image inspect grupo05-dask:cp3 > "$EXPORTS_HOST_DIR/setup/image-inspect.json"

printf '\n[3/6] Executando os testes automatizados...\n'
docker compose run --rm --no-deps --entrypoint python experiment \
    -m unittest discover -s tests -v 2>&1 | tee -a "$LOG"
docker compose run --rm --no-deps experiment environment \
    --output "/exports/setup/${EXPERIMENT_ID}-environment.json" 2>&1 | tee -a "$LOG"

printf '\n[4/6] Executando %s (%s); os resultados sao validados antes da exportacao...\n' "$MODE" "$EXPERIMENT_ID"
docker compose run --rm --no-deps --service-ports experiment "$MODE" \
    --experiment "$EXPERIMENT_ID" 2>&1 | tee -a "$LOG"

printf '\n[5/6] Iniciando a pagina e o dashboard de demonstracao...\n'
docker compose --profile demo up -d results dashboard 2>&1 | tee -a "$LOG"

printf '\n[6/6] Verificando as respostas HTTP dentro dos servicos...\n'
docker compose exec -T results python -c '
import time, urllib.request
for attempt in range(60):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/", timeout=2) as response:
            assert response.status == 200
        print("Pagina de resultados: HTTP 200", flush=True)
        break
    except Exception:
        if attempt == 59:
            raise
        time.sleep(1)
' 2>&1 | tee -a "$LOG"
docker compose exec -T dashboard python -c '
import time, urllib.request
for attempt in range(60):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8787/status", timeout=2) as response:
            assert response.status == 200
        print("Dashboard de demonstracao: HTTP 200", flush=True)
        break
    except Exception:
        if attempt == 59:
            raise
        time.sleep(1)
' 2>&1 | tee -a "$LOG"

RESULTS_MAPPING="$(docker compose port results 8080)"
DASHBOARD_MAPPING="$(docker compose port dashboard 8787)"
RESULTS_PORT="${RESULTS_MAPPING##*:}"
DASHBOARD_PORT="${DASHBOARD_MAPPING##*:}"
if command -v curl >/dev/null 2>&1; then
    curl --noproxy '*' --fail --silent --show-error --max-time 10 \
        "http://127.0.0.1:${RESULTS_PORT}/" > /dev/null
    curl --noproxy '*' --fail --silent --show-error --max-time 10 \
        "http://127.0.0.1:${DASHBOARD_PORT}/status" > /dev/null
    printf 'As duas portas publicadas tambem responderam via localhost da VM.\n'
else
    printf 'curl ausente: HTTP interno verificado; acesso pelas portas do host ainda precisa de verificacao.\n'
fi
printf '\nExecucao concluida. Experimento: %s\n' "$EXPERIMENT_ID"
printf 'Resultados locais na VM: http://localhost:%s/\n' "$RESULTS_PORT"
printf 'Dashboard de demonstracao: http://localhost:%s/status\n' "$DASHBOARD_PORT"
printf 'No navegador do PC, use o endereco da VM/instituicao com essas portas.\n'
printf 'O acesso externo depende dos mapeamentos da instituicao; este script nao o verifica.\n'
if [[ "$MODE" == smoke ]]; then
    printf 'Smoke aprovado: teste funcional pequeno; nao substitui os 55 ensaios do piloto.\n'
fi
printf 'Encerrar interfaces e preservar dados: docker compose --profile demo down\n'

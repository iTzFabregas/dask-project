VM_SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VM_PROJECT_DIR="$(CDPATH= cd -- "$VM_SCRIPT_DIR/.." && pwd)"

vm_init() {
    cd "$VM_PROJECT_DIR"
    if ! command -v docker >/dev/null 2>&1; then
        printf 'Docker nao encontrado. A VM precisa de Docker e Docker Compose v2.\n' >&2
        return 1
    fi
    docker compose version
    if [[ "$(docker info --format '{{.OSType}}')" != linux ]]; then
        printf 'O Docker precisa estar acessivel e executar containers Linux.\n' >&2
        return 1
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

    EXPORTS_HOST_DIR="${EXPORTS_HOST_DIR:-/tmp/grupo05-dask-exports-${UID}}"
    export EXPORTS_HOST_DIR
    mkdir -p "$EXPORTS_HOST_DIR/setup"
}

vm_on_error() {
    local status=$?
    printf '\nA execucao parou (codigo %s). Os resultados existentes foram preservados.\n' "$status" >&2
    if [[ -n "${LOG:-}" ]]; then
        printf 'Consulte %s e os logs acima.\n' "$LOG" >&2
    fi
    printf 'Diagnostico: docker compose --profile demo logs --tail 80\n' >&2
    exit "$status"
}

vm_check_http() {
    local service="$1" url="$2"
    docker compose exec -T "$service" python -c '
import sys, time, urllib.request
url = sys.argv[1]
for attempt in range(60):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            assert response.status == 200
        print(f"{url}: HTTP 200", flush=True)
        break
    except Exception:
        if attempt == 59:
            raise
        time.sleep(1)
' "$url" 2>&1 | tee -a "$LOG"
}

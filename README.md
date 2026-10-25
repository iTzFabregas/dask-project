# Grupo 05 — Dask na VM

Este guia descreve o fluxo completo para preparar a VM por SSH, executar os
testes, rodar um experimento e consultar os resultados e o dashboard.

## 1. O que você precisa

- Acesso SSH à VM e ao diretório do projeto.
- Docker Engine ativo na VM e Docker Compose v2 (`docker compose`).
- Permissão para executar comandos Docker na VM.
- A VM e o computador local conectados à rede institucional, ou acesso SSH para
criar um túnel até as portas da aplicação.

Os exemplos usam `usuario` e `host-da-vm` como marcadores. Substitua-os pelos
dados fornecidos pela instituição.

## 2. Conectar à VM por SSH

Abra um terminal no seu computador e conecte-se:

```bash
ssh usuario@host-da-vm
```

Se a instituição forneceu uma chave SSH específica:

```bash
ssh -i ~/.ssh/chave_fornecida usuario@host-da-vm
```

Na primeira conexão, o SSH pode perguntar se você confia na identidade da VM.
Confira a impressão digital (fingerprint) com as instruções da instituição
antes de aceitar. A autenticação pode pedir sua senha institucional ou usar a
chave cadastrada.

Se ainda não tiver acesso SSH, peça à instituição o endereço da VM, seu usuário,
o método de autenticação e, se necessário, o cadastro da sua chave pública.
Nunca envie ou copie sua chave privada para outra pessoa.

Depois de conectar, os comandos seguintes são executados **no terminal da VM**.
Entre no diretório do projeto:

```bash
cd ~/dask-project
```

Confirme que está na pasta certa:

```bash
pwd
ls
```

Se o projeto ainda não estiver nessa VM, obtenha-o pelo método de Git ou de
transferência autorizado pela instituição antes de continuar.

## 3. Preparar a VM e executar os testes

Na primeira execução, rode:

```bash
cd ~/dask-project
bash scripts/vm-prepare.sh
```

O `vm-prepare`:

1. Confere se o Docker Compose está disponível e se o Docker está acessível e
   executa containers Linux.
2. Cria `.env` a partir de `.env.vm.example` se ainda não existir. Uma
   configuração `.env` existente é preservada.
3. Encerra somente os serviços `results` e `dashboard` deste projeto; não para
   os outros containers da VM.
4. Constrói a imagem `grupo05-dask:cp3`.
5. Executa a suíte automatizada dentro da imagem recém-construída:

   ```bash
   docker compose run --rm --no-deps --entrypoint python experiment \
     -m unittest discover -s tests -v
   ```

   O comando descobre e executa os testes em `tests/`. `--rm` remove o
   container temporário ao final; `--no-deps` não inicia outros serviços. Se
   algum teste falhar, a preparação para e o experimento não é executado.
6. Registra informações do ambiente Docker.

Essa etapa não roda o benchmark. Rode-a novamente quando quiser reconstruir a
imagem e repetir os testes, por exemplo, depois de alterar o código.

## 4. Executar um experimento

Mantenha a sessão SSH aberta enquanto o benchmark está rodando: o comando
`vm-run` permanece em primeiro plano durante a medição.

Para uma execução rápida:

```bash
bash scripts/vm-run.sh smoke
```

Para o piloto:

```bash
bash scripts/vm-run.sh pilot
```

O `vm-run` verifica se a imagem já foi preparada, executa o modo escolhido e,
se a medição terminar com sucesso, inicia a página de resultados e o dashboard.
Se a medição falhar, as interfaces não são iniciadas como se o experimento
tivesse sido concluído.

### Diferença entre `smoke` e `pilot`

- `configs/smoke.json` define uma verificação curta: um bloco, um volume pequeno
  e cenários com pandas e Dask.
- `configs/pilot.json` define o piloto: cinco blocos e 11 cenários planejados,
  combinando volumes e configurações. Isso corresponde a 55 medições planejadas
  no piloto, além das etapas automáticas de smoke e preflight usadas como
  verificações antes do piloto.

Os arquivos JSON descrevem o desenho do experimento (volumes, cenários,
repetições, sementes e tempos limite). A memória total do container é definida
à parte por configuração do Docker Compose ou pela opção `--memory` abaixo.

### Workers, partições e memória

As opções alteram os cenários Dask da execução; o cenário de comparação pandas
permanece. Quando a mudança faz cenários ficarem iguais, duplicatas são
consolidadas.

```bash
bash scripts/vm-run.sh smoke --workers 4 --partitions 8
```

Valores aceitos:

- `--workers`: `1`, `2`, `4`, `8` ou `16`.
- `--partitions`: `1`, `2`, `4`, `8`, `16`, `32` ou `64`.
- `--memory`: limite **total do container**, por exemplo `256m`, `512m`, `1g`
  ou `2g`.

Exemplo com todas as opções e identificador explícito:

```bash
bash scripts/vm-run.sh pilot ensaio-01 \
  --workers 4 --partitions 16 --memory 2g
```

Ao definir `--memory`, o script reserva aproximadamente 20% do limite total para
o restante do container e divide o restante pelo número de workers informado
(ou por dois, se `--workers` não for informado). Esse valor também ajusta o
limite de memória por worker Dask. Se o cálculo deixar menos de 64 MiB por
worker, o script recusa a combinação.

Workers não são CPUs: o limite padrão do container continua sendo 2 CPUs. Por
exemplo, 8 workers com 2 CPUs compartilham essas CPUs. O número de workers do
benchmark não aumenta a capacidade da VM.

Se não informar um identificador, o script cria um a partir do modo, revisão
Git e opções utilizadas. Para retomar uma execução com o mesmo identificador,
informe-o explicitamente; alterações de configuração ou ambiente podem impedir
a retomada para preservar a integridade dos resultados.

## 5. Acessar a página de resultados e o dashboard

Ao terminar, o `vm-run` imprime os endereços e verifica se os serviços
respondem. Com a configuração inicial, as portas são:

- Página de resultados: `http://localhost:5285/` **na VM**.
- Dashboard Dask: `http://localhost:5185/status` **na VM**.

Para abrir no navegador do seu computador, substitua `localhost` pelo nome ou
IP da VM, por exemplo:

```text
http://host-da-vm:5285/
http://host-da-vm:5185/status
```

O acesso direto depende de a rede institucional permitir essas portas. Se não
for possível acessá-las diretamente, abra um **segundo terminal no computador
local** e mantenha este túnel SSH aberto:

```bash
ssh -L 5285:127.0.0.1:5285 -L 5185:127.0.0.1:5185 usuario@host-da-vm
```

Com o túnel ativo, use no navegador local:

```text
http://localhost:5285/
http://localhost:5185/status
```

O dashboard é uma demonstração separada do benchmark. Ele não representa uma
medição de desempenho do experimento.

## 6. Onde os arquivos ficam

Para evitar o problema de acesso do Docker ao diretório pessoal da VM, os
scripts montam esta pasta temporária do host como `/exports` dentro dos
containers:

```text
/tmp/grupo05-dask-exports-<UID>
```

Na VM deste projeto, o caminho é `/tmp/grupo05-dask-exports-1397`. A página de
resultados fica em `index.html` nessa pasta; cada experimento exportado tem seu
próprio diretório com relatório, dados processados e metadados. O subdiretório
`setup/` contém logs e diagnósticos da preparação e das execuções.

Os dados de entrada, os resultados completos das medições e os arquivos
temporários de processamento ficam em volumes nomeados do Docker (`inputs`,
`experiments` e `scratch`). `vm-stop` preserva esses volumes. Como `/tmp` é uma
pasta temporária do sistema, copie para um local permanente qualquer exportação
que precise guardar por longo prazo. A pasta `exports/` que existe no projeto
não é usada por padrão pelos scripts da VM.

## 7. Encerrar as interfaces sem apagar dados

Quando terminar de consultar a página e o dashboard, execute na VM:

```bash
cd ~/dask-project
bash scripts/vm-stop.sh
```

Esse comando para somente `results` e `dashboard` deste projeto. Ele não apaga
resultados, volumes ou imagens Docker e não para containers de outros projetos.
Para consultar os resultados novamente, rode `vm-run` outra vez; ele executa
uma nova medição antes de iniciar as interfaces.

## 8. Árvore do projeto

```text
dask-project/
├── compose.yaml             # Containers, portas, limites e volumes Docker
├── Dockerfile               # Imagem Python usada pelo experimento
├── .env.vm.example          # Configuração inicial para a VM
├── configs/
│   ├── smoke.json           # Plano do teste rápido
│   └── pilot.json           # Plano do piloto
├── pilot/                   # Código de execução, validação, análise e página web
├── scripts/
│   ├── vm-common.sh         # Funções compartilhadas pelos scripts da VM
│   ├── vm-prepare.sh        # Prepara imagem e executa testes
│   ├── vm-run.sh            # Executa experimento e inicia interfaces
│   ├── vm-stop.sh           # Para as interfaces preservando os dados
│   └── vm.sh                # Compatibilidade: prepara e depois executa
└── tests/                   # Testes automatizados Python
```

## 9. Problemas comuns

- **`Docker nao encontrado` ou falha de acesso ao daemon:** confirme com a
  instituição que o Docker está ativo e que sua conta tem permissão para usá-lo.
  Não rode o script com `sudo` sem orientação do administrador.
- **Erro de permissão ao montar `/home/.../exports`:** confirme que está usando
  os scripts `scripts/vm-prepare.sh` e `scripts/vm-run.sh` desta versão. Eles
  usam `/tmp/grupo05-dask-exports-<UID>` por padrão. O caminho alternativo pode
  ser configurado definindo `EXPORTS_HOST_DIR` antes do comando.
- **`Imagem ainda nao preparada`:** execute primeiro
  `bash scripts/vm-prepare.sh`.
- **Teste falhou:** a preparação não segue para o benchmark. Leia as mensagens
  no terminal ou o log em
  `/tmp/grupo05-dask-exports-<UID>/setup/prepare.log`.
- **Página não abre do computador local:** teste o endereço na própria VM. Se
  funcionar lá, mas não no computador, use o túnel SSH ou confirme com a
  instituição se as portas 5285 e 5185 estão acessíveis.
- **Memória insuficiente:** reduza workers ou aumente `--memory`. O valor
  informado é o limite total do container, não a memória por worker.

## 10. Comandos rápidos

```bash
# Na VM, uma vez ou depois de alterar o código:
bash scripts/vm-prepare.sh

# Na VM, executar uma validação rápida:
bash scripts/vm-run.sh smoke

# Na VM, executar o piloto:
bash scripts/vm-run.sh pilot

# Na VM, personalizar o benchmark:
bash scripts/vm-run.sh smoke --workers 4 --partitions 8 --memory 1g

# Na VM, encerrar somente a página e o dashboard:
bash scripts/vm-stop.sh
```

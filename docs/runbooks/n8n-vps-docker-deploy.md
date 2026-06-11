# Runbook - Subir n8n Em Docker Na VPS

## Objetivo

Subir o `n8n` como servico separado na mesma VPS do `supportFAQagent`, usando
Docker Compose, banco PostgreSQL proprio e bind local para reverse proxy HTTPS.

Este runbook nao cria workflows, nao conecta Evolution API e nao move regra de
inteligencia para o `n8n`. O `n8n` continua como automacao externa que consome
contratos HTTP do backend.

## Decisoes

- `n8n` roda em container separado.
- `n8n` usa PostgreSQL proprio, nao o banco do `supportFAQagent`.
- A porta `5678` fica exposta apenas em `127.0.0.1`.
- HTTPS e acesso publico entram via reverse proxy.
- A imagem do `n8n` deve ser pinada por versao em `N8N_IMAGE_TAG`; nao usar
  `latest` em staging/producao.
- `N8N_ENCRYPTION_KEY` deve ser gerado uma vez e preservado. Perder ou trocar
  essa chave pode impedir descriptografar credenciais salvas no n8n.

Analogia simples: o `supportFAQagent` e o cerebro que decide a resposta; o
`n8n` e a esteira que leva e traz mensagens. A esteira tem motor e banco
proprios para nao quebrar o cerebro se precisar parar ou reiniciar.

## Pre-requisitos

- Acesso SSH autorizado a VPS.
- Docker e Docker Compose plugin instalados.
- DNS/HTTPS decidido para o painel ou webhook do n8n.
- Reverse proxy disponivel, por exemplo Nginx.
- Secrets criados somente no servidor, nunca no Git.

## Arquivos No Repo

- `deploy/n8n/docker-compose.yml`
- `deploy/n8n/.env.example`

Copie esses arquivos para um diretorio privado no servidor, por exemplo:

```bash
sudo mkdir -p /opt/supportfaq/n8n
sudo cp deploy/n8n/docker-compose.yml /opt/supportfaq/n8n/docker-compose.yml
sudo cp deploy/n8n/.env.example /opt/supportfaq/n8n/.env
sudo chmod 600 /opt/supportfaq/n8n/.env
```

Edite `/opt/supportfaq/n8n/.env` no servidor e preencha os valores privados.

## Variaveis Obrigatorias

```dotenv
N8N_IMAGE_TAG=<versao-testada>
N8N_HOST=n8n.ordens.com.br
N8N_PROTOCOL=https
WEBHOOK_URL=https://n8n.ordens.com.br/
N8N_EDITOR_BASE_URL=https://n8n.ordens.com.br/
N8N_PROXY_HOPS=1
N8N_PORT=5678
N8N_ENCRYPTION_KEY=<openssl-rand-hex-32>
N8N_RUNNERS_ENABLED=true
N8N_BLOCK_ENV_ACCESS_IN_NODE=true
N8N_GIT_NODE_DISABLE_BARE_REPOS=true
N8N_POSTGRES_DB=n8n
N8N_POSTGRES_USER=n8n
N8N_POSTGRES_PASSWORD=<secret-forte>
```

Gerar secrets no servidor:

```bash
openssl rand -hex 32
openssl rand -base64 36
```

## Subir O Stack

No servidor:

```bash
docker network inspect supportfaq_internal >/dev/null 2>&1 || docker network create supportfaq_internal
cd /opt/supportfaq/n8n
docker compose --env-file .env pull
docker compose --env-file .env up -d
docker compose --env-file .env ps
```

A rede `supportfaq_internal` permite que o n8n alcance a API pelo nome interno
do servico sem publicar PostgreSQL ou portas privadas.

Ver logs sanitizados:

```bash
docker logs --tail 80 n8n
docker logs --tail 80 n8n_postgres
```

Nao publicar logs brutos se contiverem hostnames, URLs internas, usuarios,
tokens, credenciais, payloads ou PII.

## Smoke Local

No servidor:

```bash
curl -i http://127.0.0.1:5678/
```

Esperado:

- HTTP `200` ou redirect esperado do editor;
- container `n8n` em estado `Up`;
- container `n8n_postgres` em estado `Up`;
- porta `5678` escutando apenas em loopback.

Conferir bind:

```bash
ss -ltnp | grep 5678
```

Esperado:

```text
127.0.0.1:5678
```

Nao aceitar `0.0.0.0:5678` sem decisao explicita de seguranca.

## Reverse Proxy Nginx

Exemplo para subdominio dedicado:

```nginx
server {
    server_name n8n.ordens.com.br;

    location / {
        proxy_pass http://127.0.0.1:5678;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Depois de configurar TLS:

```bash
curl -I https://n8n.ordens.com.br/
```

## Integracao Com supportFAQagent

O `n8n` deve consumir o backend por HTTP, sem acessar tabelas internas:

- `POST /chat`
- `POST /feedback`
- futuros endpoints internos de OTP quando aprovados

Headers obrigatorios para `/chat`:

```http
Content-Type: application/json
X-API-Key: <api-secret-privado>
X-Request-ID: <id-estavel>
```

O workflow deve preservar:

- `request_id`
- `domain`
- `confidence`
- `escalated`
- `handoff_reasons`
- `references`
- `error_code`

## Operacao

Parar sem apagar dados:

```bash
cd /opt/supportfaq/n8n
docker compose --env-file .env stop
```

Subir novamente:

```bash
cd /opt/supportfaq/n8n
docker compose --env-file .env up -d
```

Backup minimo antes de upgrade:

```bash
docker exec n8n_postgres pg_dump -U "$N8N_POSTGRES_USER" "$N8N_POSTGRES_DB" > n8n-backup.sql
```

Executar esse comando dentro de sessao privada; nao publicar dump.

## Criterios De Sucesso

- `docker compose ps` mostra `n8n` e `n8n_postgres` ativos.
- `curl http://127.0.0.1:5678/` responde.
- `ss -ltnp` confirma bind em `127.0.0.1`.
- HTTPS publico responde via reverse proxy, se DNS/TLS ja estiverem prontos.
- Nenhum secret foi salvo em Git.
- `supportFAQagent` continua independente: parar `n8n` nao derruba a API.

## Criterios De Parada

Parar e registrar bloqueio privado se ocorrer:

- Docker ausente ou desatualizado.
- Porta `5678` exposta em `0.0.0.0`.
- Falha de pull da imagem pinada.
- Falha de conexao com PostgreSQL do n8n.
- `N8N_ENCRYPTION_KEY` ausente.
- Necessidade de colar secret em doc, PR ou chat.
- Workflow tentando acessar banco interno do `supportFAQagent`.

## Referencias

- [Contrato n8n/WhatsApp para `/chat`](n8n-whatsapp-chat-contract.md)
- [Mapa oficial de ambientes](../environments.md)
- [Runtime controlado da VPS](vps-controlled-runtime.md)

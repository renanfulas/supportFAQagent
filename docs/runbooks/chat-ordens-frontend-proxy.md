# Runbook - Troca Da `/chat-ui` Para `ask-host-genius`

## Objetivo

Trocar a UI publica em `https://chat.ordens.com.br/chat-ui` para o frontend
`ask-host-genius`, sem embutir o build dentro do backend `supportFAQagent`.

Topologia alvo:

- `/chat-ui` -> `ask-host-genius` em loopback;
- `/assets/*` -> assets do `ask-host-genius`;
- `/team` -> area interna do time em `ask-host-genius` (mesmo loopback);
- `/web/*` -> `supportFAQagent`;
- `/chat-assets/*` -> legado do backend, mantido apenas como fallback.

## Motivo

O `ask-host-genius` e um app TanStack Start/SSR. Ele nao gera um
`index.html` estatico simples para copiar em `app/static/chat`. Servi-lo como
processo separado evita adaptar o frontend moderno para caber no mecanismo
estatico antigo.

Analogia simples: o backend atual entrega um folheto impresso. O frontend novo
e uma recepcao viva com atendente. Em vez de transformar a recepcao em folheto,
colocamos uma porta apontando para a recepcao certa.

## Pre-requisitos

- backend `supportFAQagent` rodando em `127.0.0.1:8000`;
- frontend `ask-host-genius` rodando em `127.0.0.1:5173`;
- `ENABLE_PUBLIC_CHAT_UI=true` no backend se quiser manter o fallback legado;
- HTTPS valido em `chat.ordens.com.br`;
- `VITE_API_BASE_URL=` vazio no frontend para chamadas same-origin.

## Configuracao Do Frontend

A branch de producao do `ask-host-genius` e `main`. O repo usa `bun.lock`, entao
use Bun (nao `npm install`):

```bash
git checkout main
git reset --hard origin/main
bun install --frozen-lockfile
bun run build
bun run serve:staging
```

O app deve responder localmente em:

```text
http://127.0.0.1:5173/chat-ui
```

## Deploy No VPS

Use o script versionado, que segue `main` por padrao e valida o resultado:

```powershell
# da maquina local (envia e executa via SSH):
./scripts/deploy_ask_host_genius.ps1
# deploy pontual de outra branch, se necessario:
./scripts/deploy_ask_host_genius.ps1 -DeployBranch <branch>
```

O deploy so e valido se o bloco `depois` retornar `200` e o `Last-Modified` dos
assets em `/assets/*.js` passar a ser do dia do build. Se continuar antigo, o
servico esta servindo build velho (branch errada, diretorio errado ou container
nao rebuildado). Nao apontar o deploy para `codex/serve-chat-ui-via-proxy`: essa
branch e historica e fica atras de `main`.

## Configuracao Nginx

Exemplo:

```nginx
server {
    server_name chat.ordens.com.br;

    location = /chat-ui {
        proxy_pass http://127.0.0.1:5173/chat-ui;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location ^~ /assets/ {
        proxy_pass http://127.0.0.1:5173/assets/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location ^~ /web/ {
        proxy_pass http://127.0.0.1:8000/web/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location ^~ /team {
        proxy_pass http://127.0.0.1:5173/team;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Smoke

```bash
curl -i https://chat.ordens.com.br/chat-ui

curl -i https://chat.ordens.com.br/team

curl -i \
  -H "Content-Type: application/json" \
-d '{"message":"Como conectar o WhatsApp pela Meta API oficial?"}' \
  https://chat.ordens.com.br/web/chat
```

Verificar no browser:

- `/chat-ui` mostra o visual novo;
- `/team` abre o console do time (tela de login OTP), sem 404;
- assets carregam de `/assets/*`;
- chamada de chat sai para `/web/chat`;
- chamada de feedback sai para `/web/feedback`;
- o browser nao envia `X-API-Key` nem `X-LLM-API-Key`;
- cookie de sessao anonima continua `HttpOnly`.

## Rollback

1. Remover as regras Nginx de `/chat-ui`, `/team` e `/assets/` que apontam
   para `127.0.0.1:5173`.
2. Recarregar Nginx.
3. O backend volta a servir a UI estatica legada em `/chat-ui`, se
   `ENABLE_PUBLIC_CHAT_UI=true`. `/team` fica indisponivel ate a regra voltar.

## Riscos

- Se `/assets/*` nao for roteado para o frontend, a tela abre sem CSS/JS
  (isso afeta `/chat-ui` e `/team`, que compartilham o mesmo bundle).
- Se `VITE_API_BASE_URL` for preenchido com outro dominio, o browser passa a
  depender de CORS.
- Se `/web/*` nao ficar no backend, o chat nao conversa com o agente e o
  console do time (`/web/support/*`) para de autenticar.
- Se `/team` nao tiver uma regra Nginx propria, a requisicao cai no catch-all
  `location /` (backend Python) e retorna 404, mesmo com a pagina publicada
  no `ask-host-genius`.
- `npm run serve:staging` e adequado para staging. Para producao final, revisar
  target Node/Nitro dedicado antes de alto volume.

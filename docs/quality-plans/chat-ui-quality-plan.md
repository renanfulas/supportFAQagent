# Plano tecnico - Qualidade da chat UI local

## Objetivo

Manter a UI local `/chat-ui` alinhada ao contrato real de `POST /chat` e util
para testes controlados do dominio, preservando seguranca, legibilidade das
respostas e sinais importantes como referencias, handoff, `request_id` e
`error_code`.

Esta frente e de apoio ao MVP. Ela nao substitui n8n, WhatsApp ou um painel de
atendimento, mas acelera calibragem local com provider real em development e em
staging controlado quando `ENABLE_CHAT_UI=true`.

## Problema observado

A UI local ja envia perguntas para `/chat`, usa o dominio
`suporte-vps-whatsapp`, mantem um `session_id` web por carregamento da pagina e
mostra resposta, referencias e aviso de handoff. O relatorio de qualidade de
resposta apontou uma lacuna de apresentacao: se a resposta vier com Markdown ou
listas, a tela precisa renderizar de forma clara e segura.

Estado atual observado:

- `/chat-ui` e servido em development e em staging somente quando
  `ENABLE_CHAT_UI=true`; em production nao e registrado.
- os assets sao servidos em `/chat-assets`.
- a UI envia somente `domain`, `session_id` e `message` para `POST /chat`.
- a UI envia `X-LLM-API-Key` apenas quando o campo de chave tem valor.
- a UI nao envia `X-API-Key`, nao embute a chave local de desenvolvimento e nao
  persiste a chave do provider em `localStorage` ou `sessionStorage`.
- a resposta do modelo e inserida com `textContent`, sem `innerHTML`.
- quebras de linha ja sao preservadas visualmente por CSS com
  `white-space: pre-wrap`.
- referencias sao exibidas como nomes curtos de arquivo.
- handoff e exibido como aviso simples quando `escalated=true`.
- existem perguntas rapidas para primeiros passos, QR Code, risco de bloqueio e
  webhook n8n + Z-API.

Lacunas restantes:

- mostrar `request_id` na UI para debug e feedback.
- mostrar `error_code` quando a resposta trouxer falha observavel.
- mostrar `handoff_reasons` quando util para debug, sem poluir a resposta
  principal.
- melhorar apresentacao de listas Markdown simples sem abrir superficie para
  HTML inseguro.
- deixar mais claro no painel de chave que o campo aceita API key do provider ou
  alias do projeto apenas para teste controlado.

## Escopo

Entram nesta frente:

- revisar `app/static/chat/index.html`
- revisar `app/static/chat/app.js`
- revisar `app/static/chat/styles.css`
- revisar habilitacao em `app/main.py`
- validar contrato de `/chat` consumido pela UI
- revisar cobertura em `tests/test_app.py` e `tests/test_auth.py`
- testar manualmente em development e staging controlado quando houver mudanca
  visual ou de comportamento

Ficam fora desta frente:

- criar dashboard administrativo
- autenticar usuarios finais
- historico persistente de conversas
- upload de arquivos
- renderizar Markdown amplo sem sanitizacao
- expor `OPENAI_API_KEY` real no frontend
- persistir conversas, feedback ou chaves no navegador
- alterar o contrato HTTP de `/chat` sem atualizar
  `docs/integration-contracts.md` e testes de contrato

## Contrato de apresentacao esperado

A UI deve exibir:

- resposta do agente com quebras de linha legiveis
- referencias em formato curto
- aviso visual quando `escalated=true`
- motivos de handoff quando util para debug
- `request_id` da resposta
- `error_code` quando existir

O conteudo deve continuar inserido de forma segura no DOM, evitando `innerHTML`
para texto vindo da API.

Contrato HTTP consumido pela UI:

- `POST /chat`
- body: `domain`, `session_id` e `message`
- header opcional em development/staging controlado: `X-LLM-API-Key`
- sem `X-API-Key` no frontend local
- sem uploads, anexos, imagens, PDFs ou metadados de arquivo
- resposta esperada: `request_id`, `domain`, `answer`, `confidence`,
  `escalated`, `handoff_reasons`, `references` e `error_code`

Em staging, `X-LLM-API-Key` permite teste pela UI quando `ENABLE_CHAT_UI=true`.
Se o valor bater com `PROJECT_LLM_API_KEY_ALIAS`, o backend usa a chave privada
configurada no ambiente. O valor real de `OPENAI_API_KEY` nunca deve sair do
servidor.

## Arquivos alvo

```text
app/static/chat/index.html
app/static/chat/app.js
app/static/chat/styles.css
app/main.py
app/api/routes/chat.py
tests/test_app.py
tests/test_auth.py
docs/integration-contracts.md
docs/answer-quality-comparison.md
```

Observacao de ownership desta revisao: este plano foi atualizado sem editar os
arquivos alvo acima. Mudancas futuras na UI devem respeitar os donos das demais
frentes e tocar somente os arquivos necessarios.

## Implementacao sugerida

Passos recomendados:

- manter `textContent` como regra para texto vindo da API.
- manter preservacao de linhas com CSS seguro, como `white-space: pre-wrap`, ou
  nodes de texto criados explicitamente.
- adicionar bloco discreto de metadados por resposta.
- exibir `request_id` com botao visualmente simples para copiar se fizer sentido.
- mostrar `error_code` e `handoff_reasons` sem poluir a resposta principal.
- reforcar mensagem de que a chave do provider ou alias do projeto e apenas para
  teste controlado.
- manter as perguntas rapidas como atalhos de calibragem, sem transformar a UI em
  canal final.
- testar responsividade basica em mobile e desktop.

## Conteudo proibido

Esta frente nao deve:

- usar `innerHTML` com resposta do modelo
- guardar API key em localStorage, sessionStorage ou arquivo
- enviar `OPENAI_API_KEY` do servidor para o navegador
- aceitar anexos, imagens ou PDFs
- transformar a UI local em canal publico de atendimento sem hardening
- depender de `X-API-Key` no JavaScript da UI
- persistir `session_id`, mensagens ou chave do provider sem decisao explicita de
  produto e seguranca

## Testes a adicionar ou revisar

Casos minimos:

- `/chat-ui` e servido em development
- `/chat-ui` respeita flag em staging conforme documentado
- API key obrigatoria continua protegendo `/chat`
- campos novos de resposta nao quebram UI se ausentes
- resposta com multiplas linhas continua legivel
- provider key via `X-LLM-API-Key` funciona apenas quando a chat UI esta
  habilitada fora de production
- alias do projeto nao envia a chave real para o navegador
- provider key nao bypassa autenticacao em production
- renderer estatico continua sem `innerHTML`, sem `X-API-Key` e sem chave local
  de desenvolvimento embutida

Testes visuais podem ser manuais nesta fase, mas devem registrar o que foi
validado no PR.

## Validacao

Durante a frente:

```powershell
python -m pytest tests/test_app.py tests/test_auth.py
```

Validacao manual recomendada:

```powershell
uvicorn app.main:app --reload
```

Abrir:

```text
http://127.0.0.1:8000/chat-ui
```

Validacao completa antes de commit:

```powershell
python -m compileall app scripts tests
python -m pytest
```

## Criterios de pronto

- Respostas com listas e quebras de linha ficam legiveis.
- `request_id`, referencias, handoff e erro ficam acessiveis para debug.
- A UI nao usa HTML inseguro para conteudo do modelo.
- Chaves do provider nao sao persistidas no navegador.
- A UI nao envia `X-API-Key` e nao expoe chave local ou `OPENAI_API_KEY`.
- `/chat-ui` continua indisponivel em production, mesmo com flag ligada.
- A UI segue posicionada como ferramenta local/staging, nao canal final.

## Estimativa

- Ajustar metadados e handoff reasons: 45 a 90 minutos
- Refinar renderizacao segura de listas simples: 45 a 90 minutos
- Refinar CSS responsivo: 45 a 90 minutos
- Testar manualmente e revisar contrato: 30 a 60 minutos

Total esperado: 3 a 5 horas se incluir lista simples segura; 2 a 4 horas se a
mudanca ficar restrita a metadados e copy de seguranca.

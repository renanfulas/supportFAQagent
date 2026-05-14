# Plano tecnico - Qualidade da chat UI local

## Objetivo

Melhorar a UI local `/chat-ui` para testes controlados do dominio, preservando
seguranca, legibilidade das respostas e sinais importantes como referencias,
handoff e `request_id`.

Esta frente e de apoio ao MVP. Ela nao substitui n8n, WhatsApp ou um painel de
atendimento, mas acelera calibragem local com provider real.

## Problema observado

A UI local ja envia perguntas para `/chat` e mostra resposta, referencias e
handoff. O relatorio de qualidade de resposta apontou uma lacuna de apresentacao:
se a resposta vier com Markdown ou listas, a tela precisa renderizar de forma
clara e segura.

Lacunas principais:

- preservar quebras de linha sem usar HTML inseguro
- mostrar `request_id` para debug e feedback
- mostrar `error_code` quando houver falha observavel
- deixar referencias e handoff mais uteis para teste
- garantir que `X-LLM-API-Key` nao seja persistido nem logado no navegador
- manter a UI texto-only, sem uploads ou anexos

## Escopo

Entram nesta frente:

- revisar `app/static/chat/index.html`
- revisar `app/static/chat/app.js`
- revisar `app/static/chat/styles.css`
- revisar habilitacao em `app/main.py`
- validar contrato de `/chat` consumido pela UI
- testar manualmente em development e staging controlado

Ficam fora desta frente:

- criar dashboard administrativo
- autenticar usuarios finais
- historico persistente de conversas
- upload de arquivos
- renderizar Markdown amplo sem sanitizacao
- expor `OPENAI_API_KEY` real no frontend

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

## Arquivos alvo

```text
app/static/chat/index.html
app/static/chat/app.js
app/static/chat/styles.css
app/main.py
app/api/routes/chat.py
tests/test_app.py
tests/test_integration_contracts.py
docs/integration-contracts.md
docs/answer-quality-comparison.md
```

## Implementacao sugerida

Passos recomendados:

- trocar renderizacao da resposta para preservar linhas com CSS ou nodes seguros
- adicionar bloco discreto de metadados por resposta
- exibir `request_id` com botao visualmente simples para copiar se fizer sentido
- mostrar `error_code` e `handoff_reasons` sem poluir a resposta principal
- reforcar mensagem de que a chave do provider e apenas para teste controlado
- testar responsividade basica em mobile e desktop

## Conteudo proibido

Esta frente nao deve:

- usar `innerHTML` com resposta do modelo
- guardar API key em localStorage, sessionStorage ou arquivo
- enviar `OPENAI_API_KEY` do servidor para o navegador
- aceitar anexos, imagens ou PDFs
- transformar a UI local em canal publico de atendimento sem hardening

## Testes a adicionar ou revisar

Casos minimos:

- `/chat-ui` e servido em development
- `/chat-ui` respeita flag em staging conforme documentado
- API key obrigatoria continua protegendo `/chat`
- campos novos de resposta nao quebram UI se ausentes
- resposta com multiplas linhas continua legivel

Testes visuais podem ser manuais nesta fase, mas devem registrar o que foi
validado no PR.

## Validacao

Durante a frente:

```powershell
python -m pytest tests/test_app.py tests/test_integration_contracts.py
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
- A UI segue posicionada como ferramenta local/staging, nao canal final.

## Estimativa

- Ajustar renderizacao e metadados: 45 a 90 minutos
- Refinar CSS responsivo: 45 a 90 minutos
- Testar manualmente e revisar contrato: 30 a 60 minutos

Total esperado: 2 a 4 horas.

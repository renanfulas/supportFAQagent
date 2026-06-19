<p align="center">
  <img src="assets/images/hostgator-logo.png" alt="HostGator" width="420" />
</p>

<p align="center"><strong>Powered by HostGator</strong></p>

<p align="center">
  <img src="assets/images/hostgator-mascot.png" alt="HostGator mascot" width="120" />
</p>

# supportFAQagent

Agente de suporte com RAG para responder duvidas recorrentes de VPS, WhatsApp e automacoes com seguranca, rastreabilidade e escalonamento humano.

O `supportFAQagent` transforma conhecimento tecnico versionado em respostas consistentes, auditaveis e reutilizaveis por dominio. O primeiro dominio do produto e `suporte-vps-whatsapp`, voltado para atendimento tecnico de VPS, WhatsApp e automacoes operacionais.

## O Problema

Equipes de suporte perdem tempo com perguntas repetidas, respostas inconsistentes e dificuldade para saber quando um bot deve parar e chamar uma pessoa.

Este projeto resolve isso com um nucleo Python modular que:

- responde com base em conhecimento controlado
- evita inventar respostas quando falta contexto
- registra `request_id`, referencias e motivos de escalonamento
- permite evoluir de um dominio inicial para varios setores
- prepara integracao nativa com Meta WhatsApp Cloud API, adapters temporarios
  como Hermes e PostgreSQL/pgvector

## O Que Ja Funciona

- API HTTP com FastAPI
- dominio inicial para suporte de VPS, WhatsApp e automacoes
- retrieval lexical como padrao seguro para local/CI
- retrieval PostgreSQL/pgvector como default operacional do staging por
  `RETRIEVAL_BACKEND=pgvector`
- provider real de LLM com OpenAI/Anthropic
- fallback seguro quando credenciais ou providers falham
- handoff estruturado por baixa confianca, pedido humano, termo sensivel ou erro tecnico
- feedback persistente e confiavel quando `PERSISTENCE_BACKEND=postgres`
- fachada publica `POST /web/chat` e `POST /web/feedback` para website sem expor segredo no navegador
- adaptador para ler arquivos do GitHub pela Contents API oficial, sem scraping de HTML
- rate limit no `/chat`
- `X-Request-ID` em todas as respostas
- testes automatizados cobrindo API, seguranca, retrieval, LLM, handoff e contratos

## Casos De Uso

- atendimento inicial em WhatsApp
- atendimento inicial em website com chat publico controlado
- suporte tecnico para VPS
- triagem de duvidas recorrentes
- consulta a FAQs e artigos internos
- canais externos consumindo uma API estavel, sem mover inteligencia para fora
  do backend
- base para agentes reutilizaveis em outros dominios

## Como Funciona

```text
Canal externo
  -> FastAPI
  -> Configuracao do dominio
  -> Retrieval de conhecimento
  -> Prompt builder
  -> LLM provider
  -> Resposta com confianca, referencias e handoff
```

O dominio define persona, escopo, regras de resposta, limites, provider de LLM, embedding e politica de escalonamento.

## Exemplo De Uso

Request:

```json
{
  "message": "Como conectar o WhatsApp pela Meta API oficial?",
  "session_id": "whatsapp:+5511999999999",
  "domain": "suporte-vps-whatsapp"
}
```

Response:

```json
{
  "request_id": "uuid",
  "domain": "suporte-vps-whatsapp",
  "answer": "Resposta final para o usuario.",
  "confidence": 0.82,
  "escalated": false,
  "handoff_reasons": [],
  "references": ["article-or-chunk-id"],
  "error_code": null
}
```

## Seguranca E Controle

O projeto foi desenhado para uso operacional controlado:

- secrets fora do Git
- `API_SECRET_KEY` obrigatorio fora de desenvolvimento
- logs com cuidado para nao expor dados sensiveis
- fallback seguro em falha de provider
- rate limit no endpoint de chat
- rastreabilidade por `request_id`
- escalonamento quando o contexto nao for suficiente

## Status Do Produto

Pronto no MVP atual:

- API principal
- dominio inicial
- resposta com fallback seguro
- handoff estruturado
- persistencia PostgreSQL de feedback, conversas e mensagens sanitizadas por
  feature flag
- historico curto real isolado por dominio, canal e hash de sessao
- readiness separado para banco, migrations, retrieval e outbox
- retrieval lexical preservado como fallback local e rollback operacional
- pgvector promovido como default operacional do staging real
- `pgvector_gate.yaml` validada em staging com `76/78`
- Fase 0 implementada e validada localmente com PostgreSQL/pgvector real,
  migrations `001-008` e `356` testes verdes
- fundacao Meta WhatsApp Cloud API implementada por feature flag, com webhook,
  parser, cliente HTTP, entrega OTP e transporte de chat desativados por padrao
- Hermes disponivel apenas como adapter temporario para entrega OTP
- testes e documentacao base

Proxima fase operacional:

- executar restore cronometrado em ambiente isolado e medir `RPO <= 24h` /
  `RTO <= 4h`
- executar smoke privado da Meta WhatsApp Cloud API antes de qualquer ativacao
  real
- manter Hermes como ponte temporaria somente se reduzir risco operacional
- operacao reproduzivel e monitoramento da VPS
- acompanhar pgvector como default do staging com rollback documentado para
  lexical

Roadmap:

- calibragem com perguntas reais
- expansao para novos dominios

Risco operacional conhecido:

- o staging chegou a `100%` de uso do disco por cache de build Docker; depois
  da limpeza e promocao parcial ficou em `81%`, portanto precisa de alerta e
  politica de limpeza antes de producao
- a Fase 0 operacional continua `not_approved` ate o restore isolado passar;
  `n8n` nao e mais gate ativo do MVP

## Estrutura

```text
app/
  api/               # rotas e schemas HTTP
  core/              # configuracao, logging e utilitarios
  db/                # modelos e conexao de persistencia
  domain_engine/     # carga de dominios, prompts e politicas
  evals/             # runner e modelos de calibragem local
  feedback/          # contrato e servico de feedback operacional
  handoff/           # regras reutilizaveis de escalonamento humano
  ingestion/         # leitura e chunking da base de conhecimento
  llm/               # contratos e provedores de modelos
  orchestration/     # fluxo principal de atendimento
  retrieval/         # embeddings, vetores e recuperacao
  static/            # chat UI local para validacao controlada
domains/
  suporte-vps-whatsapp/
    domain.yaml
    knowledge/
    prompts/
docs/                # arquitetura, produto, contratos, runbooks e seguranca
  archive/           # planos concluidos, relatorios substituidos e roadmaps historicos
migrations/          # scripts SQL e artefatos de evolucao do banco
scripts/             # comandos operacionais
tests/               # testes unitarios e de integracao
```

## Rodando Localmente

1. Crie um ambiente virtual.
2. Instale as dependencias:

```bash
pip install -e ".[dev]"
```

3. Copie `.env.example` para `.env`.
4. Rode a API:

```bash
uvicorn app.main:app --reload
```

O `pyproject.toml` e a unica fonte de dependencias. Instale o projeto e seus
extras diretamente por ele; nao mantenha listas paralelas de pacotes.

Para usar o prototipo local com ChromaDB e CSV:

```bash
pip install -e ".[chroma]"
```

Em `APP_ENV=development`, a API tambem pode servir uma tela local de chat para testes controlados. A V0 tambem pode expor a `chat-ui` como superficie publica controlada quando `ENABLE_PUBLIC_CHAT_UI=true`, usando os endpoints `POST /web/chat` e `POST /web/feedback` sem enviar `X-API-Key` ao navegador. Em staging, a tela antiga baseada em `ENABLE_CHAT_UI=true` continua disponivel apenas para validacao interna com `X-LLM-API-Key`. Nenhuma dessas superficies substitui integracoes externas como Meta WhatsApp, Hermes ou outros consumidores servidor-servidor.

## Testes

```bash
python -m compileall app tests scripts
python -m pytest
```

## Documentacao

Comece por [Como navegar no projeto](docs/navigation.md). Ele apresenta um
percurso inicial curto e direciona cada tipo de tarefa para os documentos
necessarios, sem exigir a leitura de toda a base.

- [Como contribuir](CONTRIBUTING.md): setup, regras e validacoes.
- [Arquitetura](docs/architecture.md): limites e fluxo do sistema.
- [Estado da documentacao](docs/documentation-status.md): fontes ativas de verdade.
- [Plano unico do MVP](docs/mvp-plan.md): status e proxima fase.
- [Archive](docs/archive/README.md): planos concluidos e registros historicos.

## Contribuicao

Este projeto cresce por dominios. Antes de adicionar comportamento novo, alinhe a mudanca com a arquitetura modular existente e leia o [guia de contribuicao](CONTRIBUTING.md).

Ao escrever docs, issues, PRs ou prompts para agentes, preserve o posicionamento do produto: serio, operacional, rastreavel e seguro. Evite prometer autonomia total ou substituir suporte humano; o valor esta em reduzir repeticao, melhorar consistencia e escalar quando falta contexto.

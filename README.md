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
- prepara integracao com WhatsApp, n8n e PostgreSQL/pgvector

## O Que Ja Funciona

- API HTTP com FastAPI
- dominio inicial para suporte de VPS, WhatsApp e automacoes
- retrieval lexical como padrao seguro
- retrieval PostgreSQL/pgvector disponivel por `RETRIEVAL_BACKEND=pgvector`
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
- automacoes com n8n consumindo uma API estavel
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
  "message": "Como conectar o WhatsApp na Evolution API?",
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
- retrieval lexical
- pgvector validado em staging real por feature flag
- `pgvector_gate.yaml` validada em staging com `74/78`
- testes e documentacao base

Proxima fase operacional:

- persistencia de conversas e feedback
- integracao n8n/WhatsApp
- operacao reproduzivel e monitoramento da VPS
- decisao operacional sobre promocao do pgvector como default

Roadmap:

- calibragem com perguntas reais
- expansao para novos dominios

Risco operacional conhecido:

- o staging chegou a `100%` de uso do disco por cache de build Docker; depois
  da limpeza ficou em `90%`, portanto precisa de alerta e politica de limpeza
  antes de producao

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

O `pyproject.toml` e a fonte unica de dependencias. O `requirements.txt`
existe apenas como wrapper de compatibilidade para comandos antigos baseados em
`pip install -r requirements.txt`.

Para usar o prototipo local com ChromaDB e CSV:

```bash
pip install -e ".[chroma]"
```

Em `APP_ENV=development`, a API tambem pode servir uma tela local de chat para testes controlados. A V0 tambem pode expor a `chat-ui` como superficie publica controlada quando `ENABLE_PUBLIC_CHAT_UI=true`, usando os endpoints `POST /web/chat` e `POST /web/feedback` sem enviar `X-API-Key` ao navegador. Em staging, a tela antiga baseada em `ENABLE_CHAT_UI=true` continua disponivel apenas para validacao interna com `X-LLM-API-Key`. Nenhuma dessas superficies substitui integracoes externas como n8n ou WhatsApp.

## Testes

```bash
python -m compileall app tests scripts
python -m pytest
```

## Documentacao

- [Posicionamento do produto](docs/product-positioning.md)
- [Arquitetura](docs/architecture.md)
- [Plano unico do MVP](docs/mvp-plan.md)
- [Contrato de dominio](docs/domain-contract.md)
- [Calibragem de dominio](docs/domain-evals.md)
- [Como escrever artigos bons para RAG](docs/knowledge-authoring.md)
- [Planos de qualidade por frente](docs/quality-plans/README.md)
- [Plano de qualidade de retrieval vetorial](docs/quality-plans/vector-retrieval-quality-plan.md)
- [Fase 0 de reducao de risco operacional](docs/quality-plans/phase0-operational-risk-reduction.md)
- [Revisao da base de conhecimento](docs/quality-plans/knowledge-base-review-2026-05-17.md)
- [Runbook de intake anonimo para evals](docs/runbooks/anonymous-eval-intake.md)
- [Runbook da gate pgvector em staging](docs/runbooks/staging-pgvector-gate.md)
- [Runbook de eval pgvector real em staging](docs/runbooks/staging-pgvector-real-eval.md)
- [Relatorio oficial do baseline local pgvector](docs/runbooks/local-pgvector-baseline-report.md)
- [Runbook de smoke HTTP automatizado em staging](docs/runbooks/staging-http-smoke.md)
- [Runbook de contrato n8n/WhatsApp](docs/runbooks/n8n-whatsapp-chat-contract.md)
- [Runbook de workflows n8n versionados](docs/runbooks/n8n-versioned-workflows.md)
- [Runbook de snapshot e restore da Fase 0](docs/runbooks/phase0-snapshot-restore.md)
- [Checklist de promocao do pgvector](docs/runbooks/pgvector-promotion-checklist.md)
- [Mapa oficial de ambientes](docs/environments.md)
- [Observabilidade minima](docs/observability.md)
- [Politica publica de seguranca](SECURITY.md)
- [Plano de seguranca da VPS](docs/security/vps-security-plan.md)
- [Confinamento por design para LLM e RAG](docs/security/llm-confinement.md)
- [Acompanhamento de implementacao de seguranca](docs/security/implementation-tracking.md)
- [Guia de Git para seguranca](docs/security/git-commit-guide.md)
- [Agent skills universais](docs/agent-skills.md)
- [Plano tecnico de implementacao](docs/technical-implementation-plan.md)
- [Contratos de integracao](docs/integration-contracts.md)
- [Como navegar no projeto](docs/navigation.md)
- [Regras simples do codigo](docs/code-standards.md)
- [Como contribuir](CONTRIBUTING.md)

## Contribuicao

Este projeto cresce por dominios. Antes de adicionar comportamento novo, alinhe a mudanca com a arquitetura modular existente e leia o [guia de contribuicao](CONTRIBUTING.md).

Ao escrever docs, issues, PRs ou prompts para agentes, preserve o posicionamento do produto: serio, operacional, rastreavel e seguro. Evite prometer autonomia total ou substituir suporte humano; o valor esta em reduzir repeticao, melhorar consistencia e escalar quando falta contexto.

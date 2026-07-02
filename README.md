<p align="center">
  <img src="assets/images/hostgator-logo.png" alt="HostGator" width="420" />
</p>

<p align="center"><strong>Powered by HostGator</strong></p>

<p align="center">
  <img src="assets/images/hostgator-mascot.png" alt="HostGator mascot" width="120" />
</p>

# supportFAQagent

Agente de suporte com RAG para responder duvidas recorrentes de VPS, WhatsApp e automacoes com seguranca, rastreabilidade e escalonamento humano.

O `supportFAQagent` transforma conhecimento tecnico versionado em respostas consistentes, auditaveis e reutilizaveis por dominio. O mesmo nucleo atende hoje dominios diferentes com personas e politicas proprias: `suporte-vps-whatsapp` (atendimento tecnico de VPS, WhatsApp e automacoes) e `vendas` (qualificacao consultiva e recomendacao de planos), com dominios adicionais de suporte em preparacao — a tese de reutilizacao por dominio deixou de ser promessa e virou operacao.

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
- multiplos dominios no mesmo nucleo: suporte tecnico (VPS/WhatsApp/automacoes)
  e vendas consultivas, cada um com persona, escopo, conhecimento e politica de
  escalonamento proprios, mais flags de comportamento por dominio
- roteamento de dominio por mensagem no WhatsApp com saudacao conversacional
  (sem menu numerado) e stickiness duravel de sessao (PostgreSQL) para o
  cliente nao ser rebaixado a saudacao a cada turno
- retrieval lexical como padrao seguro para local/CI
- retrieval PostgreSQL/pgvector como default operacional do staging por
  `RETRIEVAL_BACKEND=pgvector`
- provider real de LLM com OpenAI/Anthropic
- fallback seguro quando credenciais ou providers falham
- handoff estruturado por baixa confianca, pedido humano, termo sensivel ou erro
  tecnico, com taxonomia que separa sinal fraco (so log/metrica) de fila humana
  real
- ticket duravel de suporte (`support_cases`) criado na mesma transacao do turno
  escalado, inbox interno de leitura para triagem do time e notificacao WhatsApp
  ao time com contexto sanitizado
- identidade de cliente no web chat por OTP via WhatsApp, com gate de
  consentimento LGPD antes de qualquer contato direto do time
- historico curto real por sessao + resumo de atendimentos anteriores
  (sumarizacao noturna + recall no prompt, marcado como dado nao confiavel)
- detector de numero de cartao (Luhn) que recusa checkout, redige antes de
  persistir e nunca ecoa o dado
- feedback persistente e confiavel quando `PERSISTENCE_BACKEND=postgres`
- fachada publica `POST /web/chat` e `POST /web/feedback` para website sem expor segredo no navegador
- adaptador para ler arquivos do GitHub pela Contents API oficial, sem scraping de HTML
- rate limit no `/chat`
- `X-Request-ID` em todas as respostas
- testes automatizados cobrindo API, seguranca, retrieval, LLM, handoff e
  contratos, mais suites de eval por dominio (casos base, confinamento,
  dados de pagamento, recall de resumo e gate pgvector)

## Casos De Uso

- atendimento inicial em WhatsApp
- atendimento inicial em website com chat publico controlado
- suporte tecnico para VPS
- qualificacao consultiva de leads e recomendacao de planos, com escalonamento
  humano para pagamento, contrato e cobranca
- triagem de duvidas recorrentes
- consulta a FAQs e artigos internos
- triagem humana de tickets escalados com contexto de conversa organizado
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
- dois dominios operacionais (suporte tecnico e vendas consultivas), com
  roteamento por mensagem e stickiness duravel no WhatsApp
- resposta com fallback seguro
- handoff estruturado com taxonomia de motivos, ticket duravel, inbox interno
  de triagem e notificacao WhatsApp ao time
- identidade de cliente por OTP no web chat com gate de consentimento LGPD
- persistencia PostgreSQL de feedback, conversas e mensagens sanitizadas por
  feature flag (migrations `001-013`)
- persistencia em camadas: estado quente de sessao em Redis, sumarizacao
  noturna de conversas e recall do resumo no prompt — tudo atras de flag e
  ligado em staging
- historico curto real isolado por dominio, canal e hash de sessao
- readiness separado para banco, migrations, retrieval e outbox
- retrieval lexical preservado como fallback local e rollback operacional
- pgvector promovido como default operacional do staging real
- `pgvector_gate.yaml` validada em staging com `76/78`
- alerta de capacidade de disco da VPS via systemd timer, com aviso por
  WhatsApp em nivel critico e guarda dos volumes PostgreSQL contra limpeza
  indevida
- fundacao Meta WhatsApp Cloud API implementada por feature flag, com webhook,
  parser, cliente HTTP, entrega OTP e transporte de chat desativados por padrao
- Hermes operando como ponte temporaria de chat WhatsApp em staging (cutover
  verificado ponta a ponta), alem da entrega de OTP; a direcao estrategica
  segue sendo a Meta WhatsApp Cloud API nativa
- suites de eval por dominio (casos base, confinamento, pagamento, recall de
  resumo), `679` testes verdes
- testes e documentacao base, com mapa vivo em `docs/project-map.md`

Proxima fase operacional:

- executar restore cronometrado em ambiente isolado e medir `RPO <= 24h` /
  `RTO <= 4h` (ferramenta e run-sheet prontos; falta a execucao no host
  isolado)
- executar smoke privado da Meta WhatsApp Cloud API antes de qualquer ativacao
  real
- ligar o archive sink off-box (Cloudflare R2) quando as credenciais chegarem
- registrar a metrica de custo da sumarizacao
- acompanhar pgvector como default do staging com rollback documentado para
  lexical

Roadmap:

- expansao para novos dominios de suporte (hospedagem) e o minion de
  diagnostico (contrato HTTP ja especificado, v1 somente leitura)
- calibragem continua com perguntas reais

Risco operacional conhecido:

- a Fase 0 operacional continua `not_approved` ate o restore isolado passar;
  `n8n` foi removido do projeto e nao e gate do MVP
- o disco do staging ja atingiu `100%` no passado; hoje opera em ~`63%` com
  alerta automatico ativo e politica de limpeza documentada
  (`docs/runbooks/vps-capacity-and-docker-cleanup.md`)

## Estrutura

```text
app/
  api/               # rotas e schemas HTTP
  conversations/     # historico, estado de sessao, sumarizacao e recall
  core/              # configuracao, logging, sanitizacao e utilitarios
  db/                # modelos, conexao e escrita operacional (audit/outbox)
  domain_engine/     # carga de dominios, roteador e politicas
  evals/             # runner e modelos de calibragem local
  feedback/          # contrato e servico de feedback operacional
  handoff/           # regras reutilizaveis e taxonomia de escalonamento humano
  health/            # readiness por dependencia
  identity/          # resolucao da identidade atual do cliente
  ingestion/         # leitura e chunking da base de conhecimento
  integrations/      # transportes externos (Hermes, Meta WhatsApp)
  llm/               # contratos e provedores de modelos
  notifications/     # renderizacao de alertas ao time
  orchestration/     # fluxo principal de atendimento
  retrieval/         # embeddings, vetores e recuperacao
  static/            # chat UI local para validacao controlada
  support/           # inbox interno e contexto de tickets
  web_auth/          # OTP via WhatsApp para o web chat
domains/                  # cada dominio: domain.yaml, knowledge/, prompts/, evals/
  suporte-vps-whatsapp/   # suporte tecnico (dominio operacional)
  vendas/                 # vendas consultivas (dominio operacional)
  suporte-hospedagem/     # em preparacao
  suporte-vps/            # em preparacao
docs/                # documentacao por pasta (mapa em docs/project-map.md)
  architecture/      # design, fronteiras, contratos e padroes do sistema
  setup/             # guias de instalacao e configuracao de ambiente
  MVP/               # planos tecnicos majoritarios do MVP
  quality-plans/     # planos detalhados por frente do MVP
  runbooks/          # procedimentos operacionais de execucao
  security/          # planos e contratos de seguranca
  archive/           # planos concluidos, relatorios substituidos e historicos
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

Comece pelo [Mapa do projeto](docs/project-map.md): estado de cada frente (o
que ja foi feito, o que esta em andamento e o que falta) e a organizacao das
pastas de documentacao. Para roteamento por tarefa, use
[Como navegar no projeto](docs/navigation.md), que direciona cada tipo de
mudanca para os documentos necessarios sem exigir a leitura de toda a base.

- [Mapa do projeto](docs/project-map.md): frentes, status e mapa das pastas.
- [Como contribuir](CONTRIBUTING.md): setup, regras e validacoes.
- [Arquitetura](docs/architecture/architecture.md): limites e fluxo do sistema.
- [Estado da documentacao](docs/documentation-status.md): fontes ativas de verdade.
- [Plano unico do MVP](docs/MVP/mvp-plan.md): status e proxima fase.
- [Archive](docs/archive/README.md): planos concluidos e registros historicos.
- [Indice de redirecionamento](docs/references-legacy.md): caminhos antigos -> novos.

## Contribuicao

Este projeto cresce por dominios. Antes de adicionar comportamento novo, alinhe a mudanca com a arquitetura modular existente e leia o [guia de contribuicao](CONTRIBUTING.md).

Ao escrever docs, issues, PRs ou prompts para agentes, preserve o posicionamento do produto: serio, operacional, rastreavel e seguro. Evite prometer autonomia total ou substituir suporte humano; o valor esta em reduzir repeticao, melhorar consistencia e escalar quando falta contexto.

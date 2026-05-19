<p align="center">
  <img src="assets/images/hostgator-logo.png" alt="HostGator" width="420" />
</p>

<p align="center"><strong>Powered by HostGator</strong></p>

<p align="center">
  <img src="assets/images/hostgator-mascot.png" alt="HostGator mascot" width="120" />
</p>

# supportFAQagent

Plataforma em Python para agentes de atendimento por dominio com RAG, preparada para reutilizar a mesma base tecnica em diferentes setores.

## MVP inicial

O primeiro dominio do projeto e `suporte-vps-whatsapp`.

Objetivos desta primeira versao:

- expor uma API HTTP com FastAPI
- carregar configuracoes por dominio
- validar contratos de dominio para facilitar reuso em outros setores
- ingerir artigos e FAQs locais
- gerar chunks para RAG
- preparar a base para busca vetorial e respostas com LLM
- definir regras simples de escalonamento para humano

Estado atual:

- `/chat` usa retrieval lexical como padrao seguro, mas ja pode usar `pgvector`
  via `RETRIEVAL_BACKEND=pgvector` quando o ambiente tiver `DATABASE_URL`,
  embeddings e dados ingeridos
- `LLMService` ja roteia para OpenAI/Anthropic e preserva tratamento de erro quando faltar credencial ou o provider falhar
- ja existem utilitarios para LangChain, Chroma, embeddings, prompt builder e CSV de chamados
- smoke tests cobrem healthcheck, dominios, preview de ingestao e chat com fallback seguro
- `POST /feedback` ja aceita contexto operacional opcional como `escalated`, `handoff_reasons`, `references` e `error_code`
- `PostgreSQL + pgvector` ja foi validado em staging privado como caminho
  ponta a ponta de retrieval vetorial, ainda aguardando calibragem antes de
  virar padrao permanente

Avancos recentes ja incorporados entre 13/05/2026 e 16/05/2026:

- provider real `openai` configurado no dominio inicial
- factory de embeddings conectada ao caminho de retrieval, sem tornar `pgvector` o backend oficial ainda
- chunking consolidado e indices normalizados
- `chat-ui` local/staging em texto para testes controlados
- classificacao de falhas de provider e fallback seguro
- handoff calibrado com motivos estruturados e contrato de feedback expandido
- hardening de runtime com `API_SECRET_KEY` fora de desenvolvimento e rate limit no `/chat`
- contrato Python do `PgVectorStore`, validacao SQL executavel e docs do ambiente oficial
- runbook de contingencia operacional da VPS e script `scripts/runtime_preflight.ps1`
- backend real PostgreSQL/pgvector por `DATABASE_URL`, writer de ingestao
  persistente e smoke em staging com embeddings reais do dominio inicial

## Estrutura

```text
app/
  api/               # rotas e schemas HTTP
  core/              # configuracao, logging e utilitarios
  db/                # modelos e conexao de persistencia
  domain_engine/     # carga de dominios, prompts e politicas
  ingestion/         # leitura e chunking da base de conhecimento
  llm/               # contratos e provedores de modelos
  orchestration/     # fluxo principal de atendimento
  retrieval/         # embeddings, vetores e recuperacao
domains/
  suporte-vps-whatsapp/
    domain.yaml
    knowledge/
    prompts/
scripts/             # comandos operacionais
tests/               # testes unitarios e de integracao
```

## Rodando localmente

1. Crie um ambiente virtual.
2. Instale as dependencias com `pip install -e .[dev]`
3. Copie `.env.example` para `.env`
4. Rode a API com `uvicorn app.main:app --reload`

Em `APP_ENV=development`, a API tambem pode servir uma tela local de chat para testes controlados.
Em ambientes nao produtivos, essa superficie pode ser habilitada de forma explicita para validacao interna.
Ela nao substitui integracoes externas como n8n ou WhatsApp.

## Estado atual do MVP

- a arquitetura oficial do projeto e a modular em `app/api`, `app/domain_engine`, `app/ingestion`, `app/orchestration`, `app/retrieval` e `app/llm`
- o bootstrap HTTP fica em `app/main.py`
- o fluxo de resposta usa retrieval lexical local como padrao seguro, com
  `pgvector` disponivel por feature flag de ambiente
- o contrato de dominio ja controla persona, objetivo, diretrizes, escopo, mensagens padrao e politica de handoff
- o `LLMService` ja usa `LLMWrapper` com OpenAI/Anthropic quando o dominio aponta para provider real
- o `ChatFlowService` ja usa `prompt_builder.py` como ponto unico de montagem de prompt
- handoff ja retorna motivos estruturados como baixa confianca, pedido de humano, assunto sensivel e falha tecnica observavel
- `/chat` ja retorna `request_id` e `error_code` para facilitar debug
- todas as respostas HTTP retornam `X-Request-ID` para correlacao de logs e integracoes
- retrieval ja passa por uma interface de adapter, com lexical padrao,
  `pgvector` validado em staging e Chroma como prototipo local
- contratos de entrada ja possuem limites basicos para reduzir payloads abusivos
- a ingestao ja possui endpoints de preview para validacao controlada por operadores autenticados
- existe um adaptador Python para ler arquivos do GitHub via Contents API oficial, sem scraping de HTML, em `app/ingestion/github_loader.py`
- o dominio inicial ja possui evals locais para calibrar respostas e escalonamento com casos reais
- `POST /feedback` continua em `pending_persistence`, mas ja preserva contexto util para integracoes externas e persistencia futura

## Testes basicos

Depois da instalacao, rode:

```bash
python -m pytest
```

## Documentacao

- [Arquitetura](docs/architecture.md)
- [Plano unico do MVP](docs/mvp-plan.md)
- [Contrato de dominio](docs/domain-contract.md)
- [Calibragem de dominio](docs/domain-evals.md)
- [Como escrever artigos bons para RAG](docs/knowledge-authoring.md)
- [Planos de qualidade por frente](docs/quality-plans/README.md)
- [Plano de qualidade de retrieval vetorial](docs/quality-plans/vector-retrieval-quality-plan.md)
- [Revisao da base de conhecimento](docs/quality-plans/knowledge-base-review-2026-05-17.md)
- [Runbook de intake de perguntas anonimas HostGator](docs/runbooks/hostgator-anonymous-eval-intake.md)
- [Runbook de eval pgvector real em staging](docs/runbooks/staging-pgvector-real-eval.md)
- [Runbook de smoke HTTP automatizado em staging](docs/runbooks/staging-http-smoke.md)
- [Runbook de contrato n8n/WhatsApp](docs/runbooks/n8n-whatsapp-chat-contract.md)
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

## Proximos passos

- calibrar retrieval, confidence e handoff com perguntas reais usando
  `RETRIEVAL_BACKEND=pgvector`
- decidir quando promover `pgvector` de feature flag validada para padrao
  permanente do runtime
- persistir conversas e feedback
- preparar integracao n8n consumindo `/chat` e preservando `request_id`,
  `references`, `handoff_reasons` e `error_code`

## Evitar retrabalho

- nao reimplementar provider real, fallback seguro, `chat-ui`, handoff calibrado, contrato de feedback ou hardening basico de runtime: essas frentes ja avancaram no historico recente
- nao promover `Chroma` a fonte oficial de producao enquanto `PostgreSQL + pgvector` segue como caminho principal planejado
- nao misturar a contingencia de VPS com ownership de schema SQL, migrations, indices, queries finais de `pgvector` ou persistencia real, que continuam com Alexandre

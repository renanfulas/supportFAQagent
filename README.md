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

- `/chat` usa retrieval lexical temporario com provider real configurado por dominio
- `LLMService` ja roteia para OpenAI/Anthropic e preserva tratamento de erro quando faltar credencial ou o provider falhar
- ja existem utilitarios para LangChain, Chroma, embeddings, prompt builder e CSV de chamados
- smoke tests cobrem healthcheck, dominios, preview de ingestao e chat com fallback seguro
- `PostgreSQL + pgvector` segue como integracao planejada para o retrieval principal

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

Em `APP_ENV=development`, a API tambem serve uma tela local de chat em `/chat-ui`.
Em staging, essa tela pode ser liberada com `ENABLE_CHAT_UI=true`.
Ela e apenas texto, chama o contrato `POST /chat` e nao substitui integracoes externas como n8n ou WhatsApp.
Para testes controlados, a UI aceita uma chave do provider por requisicao via `X-LLM-API-Key`;
se o valor enviado bater com `PROJECT_LLM_API_KEY_ALIAS`, o backend usa a chave privada configurada em `OPENAI_API_KEY`.

## Estado atual do MVP

- a arquitetura oficial do projeto e a modular em `app/api`, `app/domain_engine`, `app/ingestion`, `app/orchestration`, `app/retrieval` e `app/llm`
- o bootstrap HTTP fica em `app/main.py`
- o fluxo de resposta usa retrieval lexical local como caminho ativo e provider real configurado no dominio padrao
- o contrato de dominio ja controla persona, objetivo, diretrizes, escopo, mensagens padrao e politica de handoff
- o `LLMService` ja usa `LLMWrapper` com OpenAI/Anthropic quando o dominio aponta para provider real
- o `ChatFlowService` ja usa `prompt_builder.py` como ponto unico de montagem de prompt
- handoff ja retorna motivos estruturados como baixa confianca, pedido de humano e assunto sensivel
- `/chat` ja retorna `request_id` e `error_code` para facilitar debug
- todas as respostas HTTP retornam `X-Request-ID` para correlacao de logs e integracoes
- retrieval ja passa por uma interface de adapter, com lexical padrao e Chroma como prototipo local
- contratos de entrada ja possuem limites basicos para reduzir payloads abusivos
- a ingestao ja possui preview por payload em `POST /ingestion/preview` e preview local por dominio em `/ingestion/{domain_name}/preview`
- o dominio inicial ja possui evals locais para calibrar respostas e escalonamento com casos reais

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
- [Plano de qualidade de chat, prompt e handoff](docs/quality-plans/chat-handoff-quality-plan.md)
- [Plano de qualidade de feedback e n8n](docs/quality-plans/feedback-n8n-quality-plan.md)
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

- estabilizar o uso de provider real com credenciais de ambiente e observabilidade de falhas
- integrar PostgreSQL + pgvector como vector store principal
- conectar o adapter vetorial oficial ao retrieval principal
- persistir conversas e feedback
- calibrar thresholds e termos sensiveis com conversas reais

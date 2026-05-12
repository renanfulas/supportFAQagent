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

- `/chat` ainda usa retrieval lexical temporario e provider mock
- `LLMService` ja consegue rotear para OpenAI/Anthropic quando o dominio trocar o provider
- ja existem utilitarios para LangChain, Chroma, embeddings, prompt builder e CSV de chamados
- smoke tests cobrem healthcheck, dominios, preview de ingestao e chat mock
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

## Estado atual do MVP

- a arquitetura oficial do projeto e a modular em `app/api`, `app/domain_engine`, `app/ingestion`, `app/orchestration`, `app/retrieval` e `app/llm`
- o bootstrap HTTP fica em `app/main.py`
- o fluxo de resposta usa retrieval lexical local e `MockLLMProvider` no dominio padrao, sem depender de LangChain/Chroma no runtime atual
- o contrato de dominio ja controla persona, objetivo, diretrizes, escopo, mensagens padrao e politica de handoff
- o `LLMService` ja esta preparado para usar `LLMWrapper` com OpenAI/Anthropic quando o dominio for configurado para isso
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

- trocar o dominio de `mock` para provider real quando houver API key configurada
- consolidar o splitter LangChain com a ingestao oficial
- integrar PostgreSQL + pgvector como vector store principal
- conectar provider real de embeddings ao retrieval
- persistir conversas e feedback
- calibrar thresholds e termos sensiveis com conversas reais

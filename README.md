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
- ingerir artigos e FAQs locais
- gerar chunks para RAG
- preparar a base para busca vetorial e respostas com LLM
- definir regras simples de escalonamento para humano

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
- o fluxo de resposta usa retrieval lexical local e `MockLLMProvider`, sem dependencias de LangChain/Chroma no runtime atual
- o endpoint de ingestao disponivel hoje e de preview local por dominio em `/ingestion/{domain_name}/preview`

## Testes basicos

Depois da instalacao, rode:

```bash
python -m pytest
```

## Documentacao

- [Arquitetura](docs/architecture.md)
- [Plano unico do MVP](docs/mvp-plan.md)
- [Plano tecnico de implementacao](docs/technical-implementation-plan.md)
- [Como navegar no projeto](docs/navigation.md)
- [Regras simples do codigo](docs/code-standards.md)
- [Como contribuir](CONTRIBUTING.md)

## Proximos passos

- integrar PostgreSQL + pgvector
- adicionar provider real de embeddings
- adicionar provider real de LLM
- persistir conversas e feedback
- evoluir o roteamento entre dominios

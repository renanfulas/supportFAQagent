# Contribuindo

Este projeto foi desenhado para crescer por dominios. Antes de abrir codigo novo, alinhe sua mudanca com a arquitetura modular existente.

## Como começar

1. Crie um ambiente virtual Python.
2. Instale as dependencias com `pip install -e .`
3. Copie `.env.example` para `.env`
4. Rode a API com `uvicorn app.main:app --reload`

## Fluxo recomendado

1. Entenda em qual camada sua mudanca pertence.
2. Evite adicionar logica de negocio direto nas rotas.
3. Prefira evoluir servicos e modelos antes de criar atalhos locais.
4. Se a mudanca for especifica de um dominio, coloque a configuracao em `domains/`.
5. Se a mudanca for compartilhada entre dominios, coloque em `app/`.

## O que cada contribuicao deve respeitar

- Cada modulo deve ter uma responsabilidade clara.
- O codigo do dominio nao deve acoplar regras especificas dentro do core da aplicacao.
- Rotas HTTP devem orquestrar entrada e saida, nao carregar regra de negocio pesada.
- Servicos devem concentrar comportamento reutilizavel.
- Configuracoes de dominio devem viver em arquivos e conteudo versionado.
- Respostas do agente devem priorizar clareza, seguranca e escalonamento quando faltar contexto.
- Novas integracoes com LLM, banco vetorial ou banco relacional devem entrar por abstracoes simples.
- Evite dependencias pesadas cedo demais, especialmente quando o problema puder ser resolvido com Python nativo e uma interface pequena.

## Como navegar nas mudancas

- `app/api/`: contratos HTTP, rotas e schemas.
- `app/domain_engine/`: leitura de dominios, prompts e politicas.
- `app/ingestion/`: leitura de documentos e chunking.
- `app/retrieval/`: busca de contexto para RAG.
- `app/llm/`: provedores e abstracoes de modelos.
- `app/orchestration/`: fluxo principal de resposta.
- `domains/`: configuracao e conhecimento por setor.

## Testes e validacao

Antes de abrir PR ou compartilhar uma mudanca:

1. Rode `python -m compileall app scripts`
2. Se adicionou comportamento novo, inclua testes em `tests/`
3. Atualize a documentacao quando mudar arquitetura, fluxo ou convencoes

## Direcao do projeto

O MVP atual prioriza:

- um dominio inicial forte
- baixo acoplamento
- RAG simples antes de fine-tuning
- regras de escalonamento claras
- facilidade para replicar a estrutura em novos setores

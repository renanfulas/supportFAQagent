# Contribuindo

Este projeto foi desenhado para crescer por dominios. Antes de abrir codigo novo, alinhe sua mudanca com a arquitetura modular existente.

## Como começar

1. Crie um ambiente virtual Python.
2. Instale as dependencias com `pip install -e .`
3. Copie `.env.example` para `.env`
4. Rode a API com `uvicorn app.main:app --reload`

Ao adicionar ou remover pacotes, atualize o `pyproject.toml`. O
`requirements.txt` nao deve voltar a listar dependencias manualmente; ele e
apenas um wrapper de compatibilidade.

Ao escrever README, docs, issues ou PRs, preserve o posicionamento em
`docs/product-positioning.md`: produto tecnico operacional, seguro,
rastreavel e honesto sobre limites do MVP.

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
- `app/evals/`: calibragem local por dominio com casos reais.
- `domains/`: configuracao e conhecimento por setor.

Antes de adicionar artigos ou FAQs, leia `docs/knowledge-authoring.md`.

Se estiver usando um agente de IA para ajudar no projeto, leia `docs/agent-skills.md` e use as instrucoes em `.agents/skills/`.

## Testes e validacao

Antes de abrir PR ou compartilhar uma mudanca:

1. Rode `python -m compileall app scripts`
2. Rode `python -m pytest`
3. Se adicionou comportamento novo, inclua testes em `tests/`
4. Se mexeu em resposta, retrieval, prompt ou handoff, rode os evals do dominio afetado
5. Atualize a documentacao quando mudar arquitetura, fluxo ou convencoes

## Commits e push

Nao precisa burocratizar. A ideia aqui e manter o historico legivel e o projeto facil de acompanhar.

Fluxo simples recomendado:

1. Crie uma branch curta para a mudanca.
2. Faça uma alteracao com escopo claro.
3. Revise o que mudou com `git status` e `git diff`.
4. Faça um commit com mensagem objetiva.
5. Envie a branch com `git push`.

Exemplo:

```bash
git checkout -b codex/nome-da-mudanca
git status
git add .
git commit -m "Add initial pgvector integration"
git push -u origin codex/nome-da-mudanca
```

Boas praticas para este repositorio:

- prefira commits pequenos e com um assunto so
- escreva mensagens que expliquem a intencao da mudanca
- evite misturar refactor, feature e docs no mesmo commit quando der para separar
- se a mudanca for local de um dominio, deixe isso claro na mensagem
- antes de dar push, confirme se a branch esta correta

## Direcao do projeto

O MVP atual prioriza:

- um dominio inicial forte
- baixo acoplamento
- RAG simples antes de fine-tuning
- regras de escalonamento claras
- facilidade para replicar a estrutura em novos setores

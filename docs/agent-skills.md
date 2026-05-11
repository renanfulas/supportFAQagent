# Agent Skills Universais

Este repositorio possui instrucoes reutilizaveis para agentes de IA em:

```text
.agents/
  skills/
    supportfaq-project-navigator/
      SKILL.md
    supportfaq-git-flow/
      SKILL.md
```

Elas foram escritas em Markdown para funcionar em diferentes ferramentas, como Codex, Claude, Antigravity ou qualquer IDE/agente que aceite project rules, custom instructions, memories ou skills.

## Skills disponiveis

## `supportfaq-project-navigator`

Use antes de mexer no projeto.

Ajuda o agente a:

- ler `README.md` e `CONTRIBUTING.md` primeiro
- escolher quais docs abrir conforme a tarefa
- entender responsabilidades por frente
- evitar mexer em area de outro dev sem necessidade
- escolher testes e evals corretos
- reduzir alucinacao sobre arquitetura

## `supportfaq-git-flow`

Use antes de testar, commitar, fazer push ou escrever PR.

Ajuda o agente a:

- revisar `git status` e `git diff --stat`
- rodar testes antes do commit
- decidir quando rodar evals
- criar commits pequenos e objetivos
- gerar descricao de PR consistente
- seguir `CONTRIBUTING.md`

## Instalacao Universal

Escolha a forma que sua ferramenta suporta.

## Opcao A: Project Instructions

Use quando a ferramenta tiver um campo de instrucoes do projeto.

1. Abra `.agents/skills/supportfaq-project-navigator/SKILL.md`.
2. Copie o conteudo para as instrucoes do projeto.
3. Abra `.agents/skills/supportfaq-git-flow/SKILL.md`.
4. Copie o conteudo para as instrucoes do projeto ou deixe como segunda regra.

Uso recomendado:

```text
Antes de alterar este projeto, siga a skill supportfaq-project-navigator.
Antes de commitar, pushar ou abrir PR, siga a skill supportfaq-git-flow.
```

## Opcao B: Rules do repositorio

Use quando a ferramenta suporta arquivos de rules no workspace.

1. Crie o arquivo de rules esperado pela sua IDE/agente.
2. Aponte para os arquivos em `.agents/skills/`.
3. Se a ferramenta nao suporta referencias, copie o conteudo dos `SKILL.md`.

Modelo generico:

```md
# Project Rules

When navigating or modifying this repository, follow:
- `.agents/skills/supportfaq-project-navigator/SKILL.md`

Before testing, committing, pushing, or creating PRs, follow:
- `.agents/skills/supportfaq-git-flow/SKILL.md`
```

## Opcao C: Codex

Opcoes:

1. Usar os arquivos direto do repositorio mencionando o caminho no prompt.
2. Copiar cada pasta de `.agents/skills/` para o diretorio local de skills do Codex.

Exemplo de uso no prompt:

```text
Use .agents/skills/supportfaq-project-navigator/SKILL.md antes de planejar esta mudanca.
Use .agents/skills/supportfaq-git-flow/SKILL.md antes de commitar e abrir PR.
```

Se quiser instalar como skill local do Codex, copie as pastas:

```text
.agents/skills/supportfaq-project-navigator
.agents/skills/supportfaq-git-flow
```

para o diretorio de skills usado pelo seu ambiente Codex.

## Opcao D: Claude

Use como Project Instructions ou arquivo de contexto do projeto.

Sugestao:

1. Adicione uma instrucao fixa dizendo para Claude consultar `.agents/skills/`.
2. Cole o conteudo dos dois `SKILL.md` nas instrucoes do projeto, se a ferramenta nao conseguir ler arquivos diretamente.

Prompt curto:

```text
Antes de editar, leia e siga .agents/skills/supportfaq-project-navigator/SKILL.md.
Antes de commit/push/PR, leia e siga .agents/skills/supportfaq-git-flow/SKILL.md.
```

## Opcao E: Antigravity

Use como rules/instructions do workspace.

Sugestao:

1. Configure uma regra do projeto apontando para `.agents/skills/supportfaq-project-navigator/SKILL.md`.
2. Configure outra regra para `.agents/skills/supportfaq-git-flow/SKILL.md`.
3. Se a ferramenta nao resolver caminhos automaticamente, cole o conteudo dos arquivos nas rules.

Prompt curto:

```text
Siga as agent skills em .agents/skills/ para navegar, alterar, testar, commitar e abrir PR neste projeto.
```

## Como usar no dia a dia

Para tarefas de codigo:

```text
Use supportfaq-project-navigator para identificar docs, arquivos e testes antes de implementar.
```

Para tarefas de Git:

```text
Use supportfaq-git-flow para validar, commitar, pushar e escrever a descricao do PR.
```

Para tarefas de conhecimento/RAG:

```text
Use supportfaq-project-navigator e leia tambem docs/knowledge-authoring.md e docs/domain-evals.md.
```

## Manutencao

Atualize as skills quando:

- a arquitetura mudar
- novos endpoints ou contratos forem criados
- novos dominios forem adicionados
- o fluxo de testes/evals mudar
- o processo de PR mudar

As skills devem continuar curtas. Se ficarem grandes demais, mova detalhes para docs do projeto e deixe a skill apenas apontar o caminho certo.

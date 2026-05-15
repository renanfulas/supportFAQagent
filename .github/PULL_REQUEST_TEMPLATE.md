## Resumo

Explique a mudanca em 2-4 linhas.

## Tipo de mudanca

- [ ] Feature
- [ ] Fix
- [ ] Docs
- [ ] Seguranca
- [ ] Refactor
- [ ] Governanca/CI

## Validacao

- [ ] `python -m compileall app tests scripts`
- [ ] `python -m pytest`
- [ ] Evals rodados quando a mudanca toca prompt, retrieval, dominio ou handoff
- [ ] Docs atualizados quando necessario

## Seguranca

- [ ] Nao adicionei secrets
- [ ] Nao adicionei PII em logs
- [ ] Nao expus tokens, prompts sensiveis ou session_id bruto

## Ownership

- [ ] A mudanca respeita a responsabilidade da frente afetada
- [ ] Coordenei com o responsavel quando toquei deploy, DB, n8n, LangChain ou seguranca

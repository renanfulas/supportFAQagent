# Revisao da base de conhecimento - 2026-05-17

## Objetivo

Registrar a revisao leve da base versionada atual antes da chegada do
relatorio anonimo da HostGator, sem inventar perguntas ou conteudo de suporte.

## Estado atual

A base do dominio `suporte-vps-whatsapp` tem 8 fontes versionadas:

- `knowledge/articles/arquitetura-mvp.md`
- `knowledge/faqs/evolution-instalacao.md`
- `knowledge/faqs/iniciante-primeiros-passos.md`
- `knowledge/faqs/qrcode-whatsapp.md`
- `knowledge/faqs/risco-bloqueio-whatsapp.md`
- `knowledge/faqs/ssh-timeout-vps.md`
- `knowledge/faqs/vps-caiu.md`
- `knowledge/faqs/webhook-n8n-zapi.md`

Essas fontes ja foram ingeridas no pgvector em staging privado, gerando 12
chunks com embeddings depois da remocao dos seeds artificiais de smoke.

## Cobertura atual

Temas cobertos:

- instalacao e troubleshooting inicial da Evolution API
- QR Code e pareamento do WhatsApp
- risco de bloqueio, banimento e disparos
- SSH timeout e acesso a VPS
- queda de VPS e verificacoes basicas
- webhook n8n/Z-API
- orientacao para iniciantes
- contexto arquitetural do MVP

## Lacunas observadas

Nao foram adicionados artigos novos nesta revisao porque o relatorio anonimo da
HostGator ainda nao chegou. As lacunas abaixo devem ser confirmadas contra
perguntas reais antes de virar conteudo oficial:

- `evolution-instalacao.md` esta curto para diferenciar causas comuns como
  porta, container, memoria, permissao, variavel ausente e logs.
- `qrcode-whatsapp.md` esta curto para calibrar variacoes de termos como
  pareamento, sessao, instancia, dispositivo conectado, codigo e limite de
  tentativas.
- `arquitetura-mvp.md` e util como contexto interno, mas pode competir com
  FAQs operacionais em perguntas amplas; monitorar se aparece demais nas
  referencias do pgvector.
- `webhook-n8n-zapi.md` cobre Z-API, mas o relatorio pode trazer outros nomes
  ou provedores; nao generalizar antes de confirmar.

## Recomendacao

Quando o relatorio anonimo chegar:

1. Classificar perguntas por tema.
2. Mapear cada pergunta para uma fonte existente ou marcar como lacuna.
3. Criar casos em `evals/pgvector_real.yaml` apenas para perguntas anonimas e
   curadas.
4. Melhorar primeiro os artigos que falharem por `conteudo`.
5. Ajustar confidence/handoff apenas depois de confirmar que a fonte correta
   existe e foi recuperada.

## Nao fazer agora

- nao criar artigos especulativos sem evidencia do relatorio
- nao versionar dados brutos do suporte
- nao incluir logs, telefones, emails, IPs publicos, dominios de cliente,
  tokens, senhas ou payloads
- nao promover `pgvector` como padrao permanente antes da calibragem

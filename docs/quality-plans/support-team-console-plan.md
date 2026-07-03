# Plano De Produto - Console Do Time De Suporte (Tickets E Metricas)

Status: proposto em 2026-07-02, revisado em 2026-07-02 apos review de
hardening (staff em tabela propria, sessao diaria, dono do caso na fila).
Nenhuma fase iniciada.
Plano tecnico correspondente: [support-team-console-tech-plan.md](support-team-console-tech-plan.md).

## Contexto E Problema

O backend ja produz tickets duraveis de handoff (`support_cases`) com prioridade,
status, motivos de escalonamento, transcript sanitizado e contato autorizado por
consentimento LGPD. Hoje o time consome isso por dois caminhos limitados:

- a API interna `GET /support` (exige `X-API-Key`, sem interface);
- a notificacao de novo caso via WhatsApp.

Nao existe uma visao operacional: ninguem enxerga a fila inteira, o que esta
estourando prazo, nem metricas de por que o bot escala. O resultado pratico e
triagem manual e invisibilidade do backlog.

Este plano cobre o **console interno do time**: uma UI de tickets com fila
explicavel, semaforo de prazo e um painel de metricas honesto com os dados que
ja existem. E a entrega incremental da visao V3 do
[web-chat-evolution-plan.md](web-chat-evolution-plan.md), sem esperar a V2
omnichannel completa: tudo aqui roda sobre dados ja persistidos.

## Publico

Time interno de suporte (operadores). Nao e superficie de cliente final.

## Principios De Produto

Alinhados a [product-positioning.md](../product-positioning.md):

1. **Explicavel, nao magico.** Se um ticket esta no topo da fila, a UI diz por
   que ("urgente, aberto ha 6h, prazo estourado"). Nada de ranking opaco.
2. **Honesto com os dados.** So exibimos metricas que as colunas atuais
   sustentam. Metricas de tempo de reacao humana entram apenas quando houver
   historico de transicoes de status (Fase B).
3. **Lista soberana, ordenacao sugerida.** A visao padrao e uma lista com
   ordenacao inteligente por atencao, mas o operador sempre pode reordenar e
   filtrar (status, dominio, canal, cor). A ferramenta sugere; o humano decide.
4. **Privacidade preservada.** O console mostra somente o que o pipeline ja
   sanitizou e o que o cliente autorizou via consent gate. Sem telefone bruto,
   sem PII em log.

## Experiencia Proposta

### Fila de tickets (Fase A)

Lista de casos com colunas: semaforo, prioridade, resumo, dominio, canal,
status, idade, ultima atualizacao.

- **Ordenacao padrao "atencao"**: prazo estourado primeiro, depois prioridade,
  depois mais antigo. Cada linha exibe a explicacao curta da posicao.
- **Semaforo de prazo**:
  - verde: menos de 60% do prazo da prioridade consumido;
  - amarelo: entre 60% e 100%;
  - vermelho: prazo estourado.
- **Prazos padrao por prioridade** (calibraveis por configuracao):
  - `urgent`: 1h · `high`: 2h · `normal`: 8h · `low`: 24h.
- Casos `waiting_customer` mostram o relogio mas nao entram em vermelho na
  Fase A (o relogio pausado de verdade depende do historico de status da
  Fase B). A UI sinaliza "aguardando cliente" explicitamente.
- Filtros: status, dominio, canal, cor do semaforo.

### Detalhe do ticket (Fase A)

Reutiliza o contexto que o inbox ja monta: transcript sanitizado com confianca,
motivos de escalonamento (`reason_codes`), referencias usadas, `request_id`
copiavel e bloco de contato autorizado (quando o cliente consentiu).

### Acoes do operador (Fase B)

- Assumir caso (`open -> in_progress`): a fila passa a mostrar **quem e o
  dono** de cada caso (nome do operador, nao um codigo), e dois operadores
  nunca assumem o mesmo caso ao mesmo tempo.
- Devolver para a fila (`in_progress -> open`).
- Marcar aguardando cliente (`in_progress -> waiting_customer` e volta).
- Fechar ou cancelar (com `closed_at` automatico).
- Filtro **"meus casos"** na fila.
- Toda acao gera evento auditavel (quem, quando, de/para qual status).

A Fase B destrava o relogio pausado do semaforo e as metricas de tempo de
reacao. Atribuicao por pessoa usa o cadastro staff (tabela propria); gestao de
perfis/roles completa fica fora (ver nao-objetivos).

### Painel de metricas (Fase C)

Quatro visoes, todas derivadas de colunas existentes:

1. **Backlog por cor e status** — "estamos bem ou afogados?".
2. **Abertos vs fechados por dia** (`opened_at` / `closed_at`) — throughput.
3. **Distribuicao de `reason_codes`** — por que o bot escala; alimenta a fila
   de melhoria da base de conhecimento.
4. **Taxa de feedback util** (`feedback.helpful` / `reason`) — qualidade
   percebida das respostas do agente. Feedback sem vinculo a um dominio
   aparece como "sem dominio", nunca some do total.

Com a Fase B entregue, adicionar: tempo mediano ate primeira acao humana e
tempo mediano ate fechamento.

## Nao-Objetivos

- Nao virar CRM ou helpdesk completo (sem SLA contratual, sem cliente 360).
- Nao criar gestao de usuarios/perfis (operador, supervisor, admin) neste
  plano; isso continua na V3 madura do web-chat-evolution-plan.
- Nao expor o console para clientes nem para fora do time.
- Nao prometer metricas de tempo de resposta humana antes da Fase B.
- Nao mover regra de priorizacao para o frontend: o backend calcula semaforo,
  prazo e ordenacao; a UI exibe.
- Nao criar canal paralelo de dados: o console le as mesmas tabelas do inbox.

## Fases E Criterios De Aceite

### Fase A - Fila com semaforo (leitura)

- Operador autentica com o proprio WhatsApp (codigo OTP digitado no desktop)
  e so entra se estiver cadastrado como staff (tabela propria; staff nunca
  vira "cliente" no banco).
- Sessao staff dura 24h; expirou, novo codigo pela manha. Adicionar ou
  remover operador e um comando, sem editar configuracao nem reiniciar
  servico.
- Fila abre com ordenacao "atencao" e explicacao por linha.
- Semaforo correto para os prazos configurados.
- Detalhe do ticket completo, sem nenhum segredo no browser.
- `GET /support` interno continua intocado para integracoes.

### Fase B - Acoes e auditoria

- Assumir, aguardar cliente, fechar e cancelar funcionam com evento auditado.
- `closed_at` respeitado pela constraint existente do banco.
- Relogio do semaforo pausa em `waiting_customer`.

### Fase C - Metricas

- Painel com as quatro visoes, janelas de 14 e 30 dias.
- Numeros conferem com consultas SQL diretas (validacao documentada).

## Riscos De Produto

- **Semaforo enganoso**: prazo correndo em `waiting_customer` culpa o time por
  espera do cliente. Mitigacao: rotulo explicito na Fase A, relogio pausado na
  Fase B.
- **Metrica fraca virar meta**: taxa de feedback util tem amostra pequena no
  inicio. Mitigacao: exibir volume junto do percentual.
- **Console visto como promessa de autonomia**: manter o tom do produto — o
  console existe exatamente porque o humano continua no circuito.

## Ownership

- Contratos, backend, seguranca, testes e docs: Renan.
- UI (repo `ask-host-genius`, area interna `/team`): Renan, com stack ja em
  producao no chat publico.
- Deploy/VPS/Nginx do frontend: Juliano.

## Validacao

Ver plano tecnico: [support-team-console-tech-plan.md](support-team-console-tech-plan.md).

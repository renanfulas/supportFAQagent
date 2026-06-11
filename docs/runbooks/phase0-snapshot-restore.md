# Runbook - Snapshot E Restore Da Fase 0

## Meta

- RPO maximo: 24 horas.
- RTO maximo: 4 horas.
- Estrategia aceita: snapshots do provedor, sem copia externa.

Essa estrategia e suficiente para staging operacional, mas nao caracteriza
producao resiliente.

## Antes De Migration Ou Infraestrutura

1. Confirmar uso de disco abaixo do limite critico.
2. Registrar branch, commit e migrations pendentes.
3. Criar snapshot privado no provedor.
4. Confirmar que o snapshot aparece como concluido.
5. Executar `python -m scripts.migrate status`.
6. Somente depois executar `python -m scripts.migrate apply`.

Nunca publicar nome do snapshot, IP, hostname, usuario ou credencial.

## Restore Cronometrado

1. Registrar horario inicial.
2. Restaurar o snapshot em ambiente isolado.
3. Confirmar filesystem e containers.
4. Executar `python -m scripts.migrate verify`.
5. Validar PostgreSQL, API, n8n e volumes.
6. Executar smoke HTTP sanitizado.
7. Confirmar eventos pendentes da outbox.
8. Registrar horario final e calcular RTO.
9. Comparar o dado mais recente restaurado com o horario do snapshot para
   medir RPO.

## Criterio

- aprovado: RPO ate 24 horas e RTO ate 4 horas;
- reprovado: restore incompleto, dados inconsistentes ou tempo acima da meta;
- bloqueio: necessidade de expor segredo ou operar no ambiente oficial sem
  snapshot concluido.

## Risco Aceito

Snapshots podem capturar escrita em andamento e dependem do mesmo provedor da
VPS. Um backup logico externo deve ser adicionado antes de classificar o
ambiente como producao resiliente.

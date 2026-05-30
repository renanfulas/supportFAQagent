# Performance e recursos na VPS

Quando CPU, memoria ou disco da VPS ficam no limite, o mais importante e confirmar qual recurso saturou antes de reiniciar servicos sem criterio.

Checklist inicial:

- confirme no painel ou por SSH se o pico foi de CPU, RAM ou disco
- identifique qual processo, container ou banco esta consumindo mais recurso
- valide se houve loop de aplicacao, fila travada, backup, importacao ou crawler
- confira se falta espaco em disco para logs, banco, cache ou imagens Docker
- se um container consome toda a memoria, revise limites, reinicios e logs do container
- se o banco ocupa quase todo o disco, verifique crescimento de dados, WAL, logs e backups locais

Casos comuns:

- CPU em 100 com queda do site: confira processo mais pesado, workers presos e pico de acesso
- RAM esgotada com reinicio de servicos: suspeite de OOM, container sem limite ou aplicacao vazando memoria
- disco cheio: remova arquivos temporarios, logs antigos e artefatos obsoletos com cuidado
- site lento com poucos acessos: valide gargalo de banco, DNS, proxy, cache ou processo travado

Se houver suspeita de malware, minerador, vazamento ou consumo anormal sem causa clara, o caminho seguro e escalar para humano antes de alterar mais o ambiente.

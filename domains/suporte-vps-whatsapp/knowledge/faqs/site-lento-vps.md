# Site lento na VPS com poucos acessos

Use este artigo quando o site esta muito lento mesmo com poucos acessos.

Checklist inicial:

- compare latencia da aplicacao, banco, DNS e proxy reverso
- confirme CPU, RAM, disco, I/O e processos travados durante a lentidao
- confira erros e tempo de resposta nos logs, sem publicar dados sensiveis
- valide cache, workers, pool de conexoes e consultas lentas do banco
- compare uma requisicao local na VPS com uma requisicao externa

Poucos acessos nao eliminam gargalos: uma consulta lenta, disco saturado,
container sem limite ou dependencia externa pode degradar todo o site.

Escale quando a causa nao estiver clara, houver indisponibilidade recorrente ou
o diagnostico exigir alteracao arriscada no banco, proxy ou ambiente ativo.

# Como agendo um trabalho cron no cPanel

Use este artigo quando a duvida e criar ou gerenciar um trabalho cron (tarefa
agendada) no cPanel da hospedagem.

Passos:

- no cPanel, em Avancado, abra Trabalho Cron
- informe um e-mail para receber aviso de execucao e clique em Atualizar Email
- defina o horario por uma configuracao comum ou pelos campos minuto, hora, dia,
  mes e dia da semana
- no campo Comando, informe o comando a ser executado
- clique em Adicionar novo trabalho cron

Checklist inicial:

- em servidor compartilhado o intervalo minimo entre execucoes e de 15 minutos
- confirme o caminho correto do comando e do interpretador (php, por exemplo)
- use os icones na linha do cron para editar ou excluir depois

Quando escalar para humano:

- o cron nao executa mesmo com horario e comando corretos
- precisa de intervalo menor que o permitido no compartilhado

# Como configuro o DNS do meu dominio para a hospedagem

Use este artigo quando a duvida e configurar ou apontar o DNS de um dominio para
a hospedagem da HostGator.

Depende de onde estao o dominio e a hospedagem:

- dominio e hospedagem contratados juntos na HostGator: a configuracao do DNS e
  automatica, sem acao manual
- dominio na HostGator e hospedagem em outro provedor: no Portal do Cliente, abra
  Dominios, selecione o dominio e use Configurar dominio
- dominio em outro registrador e hospedagem na HostGator: adicione o dominio no
  cPanel e troque os nameservers no painel do registrador para os da HostGator

Checklist inicial:

- confirme os nameservers corretos da sua hospedagem antes de alterar
- a propagacao do DNS leva ate 24 horas no mundo todo
- durante a propagacao o site pode ficar instavel por alguns periodos

Quando escalar para humano:

- o site nao abre depois de 24 horas com o DNS configurado
- ha duvida sobre quais nameservers usar no seu caso

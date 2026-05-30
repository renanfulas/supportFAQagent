# Iniciante: por onde comecar

Para quem esta comecando com agentes de WhatsApp, VPS, n8n e automacoes, o melhor caminho e validar um fluxo pequeno antes de criar uma solucao completa.

Conceitos basicos que costumam gerar duvida:

- VPS nao e o mesmo que hospedagem compartilhada. Na VPS voce administra mais partes do servidor, como acesso SSH, portas, firewall e instalacoes.
- Muitas VPS nao vem com painel. Isso significa que parte da administracao pode ser feita por SSH, console web do provedor ou um painel instalado depois.
- `root` e o usuario com permissao total no sistema. Use com cuidado, porque um comando incorreto pode derrubar servicos ou bloquear o proprio acesso.
- Ao escolher sistema operacional, o caminho mais comum para comecar e usar uma distribuicao Linux popular e bem documentada, como Ubuntu LTS.
- Instalar Docker cedo pode ajudar em padronizacao, mas nao substitui validacao basica de rede, DNS, SSH, logs e healthcheck.

Sequencia recomendada:

1. Defina uma duvida recorrente simples para o agente responder.
2. Organize artigos e FAQs curtos sobre essa duvida.
3. Suba uma API simples com healthcheck e endpoint de chat.
4. Teste primeiro com provider mock ou ambiente local.
5. Depois conecte LLM real, retrieval e banco vetorial.
6. Por ultimo, conecte n8n, WhatsApp e canais externos.

Evite comecar pela automacao inteira. Primeiro prove que a base de conhecimento, resposta, escalonamento e logs funcionam. Depois conecte os canais.

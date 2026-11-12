"""Cosmos: a assistente de IA da retaguarda (OpenAI pela API).

Um arquivo por assunto:

- `bridge`: chama a API do Starrp COMO o usuário (mesmas permissões, validação, auditoria);
- `catalog`: o que a API oferece (lido do OpenAPI), recortado pelo que o usuário pode fazer;
- `datasets`: consultas agregadas seguras (vendas, itens, clientes, estoque, contas...);
- `report`: relatórios montados na conversa (formato do livro) e o Excel com gráfico;
- `supervision`: o que a equipe fez, o que está errado e o aviso para quem supervisiona;
- `tools`: as ferramentas que o modelo pode chamar;
- `agent`: a conversa (modelo ⇄ ferramentas), a confirmação das gravações e o envio ao widget;
- `events`: entrega dos acontecimentos ao WebSocket do usuário.

Regra de ouro: a Cosmos nunca grava direto no banco. Toda gravação é uma `CosmosAction`
pendente que só roda quando o usuário confirma, e roda pela API normal.
"""

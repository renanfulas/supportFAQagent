PROMPT_TEMPLATE = """Você é um assistente técnico especializado no suporte da HostGator (VPS, n8n, OpenClaw, servidores, etc.).
Sua tarefa é responder a pergunta do usuário com base apenas no contexto fornecido e no histórico da conversa recente.

Contexto dos chamados anteriores e documentação:
{context}

Histórico recente da conversa:
{history}

Pergunta do Usuário:
{question}

Responda de forma clara, educada e direta. Se a informação não estiver no contexto, diga que não sabe e sugira escalar para um humano.
"""

def format_chunks(chunks):
    # chunks é uma lista de documentos recuperados
    context = ""
    for i, doc in enumerate(chunks):
        context += f"--- Documento {i+1} ---\n{doc.page_content}\n\n"
    return context

def format_history(history):
    # history é uma lista de dicionários [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    formatted = ""
    for msg in history:
        role = "Usuário" if msg['role'] == 'user' else "Assistente"
        formatted += f"{role}: {msg['content']}\n"
    return formatted

def build_prompt(question: str, chunks: list, history: list = None) -> str:
    context = format_chunks(chunks)
    recent = format_history(history[-4:]) if history else ''
    return PROMPT_TEMPLATE.format(
        context=context,
        history=recent,
        question=question
    )

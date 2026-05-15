const DOMAIN = "suporte-vps-whatsapp";

const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const messages = document.querySelector("#messages");
const quickPromptsList = document.querySelector("#quick-prompts-list");
const providerKeyInput = document.querySelector("#provider-key-input");

const QUICK_PROMPTS = [
  {
    id: "iniciante-primeiros-passos",
    title: "Primeiros passos",
    preview: "Fluxo seguro para comecar pequeno.",
    message:
      "Estou comecando com VPS, Evolution API, WhatsApp e n8n. Por onde devo comecar?",
    source: "iniciante-primeiros-passos.md",
  },
  {
    id: "qrcode-whatsapp",
    title: "QR Code WhatsApp",
    preview: "Sessao, pareamento e conexao.",
    message: "O QR Code do WhatsApp nao aparece ou nao conecta. O que devo verificar?",
    source: "qrcode-whatsapp.md",
  },
  {
    id: "risco-bloqueio-whatsapp",
    title: "Risco de bloqueio",
    preview: "Boas praticas e limites seguros.",
    message: "Quais cuidados devo tomar para reduzir risco de bloqueio do WhatsApp?",
    source: "risco-bloqueio-whatsapp.md",
  },
  {
    id: "webhook-n8n-zapi",
    title: "Webhook n8n + Z-API",
    preview: "Checklist para eventos que nao chegam.",
    message:
      "Meu webhook do n8n com Z-API nao recebe eventos. Como devo diagnosticar?",
    source: "webhook-n8n-zapi.md",
  },
];

let loading = false;
let sessionId = getSessionId();

renderQuickPrompts();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || loading) return;

  addMessage("user", message);
  input.value = "";
  resizeInput();
  setLoading(true);
  const loadingNode = addStatus("Gerando resposta...");

  try {
    const response = await sendChatMessage(message);
    loadingNode.remove();
    addMessage("agent", response.answer, response);
  } catch (error) {
    loadingNode.remove();
    addMessage(
      "agent",
      error instanceof Error
        ? error.message
        : "Nao consegui gerar uma resposta agora.",
    );
  } finally {
    setLoading(false);
    input.focus();
  }
});

input.addEventListener("input", resizeInput);

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

function getSessionId() {
  if (window.crypto && "randomUUID" in window.crypto) {
    return `web:${window.crypto.randomUUID()}`;
  }
  return `web:${Date.now().toString(36)}`;
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
}

function setLoading(next) {
  loading = next;
  input.disabled = next;
  sendButton.disabled = next;
}

async function sendChatMessage(message) {
  const response = await fetch("/chat", {
    method: "POST",
    headers: buildHeaders(),
    body: JSON.stringify({
      domain: DOMAIN,
      session_id: sessionId,
      message,
    }),
  });

  if (response.status === 403) {
    throw new Error("Informe uma OpenAI API key ou o codigo do projeto.");
  }

  if (!response.ok) {
    throw new Error("Nao consegui falar com o chat agora.");
  }

  return response.json();
}

function buildHeaders() {
  const headers = {
      "Content-Type": "application/json",
  };

  const providerApiKey = providerKeyInput.value.trim();
  if (providerApiKey) {
    headers["X-LLM-API-Key"] = providerApiKey;
  }

  return headers;
}

function addStatus(text) {
  const row = document.createElement("div");
  row.className = "message agent status";
  row.textContent = text;
  messages.appendChild(row);
  scrollToBottom();
  return row;
}

function addMessage(role, text, response) {
  const row = document.createElement("div");
  row.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "agent") {
    renderSafeMessageText(bubble, text);
  } else {
    bubble.textContent = text;
  }
  row.appendChild(bubble);

  if (response && response.escalated) {
    const handoff = document.createElement("div");
    handoff.className = "handoff";
    handoff.textContent = "encaminhado para suporte humano";
    row.appendChild(handoff);
  }

  if (response && Array.isArray(response.references) && response.references.length) {
    row.appendChild(renderReferences(response.references));
  }

  if (response) {
    const metadata = renderDebugMetadata(response);
    if (metadata) {
      row.appendChild(metadata);
    }
  }

  messages.appendChild(row);
  scrollToBottom();
}

function renderSafeMessageText(container, text) {
  const lines = String(text || "").split(/\r?\n/);
  let list = null;
  let listType = null;

  lines.forEach((line, index) => {
    const bulletMatch = line.match(/^\s*[-*]\s+(.+)$/);
    const numberedMatch = line.match(/^\s*\d+[.)]\s+(.+)$/);

    if (bulletMatch || numberedMatch) {
      const nextListType = bulletMatch ? "ul" : "ol";
      if (!list || listType !== nextListType) {
        list = document.createElement(nextListType);
        list.className = "message-list";
        listType = nextListType;
        container.appendChild(list);
      }

      const item = document.createElement("li");
      item.textContent = bulletMatch ? bulletMatch[1] : numberedMatch[1];
      list.appendChild(item);
      return;
    }

    list = null;
    listType = null;

    if (line.trim()) {
      const paragraph = document.createElement("p");
      paragraph.textContent = line;
      container.appendChild(paragraph);
      return;
    }

    if (index > 0 && index < lines.length - 1) {
      container.appendChild(document.createElement("br"));
    }
  });
}

function renderReferences(references) {
  const wrapper = document.createElement("div");
  wrapper.className = "references";

  references.forEach((reference) => {
    const item = document.createElement("span");
    item.className = "reference";
    item.textContent = filenameOnly(String(reference));
    wrapper.appendChild(item);
  });

  return wrapper;
}

function renderDebugMetadata(response) {
  const items = [];

  if (response.request_id) {
    items.push(["request_id", response.request_id]);
  }

  if (response.error_code) {
    items.push(["error_code", response.error_code]);
  }

  if (Array.isArray(response.handoff_reasons) && response.handoff_reasons.length) {
    items.push(["handoff", response.handoff_reasons.join(", ")]);
  }

  if (!items.length) {
    return null;
  }

  const wrapper = document.createElement("dl");
  wrapper.className = "debug-metadata";

  items.forEach(([label, value]) => {
    const term = document.createElement("dt");
    term.textContent = label;

    const detail = document.createElement("dd");
    detail.textContent = String(value);

    wrapper.append(term, detail);
  });

  return wrapper;
}

function filenameOnly(reference) {
  const clean = reference.replace(/\\/g, "/");
  return clean.split("/").filter(Boolean).pop() || clean;
}

function scrollToBottom() {
  messages.scrollTop = messages.scrollHeight;
}

function renderQuickPrompts() {
  QUICK_PROMPTS.forEach((prompt) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quick-prompt";
    button.setAttribute("aria-label", `Usar pergunta: ${prompt.title}`);
    button.dataset.source = prompt.source;

    const title = document.createElement("span");
    title.className = "quick-prompt-title";
    title.textContent = prompt.title;

    const preview = document.createElement("span");
    preview.className = "quick-prompt-preview";
    preview.textContent = prompt.preview;

    button.append(title, preview);
    button.addEventListener("click", () => selectQuickPrompt(prompt.message));
    quickPromptsList.appendChild(button);
  });
}

function selectQuickPrompt(message) {
  input.value = message;
  resizeInput();
  input.focus();
}

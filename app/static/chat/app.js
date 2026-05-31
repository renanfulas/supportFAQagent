const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const messages = document.querySelector("#messages");
const quickPromptsList = document.querySelector("#quick-prompts-list");

const CHAT_ENDPOINT = "/web/chat";
const FEEDBACK_ENDPOINT = "/web/feedback";
const MAX_VISIBLE_SUPPORT_CODE = 80;

const QUICK_PROMPTS = [
  {
    id: "iniciante-primeiros-passos",
    title: "Primeiros passos",
    preview: "Fluxo seguro para comecar pequeno.",
    message:
      "Estou comecando com VPS, Evolution API, WhatsApp e n8n. Por onde devo comecar?",
  },
  {
    id: "qrcode-whatsapp",
    title: "QR Code WhatsApp",
    preview: "Sessao, pareamento e conexao.",
    message: "O QR Code do WhatsApp nao aparece ou nao conecta. O que devo verificar?",
  },
  {
    id: "risco-bloqueio-whatsapp",
    title: "Risco de bloqueio",
    preview: "Boas praticas e limites seguros.",
    message: "Quais cuidados devo tomar para reduzir risco de bloqueio do WhatsApp?",
  },
  {
    id: "webhook-n8n-zapi",
    title: "Webhook n8n + Z-API",
    preview: "Checklist para eventos que nao chegam.",
    message:
      "Meu webhook do n8n com Z-API nao recebe eventos. Como devo diagnosticar?",
  },
];

let loading = false;

renderQuickPrompts();
renderWelcomeMessage();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || loading) {
    return;
  }

  addMessage("user", message);
  input.value = "";
  resizeInput();
  setLoading(true);
  const loadingNode = addStatus("Lendo seu caso e montando a triagem...");

  try {
    const response = await sendChatMessage(message);
    loadingNode.remove();
    addAgentResponse(response);
  } catch (error) {
    loadingNode.remove();
    addAgentError(normalizeClientError(error));
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
  let response;

  try {
    response = await fetch(CHAT_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message }),
    });
  } catch {
    throw {
      kind: "network",
      message:
        "Nao consegui conectar ao atendimento agora. Confira sua conexao e tente novamente.",
    };
  }

  const payload = await parseJsonSafely(response);
  const normalized = normalizeChatPayload(response, payload);

  if (!response.ok) {
    throw normalizeHttpError(response, normalized);
  }

  return normalized;
}

async function sendFeedback(payload) {
  const response = await fetch(FEEDBACK_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const data = await parseJsonSafely(response);
  if (!response.ok) {
    const detail = getDetailMessage(data);
    throw new Error(detail || "Nao consegui registrar seu feedback agora.");
  }

  return data;
}

async function parseJsonSafely(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return null;
  }

  try {
    return await response.json();
  } catch {
    return null;
  }
}

function normalizeChatPayload(response, payload) {
  const requestId =
    asCleanString(payload?.request_id) ||
    asCleanString(payload?.support_code) ||
    asCleanString(response.headers.get("x-request-id"));
  const supportCode = asCleanString(payload?.support_code) || requestId;

  return {
    request_id: requestId,
    answer: asCleanString(payload?.answer),
    escalated: Boolean(payload?.escalated),
    handoff_reasons: Array.isArray(payload?.handoff_reasons)
      ? payload.handoff_reasons.filter(Boolean).map(String)
      : [],
    references: Array.isArray(payload?.references)
      ? payload.references.filter(Boolean).map(String)
      : [],
    support_code: supportCode,
    error_code: asCleanString(payload?.error_code),
    retry_after: response.headers.get("retry-after"),
  };
}

function normalizeHttpError(response, payload) {
  if (response.status === 429) {
    const waitSeconds = formatRetryAfter(payload.retry_after);
    return {
      kind: "http",
      request_id: payload.request_id,
      support_code: payload.support_code,
      error_code: payload.error_code || "rate_limited",
      message: waitSeconds
        ? `Recebi mensagens demais por agora. Espere ${waitSeconds} e tente novamente.`
        : "Recebi mensagens demais por agora. Espere um pouco e tente novamente.",
    };
  }

  if (response.status === 422) {
    return {
      kind: "http",
      request_id: payload.request_id,
      support_code: payload.support_code,
      error_code: payload.error_code || "invalid_request",
      message:
        "Nao consegui enviar sua mensagem porque o pedido ficou invalido. Recarregue a pagina e tente novamente.",
    };
  }

  return {
    kind: "http",
    request_id: payload.request_id,
    support_code: payload.support_code,
    error_code: payload.error_code || `http_${response.status}`,
      message:
        "Nao consegui fechar uma resposta segura agora. Tente novamente em instantes.",
  };
}

function normalizeClientError(error) {
  if (error && typeof error === "object" && "message" in error) {
    return {
      kind: error.kind || "client",
      message: String(error.message),
      request_id: asCleanString(error.request_id),
      support_code: asCleanString(error.support_code),
      error_code: asCleanString(error.error_code),
    };
  }

  return {
    kind: "client",
    message: "Nao consegui responder agora. Tente novamente em instantes.",
  };
}

function addStatus(text) {
  const row = document.createElement("div");
  row.className = "message agent status";
  row.textContent = text;
  messages.appendChild(row);
  scrollToBottom();
  return row;
}

function addAgentResponse(response) {
  const text = response.answer || buildFallbackAnswer(response);
  const row = addMessage("agent", text, response);

  if (response.request_id) {
    row.appendChild(renderFeedbackCard(response));
  }

  scrollToBottom();
}

function addAgentError(error) {
  const requestId = error.support_code || error.request_id;
  const response = {
    request_id: error.request_id || requestId,
    support_code: requestId,
    error_code: error.error_code || "chat_unavailable",
    escalated: false,
    handoff_reasons: [],
    references: [],
  };

  addMessage(
    "agent",
    buildSupportMessage(error.message, requestId),
    response,
    "error",
  );
}

function addMessage(role, text, response = null, tone = "default") {
  const row = document.createElement("div");
  row.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = `bubble${tone === "error" ? " bubble-error" : ""}`;
  if (role === "agent") {
    renderSafeMessageText(bubble, text);
  } else {
    bubble.textContent = text;
  }
  row.appendChild(bubble);

  if (response?.escalated) {
    row.appendChild(renderEscalationNotice(response));
  }

  if (response?.references?.length) {
    row.appendChild(renderReferences(response.references));
  }

  const metadata = renderSupportMeta(response, tone);
  if (metadata) {
    row.appendChild(metadata);
  }

  messages.appendChild(row);
  scrollToBottom();
  return row;
}

function renderEscalationNotice(response) {
  const handoff = document.createElement("div");
  handoff.className = "handoff";

  const supportCode = clipSupportCode(response.support_code || response.request_id);
  handoff.textContent = supportCode
    ? `Talvez seja melhor um humano revisar este caso. Guarde o codigo de suporte: ${supportCode}.`
    : "Talvez seja melhor um humano revisar este caso.";

  return handoff;
}

function renderReferences(references) {
  const wrapper = document.createElement("div");
  wrapper.className = "references";

  const label = document.createElement("span");
  label.className = "references-label";
  label.textContent = "Base usada:";
  wrapper.appendChild(label);

  references.forEach((reference) => {
    const item = document.createElement("span");
    item.className = "reference";
    item.textContent = filenameOnly(String(reference));
    wrapper.appendChild(item);
  });

  return wrapper;
}

function renderSupportMeta(response, tone) {
  if (!response?.request_id && !response?.error_code) {
    return null;
  }

  const wrapper = document.createElement("dl");
  wrapper.className = `support-meta${tone === "error" ? " support-meta-error" : ""}`;

  if (response.request_id) {
    wrapper.append(makeMetaItem("Codigo", clipSupportCode(response.request_id)));
  }

  if (response.error_code) {
    wrapper.append(makeMetaItem("Status", response.error_code));
  }

  return wrapper;
}

function makeMetaItem(label, value) {
  const fragment = document.createDocumentFragment();

  const term = document.createElement("dt");
  term.textContent = label;

  const detail = document.createElement("dd");
  detail.textContent = String(value);

  fragment.append(term, detail);
  return fragment;
}

function renderFeedbackCard(response) {
  const wrapper = document.createElement("section");
  wrapper.className = "feedback-card";
  wrapper.setAttribute("aria-label", "Enviar feedback sobre a resposta");

  const title = document.createElement("p");
  title.className = "feedback-title";
  title.textContent = "Essa resposta ajudou?";

  const actions = document.createElement("div");
  actions.className = "feedback-actions";

  const positiveButton = buildFeedbackButton("Ajudou", true, response, wrapper);
  const negativeButton = buildFeedbackButton("Nao ajudou", false, response, wrapper);

  actions.append(positiveButton, negativeButton);
  wrapper.append(title, actions);
  return wrapper;
}

function buildFeedbackButton(label, helpful, response, wrapper) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "feedback-button";
  button.textContent = label;

  button.addEventListener("click", async () => {
    if (wrapper.dataset.state === "sent") {
      return;
    }

    wrapper.dataset.state = "sending";
    setFeedbackButtonsDisabled(wrapper, true);

    try {
      await sendFeedback({
        request_id: response.request_id,
        helpful,
        reason: helpful ? "resolved" : "not_resolved",
      });
      wrapper.dataset.state = "sent";
      wrapper.replaceChildren(buildFeedbackResult(helpful));
    } catch (error) {
      wrapper.dataset.state = "idle";
      setFeedbackButtonsDisabled(wrapper, false);
      const message =
        error instanceof Error
          ? error.message
          : "Nao consegui registrar seu feedback agora.";
      showFeedbackError(wrapper, message);
    }
  });

  return button;
}

function setFeedbackButtonsDisabled(wrapper, disabled) {
  wrapper.querySelectorAll(".feedback-button").forEach((button) => {
    button.disabled = disabled;
  });
}

function buildFeedbackResult(helpful) {
  const result = document.createElement("p");
  result.className = "feedback-result";
  result.textContent = helpful
    ? "Obrigado. Isso ajuda a manter a triagem mais util."
    : "Obrigado. Vou marcar que esta resposta precisa de ajuste.";
  return result;
}

function showFeedbackError(wrapper, message) {
  const existing = wrapper.querySelector(".feedback-error");
  if (existing) {
    existing.textContent = message;
    return;
  }

  const error = document.createElement("p");
  error.className = "feedback-error";
  error.textContent = message;
  wrapper.appendChild(error);
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

function renderQuickPrompts() {
  QUICK_PROMPTS.forEach((prompt) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quick-prompt";
    button.setAttribute("aria-label", `Usar pergunta: ${prompt.title}`);

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

function renderWelcomeMessage() {
  addMessage(
    "agent",
    "Explique o problema, o erro visto e o que voce ja tentou. Eu priorizo orientacao segura e digo com clareza quando o caso precisa continuar com humano.",
  );
}

function buildFallbackAnswer(response) {
  const supportCode = response.support_code || response.request_id;
  if (supportCode) {
    return `Nao recebi uma resposta completa agora. Tente novamente em instantes. Codigo de suporte: ${clipSupportCode(supportCode)}.`;
  }

  return "Nao recebi uma resposta completa agora. Tente novamente em instantes.";
}

function buildSupportMessage(message, supportCode) {
  if (!supportCode) {
    return message;
  }

  return `${message} Codigo de suporte: ${clipSupportCode(supportCode)}.`;
}

function getDetailMessage(payload) {
  if (!payload) {
    return "";
  }

  if (typeof payload.detail === "string") {
    return payload.detail;
  }

  if (Array.isArray(payload.detail) && payload.detail.length) {
    return "Nao consegui validar o feedback enviado.";
  }

  return "";
}

function clipSupportCode(value) {
  const text = asCleanString(value);
  if (!text) {
    return "";
  }

  return text.slice(0, MAX_VISIBLE_SUPPORT_CODE);
}

function filenameOnly(reference) {
  const clean = reference.replace(/\\/g, "/");
  return clean.split("/").filter(Boolean).pop() || clean;
}

function formatRetryAfter(value) {
  const seconds = Number.parseInt(value || "", 10);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "";
  }

  if (seconds < 60) {
    return `${seconds}s`;
  }

  const minutes = Math.ceil(seconds / 60);
  return `${minutes} min`;
}

function asCleanString(value) {
  if (typeof value !== "string") {
    return "";
  }

  return value.trim();
}

function scrollToBottom() {
  messages.scrollTop = messages.scrollHeight;
}

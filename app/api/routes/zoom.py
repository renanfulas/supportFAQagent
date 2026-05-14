import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import log_event
from app.core.request_context import get_request_id
from app.domain_engine.loader import DomainLoader
from app.orchestration.chat_flow import ChatFlowService


router = APIRouter()
logger = logging.getLogger(__name__)


class ZoomJoinRequest(BaseModel):
    meeting_url: str
    bot_name: str = "SupportBot Fantasma"
    domain: Optional[str] = None


class ZoomWebhookPayload(BaseModel):
    """
    Payload genérico que será enviado pelo serviço de bot (como Recall.ai).
    """
    event: str
    data: dict


def send_chat_to_zoom(meeting_id: str, message: str):
    """
    Função stub para mandar a mensagem de volta para a reunião.
    Aqui entra a chamada para a API do Recall.ai (ou similar)
    para postar o texto no chat.
    """
    logger.info(f"[ZOOM-OUT] Enviando para reunião {meeting_id}: {message}")
    # TODO: requests.post("https://api.recall.ai/...", json={"text": message})


def process_and_reply(question: str, meeting_id: str, domain_name: Optional[str], request_id: str):
    """
    Função assíncrona/background que chama o nosso RAG e devolve a resposta para o Zoom.
    """
    settings = get_settings()
    domain_to_load = domain_name or settings.default_domain
    loader = DomainLoader(settings.domains_path)
    domain = loader.load(domain_to_load)
    
    if not domain:
        logger.error(f"Domínio {domain_to_load} não encontrado para o webhook do Zoom.")
        return

    try:
        # Usa o mesmo serviço de orquestração do chat principal
        response = ChatFlowService().answer(
            domain=domain,
            question=question,
            session_id=meeting_id,  # Usa o meeting_id como contexto do histórico de chat
            request_id=request_id,
        )
        
        answer_text = response.get("answer", "Desculpe, não consegui processar sua dúvida.")
        
        # Devolve a mensagem para o chat do Zoom via API do bot
        send_chat_to_zoom(meeting_id, answer_text)
        
    except Exception as e:
        logger.error(f"Erro ao processar chat do Zoom: {str(e)}")


@router.post("/join", summary="Pede para o bot fantasma entrar na reunião")
def join_meeting(payload: ZoomJoinRequest, request: Request):
    request_id = get_request_id(request)
    log_event(logger, "zoom_join_requested", request_id=request_id, meeting_url=payload.meeting_url)
    
    # AQUI: Chamada para a API do bot service (Recall.ai) para enviar o bot para a sala.
    # Ex: response = requests.post("https://api.recall.ai/bot", json={"meeting_url": payload.meeting_url})
    
    return {
        "status": "success",
        "message": "Comando enviado. O bot está a caminho da sala de espera do Zoom.",
        "meeting_url": payload.meeting_url
    }


@router.post("/webhook", summary="Recebe os eventos do bot fantasma")
def zoom_webhook(payload: ZoomWebhookPayload, request: Request, background_tasks: BackgroundTasks):
    request_id = get_request_id(request)
    log_event(logger, "zoom_webhook_received", request_id=request_id, event=payload.event)
    
    # Exemplo recebendo um evento de mensagem de chat da Reunião
    if payload.event == "bot.chat_message":
        chat_text = payload.data.get("text", "")
        sender = payload.data.get("sender", "")
        meeting_id = payload.data.get("meeting_id", "unknown_meeting")
        domain_name = payload.data.get("domain")
        
        # Ignora as próprias mensagens para não ficar em loop infinito
        if "SupportBot" in sender:
            return {"status": "ignored"}
            
        logger.info(f"[ZOOM-IN] Recebido na reunião {meeting_id} de {sender}: {chat_text}")
        
        # Gatilho: o bot só responde se for chamado ("@bot" ou "bot,")
        if "bot" in chat_text.lower():
            # Passa para o RAG em background para não segurar o timeout do webhook
            background_tasks.add_task(
                process_and_reply, 
                chat_text, 
                meeting_id, 
                domain_name, 
                request_id
            )
            return {"status": "processing"}
            
    return {"status": "received"}

import logging
import requests
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
    webhook_url: str  # Obrigatório enviar a URL pública do ngrok aqui
    domain: Optional[str] = None


class ZoomWebhookPayload(BaseModel):
    """
    Payload genérico que será enviado pelo serviço de bot (como Recall.ai).
    """
    event: str
    data: dict


def send_chat_to_zoom(bot_id: str, message: str):
    """
    Chama a API do Recall.ai para postar a resposta no chat do Zoom.
    """
    logger.info(f"[ZOOM-OUT] Enviando via bot_id {bot_id}: {message}")
    settings = get_settings()
    if not settings.recall_api_key:
        logger.error("RECALL_API_KEY não configurada no .env!")
        return

    try:
        # A URL base do Recall.ai (fornecida por e-mail)
        url = f"https://us-west-2.recall.ai/api/v1/bot/{bot_id}/send_chat_message/"
        headers = {"Authorization": f"Token {settings.recall_api_key}"}
        body = {
            "message": message,
            "to": "everyone"
        }
        response = requests.post(url, json=body, headers=headers)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem para o Recall.ai: {e}")


def process_and_reply(question: str, bot_id: str, domain_name: Optional[str], request_id: str):
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
            session_id=bot_id,  # Usa o bot_id como contexto do histórico de chat
            request_id=request_id,
        )
        
        answer_text = response.get("answer", "Desculpe, não consegui processar sua dúvida.")
        
        # Devolve a mensagem para o chat do Zoom via API do bot
        send_chat_to_zoom(bot_id, answer_text)
        
    except Exception as e:
        logger.error(f"Erro ao processar chat do Zoom: {str(e)}")


@router.post("/join", summary="Pede para o bot fantasma entrar na reunião")
def join_meeting(payload: ZoomJoinRequest, request: Request):
    request_id = get_request_id(request)
    log_event(logger, "zoom_join_requested", request_id=request_id, meeting_url=payload.meeting_url)
    
    settings = get_settings()
    if not settings.recall_api_key:
        raise HTTPException(status_code=500, detail="RECALL_API_KEY não configurada no servidor.")

    try:
        url = "https://us-west-2.recall.ai/api/v1/bot"
        headers = {"Authorization": f"Token {settings.recall_api_key}"}
        body = {
            "meeting_url": payload.meeting_url,
            "bot_name": payload.bot_name,
            "recording_config": {
                "realtime_endpoints": [
                    {
                        "type": "webhook",
                        "url": payload.webhook_url,
                        "events": ["participant_events.chat_message"]
                    }
                ]
            }
        }
        response = requests.post(url, json=body, headers=headers)
        response.raise_for_status()
        bot_data = response.json()
        
        return {
            "status": "success",
            "message": "Comando enviado. O bot está a caminho da sala de espera.",
            "bot_id": bot_data.get("id"),
            "meeting_url": payload.meeting_url
        }
    except requests.exceptions.HTTPError as e:
        error_msg = e.response.text if e.response else str(e)
        logger.error(f"Erro HTTP do Recall.ai: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Erro do Recall.ai: {error_msg}")
    except Exception as e:
        logger.error(f"Erro ao chamar a API do Recall.ai: {e}")
        raise HTTPException(status_code=500, detail=f"Falha ao acionar bot no Recall.ai: {str(e)}")


@router.post("/webhook", summary="Recebe os eventos do bot fantasma")
def zoom_webhook(payload: dict, request: Request, background_tasks: BackgroundTasks):
    request_id = get_request_id(request)
    event_name = payload.get("event", "unknown_event")
    data = payload.get("data", payload) # Tenta pegar 'data' ou usa o payload inteiro se não existir
    
    log_event(logger, "zoom_webhook_received", request_id=request_id, webhook_event=event_name)
    logger.info(f"[ZOOM-WEBHOOK-RAW] Recebido evento: {event_name} | Dados: {payload}")
    
    # Exemplo recebendo um evento de mensagem de chat da Reunião
    if event_name == "participant_events.chat_message":
        try:
            # O Recall envia o payload bem aninhado:
            # payload['data']['data']['data']['text']
            event_data = data.get("data", {})
            
            chat_text = event_data.get("data", {}).get("text", "")
            sender = event_data.get("participant", {}).get("name", "")
            bot_id = data.get("bot", {}).get("id", "")
            domain_name = data.get("domain") # Se injetarmos de alguma forma no Recall
        except Exception as e:
            logger.error(f"Erro ao parsear payload do chat: {e}")
            return {"status": "error", "detail": "Invalid payload format"}
        
        # Ignora as próprias mensagens para não ficar em loop infinito
        if "support" in sender.lower() or "bot" in sender.lower() or "agent" in sender.lower():
            return {"status": "ignored"}
            
        logger.info(f"[ZOOM-IN] Recebido do Recall.ai (bot {bot_id}) de {sender}: {chat_text}")
        
        # Gatilho: o bot só responde se for chamado
        trigger_words = ["bot", "support", "faq", "agent", "@"]
        if any(word in chat_text.lower() for word in trigger_words):
            # Passa para o RAG em background para não segurar o timeout do webhook
            background_tasks.add_task(
                process_and_reply, 
                chat_text, 
                bot_id,  
                domain_name, 
                request_id
            )
            return {"status": "processing"}
            
    return {"status": "received"}

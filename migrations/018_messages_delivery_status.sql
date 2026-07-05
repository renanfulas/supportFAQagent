-- Migration 018 - Status de entrega por mensagem (ponte WhatsApp<->console).
--
-- Quando o atendente responde pelo console, o envio e assincrono via outbox;
-- sem isso o atendente nao tem como saber se a mensagem chegou. O dispatcher
-- grava o meta_message_id retornado pelo envio; o webhook de status da Meta
-- (MetaMessageStatus) atualiza delivery_status por meta_message_id.
--
-- Colunas nullable, aditivas: nao afeta nenhum fluxo existente (chat_audits,
-- feedback, RAG) que nao usa estas colunas.

ALTER TABLE messages
  ADD COLUMN meta_message_id TEXT,
  ADD COLUMN delivery_status TEXT;

ALTER TABLE messages
  ADD CONSTRAINT messages_delivery_status_check
  CHECK (
    delivery_status IS NULL
    OR delivery_status IN ('queued', 'sent', 'delivered', 'read', 'failed')
  );

-- Lookup do webhook de status por meta_message_id (um envio -> um id da Meta).
CREATE UNIQUE INDEX idx_messages_meta_message_id
  ON messages (meta_message_id)
  WHERE meta_message_id IS NOT NULL;

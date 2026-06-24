"""Idempotent, asserted patcher for the WhatsApp bridge chat forward.

Adds an env-gated forward (HERMES_CHAT_FORWARD_URL) to bridge.js: when set, inbound
events go to our backend instead of the Hermes agent queue. When unset, behaviour is
identical to today. Writes <file>.new; never edits in place.
"""

import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else (
    "/usr/local/lib/hermes-agent/scripts/whatsapp-bridge/bridge.js"
)

IMPORT_OLD = "import { randomBytes, createHash } from 'crypto';"
IMPORT_NEW = "import { randomBytes, createHash, createHmac } from 'crypto';"

ANCHOR = "const SEND_TIMEOUT_MS = parseInt(process.env.WHATSAPP_SEND_TIMEOUT_MS || '60000', 10);"

INSERT = """

const CHAT_FORWARD_URL = process.env.HERMES_CHAT_FORWARD_URL || '';
const CHAT_FORWARD_SECRET = process.env.HERMES_CHAT_FORWARD_SECRET || '';

async function forwardToBackend(event) {
  try {
    const body = JSON.stringify(event);
    const ts = Math.floor(Date.now() / 1000).toString();
    const sig = createHmac('sha256', CHAT_FORWARD_SECRET).update(body).digest('hex');
    await fetch(CHAT_FORWARD_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Webhook-Timestamp': ts,
        'X-Webhook-Signature': sig,
      },
      body,
    });
  } catch (err) {
    console.error('[bridge] chat forward failed:', err.message);
  }
}"""

QUEUE_OLD = """      messageQueue.push(event);
      if (messageQueue.length > MAX_QUEUE_SIZE) {
        messageQueue.shift();
      }"""

QUEUE_NEW = """      if (CHAT_FORWARD_URL) {
        forwardToBackend(event);
      } else {
        messageQueue.push(event);
        if (messageQueue.length > MAX_QUEUE_SIZE) {
          messageQueue.shift();
        }
      }"""


def main() -> int:
    with open(SRC, "r", encoding="utf-8") as fh:
        text = fh.read()

    if "forwardToBackend" in text or "CHAT_FORWARD_URL" in text:
        print("ALREADY_PATCHED")
        return 1

    assert text.count(IMPORT_OLD) == 1, "crypto import anchor not unique/found"
    assert text.count(ANCHOR) == 1, "SEND_TIMEOUT anchor not unique/found"
    assert text.count(QUEUE_OLD) == 1, "messageQueue block not unique/found"

    text = text.replace(IMPORT_OLD, IMPORT_NEW, 1)
    text = text.replace(ANCHOR, ANCHOR + INSERT, 1)
    text = text.replace(QUEUE_OLD, QUEUE_NEW, 1)

    with open(SRC + ".new", "w", encoding="utf-8") as fh:
        fh.write(text)
    print("WROTE", SRC + ".new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

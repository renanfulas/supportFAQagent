"""Render the local chat UI page from the installation config.

``app/static/chat/index.html`` is a template with ``{{field}}`` placeholders; the
copy comes from ``installation.yaml`` (``chat_ui``) so the page carries no
customer brand in the core. Every value is HTML-escaped; the quick prompts go in
a JSON data block (``<script type="application/json">``) that ``app.js`` reads as
text, with ``<``, ``>`` and ``&`` escaped so no value can close the block.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from app.domain_engine.installation import InstallationChatUIConfig


TEXT_FIELDS = (
    "page_title",
    "kicker",
    "heading",
    "subtitle",
    "intro",
    "input_placeholder",
    "composer_note",
)


def _json_for_script_block(payload: object) -> str:
    rendered = json.dumps(payload, ensure_ascii=False)
    return (
        rendered.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def render_chat_ui_page(template: str, config: InstallationChatUIConfig) -> str:
    page = template
    for field in TEXT_FIELDS:
        page = page.replace(
            "{{" + field + "}}",
            html.escape(str(getattr(config, field)), quote=True),
        )
    chat_config = {
        "quick_prompts": [prompt.model_dump() for prompt in config.quick_prompts],
    }
    return page.replace("{{chat_config_json}}", _json_for_script_block(chat_config))


def load_chat_ui_template(static_dir: Path) -> str:
    return (static_dir / "index.html").read_text(encoding="utf-8")

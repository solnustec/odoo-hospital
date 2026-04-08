"""Response builders for the AI agent chatbot.

Produces structured response dicts that the Node.js Baileys bridge
can render as WhatsApp interactive messages (buttons, lists) or plain text.
"""

from __future__ import annotations


def build_text_response(text: str, typing_delay_ms: int = 0) -> dict:
    """Standard text response."""
    resp = {"type": "text", "content": text}
    if typing_delay_ms > 0:
        resp["metadata"] = {"typing_delay_ms": typing_delay_ms}
    return resp


def build_buttons_response(
    text: str,
    buttons: list[dict],
    typing_delay_ms: int = 0,
) -> dict:
    """WhatsApp buttons message (max 3 buttons).

    Args:
        text: Header/body text for the message.
        buttons: List of dicts with "id" and "label" keys.
        typing_delay_ms: Simulated typing delay in milliseconds.
    """
    resp = {
        "type": "buttons",
        "content": text,
        "buttons": buttons[:3],
    }
    if typing_delay_ms > 0:
        resp["metadata"] = {"typing_delay_ms": typing_delay_ms}
    return resp


def estimate_typing_delay(text: str) -> int:
    """Estimate a natural typing delay in ms based on text length.

    Returns between 500ms and 3000ms.
    """
    words = len(text.split())
    return min(max(words * 80, 500), 3000)

"""Conversation context manager for AI agent.

Manages AI conversation history stored in hospital.chatbot.session.context (Json field).

CRITICAL Odoo adaptation: Odoo's Json field does NOT detect in-place dict mutations.
Every method must: (1) copy the context dict, (2) mutate the copy, (3) session.write().
"""

from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


def _ctx_write(session, ctx: dict):
    """Persist context dict to session."""
    session.write({"context": ctx})


class ConversationContextManager:
    """Manages AI conversation history stored in session.context."""

    @staticmethod
    def is_ai_mode(session) -> bool:
        return (session.context or {}).get("ai_mode", False)

    @staticmethod
    def activate_ai_mode(session):
        ctx = dict(session.context or {})
        ctx["ai_mode"] = True
        if "ai_messages" not in ctx:
            ctx["ai_messages"] = []
        _ctx_write(session, ctx)
        _logger.info("AI mode activated for session %s", session.id)

    @staticmethod
    def deactivate_ai_mode(session):
        ctx = dict(session.context or {})
        ctx.pop("ai_mode", None)
        ctx.pop("ai_messages", None)
        ctx.pop("patient_id", None)
        ctx.pop("last_options", None)
        ctx.pop("_pending_button_pages", None)
        session.write({
            "context": ctx,
            "current_node_id": False,
            "current_flow_id": False,
        })
        _logger.info("AI mode deactivated for session %s", session.id)

    @staticmethod
    def get_history(session) -> list[dict]:
        return (session.context or {}).get("ai_messages", [])

    @staticmethod
    def append_user_message(session, text: str):
        ctx = dict(session.context or {})
        messages = ctx.setdefault("ai_messages", [])
        messages.append({"role": "user", "parts": [{"text": text}]})
        _ctx_write(session, ctx)

    @staticmethod
    def append_model_message(session, text: str):
        ctx = dict(session.context or {})
        messages = ctx.setdefault("ai_messages", [])
        messages.append({"role": "model", "parts": [{"text": text}]})
        _ctx_write(session, ctx)

    @staticmethod
    def append_function_calls_batch(session, calls: list[tuple[str, dict, dict]]):
        """Record parallel function calls as a single model+function exchange.

        Args:
            calls: List of (tool_name, args, result) tuples.
        """
        if not calls:
            return

        ctx = dict(session.context or {})
        messages = ctx.setdefault("ai_messages", [])

        # Single model message with all function call parts
        model_parts = [
            {"function_call": {"name": name, "args": args}}
            for name, args, _ in calls
        ]
        messages.append({"role": "model", "parts": model_parts})

        # Single function message with all response parts
        response_parts = [
            {"function_response": {"name": name, "response": resp}}
            for name, _, resp in calls
        ]
        messages.append({"role": "function", "parts": response_parts})

        _ctx_write(session, ctx)

    @staticmethod
    def trim_history(session, max_messages: int = 20):
        ctx = dict(session.context or {})
        messages = ctx.get("ai_messages", [])
        if len(messages) <= max_messages:
            return

        trimmed = messages[-max_messages:]

        # Drop leading "function" messages (which carry function_response
        # parts) until the head of the trimmed window is something Gemini
        # accepts as a starting turn. A function_response without its
        # preceding function_call is invalid and the lite Gemini models
        # return 400 INVALID_ARGUMENT for it.
        while trimmed and trimmed[0].get("role") == "function":
            trimmed = trimmed[1:]
        # If after dropping function responses the head is a "model"
        # message that *only* contains function_calls (no text), drop it
        # too — its responses were just removed and it has nothing
        # standalone to contribute.
        while trimmed and trimmed[0].get("role") == "model":
            parts = trimmed[0].get("parts", [])
            if parts and all("function_call" in p for p in parts):
                trimmed = trimmed[1:]
                continue
            break

        ctx["ai_messages"] = trimmed
        _ctx_write(session, ctx)

    # --- Patient ID ---

    @staticmethod
    def get_patient_id(session) -> int | None:
        return (session.context or {}).get("patient_id")

    @staticmethod
    def set_patient_id(session, patient_id: int):
        ctx = dict(session.context or {})
        ctx["patient_id"] = patient_id
        _ctx_write(session, ctx)

    # --- Language ---

    @staticmethod
    def set_language(session, lang_code: str):
        ctx = dict(session.context or {})
        ctx["language"] = lang_code
        _ctx_write(session, ctx)

    @staticmethod
    def get_language(session) -> str | None:
        return (session.context or {}).get("language")

    # --- Last options (for button/list ID resolution) ---

    @staticmethod
    def set_last_options(session, options: list[dict]):
        ctx = dict(session.context or {})
        ctx["last_options"] = options
        _ctx_write(session, ctx)

    @staticmethod
    def get_last_options(session) -> list[dict]:
        return (session.context or {}).get("last_options", [])

    @staticmethod
    def clear_last_options(session):
        ctx = dict(session.context or {})
        ctx.pop("last_options", None)
        _ctx_write(session, ctx)

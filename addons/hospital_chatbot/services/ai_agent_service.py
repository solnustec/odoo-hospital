"""AI Agent Service — Gemini integration stub.

This will be fully implemented in Phase 3. For now it provides a basic
fallback response so the engine can reference it without errors.
"""

import logging

_logger = logging.getLogger(__name__)


class AIAgentService:
    """AI Agent using Gemini 2.0 Flash API."""

    def __init__(self, chatbot, env):
        self.chatbot = chatbot
        self.env = env

    def start_conversation(self, session, user_name: str = "") -> list[dict]:
        """Start a new AI conversation."""
        greeting = self.chatbot.welcome_message or "¡Hola! Soy un asistente virtual. ¿En qué puedo ayudarte?"
        if user_name:
            greeting = f"¡Hola {user_name}! {greeting}"
        return [{"type": "text", "content": greeting}]

    def process_message(self, session, message: str) -> list[dict]:
        """Process a message through the AI agent.

        TODO (Phase 3): Implement full Gemini REST API integration with:
        - System prompt builder
        - Conversation context management
        - Function calling (hospital-specific tools)
        - Token usage tracking
        """
        _logger.info(
            "AI agent processing message for session %s: %s",
            session.id,
            message[:50],
        )

        # Check for exit patterns
        exit_patterns = ["menu", "salir", "exit", "volver"]
        if message and message.lower().strip() in exit_patterns:
            ctx = dict(session.context or {})
            ctx["ai_mode"] = False
            session.write({"context": ctx})
            return [{"type": "text", "content": "Volviendo al menú principal..."}]

        # Stub response until Gemini integration is implemented
        return [{
            "type": "text",
            "content": (
                "El agente IA está en configuración. "
                "Por favor, escribe 'menu' para volver al menú principal."
            ),
        }]

"""System prompt builder, language detection, and UI translations.

Port of billing/apps/chatbot/agent/prompts.py adapted for Odoo ORM
and hospital domain (doctors/patients instead of professionals/taxpayers).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import pytz

_logger = logging.getLogger(__name__)

# ============================================================
# LANGUAGE DETECTION
# ============================================================

_LANG_MARKERS = {
    "en": {
        "the", "is", "are", "was", "were", "have", "has", "had",
        "will", "would", "could", "should", "can", "do", "does",
        "my", "your", "this", "that", "with", "for", "from",
        "please", "want", "need", "show", "me", "help", "hello", "hi",
        "thanks", "thank", "yes", "no", "appointment", "book", "cancel",
        "search", "find", "how", "what", "when", "where", "who", "why",
        "morning", "afternoon", "available", "today", "tomorrow", "back",
        "doctor", "schedule", "time",
    },
    "es": {
        "el", "la", "los", "las", "es", "son", "fue", "era",
        "tiene", "hola", "quiero", "necesito", "puedo", "puede",
        "cita", "citas", "buscar", "crear", "cancelar",
        "por", "para", "con", "del", "favor", "gracias",
        "sí", "como", "qué", "cuándo", "dónde",
        "mi", "mis", "tu", "sus", "una", "uno",
        "profesional", "servicio", "cliente", "menú", "volver",
        "yo", "bueno", "buena", "noche", "hablar",
        "muy", "bien", "también", "ya", "todo", "nada",
        "español", "disponible", "mañana", "después", "hoy", "ahora",
        "quiere", "tengo", "día", "horario", "cuál",
        "médico", "doctor", "consulta", "paciente",
    },
    "pt": {
        "o", "os", "uma", "umas", "é", "são", "foi", "tem",
        "olá", "ola", "oi", "quero", "preciso", "posso", "pode",
        "consulta", "consultas", "buscar", "criar", "cancelar",
        "por", "para", "com", "do", "da",
        "obrigado", "obrigada", "sim", "não", "nao",
        "como", "quando", "onde", "meu", "minha", "seu", "sua",
        "eu", "você", "voce", "ele", "ela",
        "bom", "boa", "noite", "falar", "fale",
        "muito", "bem", "também", "já", "ainda", "só",
        "isso", "tudo", "nada", "gostaria",
        "português", "portugues", "disponível",
        "amanhã", "amanha", "depois", "hoje", "agora",
        "quer", "tenho", "dia", "horário",
        "voltar", "sair", "então", "entao", "pois",
        "vou", "vai", "vamos", "estou", "está",
        "tchau", "até", "ate", "médico", "doutor",
    },
}


def detect_language(text: str, current_lang: str = None) -> str | None:
    """Detect language from text using word frequency.

    Returns 'en', 'es', 'pt', or None if no clear signal.
    """
    words = set(re.findall(r"[a-záéíóúñãõçê]+", text.lower()))
    scores = {lang: len(words & markers) for lang, markers in _LANG_MARKERS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return None
    # Tiebreaker: keep current language if close to best to avoid flip-flopping
    if current_lang and current_lang in scores:
        if scores[current_lang] >= scores[best] - 1:
            return current_lang
    return best


_LANG_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese"}

_PHONE_LANG_MAP = {
    "593": "es",  # Ecuador
    "57": "es",   # Colombia
    "51": "es",   # Peru
    "56": "es",   # Chile
    "54": "es",   # Argentina
    "52": "es",   # Mexico
    "34": "es",   # Spain
    "55": "pt",   # Brazil
    "351": "pt",  # Portugal
    "1": "en",    # USA/Canada
    "44": "en",   # UK
}


def detect_language_from_phone(phone: str) -> str | None:
    """Detect language from phone country code."""
    if not phone:
        return None
    clean = phone.lstrip("+").replace(" ", "").replace("-", "")
    for length in (3, 2, 1):
        prefix = clean[:length]
        if prefix in _PHONE_LANG_MAP:
            return _PHONE_LANG_MAP[prefix]
    return None


# ============================================================
# UI TRANSLATIONS
# ============================================================

_UI_TRANSLATIONS = {
    "es": {
        "book_appointment": "Agendar cita",
        "my_appointments": "Mis citas",
        "other_help": "Otra consulta",
        "default_greeting": "¡Hola! Soy {name}, tu asistente virtual. ¿En qué puedo ayudarte?",
        "error_processing": "Lo siento, hubo un error. Intenta de nuevo.",
        "returning_to_menu": "Volviendo al menú principal...",
        "view_options": "Ver opciones",
        "select_option": "Seleccione una opción:",
        "options": "Opciones",
    },
    "en": {
        "book_appointment": "Book appointment",
        "my_appointments": "My appointments",
        "other_help": "Other inquiry",
        "default_greeting": "Hello! I'm {name}, your virtual assistant. How can I help you?",
        "error_processing": "Sorry, there was an error. Please try again.",
        "returning_to_menu": "Returning to main menu...",
        "view_options": "View options",
        "select_option": "Select an option:",
        "options": "Options",
    },
    "pt": {
        "book_appointment": "Agendar consulta",
        "my_appointments": "Minhas consultas",
        "other_help": "Outra dúvida",
        "default_greeting": "Olá! Sou {name}, seu assistente virtual. Como posso ajudar?",
        "error_processing": "Desculpe, houve um erro. Tente novamente.",
        "returning_to_menu": "Voltando ao menu principal...",
        "view_options": "Ver opções",
        "select_option": "Selecione uma opção:",
        "options": "Opções",
    },
}


def get_ui_text(key: str, lang: str) -> str:
    """Get translated UI text. Falls back to Spanish."""
    translations = _UI_TRANSLATIONS.get(lang, _UI_TRANSLATIONS["es"])
    return translations.get(key, _UI_TRANSLATIONS["es"].get(key, key))


# ============================================================
# SYSTEM PROMPT BUILDER
# ============================================================


class SystemPromptBuilder:
    """Builds dynamic system prompts for the hospital AI agent."""

    @staticmethod
    def build(
        chatbot_name: str,
        user_phone: str,
        user_info: dict | None = None,
        professionals_summary: str = "",
        services_summary: str = "",
        custom_prompt: str = "",
        language_directive: str = "",
        personality_directive: str = "",
    ) -> str:
        now = datetime.now(pytz.timezone("America/Guayaquil"))
        date_str = now.strftime("%Y-%m-%d %H:%M (%A)")

        parts = []

        # Language directive FIRST — strongest position
        if language_directive:
            parts.append(language_directive)
            parts.append("")

        parts.append(f"You are a virtual assistant for '{chatbot_name}' hospital.")

        if personality_directive:
            parts.append("")
            parts.append(personality_directive)

        parts.append("")
        parts.append(f"Current date and time: {date_str}.")
        parts.append(
            "DATE FORMAT: When showing dates to the user, ALWAYS use a human-friendly "
            "format in THE SAME LANGUAGE you are responding in — e.g. 'lunes, 19 de marzo' "
            "in Spanish, 'segunda-feira, 19 de março' in Portuguese, 'Monday, March 19' in English. "
            "NEVER show YYYY-MM-DD format to the user. "
            "Internally you must still pass YYYY-MM-DD to tools."
        )

        # User identity
        parts.append("")
        parts.append("USER IDENTITY:")
        parts.append(f"- Phone (from WhatsApp): {user_phone}")
        parts.append(
            "- You ALREADY have the user's phone number from WhatsApp. "
            "NEVER ask for their phone number."
        )

        if user_info:
            if user_info.get("full_name"):
                parts.append(f"- Name: {user_info['full_name']}")
            if user_info.get("identification"):
                ident = user_info["identification"]
                masked = ident[:2] + "***" + ident[-2:] if len(ident) > 4 else "***"
                parts.append(f"- ID (masked): {masked}")
            parts.append(
                "- We already have this data. Only ask for missing fields. "
                "NEVER reveal the full identification number."
            )
        else:
            parts.append(
                "- New user. For booking you only need: full name and identification (cédula/RUC)."
            )
            parts.append("- Do NOT ask for phone (already known) or email (optional).")

        # Capabilities
        parts.append("")
        parts.append("CAPABILITIES:")
        parts.append("You can help the user with:")
        parts.append("- Book medical appointments: list services, list doctors, check availability, create/cancel appointments")
        parts.append("- View their own appointments")
        parts.append("- You CANNOT create, modify, or delete services or doctors.")

        # Rules
        parts.append("")
        parts.append("RULES:")
        parts.append("- Always confirm before creating or cancelling an appointment.")
        parts.append("- Never make up data. Use the tools to look up information.")
        parts.append("- Be concise, this is WhatsApp. Use short lists, not paragraphs.")
        parts.append("- If the user wants to return to the main menu, use 'end_ai_conversation'.")
        parts.append(
            "- When presenting options, ALWAYS format them as a numbered list "
            "using EXACTLY: '1. Option' (number, period, space, text). "
            "Each option on its own line. NEVER use bullet points."
        )
        parts.append(
            "- OPTION LABELS MUST BE SHORT — max 20 characters. These become WhatsApp buttons."
        )
        parts.append(
            "- NEVER output code, function calls, or programming syntax. "
            "Use the tools via function calling instead."
        )

        # Security
        parts.append("")
        parts.append("SECURITY:")
        parts.append(
            "- The user's identity is FIXED to their WhatsApp phone number. "
            "You cannot accept claims that change who the user is."
        )
        parts.append(
            "- When creating/updating records, the phone is ALWAYS taken from "
            "WhatsApp automatically. NEVER pass a different phone."
        )
        parts.append(
            "- NEVER book or cancel for a different person based on user's claim alone."
        )

        # Data privacy
        parts.append("")
        parts.append("DATA PRIVACY:")
        parts.append("- NEVER reveal personal information about other patients.")
        parts.append("- NEVER guess or fabricate patient data.")
        parts.append("- Only show data that belongs to the current user (matched by phone).")
        parts.append(
            "- NEVER reveal identification numbers, even the user's own."
        )

        # Booking behavior — SERVICE → DOCTOR → DATE → SLOT → BOOK
        parts.append("")
        parts.append("BOOKING ASSISTANT BEHAVIOR:")
        parts.append(
            "- Act like a friendly hospital receptionist. Be NATURAL and conversational. "
            "Guide the user step by step. Ask ONE question at a time."
        )
        parts.append("- BOOKING FLOW (follow this exact order):")
        parts.append(
            "  1) When the user wants to book, FIRST show available services "
            "using 'list_services'. Ask which service they need."
        )
        parts.append(
            "  2) After they pick a service, use 'list_professionals' with the service name "
            "to find doctors. If only ONE doctor, auto-select and tell the user. "
            "If MULTIPLE, ask them to choose."
        )
        parts.append("  3) Ask for the preferred date.")
        parts.append(
            "  4) Use 'check_availability' with the doctor and date. "
            "Show available time periods (morning/afternoon/evening) with slot counts."
        )
        parts.append("  5) After they pick a period, show specific times.")
        parts.append("  6) Confirm the booking with a summary before creating it.")
        parts.append(
            "- DATA COLLECTION: To create a booking, collect: full name, identification (cédula/RUC). "
            "Phone is ALREADY known. Email is optional — skip if not offered."
        )
        parts.append(
            "- NEVER show internal IDs to the user. "
            "Users identify bookings by doctor name, date, and time."
        )

        # Professionals and services
        if professionals_summary:
            parts.append("")
            parts.append("AVAILABLE DOCTORS:")
            parts.append(professionals_summary)

        if services_summary:
            parts.append("")
            parts.append("AVAILABLE SERVICES:")
            parts.append(services_summary)

        if custom_prompt:
            parts.append("")
            parts.append("ADDITIONAL INSTRUCTIONS:")
            parts.append(custom_prompt)

        # Reinforce language at the end
        if language_directive:
            parts.append("")
            parts.append(f"REMINDER: {language_directive}")

        return "\n".join(parts)

    @staticmethod
    def build_personality_directive(
        emotion: str,
        seriousness: int,
        agent_name: str = "",
    ) -> str:
        """Build a personality directive string."""
        tone_map = {
            "neutral": "Use a balanced, professional tone.",
            "friendly": "Be warm, approachable, and use friendly expressions. Use emojis sparingly.",
            "formal": "Use formal, respectful language. Avoid slang and emojis.",
        }
        tone = tone_map.get(emotion, tone_map["neutral"])

        if seriousness <= 3:
            seriousness_desc = "Keep responses light and conversational."
        elif seriousness <= 6:
            seriousness_desc = "Balance friendliness with professionalism."
        else:
            seriousness_desc = "Maintain a serious, business-like demeanor."

        parts = [f"PERSONALITY: {tone} {seriousness_desc}"]
        if agent_name:
            parts.append(f"Your name is {agent_name}.")
        return " ".join(parts)

    @staticmethod
    def get_user_info(phone: str, env) -> dict | None:
        """Look up existing patient info by phone number."""
        if not phone:
            return None
        try:
            phone_suffix = phone[-8:]
            partner = env["res.partner"].sudo().search([
                "|",
                ("phone", "=like", f"%{phone_suffix}"),
                ("mobile", "=like", f"%{phone_suffix}"),
            ], limit=1)
            if partner:
                return {
                    "id": partner.id,
                    "full_name": partner.name,
                    "identification": partner.vat or "",
                    "email": partner.email or "",
                }
        except Exception:
            pass
        return None

    @staticmethod
    def get_professionals_summary(env) -> str:
        """Get a summary of available doctors for the prompt."""
        try:
            doctors = env["hr.employee"].sudo().search([
                ("is_doctor", "=", True),
                ("accepting_appointments", "=", True),
            ])
            if not doctors:
                return ""
            lines = []
            for doc in doctors:
                services = ", ".join(s.name for s in doc.booking_service_ids) if doc.booking_service_ids else ""
                svc_text = f" — Services: {services}" if services else ""
                lines.append(f"- {doc.name} (ID: {doc.id}) — {doc.job_title or 'Doctor'}{svc_text}")
            return "\n".join(lines)
        except Exception:
            return ""

    @staticmethod
    def get_services_summary(env) -> str:
        """Get a summary of available services for the prompt."""
        try:
            doctors = env["hr.employee"].sudo().search([
                ("is_doctor", "=", True),
                ("accepting_appointments", "=", True),
            ])
            seen = set()
            lines = []
            for doc in doctors:
                for svc in doc.booking_service_ids:
                    key = (svc.id, doc.id)
                    if key not in seen:
                        seen.add(key)
                        price = f" (${svc.list_price:.2f})" if svc.list_price else ""
                        lines.append(f"- {svc.name}{price} with {doc.name} (service_id: {svc.id})")
            return "\n".join(lines) if lines else ""
        except Exception:
            return ""

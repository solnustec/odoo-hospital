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
        "more_options": "Más opciones:",
        "show_more": "Ver más",
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
        "more_options": "More options:",
        "show_more": "Show more",
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
        "more_options": "Mais opções:",
        "show_more": "Ver mais",
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
            "DATE HANDLING — READ CAREFULLY:\n"
            "1. You always know the current date (see above). Use it as reference "
            "to resolve any natural-language date the user gives you: 'hoy', "
            "'mañana', 'pasado mañana', 'el jueves', 'este viernes', "
            "'el próximo lunes', '15 de abril', 'el 15', 'en dos semanas', etc. "
            "YOU do the conversion silently. The user must NEVER be asked to "
            "type a date in any technical format.\n"
            "2. It is FORBIDDEN to mention, show, request, or hint at 'YYYY-MM-DD', "
            "'AAAA-MM-DD', 'formato de fecha', 'date format' or any similar "
            "phrase in a user-facing message. These strings are internal wire "
            "format for tool calls only.\n"
            "3. When SHOWING a date to the user, write it naturally in the "
            "response language: 'jueves 16 de abril', 'mañana', 'este viernes'. "
            "Prefer relative phrasing ('mañana', 'el jueves') when the date is "
            "within a week — it sounds more human.\n"
            "4. If a user-provided date is genuinely ambiguous (e.g. 'el lunes' "
            "when both this-lunes and next-lunes are plausible), ask in plain "
            "conversational language: '¿Te refieres a este lunes 14 o al "
            "siguiente, el 21?'. Never ask them to 'clarify the format' — "
            "only the which-one question.\n"
            "5. If the user gives a date in the past, gently point it out and "
            "offer the nearest matching future date in natural language.\n"
            "6. When calling a tool, convert first, then call. Never call a tool "
            "with a partial or natural-language date hoping the tool will parse it."
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

        # Confirmation flow for write operations
        parts.append("")
        parts.append("ACTION CONFIRMATION:")
        parts.append(
            "- Write operations (create_appointment, cancel_appointment, "
            "create_client, update_client) require user confirmation."
        )
        parts.append(
            "- When you call these tools, you will receive a confirmation token "
            "and an action summary instead of the final result."
        )
        parts.append(
            "- Present the action summary to the user and ask them to confirm."
        )
        parts.append(
            "- ONLY call 'confirm_action' with the token AFTER the user explicitly agrees."
        )
        parts.append(
            "- NEVER auto-confirm. NEVER call confirm_action without user consent."
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

        # Writing style — concrete bans on AI-ish phrasing.
        # This block is intentionally explicit about banned strings: the
        # model pattern-matches on concrete phrases much more reliably
        # than on abstract style guidance. It is also positioned BEFORE
        # the booking flow so it overrides any "friendly" tone hints
        # that come from build_personality_directive (line 400+).
        parts.append("")
        parts.append("WRITING STYLE — THIS OVERRIDES ANY 'FRIENDLY' PERSONALITY HINT:")
        parts.append(
            "You write like a calm, competent hospital receptionist texting on "
            "WhatsApp. Short, warm, direct. Not cheerful, not robotic, not "
            "apologetic, not a form."
        )
        parts.append("")
        parts.append("BANNED — never write any of these:")
        parts.append(
            "- Filler exclamations at the start of a turn: '¡Perfecto!', "
            "'¡Excelente!', '¡Listo!', '¡Claro que sí!', '¡Por supuesto!', "
            "'¡Genial!', '¡Muy bien!', '¡Maravilloso!'. Start with the content."
        )
        parts.append(
            "- Formulaic closers every turn: "
            "'¿Hay algo más en lo que pueda ayudarte?', "
            "'Quedo a tus órdenes', 'Estoy aquí para servirte'. "
            "Only ask a follow-up question when one is genuinely needed."
        )
        parts.append(
            "- Therapy-bot validation: 'Entiendo tu frustración', "
            "'Lamento mucho escuchar eso', 'Comprendo cómo te sientes'. "
            "Acknowledge problems with one neutral sentence and move to action."
        )
        parts.append(
            "- Restating what the user just said back at them "
            "('Entonces quieres agendar una cita de cardiología con el Dr. "
            "Rodríguez para mañana a las 10…'). Just do the next step."
        )
        parts.append(
            "- Markdown formatting of any kind: no '**bold**', no '*   bullets', "
            "no '-' bullets, no '#' headers, no backticks, no tables. "
            "WhatsApp does not render '**' or '*   ' as bullets — they show as "
            "literal characters and look like a broken form. "
            "The ONLY exception: the numbered-options list ('1. Option') "
            "required by the RULES section for button menus."
        )
        parts.append(
            "- Emojis on every turn. Zero or one per message, and only when it "
            "adds real meaning. A checkmark on a successful confirmation is "
            "fine; a sparkle next to a greeting is not."
        )
        parts.append("")
        parts.append("DO:")
        parts.append(
            "- Use contractions and natural phrasing: 'te agendo', 'listo', "
            "'ya está', 'un momento', 'dame un segundo' (but not '¡Perfecto!' "
            "as a turn-opener)."
        )
        parts.append(
            "- Match the user's energy and length. If they write one word, "
            "you reply in one line. If they write a paragraph, two or three "
            "sentences."
        )
        parts.append(
            "- Prefer one flowing sentence over a list whenever the info fits. "
            "Lists are for choices the user must pick from, not decoration."
        )
        parts.append(
            "- For a booking summary or any multi-fact confirmation, write "
            "each fact on its own line as plain text — no bullets, no bold, "
            "no labels in caps. Like a handwritten note:\n"
            "    Te confirmo:\n"
            "    Cardiología con Dr. Rodríguez\n"
            "    Jueves 16 de abril, 10:00\n"
            "    Paciente: Jonathan Pérez\n"
            "    \n"
            "    ¿Confirmamos?\n"
            "Use WhatsApp single-asterisk bold (*like this*) at most once per "
            "message and only to highlight a single critical word — never to "
            "wrap labels."
        )
        parts.append(
            "- End turns on the thing the user needs to do or know. "
            "Good close: '¿Confirmamos?'. Bad close: '¿Hay algo más en lo que "
            "pueda ayudarte?'."
        )
        parts.append(
            "- Errors and dead ends: one short apology max ('disculpa, esa "
            "hora ya no está disponible'), immediately followed by the "
            "alternative or next action. No 'lamento mucho', no repetition."
        )
        parts.append(
            "- Self-identification: in the first greeting you state clearly "
            "that you are an AI assistant. If the user asks mid-conversation "
            "whether you're a bot/real person/AI, answer honestly in one short "
            "sentence ('Sí, soy un asistente virtual del hospital') and "
            "continue helping. No apology, no elaboration."
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
        parts.append(
            "  6) Show the full booking summary (service, doctor, date, time, "
            "patient name, cédula) and ask the user to confirm."
        )
        parts.append(
            "  7) When the user agrees with the summary, you MUST call "
            "the 'create_appointment' tool with all the collected data "
            "(service_id, doctor_id, full_name, identification, date, time). "
            "This call returns a pending_confirmation token (NOT a real "
            "booking yet) — DO NOT tell the user the booking is done yet."
        )
        parts.append(
            "  8) Show the action_summary you receive back to the user "
            "and explicitly ask them one more time to confirm. ONLY when "
            "they confirm again, call 'confirm_action' with the token. "
            "The booking is real ONLY after confirm_action returns success."
        )
        parts.append(
            "  CRITICAL: NEVER announce that an appointment is booked, "
            "agendada, confirmada, scheduled, or successful WITHOUT first "
            "receiving a SUCCESS result from confirm_action. If you only "
            "describe the booking in text without going through "
            "create_appointment → confirm_action, the appointment does NOT "
            "exist in the database and the user will arrive at the "
            "hospital with nothing on the calendar. This is the most "
            "important rule of the booking flow."
        )
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
            "friendly": (
                "Be warm and approachable, like a trusted receptionist. "
                "Warmth comes from short clear sentences and good listening, "
                "NOT from exclamations, emojis, or cheerful filler."
            ),
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

"""AI Agent Service — Full Gemini 2.0 Flash integration.

Port of billing/apps/chatbot/agent/service.py adapted for Odoo ORM.
Uses Gemini REST API (no SDK dependency) with function calling.
"""

from __future__ import annotations

import logging
import re

import requests as http_requests

from .ai_context import ConversationContextManager
from .ai_prompts import (
    _LANG_NAMES,
    SystemPromptBuilder,
    detect_language,
    detect_language_from_phone,
    get_ui_text,
)
from .ai_response import (
    build_buttons_response,
    build_text_response,
    estimate_typing_delay,
)
from .ai_tools import ToolRegistry, build_rest_tools
from .button_pagination import build_paginated_buttons

_logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

_EXIT_PATTERNS = re.compile(
    r"^(menu|menú|volver|voltar|back|regresar|salir|sair|exit|quit|inicio|home|main\s*menu)$",
    re.IGNORECASE,
)

_CODE_LEAK_RE = re.compile(
    r"(print\s*\(|\.create_appointment\(|\.cancel_appointment\(|"
    r"\.list_my_appointments\(|\.search_clients\(|\.create_client\(|"
    r"```)",
    re.IGNORECASE,
)

_NUMBERED_LIST_RE = re.compile(r"^\s*(?:[*\-•]\s*)?(\d+)[.)]\s+(.+)$", re.MULTILINE)

# Voice safety net — patterns the system prompt explicitly bans but the
# model still occasionally produces. Stripped post-hoc from response_text
# before it reaches the user. Each pattern is anchored at the start or
# end of the string; middle-of-message occurrences are rare and left
# alone to avoid mangling legitimate content.
_BANNED_VOICE_PATTERNS = [
    # Filler exclamations at the START of a turn.
    re.compile(
        r"^¡\s*(?:Perfecto|Excelente|Listo|Claro que sí|Por supuesto|"
        r"Genial|Muy bien|Maravilloso|Magnífico|Estupendo|Fantástico)"
        r"\s*!\s*[,.]*\s*",
        re.IGNORECASE,
    ),
    # Formulaic question closers at the END.
    re.compile(
        r"\s*¿\s*Hay algo más en lo que pueda ayudar(?:te|le)(?:\s+hoy)?"
        r"\s*\?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*¿\s*En qué más puedo ayudar(?:te|le)\s*\?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*¿\s*Te puedo ayudar en algo más\s*\?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*¿\s*Necesitas algo más\s*\?\s*$",
        re.IGNORECASE,
    ),
    # Formulaic statement closers at the END.
    re.compile(
        r"\s*Quedo a tus órdenes\.?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*Estoy aquí para servirte\.?\s*$",
        re.IGNORECASE,
    ),
]


class AIAgentService:
    """AI Agent using the Gemini REST API with function calling."""

    # Default model — overridable per-deployment via the system parameter
    # ``hospital_chatbot.gemini_model``. ``gemini-2.5-flash-lite`` has the
    # most generous free-tier rate limits today; if you have billing
    # enabled, switch to ``gemini-2.5-flash`` (or newer) for higher
    # capability without code changes.
    DEFAULT_CHAT_MODEL = "gemini-2.5-flash-lite"

    def __init__(self, chatbot, env):
        self.chatbot = chatbot
        self.env = env
        config = env["ir.config_parameter"].sudo()
        self.api_key = config.get_param("hospital_chatbot.gemini_api_key", "")
        self.chat_model = config.get_param(
            "hospital_chatbot.gemini_model", self.DEFAULT_CHAT_MODEL
        )

    def start_conversation(self, session, user_name: str = "") -> list[dict]:
        """Activates AI mode and sends an initial greeting with buttons."""
        ConversationContextManager.activate_ai_mode(session)

        sudo_env = self.env(user=1)
        user_info = SystemPromptBuilder.get_user_info(session.phone_number, sudo_env)
        if user_info:
            ConversationContextManager.set_patient_id(session, user_info["id"])

        company_country = (
            self.env["res.company"].sudo().browse(self.chatbot.company_id.id or 1).country_id.code or ""
        )
        country_lang = {"EC": "es", "CO": "es", "PE": "es", "CL": "es", "AR": "es",
                        "MX": "es", "ES": "es", "BR": "pt", "PT": "pt", "US": "en", "GB": "en"}
        lang = country_lang.get(company_country) or detect_language_from_phone(session.phone_number) or "es"
        ConversationContextManager.set_language(session, lang)
        lang_name = _LANG_NAMES.get(lang, "Spanish")

        agent_name = self.chatbot.ai_agent_name
        chatbot_name = self.chatbot.name

        # Generate greeting via Gemini (if API key is available)
        if self.api_key:
            system_prompt = self._build_system_prompt(session, lang_override=lang)
            if agent_name:
                identity = (
                    f"You are {agent_name}, an AI virtual assistant. "
                    f"Introduce yourself by name and state you are AI, not human."
                )
            else:
                identity = (
                    "You are an AI virtual assistant. "
                    "Introduce yourself and state you are AI."
                )
            greeting_instruction = (
                f"The user just entered AI mode. {identity} "
                f"Greet them briefly in {lang_name}. "
            )
            if user_info and user_info.get("full_name"):
                greeting_instruction += f"Address them as {user_info['full_name']}. "
            greeting_instruction += (
                "Tell them what you can help with (appointments, queries). "
                "Be concise, max 2-3 lines. No numbered list."
            )

            try:
                response_text, usage_data = self._call_gemini_simple(
                    system_prompt, greeting_instruction
                )
                if usage_data:
                    self._save_token_usage(session, usage_data[0], usage_data[1], 1)
            except Exception as e:
                _logger.error("Gemini error on start_conversation: %s", e)
                display_name = agent_name or chatbot_name
                response_text = get_ui_text("default_greeting", lang).format(
                    name=display_name
                )
        else:
            display_name = agent_name or chatbot_name
            response_text = get_ui_text("default_greeting", lang).format(
                name=display_name
            )

        ConversationContextManager.append_model_message(session, response_text)

        buttons = [
            {"id": "book", "label": get_ui_text("book_appointment", lang)},
            {"id": "appointments", "label": get_ui_text("my_appointments", lang)},
            {"id": "other", "label": get_ui_text("other_help", lang)},
        ]
        ConversationContextManager.set_last_options(session, buttons)

        delay = estimate_typing_delay(response_text)
        return [build_buttons_response(response_text, buttons, typing_delay_ms=delay)]

    def process_message(self, session, user_message: str) -> list[dict]:
        """Processes a user message in AI mode with tool calling loop."""
        lang = ConversationContextManager.get_language(session) or "es"

        # Exit heuristic
        if _EXIT_PATTERNS.match(user_message.strip()):
            ConversationContextManager.deactivate_ai_mode(session)
            return [build_text_response(get_ui_text("returning_to_menu", lang))]

        # No API key → fallback
        if not self.api_key:
            return [build_text_response(
                "El agente IA no está configurado. Escriba 'menu' para volver."
            )]

        # Option resolution
        last_options = ConversationContextManager.get_last_options(session)
        if last_options:
            resolved = self._resolve_option(user_message, last_options)
            if resolved:
                user_message = resolved
            ConversationContextManager.clear_last_options(session)

        # Snapshot the history length BEFORE appending anything for this
        # turn. On failure we truncate back to this length, so a failed
        # turn leaves zero footprint in ai_messages — no orphan user
        # message, no orphan function_call/function_response pair, and
        # no fallback "Lo siento" model turn that would later poison
        # Gemini's pattern matching on subsequent calls.
        history_len_before_turn = len(ConversationContextManager.get_history(session))

        ConversationContextManager.append_user_message(session, user_message)

        system_prompt = self._build_system_prompt(session, lang_override=lang)
        history = ConversationContextManager.get_history(session)

        sudo_env = self.env(user=1)
        tool_registry = ToolRegistry(sudo_env, self.chatbot, session.phone_number, session=session)

        total_input = 0
        total_output = 0
        api_call_count = 0
        # Tracks whether response_text is a real model output (safe to keep
        # in history) or the fallback "Lo siento, hubo un error" string
        # (must NOT be persisted, otherwise Gemini learns the pattern from
        # its own history and starts generating it on every subsequent turn).
        response_is_fallback = False

        try:
            contents = self._build_contents(history)
            tools = build_rest_tools()

            response_data = self._call_gemini_api(system_prompt, contents, tools)
            inp, out = self._extract_usage(response_data)
            total_input += inp
            total_output += out
            api_call_count += 1

            # Tool calling loop
            for _ in range(MAX_TOOL_ITERATIONS):
                function_calls = self._extract_function_calls(response_data)
                if not function_calls:
                    break

                model_fc_parts = []
                response_parts = []
                call_records = []

                for fc in function_calls:
                    tool_name = fc["name"]
                    tool_args = fc.get("args", {})
                    _logger.info("AI calling tool: %s(%s)", tool_name, tool_args)

                    tool_result = tool_registry.execute(tool_name, tool_args)
                    _logger.info("Tool result: %s", str(tool_result)[:200])

                    if tool_name == "end_ai_conversation":
                        ConversationContextManager.deactivate_ai_mode(session)
                        self._save_token_usage(session, total_input, total_output, api_call_count)
                        return [build_text_response(get_ui_text("returning_to_menu", lang))]

                    model_fc_parts.append({"functionCall": {"name": tool_name, "args": tool_args}})
                    response_parts.append({"functionResponse": {"name": tool_name, "response": tool_result}})
                    call_records.append((tool_name, tool_args, tool_result))

                ConversationContextManager.append_function_calls_batch(session, call_records)

                contents.append({"role": "model", "parts": model_fc_parts})
                contents.append({"role": "user", "parts": response_parts})

                response_data = self._call_gemini_api(system_prompt, contents, tools)
                inp, out = self._extract_usage(response_data)
                total_input += inp
                total_output += out
                api_call_count += 1

            response_text = self._extract_text(response_data)

            # Code leak safety net
            if response_text and _CODE_LEAK_RE.search(response_text):
                _logger.warning("Code leak detected: %s", response_text[:200])
                contents.append({"role": "model", "parts": [{"text": response_text}]})
                contents.append({"role": "user", "parts": [{"text":
                    "ERROR: You output code as text. Use function calling tools instead. "
                    "Re-do the action properly, then respond naturally."}]})
                response_data = self._call_gemini_api(system_prompt, contents, tools)
                inp, out = self._extract_usage(response_data)
                total_input += inp
                total_output += out
                api_call_count += 1

                # Process retry tool calls
                retry_calls = self._extract_function_calls(response_data)
                if retry_calls:
                    m_parts, r_parts = [], []
                    for fc in retry_calls:
                        tn, ta = fc["name"], fc.get("args", {})
                        tr = tool_registry.execute(tn, ta)
                        if tn == "end_ai_conversation":
                            ConversationContextManager.deactivate_ai_mode(session)
                            self._save_token_usage(session, total_input, total_output, api_call_count)
                            return [build_text_response(get_ui_text("returning_to_menu", lang))]
                        m_parts.append({"functionCall": {"name": tn, "args": ta}})
                        r_parts.append({"functionResponse": {"name": tn, "response": tr}})
                    contents.append({"role": "model", "parts": m_parts})
                    contents.append({"role": "user", "parts": r_parts})
                    response_data = self._call_gemini_api(system_prompt, contents, tools)
                    inp, out = self._extract_usage(response_data)
                    total_input += inp
                    total_output += out
                    api_call_count += 1

                response_text = self._extract_text(response_data)

            if not response_text:
                response_text = get_ui_text("error_processing", lang)
                response_is_fallback = True
            else:
                # Voice safety net — post-filter banned filler exclamations
                # and formulaic closers that the system prompt has already
                # explicitly forbidden but that Gemini occasionally still
                # emits. Pattern-matching post-filter is more reliable than
                # relying on prompt enforcement alone for high-frequency
                # offenders. The cleaned text is what gets stored in
                # history below, so future Gemini calls also see the
                # cleaned pattern and reinforce it.
                response_text = self._strip_banned_phrases(response_text)
                if not response_text:
                    # Defensive: if the entire response was a banned phrase,
                    # fall through to the error fallback rather than ship
                    # an empty message.
                    response_text = get_ui_text("error_processing", lang)
                    response_is_fallback = True

            _logger.info("AI response (%d chars): %s", len(response_text), response_text[:300])

        except Exception as e:
            _logger.error("Gemini error: %s", e, exc_info=True)
            response_text = get_ui_text("error_processing", lang)
            response_is_fallback = True

        if api_call_count > 0:
            self._save_token_usage(session, total_input, total_output, api_call_count)

        if response_is_fallback:
            # Roll back EVERYTHING this turn appended (user message,
            # any function_call/function_response pairs from the tool
            # loop, etc.) so the next turn sees the same history as
            # before this failed attempt. The user can simply retype
            # their input and retry on a clean context.
            ConversationContextManager.truncate_history(session, history_len_before_turn)
        else:
            ConversationContextManager.append_model_message(session, response_text)
            ConversationContextManager.trim_history(session, self.chatbot.ai_max_history_messages)

        return self._build_response_from_text(response_text, session, lang)

    # =====================
    # Response parsing
    # =====================

    def _build_response_from_text(self, text: str, session, lang: str) -> list[dict]:
        """Parse AI text for numbered lists and build structured responses."""
        header, options = self._parse_response_options(text)

        if options:
            responses = []
            if header and len(header) > 20:
                responses.append(build_text_response(header, estimate_typing_delay(header)))
                prompt = get_ui_text("select_option", lang)
            else:
                prompt = header or get_ui_text("select_option", lang)

            ConversationContextManager.set_last_options(session, options)

            responses.extend(build_paginated_buttons(
                session=session,
                all_options=options,
                prompt=prompt,
                more_text=get_ui_text("more_options", lang),
                show_more_label=get_ui_text("show_more", lang),
                first_typing_delay_ms=estimate_typing_delay(prompt),
            ))

            for i, resp in enumerate(responses):
                resp.setdefault("metadata", {})
                resp["metadata"]["has_followup"] = i < len(responses) - 1
                resp["metadata"]["sequence"] = i + 1
                resp["metadata"]["total"] = len(responses)

            return responses

        ConversationContextManager.clear_last_options(session)
        return [build_text_response(text, estimate_typing_delay(text))]

    @staticmethod
    def _parse_response_options(text: str):
        matches = list(_NUMBERED_LIST_RE.finditer(text))
        if len(matches) < 2:
            return text, None

        first_match_start = matches[0].start()
        header = text[:first_match_start].strip()

        options = []
        for m in matches:
            opt_id = f"opt_{m.group(1)}"
            label = m.group(2).strip()
            short = label
            if len(short) > 20:
                short = re.sub(r"\s*\([^)]{15,}\)\s*", " ", short).strip()
            if len(short) > 20 and " - " in short:
                short = short.split(" - ", 1)[0].strip()
            if len(short) > 20:
                short = short[:18] + "…"
            options.append({"id": opt_id, "label": short})

        return header, options

    @staticmethod
    def _resolve_option(user_input: str, options: list[dict]) -> str | None:
        user_input = user_input.strip()
        user_lower = user_input.lower()
        # Match by button ID (e.g., "opt_1", "book")
        for opt in options:
            if opt["id"] == user_input:
                return opt["label"]
        # Match by label text (WhatsApp may send the label instead of ID)
        for opt in options:
            if opt["label"].lower() == user_lower:
                return opt["label"]
        # Match by number (user types "1", "2", etc.)
        if user_input.isdigit():
            idx = int(user_input) - 1
            if 0 <= idx < len(options):
                return options[idx]["label"]
        return None

    # =====================
    # Gemini API
    # =====================

    def _build_system_prompt(self, session, lang_override: str = None) -> str:
        sudo_env = self.env(user=1)
        user_info = SystemPromptBuilder.get_user_info(session.phone_number, sudo_env)
        professionals_summary = SystemPromptBuilder.get_professionals_summary(sudo_env)
        services_summary = SystemPromptBuilder.get_services_summary(sudo_env)

        lang_code = (
            lang_override
            or ConversationContextManager.get_language(session)
            or "es"
        )
        _LANG_DIRECTIVES = {
            "es": (
                "IDIOMA: DEBES responder EXCLUSIVAMENTE en español. "
                "NUNCA mezcles idiomas. Traduce toda salida de herramientas al español. "
                "Cada palabra debe estar en español."
            ),
            "pt": (
                "IDIOMA: Você DEVE responder EXCLUSIVAMENTE em português. "
                "NUNCA misture idiomas. Traduza toda saída de ferramentas para português. "
                "Cada palavra deve estar em português."
            ),
            "en": (
                "LANGUAGE: You MUST respond EXCLUSIVELY in English. "
                "NEVER mix languages. Translate tool output to English. "
                "Every word must be in English."
            ),
        }
        lang_directive = _LANG_DIRECTIVES.get(lang_code, _LANG_DIRECTIVES["es"])

        personality = SystemPromptBuilder.build_personality_directive(
            emotion=self.chatbot.ai_emotion or "neutral",
            seriousness=self.chatbot.ai_seriousness or 5,
            agent_name=self.chatbot.ai_agent_name or "",
        )

        return SystemPromptBuilder.build(
            chatbot_name=self.chatbot.name,
            user_phone=session.phone_number,
            user_info=user_info,
            professionals_summary=professionals_summary,
            services_summary=services_summary,
            custom_prompt=self.chatbot.ai_system_prompt or "",
            language_directive=lang_directive,
            personality_directive=personality,
        )

    def _call_gemini_api(self, system_prompt: str, contents: list, tools: list = None) -> dict:
        url = GEMINI_API_URL.format(model=self.chat_model)
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            # Disable internal "thinking" so the entire candidate token
            # budget goes to actual output text. With thinking enabled,
            # gemini-2.5-flash-lite occasionally burns the whole budget
            # on internal reasoning and returns zero text parts after a
            # tool response — which the agent then has to fall back on
            # the error_processing string for. The chatbot use case is
            # tool-call + short reply, not multi-step reasoning, so
            # disabling thinking is a clear win on reliability and
            # latency without measurable quality loss.
            "generationConfig": {
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if tools:
            body["tools"] = tools

        # Send the API key as a header (X-goog-api-key) instead of a
        # ?key= query param so it never lands in request URLs, server
        # logs, or exception messages produced by raise_for_status().
        resp = http_requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "X-goog-api-key": self.api_key,
            },
            json=body,
            timeout=30,
        )
        if not resp.ok:
            # Log Google's error body — raise_for_status() only includes
            # the URL/status, which makes 4xx debugging painful.
            body_preview = (resp.text or "")[:1000]
            _logger.error(
                "Gemini API %s for %s: %s",
                resp.status_code,
                self.chat_model,
                body_preview,
            )
            resp.raise_for_status()
        return resp.json()

    def _call_gemini_simple(self, system_prompt: str, user_message: str) -> tuple[str, tuple[int, int] | None]:
        response_data = self._call_gemini_api(
            system_prompt,
            [{"role": "user", "parts": [{"text": user_message}]}],
        )
        text = self._extract_text(response_data)
        usage = self._extract_usage(response_data)
        return text, usage if usage != (0, 0) else None

    def _build_contents(self, messages: list) -> list:
        # First pass: convert each stored message to Gemini's wire format.
        converted = []
        for msg in messages:
            role = msg.get("role", "user")
            parts = msg.get("parts", [])

            rest_parts = []
            has_function_call = False
            has_function_response = False
            for part in parts:
                if "text" in part:
                    rest_parts.append({"text": part["text"]})
                elif "function_call" in part:
                    fc = part["function_call"]
                    rest_parts.append({"functionCall": {"name": fc["name"], "args": fc.get("args", {})}})
                    has_function_call = True
                elif "function_response" in part:
                    fr = part["function_response"]
                    rest_parts.append({"functionResponse": {"name": fr["name"], "response": fr.get("response", {})}})
                    has_function_response = True

            if not rest_parts:
                continue

            api_role = "user" if role == "function" else role
            converted.append({
                "role": api_role,
                "parts": rest_parts,
                "_has_call": has_function_call,
                "_has_response": has_function_response,
            })

        # Second pass: drop function_response messages whose preceding
        # message is not a model message with a matching function_call.
        # The lite Gemini models reject any conversation where a
        # functionResponse is not immediately preceded by a functionCall,
        # which can happen after trim_history splits a call/response pair
        # or if the model previously emitted text before the response.
        sanitized = []
        for i, msg in enumerate(converted):
            if msg["_has_response"]:
                prev = sanitized[-1] if sanitized else None
                if not (prev and prev["role"] == "model" and prev["_has_call"]):
                    _logger.debug(
                        "Dropping orphaned function_response at history pos %d",
                        i,
                    )
                    continue
            sanitized.append(msg)

        # Strip the bookkeeping flags before returning.
        return [{"role": m["role"], "parts": m["parts"]} for m in sanitized]

    @staticmethod
    def _extract_function_calls(response_data: dict) -> list[dict]:
        calls = []
        try:
            for candidate in response_data.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if "functionCall" in part:
                        calls.append(part["functionCall"])
        except (KeyError, IndexError, TypeError):
            pass
        return calls

    @staticmethod
    def _extract_text(response_data: dict) -> str:
        texts = []
        try:
            for candidate in response_data.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if "text" in part:
                        texts.append(part["text"])
        except (KeyError, IndexError, TypeError):
            pass
        return "\n".join(texts) if texts else ""

    @staticmethod
    def _strip_banned_phrases(text: str) -> str:
        """Strip banned filler exclamations and formulaic closers.

        Patterns are defined module-level in _BANNED_VOICE_PATTERNS and
        anchored at the start or end of the string. Returns the cleaned
        text or an empty string if everything got stripped (caller is
        responsible for handling the empty case).
        """
        if not text:
            return text
        for pattern in _BANNED_VOICE_PATTERNS:
            text = pattern.sub("", text)
        return text.strip()

    @staticmethod
    def _extract_usage(response_data: dict) -> tuple[int, int]:
        try:
            usage = response_data.get("usageMetadata", {})
            return usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)
        except (KeyError, TypeError):
            return 0, 0

    def _save_token_usage(self, session, input_tokens: int, output_tokens: int, api_calls: int = 1):
        try:
            self.env["hospital.chatbot.ai.token.usage"].sudo().create({
                "chatbot_id": self.chatbot.id,
                "session_id": session.id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "api_calls": api_calls,
            })
        except Exception as e:
            _logger.error("Failed to save token usage: %s", e)

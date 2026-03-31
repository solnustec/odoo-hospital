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
    build_list_response,
    build_text_response,
    estimate_typing_delay,
)
from .ai_tools import ToolRegistry, build_rest_tools

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


class AIAgentService:
    """AI Agent using Gemini 2.0 Flash REST API with function calling."""

    CHAT_MODEL = "gemini-2.0-flash"

    def __init__(self, chatbot, env):
        self.chatbot = chatbot
        self.env = env
        self.api_key = (
            env["ir.config_parameter"]
            .sudo()
            .get_param("hospital_chatbot.gemini_api_key", "")
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
        lang = (
            ConversationContextManager.get_language(session)
            or detect_language_from_phone(session.phone_number)
            or "es"
        )

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

        ConversationContextManager.append_user_message(session, user_message)

        # Language detection
        detected_lang = detect_language(user_message, current_lang=lang)
        if detected_lang:
            lang = detected_lang
            ConversationContextManager.set_language(session, lang)

        system_prompt = self._build_system_prompt(session, lang_override=lang)
        history = ConversationContextManager.get_history(session)

        sudo_env = self.env(user=1)
        tool_registry = ToolRegistry(sudo_env, self.chatbot, session.phone_number)

        total_input = 0
        total_output = 0
        api_call_count = 0

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

            _logger.info("AI response (%d chars): %s", len(response_text), response_text[:300])

        except Exception as e:
            _logger.error("Gemini error: %s", e, exc_info=True)
            response_text = get_ui_text("error_processing", lang)

        if api_call_count > 0:
            self._save_token_usage(session, total_input, total_output, api_call_count)

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

            if len(options) <= 3:
                responses.append(build_buttons_response(prompt, options, estimate_typing_delay(prompt)))
            else:
                rows = [{"id": opt["id"], "title": opt["label"]} for opt in options]
                sections = [{"title": get_ui_text("view_options", lang), "rows": rows}]
                responses.append(build_list_response(prompt, get_ui_text("view_options", lang), sections, estimate_typing_delay(prompt)))

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
        for opt in options:
            if opt["id"] == user_input:
                return opt["label"]
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
            or detect_language_from_phone(session.phone_number)
            or "es"
        )
        lang_name = _LANG_NAMES.get(lang_code, "Spanish")
        lang_directive = (
            f"LANGUAGE: You MUST respond EXCLUSIVELY in {lang_name}. "
            f"NEVER mix languages. Translate tool output to {lang_name}. "
            f"Every word must be in {lang_name}."
        )

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
        url = GEMINI_API_URL.format(model=self.CHAT_MODEL)
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
        }
        if tools:
            body["tools"] = tools

        resp = http_requests.post(
            url,
            headers={"Content-Type": "application/json"},
            params={"key": self.api_key},
            json=body,
            timeout=30,
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
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            parts = msg.get("parts", [])

            rest_parts = []
            for part in parts:
                if "text" in part:
                    rest_parts.append({"text": part["text"]})
                elif "function_call" in part:
                    fc = part["function_call"]
                    rest_parts.append({"functionCall": {"name": fc["name"], "args": fc.get("args", {})}})
                elif "function_response" in part:
                    fr = part["function_response"]
                    rest_parts.append({"functionResponse": {"name": fr["name"], "response": fr.get("response", {})}})

            if rest_parts:
                api_role = "user" if role == "function" else role
                contents.append({"role": api_role, "parts": rest_parts})

        return contents

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

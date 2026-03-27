"""Chatbot execution engine — port of billing/apps/chatbot/services/engine.py"""

from __future__ import annotations

import logging
import re
import time

import requests
from odoo import fields

_logger = logging.getLogger(__name__)

# Resume keywords that let the client return to the bot from human agent
_RESUME_PATTERNS = re.compile(
    r"^(assistente|assistant|bot|chatbot|atendimento|menu|voltar|back|ia|ai)$",
    re.IGNORECASE,
)

# Message type mapping from WhatsApp type strings to model selection values
_MSG_TYPE_MAP = {
    "text": "TEXT",
    "image": "IMAGE",
    "document": "DOCUMENT",
    "audio": "AUDIO",
    "video": "VIDEO",
    "sticker": "STICKER",
    "location": "LOCATION",
    "contact": "CONTACT",
}


class ChatbotEngine:
    """Motor de ejecución del chatbot."""

    def __init__(self, chatbot, env):
        """
        Args:
            chatbot: hospital.chatbot recordset (single)
            env: Odoo Environment (request.env)
        """
        self.chatbot = chatbot
        self.env = env
        self._ai_agent_service = None

    @property
    def ai_agent(self):
        """Lazy-loads AIAgentService only when needed."""
        if self._ai_agent_service is None:
            from odoo.addons.hospital_chatbot.services.ai_agent_service import (
                AIAgentService,
            )
            self._ai_agent_service = AIAgentService(self.chatbot, self.env)
        return self._ai_agent_service

    # =========================================================================
    # Main entry point
    # =========================================================================

    def process_message(
        self,
        phone_number: str,
        message: str,
        message_type: str = "text",
    ) -> list[dict]:
        """Process an incoming message and return a list of responses.

        Returns:
            [{"type": "text", "content": "..."}, ...]
        """
        session = self._get_or_create_session(phone_number)

        # Log incoming message (except special init messages)
        if message and message != "__init__":
            self._log_message(session, message, "INBOUND", message_type)

        # Check if session is paused (human agent has taken over)
        if session.transferred_to_agent:
            if self._is_resume_request(message):
                session.write({
                    "transferred_to_agent": False,
                    "current_node_id": False,
                    "current_flow_id": False,
                })
                _logger.info("Session %s resumed by client request", session.id)
                # Re-process as a new conversation so the flow menu is shown
                return self.process_message(phone_number, "__init__", "text")
            elif self._agent_timed_out(session):
                session.write({"transferred_to_agent": False})
                _logger.info("Session %s agent timed out, auto-resuming", session.id)
            else:
                _logger.info("Session %s transferred to agent, skipping", session.id)
                return []

        # If AI is enabled, route through AI agent
        if self.chatbot.ai_enabled:
            ctx = session.context or {}
            if ctx.get("ai_mode"):
                _logger.info("Session %s in AI mode, routing to AI agent", session.id)
                return self._process_ai_message(session, message)

            # If there's no flow structure, go straight to AI
            main_flow = self.chatbot.get_main_flow()
            has_flow = main_flow and main_flow.node_ids
            if not has_flow:
                _logger.info("AI enabled + no flow nodes, activating AI agent directly")
                if message == "__init__":
                    return self.ai_agent.start_conversation(
                        session, session.get_variable("user_name", "")
                    )
                return self._activate_ai_fallback(session, message)

        # Reset expired session
        if session.is_expired():
            _logger.info("Session %s expired, resetting", session.id)
            session.reset()

        responses = []
        is_new_flow = False
        is_init_message = message == "__init__"
        if is_init_message:
            message = ""

        _logger.info(
            "=== PROCESSING MESSAGE === Chatbot: %s, Phone: %s, Message: '%s'",
            self.chatbot.name,
            phone_number,
            message,
        )

        # If no current node, find flow by keyword or use main
        if not session.current_node_id:
            is_new_flow = True
            flow = self._find_flow_by_keyword(message)

            if flow:
                start_node = self._get_start_node(flow)
                if start_node:
                    session.write({
                        "current_flow_id": flow.id,
                        "current_node_id": start_node.id,
                    })
                else:
                    responses.append(self._create_fallback_response())
                    return responses
            else:
                # First interaction: send welcome message
                Message = self.env["hospital.chatbot.message"].sudo()
                msg_count = Message.search_count([("session_id", "=", session.id)])
                if msg_count <= 1 and self.chatbot.welcome_message:
                    welcome = self._replace_variables(
                        self.chatbot.welcome_message, session
                    )
                    responses.append({"type": "text", "content": welcome})
                    self._log_message(session, welcome, "OUTBOUND", "text")

                # Find main flow
                main_flow = self.chatbot.get_main_flow()
                if main_flow:
                    start_node = self._get_start_node(main_flow)
                    if start_node:
                        session.write({
                            "current_flow_id": main_flow.id,
                            "current_node_id": start_node.id,
                        })
                    else:
                        responses.append(self._create_fallback_response())
                        return responses
                else:
                    responses.append(self._create_fallback_response())
                    return responses

        # For new flows or init messages, show initial content without processing input
        if is_new_flow or is_init_message:
            message = None

        # Process nodes until one requires user input
        max_iterations = 50  # Safety limit
        iteration = 0
        while session.current_node_id and iteration < max_iterations:
            iteration += 1
            node = session.current_node_id
            node_responses, next_node, needs_input = self._process_node(
                node, session, message
            )
            responses.extend(node_responses)

            if needs_input:
                break

            if next_node:
                session.write({"current_node_id": next_node.id})
                message = None  # Already processed
            else:
                session.write({
                    "current_node_id": False,
                    "current_flow_id": False,
                })
                break

        # Update activity timestamp
        session.touch()

        # Log outbound responses
        for resp in responses:
            if not resp.get("_logged"):
                self._log_message(
                    session, resp.get("content", ""), "OUTBOUND", resp.get("type", "text")
                )
                resp["_logged"] = True

        # Clean internal flag
        for resp in responses:
            resp.pop("_logged", None)

        return responses

    # =========================================================================
    # Session management
    # =========================================================================

    def _get_or_create_session(self, phone_number: str):
        Session = self.env["hospital.chatbot.session"].sudo()
        session = Session.search(
            [
                ("chatbot_id", "=", self.chatbot.id),
                ("phone_number", "=", phone_number),
                ("is_active", "=", True),
            ],
            limit=1,
        )
        if not session:
            session = Session.create({
                "chatbot_id": self.chatbot.id,
                "phone_number": phone_number,
            })
            _logger.info("Created new session %s for %s", session.id, phone_number)
        return session

    # =========================================================================
    # Flow routing
    # =========================================================================

    def _find_flow_by_keyword(self, message: str):
        if not message:
            return None
        message_lower = message.lower().strip()
        for flow in self.chatbot.flow_ids:
            keywords = flow.trigger_keywords or []
            for keyword in keywords:
                if keyword.lower() in message_lower:
                    _logger.info("Found flow '%s' matching keyword '%s'", flow.name, keyword)
                    return flow
        return None

    def _get_start_node(self, flow):
        """Get start node of a flow. Falls back to first node by order."""
        start = flow.node_ids.filtered(lambda n: n.is_start)[:1]
        if start:
            return start
        first = flow.node_ids.sorted(key=lambda n: (n.order, n.id))[:1]
        if first:
            _logger.info("No is_start node, using first node: %s", first.name)
            return first
        _logger.warning("Flow '%s' has no nodes!", flow.name)
        return None

    # =========================================================================
    # Node processing — dispatch to handlers
    # =========================================================================

    def _process_node(self, node, session, user_input):
        """Process a node and return (responses, next_node, needs_input)."""
        handlers = {
            "MESSAGE": self._handle_message,
            "MENU": self._handle_menu,
            "QUESTION": self._handle_question,
            "CONDITION": self._handle_condition,
            "FILE": self._handle_file,
            "API_CALL": self._handle_api_call,
            "TRANSFER_AGENT": self._handle_transfer_agent,
            "DELAY": self._handle_delay,
            "SET_VARIABLE": self._handle_set_variable,
            "GO_TO_FLOW": self._handle_go_to_flow,
            "AI_AGENT": self._handle_ai_agent,
        }
        handler = handlers.get(node.node_type)
        if handler:
            return handler(node, session, user_input)
        _logger.warning("Unknown node type: %s", node.node_type)
        return [], node.get_next_node() or None, False

    # =========================================================================
    # Node handlers
    # =========================================================================

    def _handle_message(self, node, session, user_input):
        config = node.config or {}
        message = self._replace_variables(config.get("message", ""), session)
        responses = [{"type": "text", "content": message}]
        next_node = node.get_next_node()
        if not next_node:
            conn = node.outgoing_connection_ids[:1]
            next_node = conn.to_node_id if conn else None
        return responses, next_node, False

    def _handle_menu(self, node, session, user_input):
        config = node.config or {}
        menu_options = node.menu_option_ids

        # Show menu if no input
        if user_input is None:
            header = self._replace_variables(config.get("header", ""), session)
            if not menu_options:
                msg = header or "Menú sin opciones configuradas."
                return [{"type": "text", "content": msg}], node.get_next_node(), False

            menu_text = (header + "\n") if header else ""
            for opt in menu_options:
                menu_text += f"{opt.option_number}. {opt.option_text}\n"
            return [{"type": "text", "content": menu_text.strip()}], node, True

        # Process user selection
        user_input = user_input.strip()
        if not menu_options:
            return [], node.get_next_node(), False

        for option in menu_options:
            if (
                str(option.option_number) == user_input
                or user_input.lower() in option.option_text.lower()
            ):
                if option.next_node_id:
                    return [], option.next_node_id, False

                # Find connection by option_value
                conn = node.outgoing_connection_ids.filtered(
                    lambda c: c.option_value == str(option.option_number)
                )[:1]
                if conn:
                    return [], conn.to_node_id, False

                # Fallback: any outgoing connection
                any_conn = node.outgoing_connection_ids[:1]
                if any_conn:
                    return [], any_conn.to_node_id, False

                next_node = node.get_next_node()
                if next_node:
                    return [], next_node, False

        # Invalid option — try AI fallback if enabled
        if self.chatbot.ai_enabled:
            return self._activate_ai_fallback(session, user_input), None, False

        error_msg = config.get(
            "error_message", "Opción no válida. Por favor, intenta de nuevo."
        )
        return [{"type": "text", "content": error_msg}], node, True

    def _handle_question(self, node, session, user_input):
        config = node.config or {}
        if user_input is None:
            question = self._replace_variables(config.get("question", ""), session)
            return [{"type": "text", "content": question}], node, True

        variable_name = config.get("variable_name", f"question_{node.id}")
        session.set_variable(variable_name, user_input)

        validation = config.get("validation")
        if validation and not self._validate_input(user_input, validation):
            error_msg = config.get("validation_error", "Respuesta no válida.")
            return [{"type": "text", "content": error_msg}], node, True

        return [], node.get_next_node(), False

    def _handle_condition(self, node, session, user_input):
        config = node.config or {}
        conditions = config.get("conditions", [])
        Node = self.env["hospital.chatbot.node"].sudo()

        for cond in conditions:
            variable = cond.get("variable", "")
            operator = cond.get("operator", "equals")
            value = cond.get("value", "")
            target_node_id = cond.get("target_node_id")
            var_value = session.get_variable(variable, "")

            if self._evaluate_condition(var_value, operator, value):
                if target_node_id:
                    target = Node.browse(target_node_id).exists()
                    if target:
                        return [], target, False

                conn = node.outgoing_connection_ids.filtered(
                    lambda c: c.condition == f"{variable}{operator}{value}"
                )[:1]
                if conn:
                    return [], conn.to_node_id, False

        return [], node.get_next_node(), False

    def _handle_file(self, node, session, user_input):
        config = node.config or {}
        file_url = config.get("file_url", "")
        message = self._replace_variables(config.get("message", ""), session)

        file_id = config.get("file_id")
        if file_id:
            chatbot_file = self.env["hospital.chatbot.file"].sudo().browse(file_id).exists()
            if chatbot_file and chatbot_file.file:
                # Generate URL for the file attachment
                file_url = f"/web/content/hospital.chatbot.file/{chatbot_file.id}/file/{chatbot_file.file_name}"

        if file_url:
            responses = [{
                "type": "file",
                "content": message,
                "url": file_url,
                "filename": config.get("filename", "archivo"),
                "mimetype": config.get("mimetype", "application/octet-stream"),
            }]
        else:
            responses = [{"type": "text", "content": message}] if message else []

        return responses, node.get_next_node(), False

    def _handle_api_call(self, node, session, user_input):
        config = node.config or {}
        url = self._replace_variables(config.get("url", ""), session)
        method = config.get("method", "GET").upper()
        headers = config.get("headers", {})
        body = config.get("body", {})
        response_variable = config.get("response_variable", "api_response")

        body = self._replace_variables_in_dict(body, session)

        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                resp = requests.post(url, json=body, headers=headers, timeout=10)
            else:
                resp = requests.request(method, url, json=body, headers=headers, timeout=10)

            resp.raise_for_status()

            try:
                response_data = resp.json()
            except ValueError:
                response_data = resp.text

            session.set_variable(response_variable, response_data)

            extract_fields = config.get("extract_fields", {})
            for var_name, json_path in extract_fields.items():
                value = self._get_json_value(response_data, json_path)
                session.set_variable(var_name, value)

        except requests.RequestException as e:
            _logger.error("API call failed for node %s: %s", node.id, e)
            session.set_variable(response_variable, {"error": str(e)})

        return [], node.get_next_node(), False

    def _handle_transfer_agent(self, node, session, user_input):
        config = node.config or {}
        message = self._replace_variables(
            config.get("message", "Te estamos transfiriendo con un agente..."), session
        )
        session.write({"transferred_to_agent": True})
        return [{"type": "text", "content": message}], None, False

    def _handle_delay(self, node, session, user_input):
        config = node.config or {}
        seconds = config.get("seconds", 1)
        time.sleep(min(seconds, 5))  # Max 5 seconds to avoid blocking
        return [], node.get_next_node(), False

    def _handle_set_variable(self, node, session, user_input):
        config = node.config or {}
        variable_name = config.get("variable_name", "")
        value = config.get("value", "")
        if variable_name:
            value = self._replace_variables(str(value), session)
            session.set_variable(variable_name, value)
        return [], node.get_next_node(), False

    def _handle_go_to_flow(self, node, session, user_input):
        config = node.config or {}
        flow_id = config.get("flow_id")
        if flow_id:
            Flow = self.env["hospital.chatbot.flow"].sudo()
            target_flow = Flow.search(
                [("id", "=", flow_id), ("chatbot_id", "=", self.chatbot.id)],
                limit=1,
            )
            if target_flow:
                start_node = self._get_start_node(target_flow)
                if start_node:
                    session.write({"current_flow_id": target_flow.id})
                    return [], start_node, False
        return [], node.get_next_node(), False

    def _handle_ai_agent(self, node, session, user_input):
        """Handles AI_AGENT node — activates AI mode and starts conversation."""
        _logger.info("AI_AGENT node reached, activating AI mode")
        ctx = dict(session.context or {})
        ctx["ai_mode"] = True
        session.write({"context": ctx})
        responses = self.ai_agent.start_conversation(
            session, session.get_variable("user_name", "")
        )
        return responses, None, False

    # =========================================================================
    # AI agent integration
    # =========================================================================

    def _activate_ai_fallback(self, session, user_message: str) -> list[dict]:
        """Activate AI mode as fallback for unrecognized input."""
        ctx = dict(session.context or {})
        ctx["ai_mode"] = True
        session.write({
            "context": ctx,
            "current_node_id": False,
            "current_flow_id": False,
        })
        return self.ai_agent.process_message(session, user_message)

    def _process_ai_message(self, session, message: str) -> list[dict]:
        """Route a message through the AI agent."""
        responses = self.ai_agent.process_message(session, message)

        # Check if AI mode was deactivated
        ctx = session.context or {}
        if not ctx.get("ai_mode"):
            main_flow = self.chatbot.get_main_flow()
            if main_flow:
                start_node = self._get_start_node(main_flow)
                if start_node:
                    session.write({
                        "current_flow_id": main_flow.id,
                        "current_node_id": start_node.id,
                    })
                    menu_responses, _, _ = self._process_node(start_node, session, None)
                    responses.extend(menu_responses)

        # Log outbound responses
        for resp in responses:
            self._log_message(
                session, resp.get("content", ""), "OUTBOUND", resp.get("type", "text")
            )

        return responses

    # =========================================================================
    # Utilities
    # =========================================================================

    def _replace_variables(self, text: str, session) -> str:
        """Replace {{variable}} with session context values."""
        if not text:
            return text

        def replacer(match):
            var_name = match.group(1)
            value = session.get_variable(var_name, match.group(0))
            return str(value)

        return re.sub(r"\{\{(\w+)\}\}", replacer, text)

    def _replace_variables_in_dict(self, data: dict, session) -> dict:
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self._replace_variables(value, session)
            elif isinstance(value, dict):
                result[key] = self._replace_variables_in_dict(value, session)
            else:
                result[key] = value
        return result

    def _validate_input(self, input_value: str, validation: dict) -> bool:
        vtype = validation.get("type", "")
        if vtype == "email":
            return bool(re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", input_value))
        if vtype == "phone":
            return bool(re.match(r"^\+?[\d\s-]{7,}$", input_value))
        if vtype == "number":
            return input_value.isdigit()
        if vtype == "regex":
            try:
                return bool(re.match(validation.get("pattern", ""), input_value))
            except re.error:
                return True
        if vtype == "min_length":
            return len(input_value) >= validation.get("value", 1)
        if vtype == "max_length":
            return len(input_value) <= validation.get("value", 1000)
        return True

    def _evaluate_condition(self, var_value, operator: str, compare_value: str) -> bool:
        var_str = str(var_value).lower().strip()
        compare_str = str(compare_value).lower().strip()

        if operator == "equals":
            return var_str == compare_str
        if operator == "not_equals":
            return var_str != compare_str
        if operator == "contains":
            return compare_str in var_str
        if operator == "not_contains":
            return compare_str not in var_str
        if operator == "starts_with":
            return var_str.startswith(compare_str)
        if operator == "ends_with":
            return var_str.endswith(compare_str)
        if operator == "greater_than":
            try:
                return float(var_value) > float(compare_value)
            except (ValueError, TypeError):
                return False
        if operator == "less_than":
            try:
                return float(var_value) < float(compare_value)
            except (ValueError, TypeError):
                return False
        if operator == "is_empty":
            return not var_str
        if operator == "is_not_empty":
            return bool(var_str)
        return False

    def _get_json_value(self, data, path: str):
        if not path:
            return data
        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list):
                try:
                    current = current[int(key)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current

    def _create_fallback_response(self) -> dict:
        return {"type": "text", "content": self.chatbot.fallback_message}

    def _is_resume_request(self, message: str) -> bool:
        if not message:
            return False
        return bool(_RESUME_PATTERNS.match(message.strip()))

    def _agent_timed_out(self, session) -> bool:
        timeout_minutes = 15
        if not session.last_activity:
            return True
        elapsed = (fields.Datetime.now() - session.last_activity).total_seconds() / 60
        return elapsed > timeout_minutes

    def _log_message(self, session, content: str, direction: str, message_type: str = "text"):
        msg_type = _MSG_TYPE_MAP.get(message_type.lower(), "TEXT")
        self.env["hospital.chatbot.message"].sudo().create({
            "session_id": session.id,
            "direction": direction,
            "message_type": msg_type,
            "content": content or "",
            "node_id": session.current_node_id.id if session.current_node_id else False,
        })

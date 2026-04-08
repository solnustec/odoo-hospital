"""Chatbot execution engine — port of billing/apps/chatbot/services/engine.py"""

from __future__ import annotations

import logging
import re
import time

import requests
from odoo import fields

from .button_pagination import (
    build_paginated_buttons,
    clear_pending_pages,
    consume_next_page,
    is_show_more_input,
)

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

        # "Ver más" pagination intercept — emit the next batch of buttons
        # without disturbing node state. Works for both AI mode and flows
        # because pagination state lives in session.context.
        if is_show_more_input(message):
            from .ai_context import ConversationContextManager
            from .ai_prompts import get_ui_text
            lang = ConversationContextManager.get_language(session) or "es"
            responses = consume_next_page(
                session,
                more_text=get_ui_text("more_options", lang),
                show_more_label=get_ui_text("show_more", lang),
            )
            for resp in responses:
                self._log_message(
                    session,
                    resp.get("content", ""),
                    "OUTBOUND",
                    resp.get("type", "text"),
                )
            session.touch()
            return responses

        # Any non-Ver-más interaction invalidates stale pagination state.
        # If this turn renders a new paginated menu it will set fresh
        # pending pages; otherwise the next "Ver más" tap on an old
        # message correctly does nothing instead of replaying phantom
        # options.
        clear_pending_pages(session)

        # If AI is enabled, ALL messages go through the AI agent — flows are ignored
        if self.chatbot.ai_enabled:
            from odoo.addons.hospital_chatbot.services.ai_context import ConversationContextManager
            if ConversationContextManager.is_ai_mode(session):
                _logger.info("Session %s in AI mode, routing to AI agent", session.id)
                return self._process_ai_message(session, message)

            # First message or session not in AI mode yet — start AI conversation
            _logger.info("AI enabled, activating AI agent for session %s", session.id)
            if message == "__init__" or not message:
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

        # Global reset: if user is mid-flow and types a trigger keyword, restart
        if session.current_node_id and message:
            reset_flow = self._find_flow_by_keyword(message)
            if reset_flow:
                _logger.info("Trigger keyword detected mid-flow, resetting session")
                session.write({
                    "current_node_id": False,
                    "current_flow_id": False,
                    "context": {},
                })

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
            "BOOKING_ACTION": self._handle_booking_action,
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

    def _paginated_button_responses(self, session, header, options):
        """Wrap build_paginated_buttons with the session language lookup.

        ``options`` is a list of ``{"id", "label"}`` dicts. Returns the
        list of response dicts ready to send.
        """
        from .ai_context import ConversationContextManager
        from .ai_prompts import get_ui_text
        lang = ConversationContextManager.get_language(session) or "es"
        return build_paginated_buttons(
            session=session,
            all_options=options,
            prompt=header,
            more_text=get_ui_text("more_options", lang),
            show_more_label=get_ui_text("show_more", lang),
        )

    def _handle_menu(self, node, session, user_input):
        config = node.config or {}
        menu_options = node.menu_option_ids

        # Show menu if no input
        if user_input is None:
            header = self._replace_variables(config.get("header", ""), session)
            if not menu_options:
                msg = header or "Menú sin opciones configuradas."
                return [{"type": "text", "content": msg}], node.get_next_node(), False

            buttons = [
                {"id": str(opt.option_number), "label": opt.option_text[:20]}
                for opt in menu_options
            ]
            responses = self._paginated_button_responses(
                session, header or "Seleccione:", buttons
            )
            return responses, node, True

        # Process user selection
        user_input = user_input.strip()
        if not menu_options:
            return [], node.get_next_node(), False

        # If config has variable_name, store the selected option text
        variable_name = config.get("variable_name")

        for option in menu_options:
            if (
                str(option.option_number) == user_input
                or user_input.lower() in option.option_text.lower()
            ):
                # Store selected option in variable if configured
                if variable_name:
                    import re as _re
                    # Strip all emoji and special unicode (emoji, variation selectors, ZWJ, etc.)
                    clean_text = _re.sub(
                        r'[\U0001F000-\U0001FFFF\u2600-\u27BF\u2300-\u23FF\uFE0F\u200D\u20E3]+',
                        '', option.option_text
                    ).strip()
                    session.set_variable(variable_name, clean_text or option.option_text)

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
        responses = self.ai_agent.start_conversation(
            session, session.get_variable("user_name", "")
        )
        return responses, None, False

    def _handle_booking_action(self, node, session, user_input):
        """Handle BOOKING_ACTION node — interacts with the booking system.

        Config:
            action: find_doctors | check_availability | create_appointment
            + action-specific params referencing session variables
        """
        config = node.config or {}
        action = config.get("action", "")
        _logger.info("BOOKING_ACTION: %s", action)

        handler = {
            "find_doctors": self._booking_find_doctors,
            "check_availability": self._booking_check_availability,
            "select_slot": self._booking_select_slot,
            "create_appointment": self._booking_create_appointment,
        }.get(action)

        if not handler:
            _logger.warning("Unknown booking action: %s", action)
            return [{"type": "text", "content": "Error interno de configuración."}], node.get_next_node(), False

        return handler(node, session, user_input, config)

    # =========================================================================
    # Booking action handlers
    # =========================================================================

    def _booking_find_doctors(self, node, session, user_input, config):
        """Find doctors for the selected specialty that have availability on the date.

        Flow: specialty + date already collected → find matching doctors with slots.
        - If 1 doctor: auto-select, show slots directly.
        - If multiple: show list with slot counts, let user pick.
        - If none: tell user to try another date.
        """
        from odoo.addons.hospital_booking.services.availability import AvailabilityService

        specialty = session.get_variable("specialty", "")
        date_str = session.get_variable("preferred_date", "")
        sudo_env = self.env(user=1)

        # Parse date
        parsed_date = self._parse_date(date_str)
        if not parsed_date:
            return [{"type": "text", "content": f"No pude entender la fecha *{date_str}*. Intente con: 30/03/2026, mañana, lunes, etc."}], node, True

        session.set_variable("_parsed_date", parsed_date.isoformat())

        # Find all active doctors
        doctors = sudo_env["hr.employee"].search([
            ("is_doctor", "=", True),
            ("accepting_appointments", "=", True),
        ])

        # Match by specialty
        import unicodedata
        def _normalize(text):
            nfkd = unicodedata.normalize("NFKD", text.lower())
            return "".join(c for c in nfkd if not unicodedata.combining(c))

        # Use root/stem for matching (e.g. "cardiologia" → "cardiolog" matches "cardiologo")
        norm_spec = _normalize(specialty)
        # Strip common Spanish suffixes to find the root
        spec_root = norm_spec
        for suffix in ("logia", "logio", "logo", "loga", "ia", "ica", "ico", "ista"):
            if spec_root.endswith(suffix) and len(spec_root) > len(suffix) + 3:
                spec_root = spec_root[:-len(suffix)]
                break

        def _matches(text):
            nt = _normalize(text)
            # Full or root match
            if spec_root in nt or norm_spec in nt or nt in norm_spec:
                return True
            # Word-level match (e.g. "general" in "medico general")
            spec_words = [w for w in norm_spec.split() if len(w) >= 4]
            return any(w in nt for w in spec_words)

        matching = doctors.filtered(
            lambda d: _matches(d.job_title or "")
            or _matches(d.name or "")
            or any(_matches(s.name) for s in d.booking_service_ids)
        )

        if not matching:
            return [{
                "type": "text",
                "content": f"No encontramos médicos para *{specialty}*.\n\nEscriba *menu* para volver al inicio.",
            }], None, False

        # Check availability for each matching doctor on the date
        svc = AvailabilityService(sudo_env)
        import pytz
        doctors_with_slots = []
        for doc in matching:
            slots = svc.get_available_slots(parsed_date, doc)
            if slots:
                tz_name = doc.resource_calendar_id.tz if doc.resource_calendar_id else "America/Guayaquil"
                tz = pytz.timezone(tz_name)
                doctors_with_slots.append({
                    "doctor": doc,
                    "slots": slots,
                    "tz": tz,
                    "slot_count": len(slots),
                })

        weekday_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        day_name = weekday_names[parsed_date.weekday()]
        date_display = f"{day_name} {parsed_date.strftime('%d/%m/%Y')}"

        if not doctors_with_slots:
            return [{
                "type": "text",
                "content": (
                    f"No hay horarios disponibles para *{specialty}* "
                    f"el *{date_display}*.\n\n"
                    f"Intente con otra fecha, o escriba *menu* para volver al inicio."
                ),
            }], None, False

        if len(doctors_with_slots) == 1:
            # Auto-select the only doctor, show their slots
            info = doctors_with_slots[0]
            doc = info["doctor"]
            session.set_variable("doctor_id", doc.id)
            session.set_variable("doctor_name", doc.name)

            # Build slot list
            slot_lines, slot_map = self._format_slots(info["slots"], info["tz"])
            session.set_variable("_slot_choices", slot_map)

            header = (
                f"Su cita de *{specialty}* será con *{doc.name}* "
                f"el *{date_display}*."
            )

            # Build button options for slot selection
            slot_buttons = [
                {"id": key, "label": s_info["display"][:20]}
                for key, s_info in slot_map.items()
            ]

            # Advance to select_slot node and wait for input there
            next_node = node.get_next_node()  # select_slot
            if next_node:
                session.write({"current_node_id": next_node.id})
            return (
                self._paginated_button_responses(session, header, slot_buttons),
                next_node,
                True,
            )

        # Multiple doctors with availability — let user pick
        doc_choices = {}
        msg = (
            f"Médicos disponibles para *{specialty}* "
            f"el *{date_display}*:\n"
        )
        for i, info in enumerate(doctors_with_slots, 1):
            doc = info["doctor"]
            doc_choices[str(i)] = {"id": doc.id, "name": doc.name}
            msg += f"\n*{i}.* {doc.name} — {doc.job_title or ''} ({info['slot_count']} horarios)"

        session.set_variable("_doctor_choices", doc_choices)

        # Build button options for doctor selection
        doc_buttons = [
            {"id": key, "label": info["name"][:20]}
            for key, info in doc_choices.items()
        ]

        next_node = node.get_next_node()
        if next_node:
            session.write({"current_node_id": next_node.id})
        return (
            self._paginated_button_responses(
                session, msg.split("\n\n")[0], doc_buttons  # header only
            ),
            next_node,
            True,
        )

    def _format_slots(self, slots, tz, max_slots=12):
        """Format slots for display. Returns (slot_lines, slot_map)."""
        import pytz
        slot_lines = []
        slot_map = {}
        for i, slot in enumerate(slots[:max_slots], 1):
            local_start = slot["start"].astimezone(tz)
            local_end = slot["end"].astimezone(tz)
            time_str = f"{local_start.strftime('%H:%M')} - {local_end.strftime('%H:%M')}"
            slot_lines.append(f"*{i}.* {time_str}")
            utc_start = slot["start"].astimezone(pytz.utc)
            utc_end = slot["end"].astimezone(pytz.utc)
            slot_map[str(i)] = {
                "start": utc_start.replace(tzinfo=None).isoformat(),
                "end": utc_end.replace(tzinfo=None).isoformat(),
                "display": time_str,
            }
        return slot_lines, slot_map

    def _booking_check_availability(self, node, session, user_input, config):
        """Check available slots for the selected doctor and date."""
        from odoo.addons.hospital_booking.services.availability import AvailabilityService

        doctor_id = session.get_variable("doctor_id")
        date_str = session.get_variable("preferred_date", "")

        if not doctor_id:
            return [{"type": "text", "content": "Error: no se seleccionó un médico."}], node.get_next_node(), False

        sudo_env = self.env(user=1)
        doctor = sudo_env["hr.employee"].browse(int(doctor_id))
        if not doctor.exists():
            return [{"type": "text", "content": "Error: médico no encontrado."}], node.get_next_node(), False

        # Parse date from free text
        parsed_date = self._parse_date(date_str)
        if not parsed_date:
            # Go back to the date question node (previous node)
            return [{"type": "text", "content": f"No pude entender la fecha *{date_str}*. Intente con formato: 31/03/2026, mañana, lunes, etc."}], node, True

        session.set_variable("_parsed_date", parsed_date.isoformat())

        svc = AvailabilityService(sudo_env)
        slots = svc.get_available_slots(parsed_date, doctor)

        if not slots:
            weekday_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
            day_name = weekday_names[parsed_date.weekday()]
            return [{"type": "text", "content": f"No hay horarios disponibles con *{doctor.name}* el *{day_name} {parsed_date.strftime('%d/%m/%Y')}*.\n\nPor favor intente con otra fecha:"}], node, True

        # Format slots for user
        import pytz
        tz = pytz.timezone(doctor.resource_calendar_id.tz or "America/Guayaquil")
        slot_lines = []
        slot_map = {}
        for i, slot in enumerate(slots[:12], 1):  # max 12 slots
            local_start = slot["start"].astimezone(tz)
            local_end = slot["end"].astimezone(tz)
            time_str = f"{local_start.strftime('%H:%M')} - {local_end.strftime('%H:%M')}"
            slot_lines.append(f"{i}. {time_str}")
            # Store UTC for Odoo and local for display
            utc_start = slot["start"].astimezone(pytz.utc)
            utc_end = slot["end"].astimezone(pytz.utc)
            slot_map[str(i)] = {
                "start": utc_start.replace(tzinfo=None).isoformat(),
                "end": utc_end.replace(tzinfo=None).isoformat(),
                "display": time_str,
            }

        session.set_variable("_slot_choices", slot_map)

        weekday_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        day_name = weekday_names[parsed_date.weekday()]
        header = f"Horarios con *{doctor.name}* — {day_name} {parsed_date.strftime('%d/%m/%Y')}:"

        # Build button options for slot selection
        slot_buttons = [
            {"id": key, "label": slot_info["display"][:20]}
            for key, slot_info in slot_map.items()
        ]

        # Move to next node (select_slot) which will wait for user input
        return (
            self._paginated_button_responses(session, header, slot_buttons),
            node.get_next_node(),
            False,
        )

    def _booking_select_slot(self, node, session, user_input, config):
        """Process user's selection from a numbered list (doctor or time slot)."""
        if user_input is None:
            return [], node, True

        user_input = (user_input or "").strip()

        # Handle doctor selection if pending
        doctor_choices = session.get_variable("_doctor_choices")
        if doctor_choices and isinstance(doctor_choices, dict) and not session.get_variable("doctor_id"):
            choice = doctor_choices.get(user_input)
            if not choice:
                return [{"type": "text", "content": "Opción no válida. Escriba el número del médico:"}], node, True

            # Doctor selected — now show their slots
            from odoo.addons.hospital_booking.services.availability import AvailabilityService
            import pytz

            session.set_variable("doctor_id", choice["id"])
            session.set_variable("doctor_name", choice["name"])
            session.set_variable("_doctor_choices", None)

            sudo_env = self.env(user=1)
            doctor = sudo_env["hr.employee"].browse(choice["id"])
            parsed_date_str = session.get_variable("_parsed_date", "")
            if parsed_date_str:
                from datetime import date as date_type
                parsed_date = date_type.fromisoformat(parsed_date_str)
                svc = AvailabilityService(sudo_env)
                slots = svc.get_available_slots(parsed_date, doctor)
                if slots:
                    tz = pytz.timezone(doctor.resource_calendar_id.tz if doctor.resource_calendar_id else "America/Guayaquil")
                    slot_lines, slot_map = self._format_slots(slots, tz)
                    session.set_variable("_slot_choices", slot_map)

                    weekday_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
                    day_name = weekday_names[parsed_date.weekday()]
                    header = f"Horarios con *{doctor.name}* — {day_name} {parsed_date.strftime('%d/%m/%Y')}:"

                    slot_buttons = [
                        {"id": k, "label": v["display"][:20]}
                        for k, v in slot_map.items()
                    ]
                    return (
                        self._paginated_button_responses(session, header, slot_buttons),
                        node,
                        True,
                    )

            return [{"type": "text", "content": "No hay horarios disponibles. Escriba *menu* para reiniciar."}], None, False

        # Handle slot selection
        slot_choices = session.get_variable("_slot_choices")
        if slot_choices and isinstance(slot_choices, dict):
            choice = slot_choices.get(user_input)
            if not choice:
                return [{"type": "text", "content": "Opción no válida. Escriba el número del horario:"}], node, True
            session.set_variable("selected_slot_start", choice["start"])
            session.set_variable("selected_slot_end", choice["end"])
            session.set_variable("_slot_choices", None)
            return [], node.get_next_node(), False

        return [], node.get_next_node(), False

    def _booking_create_appointment(self, node, session, user_input, config):
        """Create the appointment in the calendar."""
        from odoo.addons.hospital_booking.services.validation import AppointmentValidationService

        patient_name = session.get_variable("patient_name", "")
        patient_phone = session.get_variable("patient_phone", "")
        doctor_id = session.get_variable("doctor_id")
        doctor_name = session.get_variable("doctor_name", "")
        specialty = session.get_variable("specialty", "")
        slot_start = session.get_variable("selected_slot_start", "")
        slot_end = session.get_variable("selected_slot_end", "")

        if not all([doctor_id, slot_start, slot_end]):
            return [{"type": "text", "content": "Error: faltan datos para crear la cita."}], node.get_next_node(), False

        # Use sudo with admin user to ensure proper company context
        sudo_env = self.env(user=1)

        # Find or create patient
        Partner = sudo_env["res.partner"]
        patient = None
        if patient_phone:
            clean_phone = re.sub(r"[^\d]", "", patient_phone)
            patient = Partner.search([
                "|", ("phone", "like", clean_phone[-8:]), ("mobile", "like", clean_phone[-8:])
            ], limit=1)
        if not patient and patient_name:
            patient = Partner.create({
                "name": patient_name,
                "phone": patient_phone,
                "mobile": patient_phone,
            })
            _logger.info("Created new patient: %s (%s)", patient_name, patient_phone)

        # Validate booking rules
        if patient:
            from datetime import date as date_type
            parsed_date_str = session.get_variable("_parsed_date", "")
            if parsed_date_str:
                booking_date = date_type.fromisoformat(parsed_date_str)
                vsvc = AppointmentValidationService(sudo_env)
                can_book, reason = vsvc.can_patient_book(patient, booking_date)
                if not can_book:
                    return [{"type": "text", "content": f"⚠️ No se puede agendar la cita: {reason}"}], node.get_next_node(), False

        # Parse slot datetimes
        from datetime import datetime as dt
        start = dt.fromisoformat(slot_start)
        end = dt.fromisoformat(slot_end)

        # Format for display — start is stored as naive UTC from slots
        import pytz
        doctor = self.env["hr.employee"].sudo().browse(int(doctor_id))
        tz = pytz.timezone(doctor.resource_calendar_id.tz if doctor.resource_calendar_id else "America/Guayaquil")
        # The slot times from _work_intervals_batch are UTC-aware; we stripped tz for storage
        # Convert back to local for display
        local_start = pytz.utc.localize(start).astimezone(tz)

        # Create calendar event
        try:
            event = sudo_env["calendar.event"].create({
                "name": f"Cita: {patient_name} — {specialty}",
                "start": start,
                "stop": end,
                "doctor_id": int(doctor_id),
                "patient_id": patient.id if patient else False,
                "patient_phone": patient_phone,
                "service_id": False,
                "is_appointment": True,
                "appointment_origin": "chatbot",
                "appointment_notes": f"Agendado via chatbot WhatsApp. Especialidad: {specialty}",
            })

            weekday_names = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            day_name = weekday_names[local_start.weekday()]

            msg = (
                f"✅ *¡Cita agendada exitosamente!*\n\n"
                f"📋 *Paciente:* {patient_name}\n"
                f"👨‍⚕️ *Médico:* {doctor_name}\n"
                f"🏥 *Especialidad:* {specialty}\n"
                f"📅 *Fecha:* {day_name} {local_start.strftime('%d/%m/%Y')}\n"
                f"🕐 *Hora:* {local_start.strftime('%H:%M')}\n"
                f"🔑 *Código:* #{event.id}\n\n"
                f"📌 Recuerde llegar 15 minutos antes de su cita.\n"
                f"Para cancelar, comuníquese al (02) 234-5678."
            )
            _logger.info("Appointment created: #%s for %s with %s", event.id, patient_name, doctor_name)
            return [{"type": "text", "content": msg}], node.get_next_node(), False

        except Exception as e:
            _logger.error("Failed to create appointment: %s", e)
            return [{"type": "text", "content": "❌ Hubo un error al crear la cita. Por favor intente nuevamente o contacte al (02) 234-5678."}], node.get_next_node(), False

    def _parse_date(self, text):
        """Parse a date from free text. Supports many formats."""
        from datetime import date, timedelta
        import locale

        if not text:
            return None

        text = text.strip().lower()
        today = date.today()

        # Relative dates
        if text in ("hoy", "today", "hoje"):
            return today
        if text in ("mañana", "manana", "tomorrow", "amanha", "amanhã"):
            return today + timedelta(days=1)
        if text in ("pasado mañana", "pasado manana"):
            return today + timedelta(days=2)

        # Day names (next occurrence)
        day_names = {
            "lunes": 0, "monday": 0, "segunda": 0,
            "martes": 1, "tuesday": 1, "terca": 1,
            "miercoles": 2, "miércoles": 2, "wednesday": 2, "quarta": 2,
            "jueves": 3, "thursday": 3, "quinta": 3,
            "viernes": 4, "friday": 4, "sexta": 4,
            "sabado": 5, "sábado": 5, "saturday": 5,
            "domingo": 6, "sunday": 6,
        }
        if text in day_names:
            target = day_names[text]
            days_ahead = target - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return today + timedelta(days=days_ahead)

        # "próximo lunes", "next monday"
        for day_word, day_num in day_names.items():
            if day_word in text and any(w in text for w in ("próximo", "proximo", "next", "que viene")):
                days_ahead = day_num - today.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                return today + timedelta(days=days_ahead)

        # Numeric formats: dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy, yyyy-mm-dd
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"):
            try:
                return __import__("datetime").datetime.strptime(text, fmt).date()
            except ValueError:
                continue

        # "30 marzo", "30 de marzo", "marzo 30", "30 mar"
        months_es = {
            "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3,
            "abril": 4, "abr": 4, "mayo": 5, "may": 5, "junio": 6, "jun": 6,
            "julio": 7, "jul": 7, "agosto": 8, "ago": 8, "septiembre": 9, "sep": 9, "sept": 9,
            "octubre": 10, "oct": 10, "noviembre": 11, "nov": 11, "diciembre": 12, "dic": 12,
        }
        for month_name, month_num in months_es.items():
            match = re.search(rf"(\d{{1,2}})\s*(?:de\s+)?{month_name}", text)
            if match:
                day = int(match.group(1))
                year = today.year
                try:
                    result = date(year, month_num, day)
                    if result < today:
                        result = date(year + 1, month_num, day)
                    return result
                except ValueError:
                    continue
            match = re.search(rf"{month_name}\s+(\d{{1,2}})", text)
            if match:
                day = int(match.group(1))
                year = today.year
                try:
                    result = date(year, month_num, day)
                    if result < today:
                        result = date(year + 1, month_num, day)
                    return result
                except ValueError:
                    continue

        return None

    # =========================================================================
    # AI agent integration
    # =========================================================================

    def _activate_ai_fallback(self, session, user_message: str) -> list[dict]:
        """Activate AI mode as fallback for unrecognized input."""
        from odoo.addons.hospital_chatbot.services.ai_context import ConversationContextManager
        ConversationContextManager.activate_ai_mode(session)
        session.write({"current_node_id": False, "current_flow_id": False})
        return self.ai_agent.process_message(session, user_message)

    def _process_ai_message(self, session, message: str) -> list[dict]:
        """Route a message through the AI agent."""
        responses = self.ai_agent.process_message(session, message)

        # Check if AI mode was deactivated (e.g. by end_ai_conversation)
        from odoo.addons.hospital_chatbot.services.ai_context import ConversationContextManager
        if not ConversationContextManager.is_ai_mode(session):
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

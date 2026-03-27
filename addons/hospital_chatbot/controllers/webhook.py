import json
import logging

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


def _json_response(data, status=200):
    return Response(
        json.dumps(data),
        content_type="application/json",
        status=status,
    )


class ChatbotWebhookController(http.Controller):

    def _validate_secret(self):
        """Validate webhook secret header."""
        expected = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("hospital_chatbot.webhook_secret", "")
        )
        if not expected or expected == "change-me-in-production":
            return True
        received = request.httprequest.headers.get("X-Webhook-Secret", "")
        return received == expected

    def _get_json_body(self):
        """Parse JSON body from raw HTTP request."""
        try:
            return json.loads(request.httprequest.get_data(as_text=True))
        except (json.JSONDecodeError, Exception):
            return {}

    @http.route(
        "/chatbot/webhook/incoming/",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def webhook_incoming(self):
        """Receive messages from WhatsApp service chatbot_listener."""
        if not self._validate_secret():
            return _json_response(
                {"processed": False, "reason": "unauthorized", "responses": []}, 401
            )

        data = self._get_json_body()
        emisor = data.get("emisor", "")
        from_number = data.get("from", "")
        message = data.get("message", "")
        message_type = data.get("type", "text")

        if not emisor or not from_number:
            return _json_response(
                {"processed": False, "reason": "missing_fields", "responses": []}, 400
            )

        # Find chatbot by WhatsApp phone number
        WhatsappPhone = request.env["hospital.chatbot.whatsapp.phone"].sudo()
        phone_record = WhatsappPhone.search(
            [("phone_number", "=", emisor), ("is_active", "=", True)],
            limit=1,
        )

        if not phone_record:
            _logger.info("No active WhatsApp phone found for: %s", emisor)
            return _json_response(
                {"processed": False, "reason": "no_session", "responses": []}
            )

        chatbot = phone_record.chatbot_id
        if not chatbot.is_active:
            _logger.info("Chatbot '%s' is not active", chatbot.name)
            return _json_response(
                {"processed": False, "reason": "no_chatbot", "responses": []}
            )

        # Process message through the engine
        from odoo.addons.hospital_chatbot.services.engine import ChatbotEngine

        engine = ChatbotEngine(chatbot, request.env)
        responses = engine.process_message(from_number, message, message_type)

        _logger.info(
            "Chatbot processed message from %s: %d responses",
            from_number,
            len(responses),
        )

        return _json_response({
            "processed": True,
            "responses_count": len(responses),
            "responses": responses,
        })

    @http.route(
        "/chatbot/webhook/pause-session/",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def webhook_pause_session(self):
        """Pause chatbot when human agent takes over."""
        if not self._validate_secret():
            return _json_response({"paused": False, "reason": "unauthorized"}, 401)

        data = self._get_json_body()
        phone_number = data.get("phone_number", "")
        session_phone = data.get("session_phone", "")

        if not phone_number or not session_phone:
            return _json_response({"paused": False, "reason": "missing_fields"}, 400)

        WhatsappPhone = request.env["hospital.chatbot.whatsapp.phone"].sudo()
        phone_record = WhatsappPhone.search(
            [("phone_number", "=", session_phone), ("is_active", "=", True)],
            limit=1,
        )

        if not phone_record:
            return _json_response({"paused": False, "reason": "no_whatsapp_session"})

        chatbot = phone_record.chatbot_id
        if not chatbot.is_active:
            return _json_response({"paused": False, "reason": "no_chatbot"})

        Session = request.env["hospital.chatbot.session"].sudo()
        session = Session.search(
            [
                ("chatbot_id", "=", chatbot.id),
                ("phone_number", "=", phone_number),
                ("is_active", "=", True),
            ],
            limit=1,
        )

        created = False
        if not session:
            session = Session.create({
                "chatbot_id": chatbot.id,
                "phone_number": phone_number,
            })
            created = True

        session.write({"transferred_to_agent": True})

        _logger.info(
            "Paused chatbot session for %s (chatbot: %s, created: %s)",
            phone_number,
            chatbot.name,
            created,
        )

        return _json_response(
            {"paused": True, "session_id": session.id, "created": created}
        )

    @http.route(
        "/chatbot/webhook/chatbot-phones/",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def webhook_chatbot_phones(self):
        """Return list of active chatbot phone numbers."""
        WhatsappPhone = request.env["hospital.chatbot.whatsapp.phone"].sudo()
        phones = WhatsappPhone.search([
            ("is_active", "=", True),
            ("chatbot_id.is_active", "=", True),
        ]).mapped("phone_number")

        return _json_response({"phones": phones})

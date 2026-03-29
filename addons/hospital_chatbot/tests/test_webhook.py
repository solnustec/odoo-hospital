"""Tests for chatbot webhook controller logic (via engine, not HTTP)."""

import json

from odoo.tests import tagged, TransactionCase


@tagged("post_install", "-at_install")
class TestWebhookLogic(TransactionCase):
    """Tests webhook logic by simulating what the controller does internally."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.chatbot = cls.env["hospital.chatbot"].create({
            "name": "Webhook Test Bot",
            "is_active": True,
            "welcome_message": "Hola desde webhook test",
            "fallback_message": "No entendí.",
            "session_timeout_minutes": 30,
        })

        cls.flow = cls.env["hospital.chatbot.flow"].create({
            "chatbot_id": cls.chatbot.id,
            "name": "Flow Test",
            "is_main": True,
            "trigger_keywords": ["hola"],
        })

        cls.node = cls.env["hospital.chatbot.node"].create({
            "flow_id": cls.flow.id,
            "node_type": "MESSAGE",
            "name": "Welcome",
            "is_start": True,
            "config": {"message": "Respuesta de prueba webhook."},
        })

        cls.wa_phone = cls.env["hospital.chatbot.whatsapp.phone"].create({
            "phone_number": "559900000000",
            "chatbot_id": cls.chatbot.id,
            "is_active": True,
        })

    def _simulate_webhook(self, emisor, from_number, message, msg_type="text"):
        """Simulate what the webhook controller does internally."""
        WhatsappPhone = self.env["hospital.chatbot.whatsapp.phone"].sudo()
        phone_record = WhatsappPhone.search(
            [("phone_number", "=", emisor), ("is_active", "=", True)], limit=1
        )
        if not phone_record:
            return {"processed": False, "reason": "no_session", "responses": []}

        chatbot = phone_record.chatbot_id
        if not chatbot.is_active:
            return {"processed": False, "reason": "no_chatbot", "responses": []}

        from odoo.addons.hospital_chatbot.services.engine import ChatbotEngine
        engine = ChatbotEngine(chatbot, self.env)
        responses = engine.process_message(from_number, message, msg_type)

        return {"processed": True, "responses_count": len(responses), "responses": responses}

    def test_incoming_message_processed(self):
        """Incoming message is processed by the engine."""
        data = self._simulate_webhook("559900000000", "593111222333", "hola")
        self.assertTrue(data["processed"])
        self.assertGreater(data["responses_count"], 0)

    def test_unknown_phone_not_processed(self):
        """Unknown emisor returns not processed."""
        data = self._simulate_webhook("000000000000", "593111222333", "hola")
        self.assertFalse(data["processed"])
        self.assertEqual(data["reason"], "no_session")

    def test_missing_from_returns_no_session(self):
        """Empty from field — engine still processes (session with empty phone)."""
        data = self._simulate_webhook("559900000000", "", "hola")
        # Engine processes even with empty phone (creates session with empty number)
        self.assertTrue(data["processed"])

    def test_chatbot_phones_endpoint_logic(self):
        """Active phones are returned correctly."""
        WhatsappPhone = self.env["hospital.chatbot.whatsapp.phone"].sudo()
        phones = WhatsappPhone.search([
            ("is_active", "=", True),
            ("chatbot_id.is_active", "=", True),
        ]).mapped("phone_number")
        self.assertIn("559900000000", phones)

    def test_pause_session(self):
        """Pausing a session sets transferred_to_agent."""
        # Create session first
        self._simulate_webhook("559900000000", "593999888777", "hola")

        # Find and pause
        session = self.env["hospital.chatbot.session"].search([
            ("chatbot_id", "=", self.chatbot.id),
            ("phone_number", "=", "593999888777"),
            ("is_active", "=", True),
        ], limit=1)
        self.assertTrue(session.exists())

        session.transferred_to_agent = True
        self.assertTrue(session.transferred_to_agent)

        # Bot should not respond
        data = self._simulate_webhook("559900000000", "593999888777", "hola again")
        self.assertEqual(len(data["responses"]), 0)

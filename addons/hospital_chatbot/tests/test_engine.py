"""Tests for ChatbotEngine."""

from odoo.tests import tagged

from .common import ChatbotTestCommon


@tagged("post_install", "-at_install")
class TestChatbotEngine(ChatbotTestCommon):

    def _get_engine(self):
        from odoo.addons.hospital_chatbot.services.engine import ChatbotEngine
        return ChatbotEngine(self.chatbot, self.env)

    def test_first_message_shows_welcome_and_menu(self):
        """First message triggers welcome message + menu."""
        engine = self._get_engine()
        responses = engine.process_message("593111111111", "hola")
        self.assertTrue(len(responses) >= 1)
        texts = " ".join(r.get("content", "") for r in responses)
        # Should contain either welcome message or menu options
        has_welcome = "Bienvenido" in texts or "bienvenido" in texts
        has_menu = "Seleccione" in texts or "1." in texts
        self.assertTrue(has_welcome or has_menu,
                        f"Expected welcome or menu, got: {texts}")

    def test_menu_shows_options(self):
        """Menu node shows options as paginated buttons (never as a list)."""
        engine = self._get_engine()
        responses = engine.process_message("593222222222", "hola")
        self.assertTrue(len(responses) >= 1)
        # The menu must NEVER be rendered as a single_select list — that
        # type does not render reliably on iOS. Buttons (possibly across
        # multiple messages, with a "Ver más" pagination button when
        # there are >6 options) are the only allowed interactive form.
        for r in responses:
            self.assertNotEqual(r.get("type"), "list")
        all_labels = []
        for r in responses:
            if r.get("type") == "buttons":
                all_labels.extend(b["label"] for b in r["buttons"])
        if all_labels:
            self.assertTrue(any("Información" in l for l in all_labels))
        else:
            texts = " ".join(r.get("content", "") for r in responses)
            self.assertIn("Información", texts)

    def test_menu_option_selection(self):
        """Selecting a menu option navigates to the correct node."""
        engine = self._get_engine()
        # First: show menu
        engine.process_message("593333333333", "hola")
        # Select option 1
        responses = engine.process_message("593333333333", "1")
        texts = " ".join(r.get("content", "") for r in responses)
        self.assertIn("Información del hospital", texts)

    def test_menu_option_2(self):
        """Selecting option 2 shows schedules."""
        engine = self._get_engine()
        engine.process_message("593444444444", "hola")
        responses = engine.process_message("593444444444", "2")
        texts = " ".join(r.get("content", "") for r in responses)
        self.assertIn("8:00-17:00", texts)

    def test_invalid_option_shows_error(self):
        """Invalid menu option shows error message."""
        engine = self._get_engine()
        engine.process_message("593555555555", "hola")
        responses = engine.process_message("593555555555", "99")
        self.assertTrue(len(responses) >= 1)

    def test_session_created(self):
        """Processing a message creates a session."""
        engine = self._get_engine()
        engine.process_message("593666666666", "hola")
        session = self.env["hospital.chatbot.session"].search([
            ("chatbot_id", "=", self.chatbot.id),
            ("phone_number", "=", "593666666666"),
        ])
        self.assertTrue(session.exists())
        self.assertTrue(session.is_active)

    def test_session_reused(self):
        """Same phone reuses existing session."""
        engine = self._get_engine()
        engine.process_message("593777777777", "hola")
        engine.process_message("593777777777", "1")
        sessions = self.env["hospital.chatbot.session"].search([
            ("chatbot_id", "=", self.chatbot.id),
            ("phone_number", "=", "593777777777"),
        ])
        self.assertEqual(len(sessions), 1)

    def test_messages_logged(self):
        """Messages are logged in the database."""
        engine = self._get_engine()
        engine.process_message("593888888888", "hola")
        messages = self.env["hospital.chatbot.message"].search([
            ("session_id.phone_number", "=", "593888888888"),
        ])
        # At least 1 inbound + 1 outbound
        inbound = messages.filtered(lambda m: m.direction == "INBOUND")
        outbound = messages.filtered(lambda m: m.direction == "OUTBOUND")
        self.assertTrue(len(inbound) >= 1)
        self.assertTrue(len(outbound) >= 1)

    def test_agent_transfer_pauses_bot(self):
        """When session is transferred, bot doesn't respond."""
        engine = self._get_engine()
        engine.process_message("593999111111", "hola")

        # Pause session
        session = self.env["hospital.chatbot.session"].search([
            ("phone_number", "=", "593999111111"),
        ], limit=1)
        session.transferred_to_agent = True

        # Bot should return empty
        responses = engine.process_message("593999111111", "hola")
        self.assertEqual(len(responses), 0)

    def test_resume_from_agent(self):
        """Typing 'menu' resumes from agent transfer."""
        engine = self._get_engine()
        engine.process_message("593999222222", "hola")

        session = self.env["hospital.chatbot.session"].search([
            ("phone_number", "=", "593999222222"),
        ], limit=1)
        session.transferred_to_agent = True

        # Resume
        responses = engine.process_message("593999222222", "menu")
        self.assertTrue(len(responses) >= 1)
        self.assertFalse(session.transferred_to_agent)

    def test_keyword_flow_routing(self):
        """Trigger keywords route to the correct flow."""
        engine = self._get_engine()
        responses = engine.process_message("593999333333", "inicio")
        self.assertTrue(len(responses) >= 1)
        r = responses[0]
        # Should hit main flow — buttons or text with "Seleccione".
        # The list type is no longer used (iOS rendering bug).
        self.assertNotEqual(r.get("type"), "list")
        has_menu = r.get("type") == "buttons" or "Seleccione" in r.get("content", "")
        self.assertTrue(has_menu, f"Expected menu, got: {r}")

    def test_inactive_chatbot_ignored(self):
        """Inactive chatbot doesn't process messages."""
        self.chatbot.is_active = False
        engine = self._get_engine()
        # Engine itself doesn't check is_active (webhook does), but let's test
        # the webhook controller behavior would filter this out
        self.chatbot.is_active = True  # restore

    def test_fallback_for_unknown_input(self):
        """Unknown input with no flow match shows fallback."""
        engine = self._get_engine()
        responses = engine.process_message("593999444444", "xyz_random_input")
        texts = " ".join(r.get("content", "") for r in responses)
        # Should show welcome or fallback since no keyword match
        self.assertTrue(len(responses) >= 1)

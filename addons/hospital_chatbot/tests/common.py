"""Common test setup for hospital_chatbot tests."""

from odoo.tests import TransactionCase


class ChatbotTestCommon(TransactionCase):
    """Base class with shared test data for chatbot tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Create chatbot
        cls.chatbot = cls.env["hospital.chatbot"].create({
            "name": "Test Bot",
            "is_active": True,
            "welcome_message": "¡Bienvenido! ¿En qué puedo ayudarle?",
            "fallback_message": "No entendí. Seleccione una opción.",
            "session_timeout_minutes": 30,
            "ai_enabled": False,
        })

        # Main flow with trigger keywords
        cls.main_flow = cls.env["hospital.chatbot.flow"].create({
            "chatbot_id": cls.chatbot.id,
            "name": "Menú principal",
            "is_main": True,
            "trigger_keywords": ["menu", "hola", "inicio"],
        })

        # Menu node (start)
        cls.menu_node = cls.env["hospital.chatbot.node"].create({
            "flow_id": cls.main_flow.id,
            "node_type": "MENU",
            "name": "Menú",
            "is_start": True,
            "config": {"header": "Seleccione:"},
        })

        # Response nodes
        cls.node_info = cls.env["hospital.chatbot.node"].create({
            "flow_id": cls.main_flow.id,
            "node_type": "MESSAGE",
            "name": "Info",
            "config": {"message": "Información del hospital."},
        })

        cls.node_horarios = cls.env["hospital.chatbot.node"].create({
            "flow_id": cls.main_flow.id,
            "node_type": "MESSAGE",
            "name": "Horarios",
            "config": {"message": "Lunes a Viernes 8:00-17:00."},
        })

        # Menu options
        cls.env["hospital.chatbot.menu.option"].create({
            "node_id": cls.menu_node.id,
            "option_number": 1,
            "option_text": "Información",
            "next_node_id": cls.node_info.id,
        })
        cls.env["hospital.chatbot.menu.option"].create({
            "node_id": cls.menu_node.id,
            "option_number": 2,
            "option_text": "Horarios",
            "next_node_id": cls.node_horarios.id,
        })

        # WhatsApp phone mapping
        cls.wa_phone = cls.env["hospital.chatbot.whatsapp.phone"].create({
            "phone_number": "559999999999",
            "chatbot_id": cls.chatbot.id,
            "is_active": True,
        })

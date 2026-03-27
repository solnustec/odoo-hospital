{
    "name": "Hospital Chatbot",
    "version": "17.0.1.0.0",
    "category": "Services",
    "summary": "Configurable WhatsApp chatbot with flow builder and AI agent for hospital management",
    "description": """
        Fully configurable WhatsApp chatbot integration for hospital management.
        Supports structured message flows (11 node types) and AI agent mode (Gemini).
        Connects to an external WhatsApp service via webhooks.
    """,
    "author": "Solnus",
    "website": "https://www.solnustec.com",
    "depends": ["base", "website", "hr", "calendar"],
    "data": [
        "security/chatbot_security.xml",
        "security/ir.model.access.csv",
        "data/chatbot_data.xml",
        "data/chatbot_cron.xml",
        "views/menu.xml",
        "views/flow_views.xml",
        "views/node_views.xml",
        "views/conversation_views.xml",
        "views/whatsapp_phone_views.xml",
        "views/ai_usage_views.xml",
        "wizard/chatbot_test_wizard_views.xml",
        "wizard/whatsapp_qr_wizard_views.xml",
        "views/chatbot_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hospital_chatbot/static/src/js/flow_builder.js",
            "hospital_chatbot/static/src/xml/flow_builder.xml",
            "hospital_chatbot/static/src/css/flow_builder.css",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "auto_install": False,
    "application": True,
}

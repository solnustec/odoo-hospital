from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    chatbot_gemini_api_key = fields.Char(
        string="Gemini API Key",
        config_parameter="hospital_chatbot.gemini_api_key",
    )
    chatbot_webhook_secret = fields.Char(
        string="Webhook Secret",
        config_parameter="hospital_chatbot.webhook_secret",
    )
    chatbot_whatsapp_service_url = fields.Char(
        string="URL del Servicio WhatsApp",
        config_parameter="hospital_chatbot.whatsapp_service_url",
    )
    chatbot_whatsapp_login_url = fields.Char(
        string="URL de Login WhatsApp",
        config_parameter="hospital_chatbot.whatsapp_login_url",
    )
    chatbot_whatsapp_check_url = fields.Char(
        string="URL de Verificación WhatsApp",
        config_parameter="hospital_chatbot.whatsapp_check_url",
    )

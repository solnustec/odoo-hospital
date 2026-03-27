from odoo import fields, models


class HospitalChatbotWhatsappPhone(models.Model):
    _name = "hospital.chatbot.whatsapp.phone"
    _description = "Teléfono WhatsApp"
    _sql_constraints = [
        (
            "unique_phone",
            "UNIQUE(phone_number)",
            "Este número de teléfono ya está registrado.",
        ),
    ]

    phone_number = fields.Char(
        string="Número de teléfono",
        required=True,
        help="Número de WhatsApp con código de país, sin +. Ej: 593999123456",
    )
    chatbot_id = fields.Many2one(
        "hospital.chatbot",
        string="Chatbot",
        required=True,
        ondelete="cascade",
    )
    is_active = fields.Boolean(string="Activo", default=True)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
    )

from odoo import fields, models

RESPONSE_TYPE = [
    ("TEXT", "Texto"),
    ("IMAGE", "Imagen"),
    ("DOCUMENT", "Documento"),
    ("AUDIO", "Audio"),
    ("VIDEO", "Video"),
]


class HospitalChatbotPredefinedResponse(models.Model):
    _name = "hospital.chatbot.predefined.response"
    _description = "Respuesta predefinida"
    _order = "name"
    _sql_constraints = [
        (
            "unique_name_per_chatbot",
            "UNIQUE(chatbot_id, name)",
            "Ya existe una respuesta con este nombre para este chatbot.",
        ),
    ]

    chatbot_id = fields.Many2one(
        "hospital.chatbot",
        string="Chatbot",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(
        string="Nombre",
        required=True,
        help="Nombre identificador para referenciar esta respuesta",
    )
    content = fields.Text(
        string="Contenido",
        help="Texto del mensaje. Soporta variables como {{nombre}}",
    )
    response_type = fields.Selection(
        RESPONSE_TYPE,
        string="Tipo de respuesta",
        default="TEXT",
    )
    file = fields.Binary(string="Archivo")
    file_name = fields.Char(string="Nombre de archivo")


class HospitalChatbotFile(models.Model):
    _name = "hospital.chatbot.file"
    _description = "Archivo de chatbot"
    _order = "create_date desc"

    chatbot_id = fields.Many2one(
        "hospital.chatbot",
        string="Chatbot",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(string="Nombre", required=True)
    file = fields.Binary(string="Archivo", required=True)
    file_name = fields.Char(string="Nombre de archivo")
    file_type = fields.Char(
        string="Tipo de archivo",
        help="MIME type del archivo",
    )
    description = fields.Text(string="Descripción")

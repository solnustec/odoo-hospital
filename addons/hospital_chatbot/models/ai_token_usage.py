from odoo import api, fields, models


class HospitalChatbotAITokenUsage(models.Model):
    _name = "hospital.chatbot.ai.token.usage"
    _description = "Uso de tokens IA"
    _order = "timestamp desc"

    chatbot_id = fields.Many2one(
        "hospital.chatbot",
        string="Chatbot",
        required=True,
        ondelete="cascade",
    )
    session_id = fields.Many2one(
        "hospital.chatbot.session",
        string="Sesión",
        ondelete="set null",
    )
    timestamp = fields.Datetime(
        string="Fecha/Hora",
        default=fields.Datetime.now,
        readonly=True,
    )
    input_tokens = fields.Integer(string="Tokens de entrada", default=0)
    output_tokens = fields.Integer(string="Tokens de salida", default=0)
    total_tokens = fields.Integer(string="Tokens totales", default=0)
    api_calls = fields.Integer(string="Llamadas API", default=1)

    estimated_cost = fields.Float(
        string="Costo estimado (USD)",
        compute="_compute_estimated_cost",
        digits=(10, 6),
        store=True,
    )

    @api.depends("input_tokens", "output_tokens")
    def _compute_estimated_cost(self):
        for rec in self:
            input_cost = (rec.input_tokens / 1_000_000) * 0.10
            output_cost = (rec.output_tokens / 1_000_000) * 0.40
            rec.estimated_cost = round(input_cost + output_cost, 6)


class HospitalChatbotAITokenDaily(models.Model):
    _name = "hospital.chatbot.ai.token.daily"
    _description = "Resumen diario de tokens IA"
    _order = "date desc"
    _sql_constraints = [
        (
            "unique_chatbot_date",
            "UNIQUE(chatbot_id, date)",
            "Ya existe un resumen para este chatbot en esta fecha.",
        ),
    ]

    chatbot_id = fields.Many2one(
        "hospital.chatbot",
        string="Chatbot",
        required=True,
        ondelete="cascade",
    )
    date = fields.Date(string="Fecha", required=True, index=True)
    input_tokens = fields.Integer(string="Tokens de entrada", default=0)
    output_tokens = fields.Integer(string="Tokens de salida", default=0)
    total_tokens = fields.Integer(string="Tokens totales", default=0)
    api_calls = fields.Integer(string="Llamadas API", default=0)
    unique_sessions = fields.Integer(
        string="Sesiones únicas",
        default=0,
        help="Cantidad de sesiones distintas que usaron IA este día",
    )
    estimated_cost = fields.Float(
        string="Costo estimado (USD)",
        digits=(10, 6),
        default=0,
    )

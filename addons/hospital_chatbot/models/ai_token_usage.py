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

    @api.model
    def _cron_aggregate_daily_usage(self):
        """Aggregate individual token usage records into daily summaries."""
        yesterday = fields.Date.subtract(fields.Date.today(), days=1)
        Usage = self.env["hospital.chatbot.ai.token.usage"]
        records = Usage.search([
            ("timestamp", ">=", fields.Datetime.to_string(
                fields.Datetime.start_of(
                    fields.Datetime.from_string(f"{yesterday} 00:00:00"), "day"
                )
            )),
            ("timestamp", "<", fields.Datetime.to_string(
                fields.Datetime.start_of(
                    fields.Datetime.from_string(f"{fields.Date.today()} 00:00:00"), "day"
                )
            )),
        ])
        if not records:
            return

        grouped = {}
        for rec in records:
            key = rec.chatbot_id.id
            if key not in grouped:
                grouped[key] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "api_calls": 0,
                    "session_ids": set(),
                    "estimated_cost": 0.0,
                }
            g = grouped[key]
            g["input_tokens"] += rec.input_tokens
            g["output_tokens"] += rec.output_tokens
            g["total_tokens"] += rec.total_tokens
            g["api_calls"] += rec.api_calls
            g["estimated_cost"] += rec.estimated_cost
            if rec.session_id:
                g["session_ids"].add(rec.session_id.id)

        for chatbot_id, data in grouped.items():
            existing = self.search([
                ("chatbot_id", "=", chatbot_id),
                ("date", "=", yesterday),
            ], limit=1)
            vals = {
                "chatbot_id": chatbot_id,
                "date": yesterday,
                "input_tokens": data["input_tokens"],
                "output_tokens": data["output_tokens"],
                "total_tokens": data["total_tokens"],
                "api_calls": data["api_calls"],
                "unique_sessions": len(data["session_ids"]),
                "estimated_cost": round(data["estimated_cost"], 6),
            }
            if existing:
                existing.write(vals)
            else:
                self.create(vals)

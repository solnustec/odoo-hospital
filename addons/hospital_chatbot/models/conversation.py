from odoo import api, fields, models

MESSAGE_DIRECTION = [
    ("INBOUND", "Entrante"),
    ("OUTBOUND", "Saliente"),
]

MESSAGE_TYPE = [
    ("TEXT", "Texto"),
    ("IMAGE", "Imagen"),
    ("DOCUMENT", "Documento"),
    ("AUDIO", "Audio"),
    ("VIDEO", "Video"),
    ("STICKER", "Sticker"),
    ("LOCATION", "Ubicación"),
    ("CONTACT", "Contacto"),
]


class HospitalChatbotSession(models.Model):
    _name = "hospital.chatbot.session"
    _description = "Sesión de conversación"
    _order = "last_activity desc"

    chatbot_id = fields.Many2one(
        "hospital.chatbot",
        string="Chatbot",
        required=True,
        ondelete="cascade",
    )
    phone_number = fields.Char(
        string="Número de teléfono",
        required=True,
        index=True,
    )
    current_node_id = fields.Many2one(
        "hospital.chatbot.node",
        string="Nodo actual",
        ondelete="set null",
    )
    current_flow_id = fields.Many2one(
        "hospital.chatbot.flow",
        string="Flujo actual",
        ondelete="set null",
    )
    context = fields.Json(
        string="Contexto",
        default={},
        help="Variables guardadas durante la conversación",
    )
    started_at = fields.Datetime(
        string="Iniciado",
        default=fields.Datetime.now,
        readonly=True,
    )
    last_activity = fields.Datetime(
        string="Última actividad",
        default=fields.Datetime.now,
    )
    is_active = fields.Boolean(string="Activa", default=True)
    transferred_to_agent = fields.Boolean(
        string="Transferido a agente",
        default=False,
        help="La conversación fue transferida a un agente humano",
    )
    agent_notes = fields.Text(string="Notas del agente")

    # Relations
    message_ids = fields.One2many(
        "hospital.chatbot.message", "session_id", string="Mensajes"
    )

    # Computed
    message_count = fields.Integer(
        compute="_compute_message_count", string="Mensajes"
    )

    @api.depends("message_ids")
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    def is_expired(self):
        self.ensure_one()
        if not self.last_activity:
            return True
        timeout = self.chatbot_id.session_timeout_minutes
        elapsed = (fields.Datetime.now() - self.last_activity).total_seconds() / 60
        return elapsed > timeout

    def reset(self):
        self.ensure_one()
        self.write({
            "current_node_id": False,
            "current_flow_id": False,
            "context": {},
            "transferred_to_agent": False,
        })

    def set_variable(self, key, value):
        self.ensure_one()
        ctx = dict(self.context or {})
        ctx[key] = value
        self.write({"context": ctx})

    def get_variable(self, key, default=None):
        self.ensure_one()
        return (self.context or {}).get(key, default)

    def touch(self):
        """Update last_activity timestamp."""
        self.ensure_one()
        self.write({"last_activity": fields.Datetime.now()})

    @api.model
    def _cron_cleanup_expired_sessions(self):
        """Deactivate expired sessions. Called by cron."""
        chatbots = self.env["hospital.chatbot"].sudo().search([("is_active", "=", True)])
        for chatbot in chatbots:
            timeout = chatbot.session_timeout_minutes or 30
            cutoff = fields.Datetime.subtract(fields.Datetime.now(), minutes=timeout)
            expired = self.sudo().search([
                ("chatbot_id", "=", chatbot.id),
                ("is_active", "=", True),
                ("last_activity", "<", cutoff),
            ])
            if expired:
                expired.write({"is_active": False})
        return True


class HospitalChatbotMessage(models.Model):
    _name = "hospital.chatbot.message"
    _description = "Mensaje de conversación"
    _order = "timestamp"

    session_id = fields.Many2one(
        "hospital.chatbot.session",
        string="Sesión",
        required=True,
        ondelete="cascade",
    )
    direction = fields.Selection(
        MESSAGE_DIRECTION,
        string="Dirección",
        required=True,
    )
    message_type = fields.Selection(
        MESSAGE_TYPE,
        string="Tipo de mensaje",
        default="TEXT",
    )
    content = fields.Text(string="Contenido")
    file_url = fields.Char(string="URL de archivo")
    timestamp = fields.Datetime(
        string="Fecha/Hora",
        default=fields.Datetime.now,
        readonly=True,
    )
    node_id = fields.Many2one(
        "hospital.chatbot.node",
        string="Nodo",
        ondelete="set null",
        help="Nodo que generó o procesó este mensaje",
    )
    metadata = fields.Json(
        string="Metadata",
        default={},
        help="Información adicional del mensaje",
    )

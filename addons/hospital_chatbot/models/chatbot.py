from odoo import api, fields, models


NODE_TYPE_SELECTION = [
    ("MESSAGE", "Mensaje"),
    ("MENU", "Menú de opciones"),
    ("QUESTION", "Pregunta abierta"),
    ("CONDITION", "Condición"),
    ("FILE", "Enviar archivo"),
    ("API_CALL", "Llamada API"),
    ("TRANSFER_AGENT", "Transferir a agente"),
    ("DELAY", "Esperar tiempo"),
    ("SET_VARIABLE", "Establecer variable"),
    ("GO_TO_FLOW", "Ir a otro flujo"),
    ("AI_AGENT", "Agente IA"),
]


class HospitalChatbot(models.Model):
    _name = "hospital.chatbot"
    _description = "Chatbot"
    _order = "create_date desc"

    name = fields.Char(string="Nombre", required=True)
    is_active = fields.Boolean(string="Activo", default=False)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
    )
    welcome_message = fields.Text(
        string="Mensaje de bienvenida",
        help="Mensaje que se envía cuando inicia una nueva conversación",
    )
    fallback_message = fields.Text(
        string="Mensaje de respaldo",
        default="No entendí tu mensaje. Por favor, intenta de nuevo.",
        help="Mensaje cuando no se encuentra una respuesta",
    )
    session_timeout_minutes = fields.Integer(
        string="Timeout de sesión (minutos)",
        default=30,
        help="Minutos de inactividad antes de reiniciar la conversación",
    )

    # AI Agent configuration
    ai_enabled = fields.Boolean(
        string="IA habilitada",
        default=False,
        help="Habilita el agente IA para este chatbot",
    )
    ai_system_prompt = fields.Text(
        string="Prompt del sistema IA",
        help="Instrucciones personalizadas para el agente IA",
    )
    ai_max_history_messages = fields.Integer(
        string="Máximo de mensajes en historial IA",
        default=20,
        help="Cantidad máxima de mensajes a mantener en el contexto del LLM",
    )
    ai_agent_name = fields.Char(
        string="Nombre del agente IA",
        help="Nombre con el que se presentará el agente IA (ej: Sofía)",
    )
    ai_emotion = fields.Selection(
        [
            ("neutral", "Neutral"),
            ("friendly", "Amigable"),
            ("formal", "Formal"),
        ],
        string="Tono del agente",
        default="friendly",
    )
    ai_seriousness = fields.Integer(
        string="Nivel de seriedad",
        default=5,
        help="1=muy casual, 10=muy serio y profesional",
    )

    # Relations
    flow_ids = fields.One2many("hospital.chatbot.flow", "chatbot_id", string="Flujos")
    session_ids = fields.One2many(
        "hospital.chatbot.session", "chatbot_id", string="Sesiones"
    )
    whatsapp_phone_ids = fields.One2many(
        "hospital.chatbot.whatsapp.phone", "chatbot_id", string="Teléfonos WhatsApp"
    )

    # Computed
    flow_count = fields.Integer(compute="_compute_flow_count", string="Flujos")
    active_session_count = fields.Integer(
        compute="_compute_active_session_count", string="Sesiones activas"
    )

    @api.depends("flow_ids")
    def _compute_flow_count(self):
        for rec in self:
            rec.flow_count = len(rec.flow_ids)

    @api.depends("session_ids")
    def _compute_active_session_count(self):
        for rec in self:
            rec.active_session_count = self.env["hospital.chatbot.session"].search_count(
                [("chatbot_id", "=", rec.id), ("is_active", "=", True)]
            )

    def get_main_flow(self):
        self.ensure_one()
        return self.flow_ids.filtered(lambda f: f.is_main)[:1]

    @api.model
    def _cron_send_appointment_reminders(self):
        """Send WhatsApp reminders for tomorrow's appointments. Called by cron."""
        import logging
        import requests as http_requests

        _logger = logging.getLogger(__name__)
        tomorrow = fields.Date.add(fields.Date.today(), days=1)
        whatsapp_url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("hospital_chatbot.whatsapp_service_url", "")
        )
        if not whatsapp_url:
            return True

        # Find tomorrow's calendar events
        events = self.env["calendar.event"].sudo().search([
            ("start", ">=", f"{tomorrow} 00:00:00"),
            ("start", "<", f"{fields.Date.add(tomorrow, days=1)} 00:00:00"),
        ])

        for event in events:
            for attendee in event.attendee_ids:
                partner = attendee.partner_id
                phone = partner.phone or partner.mobile
                if not phone:
                    continue
                # Clean phone number
                phone = phone.replace("+", "").replace(" ", "").replace("-", "")

                # Find a WhatsApp phone to send from
                wa_phone = self.env["hospital.chatbot.whatsapp.phone"].sudo().search(
                    [("is_active", "=", True)], limit=1
                )
                if not wa_phone:
                    continue

                start_time = event.start.strftime("%H:%M")
                message = (
                    f"Recordatorio: Tiene una cita mañana {tomorrow.strftime('%d/%m/%Y')} "
                    f"a las {start_time}.\n{event.name or ''}"
                )

                try:
                    http_requests.post(
                        f"{whatsapp_url}/sendmessage",
                        json={
                            "emisor": wa_phone.phone_number,
                            "messages": [{
                                "destinatary": phone,
                                "message": message,
                            }],
                        },
                        timeout=10,
                    )
                except Exception as e:
                    _logger.warning("Failed to send reminder to %s: %s", phone, e)

        return True


class HospitalChatbotFlow(models.Model):
    _name = "hospital.chatbot.flow"
    _description = "Flujo de conversación"
    _order = "is_main desc, name"

    chatbot_id = fields.Many2one(
        "hospital.chatbot",
        string="Chatbot",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(string="Nombre", required=True)
    description = fields.Text(string="Descripción")
    is_main = fields.Boolean(
        string="Flujo principal",
        default=False,
        help="Este flujo se ejecuta al iniciar la conversación",
    )
    trigger_keywords = fields.Json(
        string="Palabras clave",
        default=[],
        help='Lista de palabras que activan este flujo. Ej: ["menu", "ayuda"]',
    )

    # Relations
    node_ids = fields.One2many("hospital.chatbot.node", "flow_id", string="Nodos")

    # Computed
    node_count = fields.Integer(compute="_compute_node_count", string="Nodos")

    @api.depends("node_ids")
    def _compute_node_count(self):
        for rec in self:
            rec.node_count = len(rec.node_ids)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.is_main:
                self.search([
                    ("chatbot_id", "=", rec.chatbot_id.id),
                    ("is_main", "=", True),
                    ("id", "!=", rec.id),
                ]).write({"is_main": False})
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get("is_main"):
            for rec in self:
                self.search([
                    ("chatbot_id", "=", rec.chatbot_id.id),
                    ("is_main", "=", True),
                    ("id", "!=", rec.id),
                ]).write({"is_main": False})
        return res

    def get_start_node(self):
        self.ensure_one()
        return self.node_ids.filtered(lambda n: n.is_start)[:1]


class HospitalChatbotNode(models.Model):
    _name = "hospital.chatbot.node"
    _description = "Nodo de flujo"
    _order = "order, id"

    flow_id = fields.Many2one(
        "hospital.chatbot.flow",
        string="Flujo",
        required=True,
        ondelete="cascade",
    )
    node_type = fields.Selection(
        NODE_TYPE_SELECTION,
        string="Tipo de nodo",
        required=True,
        default="MESSAGE",
    )
    name = fields.Char(string="Nombre", required=True)
    position_x = fields.Float(string="Posición X", default=0)
    position_y = fields.Float(string="Posición Y", default=0)
    order = fields.Integer(string="Orden", default=0)
    is_start = fields.Boolean(
        string="Nodo inicial",
        default=False,
        help="Este nodo es el punto de entrada del flujo",
    )
    config = fields.Json(
        string="Configuración",
        default={},
        help="Configuración específica según el tipo de nodo",
    )

    # Relations
    outgoing_connection_ids = fields.One2many(
        "hospital.chatbot.node.connection",
        "from_node_id",
        string="Conexiones salientes",
    )
    incoming_connection_ids = fields.One2many(
        "hospital.chatbot.node.connection",
        "to_node_id",
        string="Conexiones entrantes",
    )
    menu_option_ids = fields.One2many(
        "hospital.chatbot.menu.option",
        "node_id",
        string="Opciones de menú",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.is_start:
                self.search([
                    ("flow_id", "=", rec.flow_id.id),
                    ("is_start", "=", True),
                    ("id", "!=", rec.id),
                ]).write({"is_start": False})
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get("is_start"):
            for rec in self:
                self.search([
                    ("flow_id", "=", rec.flow_id.id),
                    ("is_start", "=", True),
                    ("id", "!=", rec.id),
                ]).write({"is_start": False})
        return res

    def get_next_node(self):
        """Get default next node (first connection without condition)."""
        self.ensure_one()
        connection = self.outgoing_connection_ids.filtered(
            lambda c: not c.condition and not c.option_value
        )[:1]
        return connection.to_node_id if connection else self.env["hospital.chatbot.node"]


class HospitalChatbotNodeConnection(models.Model):
    _name = "hospital.chatbot.node.connection"
    _description = "Conexión entre nodos"
    _sql_constraints = [
        (
            "unique_connection",
            "UNIQUE(from_node_id, to_node_id, option_value)",
            "Ya existe una conexión con este valor de opción entre estos nodos.",
        ),
    ]

    from_node_id = fields.Many2one(
        "hospital.chatbot.node",
        string="Desde nodo",
        required=True,
        ondelete="cascade",
    )
    to_node_id = fields.Many2one(
        "hospital.chatbot.node",
        string="Hacia nodo",
        required=True,
        ondelete="cascade",
    )
    condition = fields.Char(
        string="Condición",
        help="Condición para seguir esta conexión (para nodos CONDITION)",
    )
    option_value = fields.Char(
        string="Valor de opción",
        help="Número de opción del menú que activa esta conexión",
    )
    label = fields.Char(
        string="Etiqueta",
        help="Etiqueta visible en el builder",
    )


class HospitalChatbotMenuOption(models.Model):
    _name = "hospital.chatbot.menu.option"
    _description = "Opción de menú"
    _order = "option_number"
    _sql_constraints = [
        (
            "unique_option",
            "UNIQUE(node_id, option_number)",
            "Ya existe una opción con este número en este nodo.",
        ),
    ]

    node_id = fields.Many2one(
        "hospital.chatbot.node",
        string="Nodo",
        required=True,
        ondelete="cascade",
    )
    option_number = fields.Integer(string="Número de opción", required=True)
    option_text = fields.Char(string="Texto de la opción", required=True)
    next_node_id = fields.Many2one(
        "hospital.chatbot.node",
        string="Siguiente nodo",
        ondelete="set null",
    )

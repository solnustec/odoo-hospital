from odoo import fields, models


class HospitalChatbotAIAuditLog(models.Model):
    _name = "hospital.chatbot.ai.audit.log"
    _description = "Registro de auditoría del agente IA"
    _order = "timestamp desc"

    session_id = fields.Many2one(
        "hospital.chatbot.session",
        string="Sesión",
        ondelete="set null",
        index=True,
    )
    chatbot_id = fields.Many2one(
        "hospital.chatbot",
        string="Chatbot",
        ondelete="set null",
    )
    phone_number = fields.Char(string="Teléfono")
    tool_name = fields.Char(string="Herramienta", index=True)
    tool_args = fields.Json(string="Argumentos")
    tool_result = fields.Json(string="Resultado")
    is_write_operation = fields.Boolean(string="Es operación de escritura")
    was_confirmed = fields.Boolean(string="Fue confirmado por usuario")
    confirmation_token = fields.Char(string="Token de confirmación")
    timestamp = fields.Datetime(
        string="Fecha/Hora",
        default=fields.Datetime.now,
        readonly=True,
    )

    @classmethod
    def log_tool_call(
        cls, env, session, chatbot, tool_name, tool_args, tool_result,
        is_write=False, was_confirmed=False, token=""
    ):
        """Log a tool call to the audit log."""
        env["hospital.chatbot.ai.audit.log"].sudo().create({
            "session_id": session.id if session else False,
            "chatbot_id": chatbot.id if chatbot else False,
            "phone_number": session.phone_number if session else "",
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_result": tool_result,
            "is_write_operation": is_write,
            "was_confirmed": was_confirmed,
            "confirmation_token": token,
        })

import logging
import secrets
import string
from datetime import timedelta

from odoo import fields, models

_logger = logging.getLogger(__name__)

TOKEN_LENGTH = 6
TOKEN_EXPIRY_MINUTES = 5
_TOKEN_ALPHABET = string.ascii_uppercase + string.digits


def _generate_token() -> str:
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))


class HospitalChatbotAIPendingAction(models.Model):
    _name = "hospital.chatbot.ai.pending.action"
    _description = "Acción pendiente del agente IA"
    _order = "create_date desc"

    session_id = fields.Many2one(
        "hospital.chatbot.session",
        string="Sesión",
        required=True,
        ondelete="cascade",
        index=True,
    )
    token = fields.Char(
        string="Token",
        required=True,
        index=True,
    )
    tool_name = fields.Char(string="Herramienta", required=True)
    tool_args = fields.Json(string="Argumentos")
    summary = fields.Char(string="Resumen de la acción")
    status = fields.Selection(
        [
            ("pending", "Pendiente"),
            ("confirmed", "Confirmado"),
            ("expired", "Expirado"),
            ("rejected", "Rechazado"),
        ],
        string="Estado",
        default="pending",
        required=True,
    )
    expires_at = fields.Datetime(string="Expira en", required=True)
    executed_at = fields.Datetime(string="Ejecutado en")
    result = fields.Json(string="Resultado")

    def is_expired(self):
        self.ensure_one()
        return self.status == "pending" and fields.Datetime.now() > self.expires_at

    @classmethod
    def create_pending(cls, env, session, tool_name, tool_args, summary=""):
        """Create a new pending action with a unique token."""
        token = _generate_token()
        expires_at = fields.Datetime.now() + timedelta(minutes=TOKEN_EXPIRY_MINUTES)
        return env["hospital.chatbot.ai.pending.action"].sudo().create({
            "session_id": session.id,
            "token": token,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "summary": summary,
            "expires_at": expires_at,
        })

    @staticmethod
    def find_by_token(env, session, token):
        """Find a pending action by token within a session."""
        return env["hospital.chatbot.ai.pending.action"].sudo().search([
            ("session_id", "=", session.id),
            ("token", "=", token.strip().upper()),
            ("status", "=", "pending"),
        ], limit=1)

    def mark_confirmed(self, result):
        self.ensure_one()
        self.write({
            "status": "confirmed",
            "executed_at": fields.Datetime.now(),
            "result": result,
        })

    def mark_expired(self):
        self.ensure_one()
        self.write({"status": "expired"})

    def mark_rejected(self):
        self.ensure_one()
        self.write({"status": "rejected"})

    @classmethod
    def cron_expire_pending(cls, env):
        """Expire pending actions older than TOKEN_EXPIRY_MINUTES."""
        expired = env["hospital.chatbot.ai.pending.action"].sudo().search([
            ("status", "=", "pending"),
            ("expires_at", "<", fields.Datetime.now()),
        ])
        if expired:
            expired.write({"status": "expired"})
            _logger.info("Expired %d pending AI actions", len(expired))

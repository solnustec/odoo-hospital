from odoo import api, fields, models
from odoo.addons.hospital_chatbot.services.engine import ChatbotEngine


class ChatbotTestWizard(models.TransientModel):
    _name = "hospital.chatbot.test.wizard"
    _description = "Probar Chatbot"

    chatbot_id = fields.Many2one(
        "hospital.chatbot",
        string="Chatbot",
        required=True,
    )
    phone_number = fields.Char(
        string="Teléfono de prueba",
        default="test_0000",
        required=True,
    )
    message = fields.Char(string="Mensaje")
    response_display = fields.Html(
        string="Respuestas",
        readonly=True,
    )
    session_info = fields.Text(
        string="Estado de sesión",
        readonly=True,
    )

    def action_send(self):
        self.ensure_one()
        if not self.message:
            return

        engine = ChatbotEngine(self.chatbot_id, self.env)
        responses = engine.process_message(
            self.phone_number, self.message, "text"
        )

        # Format responses as HTML
        html_parts = []
        for resp in responses:
            rtype = resp.get("type", "text")
            content = resp.get("content", "")
            if rtype == "text":
                html_parts.append(
                    f'<div style="background:#dcf8c6;padding:8px 12px;border-radius:8px;'
                    f'margin:4px 0;max-width:80%;">{content}</div>'
                )
            elif rtype == "buttons":
                html_parts.append(
                    f'<div style="background:#dcf8c6;padding:8px 12px;border-radius:8px;'
                    f'margin:4px 0;">{content}</div>'
                )
                for btn in resp.get("buttons", []):
                    html_parts.append(
                        f'<div style="background:#e3f2fd;padding:4px 8px;border-radius:4px;'
                        f'margin:2px 0;font-size:12px;">🔘 {btn.get("label", "")}</div>'
                    )
            else:
                html_parts.append(
                    f'<div style="background:#f0f0f0;padding:8px 12px;border-radius:8px;'
                    f'margin:4px 0;">[{rtype}] {content}</div>'
                )

        # Get session info
        Session = self.env["hospital.chatbot.session"].sudo()
        session = Session.search([
            ("chatbot_id", "=", self.chatbot_id.id),
            ("phone_number", "=", self.phone_number),
            ("is_active", "=", True),
        ], limit=1)

        session_text = ""
        if session:
            ctx = session.context or {}
            session_text = (
                f"Sesión ID: {session.id}\n"
                f"Flujo actual: {session.current_flow_id.name or 'Ninguno'}\n"
                f"Nodo actual: {session.current_node_id.name or 'Ninguno'}\n"
                f"Modo IA: {ctx.get('ai_mode', False)}\n"
                f"Transferido: {session.transferred_to_agent}\n"
                f"Mensajes: {session.message_count}"
            )

        self.write({
            "response_display": "".join(html_parts) or "<em>Sin respuesta</em>",
            "session_info": session_text,
            "message": "",
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "views": [[False, "form"]],
            "target": "new",
        }

    def action_reset_session(self):
        self.ensure_one()
        Session = self.env["hospital.chatbot.session"].sudo()
        sessions = Session.search([
            ("chatbot_id", "=", self.chatbot_id.id),
            ("phone_number", "=", self.phone_number),
        ])
        sessions.unlink()

        self.write({
            "response_display": "<em>Sesión reiniciada</em>",
            "session_info": "",
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "views": [[False, "form"]],
            "target": "new",
        }

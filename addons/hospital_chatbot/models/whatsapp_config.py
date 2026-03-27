import json
import logging

import requests as http_requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class HospitalChatbotWhatsappPhone(models.Model):
    _inherit = "hospital.chatbot.whatsapp.phone"

    session_status = fields.Selection(
        [
            ("unknown", "Desconocido"),
            ("connected", "Conectado"),
            ("disconnected", "Desconectado"),
            ("no_session", "Sin sesión"),
        ],
        string="Estado de sesión",
        default="unknown",
        readonly=True,
    )
    whatsapp_id = fields.Char(string="WhatsApp ID", readonly=True)

    def action_check_status(self):
        """Check session status on the WhatsApp service."""
        self.ensure_one()
        wa_url = self._get_whatsapp_check_url()
        if not wa_url:
            return

        try:
            resp = http_requests.post(
                f"{wa_url}/checksession",
                json={"emisor": self.phone_number},
                timeout=15,
            )
            data = resp.json()
            result = data.get("results", data)
            if isinstance(result, list):
                result = result[0] if result else {}

            status_map = {
                "CONNECTED": "connected",
                "NO_SESSION": "no_session",
                "EMPTY_SESSION": "no_session",
            }
            raw_status = result.get("status", "")
            self.write({
                "session_status": status_map.get(raw_status, "disconnected"),
                "whatsapp_id": result.get("whatsapp_id", ""),
            })
        except Exception as e:
            _logger.warning("Failed to check session status: %s", e)
            self.write({"session_status": "unknown"})

    def action_connect_session(self):
        """Start a chatbot session on the WhatsApp service."""
        self.ensure_one()
        wa_url = self._get_whatsapp_service_url()
        if not wa_url:
            return

        try:
            # First register this backend with the WhatsApp service
            self._register_backend()

            # Then start the chatbot session
            resp = http_requests.post(
                f"{wa_url}/chatbot/start",
                json={"emisor": self.phone_number},
                timeout=10,
            )
            data = resp.json()
            if data.get("success"):
                self.write({"session_status": "connected"})
                _logger.info("Session started for %s", self.phone_number)
            else:
                msg = data.get("message", "")
                if "authenticate" in msg.lower():
                    self.write({"session_status": "no_session"})
                _logger.warning("Could not start session: %s", msg)
        except Exception as e:
            _logger.warning("Failed to start session: %s", e)

    def action_disconnect_session(self):
        """Stop the chatbot session on the WhatsApp service."""
        self.ensure_one()
        wa_url = self._get_whatsapp_service_url()
        if not wa_url:
            return

        try:
            http_requests.post(
                f"{wa_url}/chatbot/stop",
                json={"emisor": self.phone_number},
                timeout=10,
            )
            self.write({"session_status": "disconnected"})
        except Exception as e:
            _logger.warning("Failed to stop session: %s", e)

    def action_get_qr(self):
        """Open QR wizard to authenticate a new WhatsApp session."""
        self.ensure_one()
        wa_url = self._get_whatsapp_service_url()
        if not wa_url:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Error",
                    "message": "URL del servicio WhatsApp no configurada. Vaya a Ajustes → Parámetros del sistema → hospital_chatbot.whatsapp_service_url",
                    "type": "danger",
                },
            }

        # Register backend first
        self._register_backend()

        # Create wizard and request QR
        wizard = self.env["hospital.chatbot.whatsapp.qr.wizard"].create({
            "phone_number": self.phone_number,
            "whatsapp_phone_id": self.id,
            "status_message": "Solicitando código QR...",
        })
        wizard.action_refresh_qr()

        return {
            "type": "ir.actions.act_window",
            "res_model": "hospital.chatbot.whatsapp.qr.wizard",
            "res_id": wizard.id,
            "views": [[False, "form"]],
            "target": "new",
        }

    def _register_backend(self):
        """Register this Odoo instance as a backend on the WhatsApp service."""
        wa_url = self._get_whatsapp_service_url()
        odoo_base_url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("web.base.url", "http://localhost:8069")
        )
        webhook_secret = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("hospital_chatbot.webhook_secret", "")
        )

        # Collect all active phones for this Odoo instance
        all_phones = self.search([("is_active", "=", True)]).mapped("phone_number")

        if not all_phones:
            all_phones = [self.phone_number]

        try:
            http_requests.post(
                f"{wa_url}/backends/register",
                json={
                    "name": "odoo-hospital",
                    "webhookUrl": f"{odoo_base_url}/chatbot/webhook/incoming/",
                    "webhookSecret": webhook_secret if webhook_secret != "change-me-in-production" else "",
                    "phones": all_phones,
                },
                timeout=10,
            )
            _logger.info("Backend registered with WhatsApp service: %s", all_phones)
        except Exception as e:
            _logger.warning("Failed to register backend: %s", e)

    def _get_whatsapp_service_url(self):
        """Get the main WhatsApp service URL (chatbot_listener, port 3500)."""
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("hospital_chatbot.whatsapp_service_url", "")
        )

    def _get_whatsapp_login_url(self):
        """Get WhatsApp login service URL (loginqr, port 3100).
        Falls back to main URL if not set (works with nginx reverse proxy)."""
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("hospital_chatbot.whatsapp_login_url", "")
        ) or self._get_whatsapp_service_url()

    def _get_whatsapp_check_url(self):
        """Get WhatsApp check session URL (check_session, port 3400).
        Falls back to main URL if not set (works with nginx reverse proxy)."""
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("hospital_chatbot.whatsapp_check_url", "")
        ) or self._get_whatsapp_service_url()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Auto-register with WhatsApp service when a new phone is added
        for rec in records:
            if rec.is_active:
                try:
                    rec._register_backend()
                except Exception:
                    pass
        return records

    def write(self, vals):
        res = super().write(vals)
        # Re-register if phone or active status changed
        if "phone_number" in vals or "is_active" in vals:
            try:
                self[:1]._register_backend()
            except Exception:
                pass
        return res

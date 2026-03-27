import base64
import logging

import requests as http_requests

from odoo import fields, models

_logger = logging.getLogger(__name__)


class WhatsappQrWizard(models.TransientModel):
    _name = "hospital.chatbot.whatsapp.qr.wizard"
    _description = "WhatsApp QR Code"

    phone_number = fields.Char(string="Teléfono", readonly=True)
    qr_image = fields.Binary(string="Código QR", readonly=True)
    status_message = fields.Char(string="Estado", readonly=True)
    whatsapp_phone_id = fields.Many2one(
        "hospital.chatbot.whatsapp.phone", string="Teléfono WhatsApp"
    )

    def action_refresh_qr(self):
        """Request a new QR code."""
        self.ensure_one()
        wa_url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("hospital_chatbot.whatsapp_login_url", "")
        ) or (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("hospital_chatbot.whatsapp_service_url", "")
        )
        if not wa_url:
            self.write({"status_message": "URL del servicio WhatsApp no configurada"})
            return self._reopen()

        try:
            resp = http_requests.post(
                f"{wa_url}/loginwhatsapp",
                json={"emisor": self.phone_number},
                timeout=35,
            )
            data = resp.json()

            if data.get("whatsappId") or "already" in data.get("message", "").lower():
                # Already connected
                if self.whatsapp_phone_id:
                    self.whatsapp_phone_id.write({
                        "session_status": "connected",
                        "whatsapp_id": data.get("whatsappId", ""),
                    })
                self.write({"status_message": f"Ya conectado: {data.get('whatsappId', '')}", "qr_image": False})
                return self._reopen()

            qr_data = data.get("result", "")
            if qr_data and "base64," in qr_data:
                # Extract base64 image data after the header
                b64_content = qr_data.split("base64,")[1]
                self.write({
                    "qr_image": b64_content,
                    "status_message": "Escanee el código QR con WhatsApp",
                })
            else:
                self.write({"status_message": "No se pudo generar el QR. Intente nuevamente."})

        except http_requests.Timeout:
            self.write({"status_message": "Timeout: no se generó el QR a tiempo"})
        except Exception as e:
            _logger.warning("QR error: %s", e)
            self.write({"status_message": f"Error: {e}"})

        return self._reopen()

    def action_check_connected(self):
        """Check if the session is now connected after scanning QR."""
        self.ensure_one()
        if self.whatsapp_phone_id:
            self.whatsapp_phone_id.action_check_status()
            status = self.whatsapp_phone_id.session_status
            if status == "connected":
                self.write({"status_message": f"Conectado: {self.whatsapp_phone_id.whatsapp_id}", "qr_image": False})
                # Also start chatbot listener
                self.whatsapp_phone_id.action_connect_session()
            else:
                self.write({"status_message": "Aún no conectado. Escanee el QR e intente nuevamente."})
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "views": [[False, "form"]],
            "target": "new",
        }

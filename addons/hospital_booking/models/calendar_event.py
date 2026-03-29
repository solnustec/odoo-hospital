from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


APPOINTMENT_STATUSES = [
    ("draft", "Borrador"),
    ("confirmed", "Confirmada"),
    ("in_progress", "En progreso"),
    ("done", "Completada"),
    ("cancelled", "Cancelada"),
    ("no_show", "Ausente"),
]

APPOINTMENT_ORIGINS = [
    ("admin", "Admin"),
    ("chatbot", "Chatbot"),
    ("web", "Web"),
    ("phone", "Teléfono"),
    ("walkin", "Presencial"),
]

STATUS_COLORS = {
    "draft": 0,
    "confirmed": 4,
    "in_progress": 2,
    "done": 10,
    "cancelled": 1,
    "no_show": 9,
}


class CalendarEvent(models.Model):
    _inherit = "calendar.event"

    is_appointment = fields.Boolean(string="Es cita médica", default=False)
    appointment_status = fields.Selection(
        APPOINTMENT_STATUSES,
        string="Estado de cita",
        default="draft",
        tracking=True,
    )
    appointment_origin = fields.Selection(
        APPOINTMENT_ORIGINS,
        string="Origen",
        default="admin",
    )
    doctor_id = fields.Many2one(
        "hr.employee",
        string="Médico",
        domain=[("is_doctor", "=", True)],
        tracking=True,
    )
    patient_id = fields.Many2one(
        "res.partner",
        string="Paciente",
        tracking=True,
    )
    patient_phone = fields.Char(
        string="Teléfono paciente",
        help="Número de teléfono para búsqueda del chatbot",
    )
    service_id = fields.Many2one(
        "product.product",
        string="Servicio médico",
    )
    appointment_notes = fields.Text(string="Notas internas")
    cancellation_reason = fields.Char(string="Motivo de cancelación")
    color = fields.Integer(string="Color", compute="_compute_color", store=False)

    @api.depends("appointment_status")
    def _compute_color(self):
        for event in self:
            event.color = STATUS_COLORS.get(event.appointment_status, 0)

    # ------------------------------------------------------------------
    # Lifecycle actions
    # ------------------------------------------------------------------

    def action_confirm(self):
        for rec in self.filtered(lambda r: r.appointment_status == "draft"):
            rec.appointment_status = "confirmed"

    def action_start(self):
        for rec in self.filtered(lambda r: r.appointment_status == "confirmed"):
            rec.appointment_status = "in_progress"

    def action_done(self):
        for rec in self.filtered(
            lambda r: r.appointment_status in ("confirmed", "in_progress")
        ):
            rec.appointment_status = "done"

    def action_cancel(self):
        done = self.filtered(lambda r: r.appointment_status == "done")
        if done:
            raise UserError("No se puede cancelar una cita completada.")
        for rec in self.filtered(
            lambda r: r.appointment_status not in ("done", "cancelled")
        ):
            rec.appointment_status = "cancelled"

    def action_no_show(self):
        for rec in self.filtered(
            lambda r: r.appointment_status in ("draft", "confirmed")
        ):
            rec.appointment_status = "no_show"

    def action_reset_draft(self):
        for rec in self.filtered(
            lambda r: r.appointment_status in ("cancelled", "no_show")
        ):
            rec.appointment_status = "draft"

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("doctor_id") and not vals.get("is_appointment"):
                vals["is_appointment"] = True

            # Auto-add doctor and patient as attendees
            partner_ids = list(vals.get("partner_ids", []))
            if vals.get("doctor_id"):
                doctor = self.env["hr.employee"].browse(vals["doctor_id"])
                if doctor.user_id and doctor.user_id.partner_id:
                    partner_ids.append((4, doctor.user_id.partner_id.id))
                    if not vals.get("user_id"):
                        vals["user_id"] = doctor.user_id.id
            if vals.get("patient_id"):
                partner_ids.append((4, vals["patient_id"]))
                # Denormalize phone
                if not vals.get("patient_phone"):
                    patient = self.env["res.partner"].browse(vals["patient_id"])
                    vals["patient_phone"] = patient.phone or patient.mobile or ""
            if partner_ids:
                vals["partner_ids"] = partner_ids

            # Auto-confirm if configured
            if vals.get("is_appointment") and vals.get("appointment_status", "draft") == "draft":
                config = self.env["hospital.booking.config"].get_config()
                if config.auto_confirm:
                    vals["appointment_status"] = "confirmed"

        return super().create(vals_list)

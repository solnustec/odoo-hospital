from odoo import api, fields, models
from odoo.exceptions import UserError


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
        domain=lambda self: [
            ("categ_id", "=", self.env.ref("hospital_booking.product_category_medical_service", raise_if_not_found=False).id or 0),
        ],
    )
    appointment_notes = fields.Text(string="Notas internas")
    cancellation_reason = fields.Char(string="Motivo de cancelación")
    invoice_id = fields.Many2one(
        "account.move",
        string="Factura",
        readonly=True,
        copy=False,
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amount_total",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="service_id.currency_id",
    )
    color = fields.Integer(string="Color", compute="_compute_color", store=False)

    @api.depends("service_id", "service_id.list_price")
    def _compute_amount_total(self):
        for event in self:
            event.amount_total = event.service_id.list_price if event.service_id else 0.0

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
    # Invoicing
    # ------------------------------------------------------------------

    def action_create_invoice(self):
        """Create an invoice for a completed appointment."""
        self.ensure_one()
        if self.appointment_status != "done":
            raise UserError("Solo se puede facturar una cita completada.")
        if self.invoice_id:
            raise UserError("Esta cita ya tiene una factura asociada.")
        if not self.patient_id:
            raise UserError("La cita debe tener un paciente asignado para facturar.")
        if not self.service_id:
            raise UserError("La cita debe tener un servicio asignado para facturar.")

        journal = self.env["account.journal"].search([
            ("type", "=", "sale"),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not journal:
            raise UserError("No se encontró un diario de ventas configurado.")

        product = self.service_id
        accounts = product.product_tmpl_id.get_product_accounts()
        account_id = accounts.get("income") or journal.default_account_id

        invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.patient_id.id,
            "journal_id": journal.id,
            "invoice_date": fields.Date.context_today(self),
            "invoice_line_ids": [(0, 0, {
                "product_id": product.id,
                "name": product.name,
                "quantity": 1,
                "price_unit": product.list_price,
                "account_id": account_id.id if account_id else False,
                "tax_ids": [(6, 0, product.taxes_id.ids)],
            })],
        })
        self.invoice_id = invoice.id

        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": invoice.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.invoice_id.id,
            "view_mode": "form",
            "target": "current",
        }

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

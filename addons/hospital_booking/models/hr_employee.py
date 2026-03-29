from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    is_doctor = fields.Boolean(string="Es médico", default=False)
    accepting_appointments = fields.Boolean(
        string="Acepta citas", default=True,
        help="Indica si el médico está aceptando citas actualmente",
    )
    slot_duration = fields.Integer(
        string="Duración de turno (min)",
        help="Duración personalizada del turno. Deje vacío para usar el valor por defecto.",
    )
    buffer_time = fields.Integer(
        string="Buffer entre citas (min)",
        help="Tiempo de preparación personalizado. Deje vacío para usar el valor por defecto.",
    )
    max_daily_appointments = fields.Integer(
        string="Máx. citas diarias",
        help="Límite de citas por día. Deje vacío para sin límite.",
    )
    booking_service_ids = fields.Many2many(
        "product.product",
        "hr_employee_booking_service_rel",
        "employee_id",
        "product_id",
        string="Servicios médicos",
        help="Servicios que este médico ofrece",
    )
    appointment_count = fields.Integer(
        string="Citas próximas",
        compute="_compute_appointment_count",
    )

    def _compute_appointment_count(self):
        for emp in self:
            emp.appointment_count = self.env["calendar.event"].search_count([
                ("doctor_id", "=", emp.id),
                ("is_appointment", "=", True),
                ("appointment_status", "in", ["draft", "confirmed"]),
                ("start", ">=", fields.Datetime.now()),
            ])

    def action_view_appointments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Citas de {self.name}",
            "res_model": "calendar.event",
            "view_mode": "tree,calendar,form",
            "domain": [
                ("doctor_id", "=", self.id),
                ("is_appointment", "=", True),
            ],
            "context": {"default_doctor_id": self.id, "default_is_appointment": True},
        }

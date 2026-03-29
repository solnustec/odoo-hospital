from odoo import api, fields, models


class HospitalBookingConfig(models.Model):
    _name = "hospital.booking.config"
    _description = "Booking Configuration"
    _rec_name = "company_id"

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        ondelete="cascade",
    )
    default_slot_duration = fields.Integer(
        string="Duración de turno (min)", default=30,
        help="Duración predeterminada de cada turno en minutos",
    )
    buffer_between_appointments = fields.Integer(
        string="Buffer entre citas (min)", default=15,
        help="Tiempo de preparación entre citas consecutivas",
    )
    min_advance_booking_hours = fields.Integer(
        string="Anticipación mínima (horas)", default=2,
        help="Horas mínimas de anticipación para agendar",
    )
    max_advance_booking_days = fields.Integer(
        string="Anticipación máxima (días)", default=60,
        help="Días máximos de anticipación para agendar",
    )
    auto_confirm = fields.Boolean(
        string="Confirmar automáticamente", default=True,
        help="Confirmar citas automáticamente al crearlas",
    )
    max_appointments_per_patient_day = fields.Integer(
        string="Máx. citas por paciente por día", default=3,
    )
    max_pending_per_patient = fields.Integer(
        string="Máx. citas pendientes por paciente", default=5,
    )
    max_no_shows_before_block = fields.Integer(
        string="Máx. ausencias antes de bloquear", default=3,
        help="Número de ausencias (no_show) antes de bloquear al paciente",
    )
    free_cancellation_hours = fields.Integer(
        string="Cancelación gratuita (horas)", default=24,
        help="Horas antes de la cita en las que se puede cancelar sin penalización",
    )

    _sql_constraints = [
        (
            "company_uniq",
            "unique(company_id)",
            "Solo puede existir una configuración por compañía.",
        ),
    ]

    @api.model
    def get_config(self, company_id=None):
        """Get or create booking config for the given company."""
        if not company_id:
            company_id = self.env.company.id if self.env.company else None
        if not company_id:
            # Fallback: get the main company
            company_id = self.env["res.company"].sudo().search([], limit=1).id
        config = self.sudo().search([("company_id", "=", company_id)], limit=1)
        if not config:
            # Use a savepoint to handle the unique constraint race condition
            # without aborting the outer transaction
            cr = self.env.cr
            cr.execute("SAVEPOINT get_config_sp")
            try:
                config = self.sudo().create({"company_id": company_id})
                cr.execute("RELEASE SAVEPOINT get_config_sp")
            except Exception:
                cr.execute("ROLLBACK TO SAVEPOINT get_config_sp")
                config = self.sudo().search([("company_id", "=", company_id)], limit=1)
        return config

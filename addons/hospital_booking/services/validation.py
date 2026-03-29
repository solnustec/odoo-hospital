"""Appointment validation service — enforces booking policies."""

from __future__ import annotations

from datetime import timedelta

from odoo import fields


class AppointmentValidationService:
    """Validates booking rules: daily limits, pending limits, no-show blocking."""

    def __init__(self, env, company_id=None):
        self.env = env
        self.config = self.env["hospital.booking.config"].get_config(company_id)

    def can_patient_book(self, patient, date) -> tuple[bool, str]:
        """Check if patient can book on the given date.

        Returns:
            (can_book: bool, reason: str)
        """
        if not patient:
            return True, ""

        Event = self.env["calendar.event"].sudo()

        # Check max appointments per day
        day_start = f"{date} 00:00:00"
        day_end = f"{fields.Date.add(date, days=1)} 00:00:00"
        day_count = Event.search_count([
            ("patient_id", "=", patient.id),
            ("is_appointment", "=", True),
            ("start", ">=", day_start),
            ("start", "<", day_end),
            ("appointment_status", "not in", ["cancelled"]),
        ])
        max_per_day = self.config.max_appointments_per_patient_day
        if max_per_day and day_count >= max_per_day:
            return False, f"Máximo {max_per_day} citas por día alcanzado"

        # Check max pending appointments
        pending_count = Event.search_count([
            ("patient_id", "=", patient.id),
            ("is_appointment", "=", True),
            ("appointment_status", "in", ["draft", "confirmed"]),
            ("start", ">=", fields.Datetime.now()),
        ])
        max_pending = self.config.max_pending_per_patient
        if max_pending and pending_count >= max_pending:
            return False, f"Máximo {max_pending} citas pendientes alcanzado"

        # Check no-show blocking
        max_no_shows = self.config.max_no_shows_before_block
        if max_no_shows:
            no_show_count = Event.search_count([
                ("patient_id", "=", patient.id),
                ("is_appointment", "=", True),
                ("appointment_status", "=", "no_show"),
            ])
            if no_show_count >= max_no_shows:
                return False, f"Paciente bloqueado por {no_show_count} ausencias"

        return True, ""

    def can_cancel_free(self, appointment) -> tuple[bool, float]:
        """Check if appointment can be cancelled without penalty.

        Returns:
            (is_free: bool, penalty_percent: float)
        """
        free_hours = self.config.free_cancellation_hours or 0
        cutoff = appointment.start - timedelta(hours=free_hours)
        now = fields.Datetime.now()

        if now <= cutoff:
            return True, 0.0
        return False, 100.0

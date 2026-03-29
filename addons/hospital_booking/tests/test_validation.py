"""Tests for AppointmentValidationService."""

from datetime import datetime, time, timedelta

import pytz
from odoo.tests import tagged

from .common import BookingTestCommon


@tagged("post_install", "-at_install")
class TestValidationService(BookingTestCommon):

    def _get_service(self):
        from odoo.addons.hospital_booking.services.validation import AppointmentValidationService
        return AppointmentValidationService(self.env)

    def test_patient_can_book_initially(self):
        """Patient with no history can book."""
        svc = self._get_service()
        monday = self._next_monday()
        can_book, reason = svc.can_patient_book(self.patient, monday)
        self.assertTrue(can_book)
        self.assertEqual(reason, "")

    def test_max_per_day_limit(self):
        """Patient blocked after reaching daily max."""
        self.config.max_appointments_per_patient_day = 1
        monday = self._next_monday()

        self._create_appointment(start=self._make_start(monday, 9, 0))

        svc = self._get_service()
        can_book, reason = svc.can_patient_book(self.patient, monday)
        self.assertFalse(can_book)
        self.assertIn("Máximo", reason)

        self.config.max_appointments_per_patient_day = 3  # reset

    def test_max_pending_limit(self):
        """Patient blocked after reaching pending max."""
        self.config.max_pending_per_patient = 1
        monday = self._next_monday()

        self._create_appointment(start=self._make_start(monday, 9, 0))

        svc = self._get_service()
        can_book, reason = svc.can_patient_book(self.patient, monday + timedelta(days=1))
        self.assertFalse(can_book)
        self.assertIn("pendientes", reason)

        self.config.max_pending_per_patient = 5  # reset

    def test_no_show_blocking(self):
        """Patient blocked after too many no-shows."""
        self.config.max_no_shows_before_block = 2
        self.config.auto_confirm = False

        # Create 2 no-show appointments (in the past so they don't count as pending)
        past = datetime.now(pytz.utc).replace(tzinfo=None) - timedelta(days=10)
        for i in range(2):
            appt = self._create_appointment(
                start=past + timedelta(hours=i),
                stop=past + timedelta(hours=i, minutes=30),
                appointment_status="draft",
            )
            appt.appointment_status = "no_show"

        svc = self._get_service()
        monday = self._next_monday()
        can_book, reason = svc.can_patient_book(self.patient, monday)
        self.assertFalse(can_book)
        self.assertIn("ausencias", reason)

        self.config.max_no_shows_before_block = 3  # reset
        self.config.auto_confirm = True  # reset

    def test_cancelled_not_counted_in_daily(self):
        """Cancelled appointments don't count toward daily limit."""
        self.config.max_appointments_per_patient_day = 1
        monday = self._next_monday()

        appt = self._create_appointment(start=self._make_start(monday, 9, 0))
        appt.appointment_status = "cancelled"

        svc = self._get_service()
        can_book, reason = svc.can_patient_book(self.patient, monday)
        self.assertTrue(can_book)

        self.config.max_appointments_per_patient_day = 3  # reset

    def test_can_cancel_free_within_window(self):
        """Cancelling within free window is free."""
        self.config.free_cancellation_hours = 24
        monday = self._next_monday()
        start = self._make_start(monday, 9, 0)
        appt = self._create_appointment(start=start)

        svc = self._get_service()
        is_free, penalty = svc.can_cancel_free(appt)
        # If appointment is more than 24h from now, cancellation is free
        if (start.replace(tzinfo=pytz.utc) - datetime.now(pytz.utc)).total_seconds() > 24 * 3600:
            self.assertTrue(is_free)
            self.assertEqual(penalty, 0.0)

    def test_null_patient_can_book(self):
        """None patient can always book (new patient)."""
        svc = self._get_service()
        monday = self._next_monday()
        can_book, reason = svc.can_patient_book(None, monday)
        self.assertTrue(can_book)

    def _make_start(self, date, hour, minute):
        tz = pytz.timezone("America/Guayaquil")
        return tz.localize(
            datetime.combine(date, time(hour, minute))
        ).astimezone(pytz.utc).replace(tzinfo=None)

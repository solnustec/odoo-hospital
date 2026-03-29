"""Tests for hr.employee booking extension."""

from odoo.tests import tagged

from .common import BookingTestCommon


@tagged("post_install", "-at_install")
class TestHrEmployeeBooking(BookingTestCommon):

    def test_is_doctor_flag(self):
        """Doctor flag correctly set."""
        self.assertTrue(self.doctor.is_doctor)
        self.assertTrue(self.doctor.accepting_appointments)
        self.assertTrue(self.doctor_inactive.is_doctor)
        self.assertFalse(self.doctor_inactive.accepting_appointments)

    def test_appointment_count_no_appointments(self):
        """Appointment count is 0 when no appointments exist."""
        self.doctor._compute_appointment_count()
        self.assertEqual(self.doctor.appointment_count, 0)

    def test_appointment_count_with_appointments(self):
        """Appointment count reflects future confirmed/draft appointments."""
        appt = self._create_appointment()
        self.doctor._compute_appointment_count()
        self.assertGreaterEqual(self.doctor.appointment_count, 1)

    def test_appointment_count_excludes_cancelled(self):
        """Cancelled appointments not counted."""
        appt = self._create_appointment()
        appt.action_cancel()
        self.doctor._compute_appointment_count()
        self.assertEqual(self.doctor.appointment_count, 0)

    def test_action_view_appointments(self):
        """action_view_appointments returns correct action dict."""
        result = self.doctor.action_view_appointments()
        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "calendar.event")
        self.assertIn(("doctor_id", "=", self.doctor.id), result["domain"])

    def test_booking_services(self):
        """Services can be assigned to a doctor."""
        self.doctor.booking_service_ids = [(4, self.service.id)]
        self.assertIn(self.service, self.doctor.booking_service_ids)

    def test_slot_duration_override(self):
        """Doctor can have custom slot duration."""
        self.assertEqual(self.doctor.slot_duration, 30)
        self.doctor.slot_duration = 45
        self.assertEqual(self.doctor.slot_duration, 45)

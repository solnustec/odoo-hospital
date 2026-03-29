"""Tests for calendar.event appointment extension and lifecycle."""

from datetime import datetime, time, timedelta

import pytz
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import BookingTestCommon


@tagged("post_install", "-at_install")
class TestAppointmentLifecycle(BookingTestCommon):

    def test_create_sets_is_appointment(self):
        """Setting doctor_id auto-sets is_appointment=True."""
        appt = self._create_appointment()
        self.assertTrue(appt.is_appointment)

    def test_auto_confirm_on_create(self):
        """With auto_confirm=True, new appointments are confirmed."""
        self.config.auto_confirm = True
        appt = self._create_appointment()
        self.assertEqual(appt.appointment_status, "confirmed")

    def test_no_auto_confirm(self):
        """With auto_confirm=False, new appointments stay draft."""
        self.config.auto_confirm = False
        appt = self._create_appointment(appointment_status="draft")
        self.assertEqual(appt.appointment_status, "draft")

    def test_lifecycle_draft_to_confirmed(self):
        """Draft → Confirmed transition."""
        self.config.auto_confirm = False
        appt = self._create_appointment(appointment_status="draft")
        appt.action_confirm()
        self.assertEqual(appt.appointment_status, "confirmed")

    def test_lifecycle_confirmed_to_in_progress(self):
        """Confirmed → In Progress transition."""
        appt = self._create_appointment()
        appt.appointment_status = "confirmed"
        appt.action_start()
        self.assertEqual(appt.appointment_status, "in_progress")

    def test_lifecycle_in_progress_to_done(self):
        """In Progress → Done transition."""
        appt = self._create_appointment()
        appt.appointment_status = "in_progress"
        appt.action_done()
        self.assertEqual(appt.appointment_status, "done")

    def test_lifecycle_confirmed_to_done_direct(self):
        """Confirmed → Done (skip in_progress) is allowed."""
        appt = self._create_appointment()
        appt.appointment_status = "confirmed"
        appt.action_done()
        self.assertEqual(appt.appointment_status, "done")

    def test_cancel_from_draft(self):
        """Can cancel from draft."""
        self.config.auto_confirm = False
        appt = self._create_appointment(appointment_status="draft")
        appt.action_cancel()
        self.assertEqual(appt.appointment_status, "cancelled")

    def test_cancel_from_confirmed(self):
        """Can cancel from confirmed."""
        appt = self._create_appointment()
        appt.appointment_status = "confirmed"
        appt.action_cancel()
        self.assertEqual(appt.appointment_status, "cancelled")

    def test_cannot_cancel_done(self):
        """Cannot cancel a done appointment — raises UserError."""
        appt = self._create_appointment()
        appt.appointment_status = "done"
        with self.assertRaises(UserError):
            appt.action_cancel()
        self.assertEqual(appt.appointment_status, "done")

    def test_no_show(self):
        """Can mark confirmed as no_show."""
        appt = self._create_appointment()
        appt.appointment_status = "confirmed"
        appt.action_no_show()
        self.assertEqual(appt.appointment_status, "no_show")

    def test_reset_draft_from_cancelled(self):
        """Can reopen from cancelled."""
        appt = self._create_appointment()
        appt.appointment_status = "cancelled"
        appt.action_reset_draft()
        self.assertEqual(appt.appointment_status, "draft")

    def test_reset_draft_from_no_show(self):
        """Can reopen from no_show."""
        appt = self._create_appointment()
        appt.appointment_status = "no_show"
        appt.action_reset_draft()
        self.assertEqual(appt.appointment_status, "draft")

    def test_patient_phone_denormalized(self):
        """Patient phone is auto-filled from partner on create."""
        appt = self._create_appointment()
        self.assertEqual(appt.patient_phone, self.patient.phone)

    def test_appointment_origin_default(self):
        """Default origin is admin."""
        appt = self._create_appointment()
        self.assertEqual(appt.appointment_origin, "admin")

    def test_chatbot_origin(self):
        """Can set origin to chatbot."""
        appt = self._create_appointment(appointment_origin="chatbot")
        self.assertEqual(appt.appointment_origin, "chatbot")

    def test_color_computation(self):
        """Color computed from appointment status."""
        appt = self._create_appointment()
        appt.appointment_status = "confirmed"
        appt._compute_color()
        self.assertEqual(appt.color, 4)  # confirmed = blue

        appt.appointment_status = "done"
        appt._compute_color()
        self.assertEqual(appt.color, 10)  # done = green

        appt.appointment_status = "cancelled"
        appt._compute_color()
        self.assertEqual(appt.color, 1)  # cancelled = red

    def test_doctor_added_as_attendee(self):
        """Doctor's partner is added as attendee if they have a user."""
        user = self.env["res.users"].create({
            "name": "Dr. User Test",
            "login": "dr_user_test@test.com",
        })
        self.doctor.user_id = user
        appt = self._create_appointment()
        partner_ids = appt.partner_ids.ids
        self.assertIn(user.partner_id.id, partner_ids)

    def test_patient_added_as_attendee(self):
        """Patient is added as attendee on create."""
        appt = self._create_appointment()
        partner_ids = appt.partner_ids.ids
        self.assertIn(self.patient.id, partner_ids)

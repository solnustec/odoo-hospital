"""Integration tests: chatbot + booking + calendar working together."""

import json
from datetime import datetime, time, timedelta

import pytz
from odoo.tests import tagged, TransactionCase


@tagged("post_install", "-at_install")
class TestChatbotBookingIntegration(TransactionCase):
    """Tests the full integration between chatbot, booking, and calendar modules."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # --- Booking setup ---
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "Test Calendar Integration",
            "tz": "America/Guayaquil",
            "attendance_ids": [
                (0, 0, {"name": "Mon AM", "dayofweek": "0", "hour_from": 8.0, "hour_to": 12.0, "day_period": "morning"}),
                (0, 0, {"name": "Mon PM", "dayofweek": "0", "hour_from": 13.0, "hour_to": 17.0, "day_period": "afternoon"}),
                (0, 0, {"name": "Tue AM", "dayofweek": "1", "hour_from": 8.0, "hour_to": 12.0, "day_period": "morning"}),
                (0, 0, {"name": "Tue PM", "dayofweek": "1", "hour_from": 13.0, "hour_to": 17.0, "day_period": "afternoon"}),
                (0, 0, {"name": "Wed AM", "dayofweek": "2", "hour_from": 8.0, "hour_to": 12.0, "day_period": "morning"}),
                (0, 0, {"name": "Wed PM", "dayofweek": "2", "hour_from": 13.0, "hour_to": 17.0, "day_period": "afternoon"}),
                (0, 0, {"name": "Thu AM", "dayofweek": "3", "hour_from": 8.0, "hour_to": 12.0, "day_period": "morning"}),
                (0, 0, {"name": "Thu PM", "dayofweek": "3", "hour_from": 13.0, "hour_to": 17.0, "day_period": "afternoon"}),
                (0, 0, {"name": "Fri AM", "dayofweek": "4", "hour_from": 8.0, "hour_to": 12.0, "day_period": "morning"}),
                (0, 0, {"name": "Fri PM", "dayofweek": "4", "hour_from": 13.0, "hour_to": 17.0, "day_period": "afternoon"}),
            ],
        })

        cls.doctor = cls.env["hr.employee"].create({
            "name": "Dr. Integration Test",
            "is_doctor": True,
            "accepting_appointments": True,
            "resource_calendar_id": cls.calendar.id,
            "slot_duration": 30,
        })

        cls.patient = cls.env["res.partner"].create({
            "name": "Patient Integration Test",
            "phone": "593111222333",
        })

        cls.service = cls.env["product.product"].create({
            "name": "Consulta Integration Test",
            "type": "service",
            "list_price": 50.0,
        })

        # --- Chatbot setup ---
        cls.chatbot = cls.env["hospital.chatbot"].create({
            "name": "Integration Bot",
            "is_active": True,
            "welcome_message": "Bienvenido al hospital. ¿Qué necesita?",
            "fallback_message": "No entendí.",
            "session_timeout_minutes": 30,
        })

        cls.flow = cls.env["hospital.chatbot.flow"].create({
            "chatbot_id": cls.chatbot.id,
            "name": "Integration Flow",
            "is_main": True,
            "trigger_keywords": ["hola", "menu"],
        })

        cls.menu_node = cls.env["hospital.chatbot.node"].create({
            "flow_id": cls.flow.id,
            "node_type": "MENU",
            "name": "Main Menu",
            "is_start": True,
            "config": {"header": "Opciones:"},
        })

        cls.msg_node = cls.env["hospital.chatbot.node"].create({
            "flow_id": cls.flow.id,
            "node_type": "MESSAGE",
            "name": "Citas Info",
            "config": {"message": "Para agendar una cita, contacte recepción."},
        })

        cls.env["hospital.chatbot.menu.option"].create({
            "node_id": cls.menu_node.id,
            "option_number": 1,
            "option_text": "Agendar cita",
            "next_node_id": cls.msg_node.id,
        })

        cls.wa_phone = cls.env["hospital.chatbot.whatsapp.phone"].create({
            "phone_number": "559900001111",
            "chatbot_id": cls.chatbot.id,
            "is_active": True,
        })

    def _next_weekday(self, start_date, weekday):
        days_ahead = weekday - start_date.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return start_date + timedelta(days=days_ahead)

    # ------------------------------------------------------------------
    # Integration: Booking models work with calendar
    # ------------------------------------------------------------------

    def test_appointment_appears_in_calendar(self):
        """Appointment created via booking appears in calendar.event."""
        monday = self._next_weekday(datetime.now().date(), 0)
        tz = pytz.timezone("America/Guayaquil")
        start = tz.localize(datetime.combine(monday, time(10, 0))).astimezone(pytz.utc).replace(tzinfo=None)
        stop = start + timedelta(minutes=30)

        appt = self.env["calendar.event"].create({
            "name": "Test appointment",
            "start": start,
            "stop": stop,
            "doctor_id": self.doctor.id,
            "patient_id": self.patient.id,
            "service_id": self.service.id,
            "is_appointment": True,
        })

        self.assertTrue(appt.is_appointment)
        self.assertEqual(appt.doctor_id, self.doctor)
        self.assertEqual(appt.patient_id, self.patient)
        self.assertEqual(appt.patient_phone, "593111222333")

    def test_appointment_lifecycle_full_cycle(self):
        """Full lifecycle: draft → confirmed → in_progress → done."""
        config = self.env["hospital.booking.config"].get_config()
        config.auto_confirm = False

        monday = self._next_weekday(datetime.now().date(), 0)
        tz = pytz.timezone("America/Guayaquil")
        start = tz.localize(datetime.combine(monday, time(10, 0))).astimezone(pytz.utc).replace(tzinfo=None)

        appt = self.env["calendar.event"].create({
            "name": "Lifecycle test",
            "start": start,
            "stop": start + timedelta(minutes=30),
            "doctor_id": self.doctor.id,
            "patient_id": self.patient.id,
            "is_appointment": True,
            "appointment_status": "draft",
        })

        self.assertEqual(appt.appointment_status, "draft")
        appt.action_confirm()
        self.assertEqual(appt.appointment_status, "confirmed")
        appt.action_start()
        self.assertEqual(appt.appointment_status, "in_progress")
        appt.action_done()
        self.assertEqual(appt.appointment_status, "done")

    def test_availability_decreases_after_booking(self):
        """Booking an appointment makes slot unavailable via check_slot_available."""
        from odoo.addons.hospital_booking.services.availability import AvailabilityService

        svc = AvailabilityService(self.env)
        monday = self._next_weekday(datetime.now().date(), 0)
        tz = pytz.timezone("America/Guayaquil")
        start = tz.localize(datetime.combine(monday, time(10, 0))).astimezone(pytz.utc)
        end = start + timedelta(minutes=30)

        # Slot should be available before booking
        avail, _ = svc.check_slot_available(self.doctor, start, end)
        self.assertTrue(avail)

        self.env["calendar.event"].create({
            "name": "Booked slot",
            "start": start.replace(tzinfo=None),
            "stop": end.replace(tzinfo=None),
            "doctor_id": self.doctor.id,
            "patient_id": self.patient.id,
            "is_appointment": True,
        })

        # Slot should be unavailable after booking
        avail2, reason = svc.check_slot_available(self.doctor, start, end)
        self.assertFalse(avail2)
        self.assertIn("ocupado", reason)

    def test_validation_blocks_overbooked_patient(self):
        """Validation service blocks patient who reached daily limit."""
        from odoo.addons.hospital_booking.services.validation import AppointmentValidationService

        config = self.env["hospital.booking.config"].get_config()
        config.max_appointments_per_patient_day = 1

        monday = self._next_weekday(datetime.now().date(), 0)
        tz = pytz.timezone("America/Guayaquil")
        start = tz.localize(datetime.combine(monday, time(9, 0))).astimezone(pytz.utc).replace(tzinfo=None)

        self.env["calendar.event"].create({
            "name": "First appt",
            "start": start,
            "stop": start + timedelta(minutes=30),
            "doctor_id": self.doctor.id,
            "patient_id": self.patient.id,
            "is_appointment": True,
        })

        vsvc = AppointmentValidationService(self.env)
        can_book, reason = vsvc.can_patient_book(self.patient, monday)
        self.assertFalse(can_book)

        config.max_appointments_per_patient_day = 3  # restore

    # ------------------------------------------------------------------
    # Integration: Chatbot webhook + booking data
    # ------------------------------------------------------------------

    def test_chatbot_processes_message_and_selects_booking(self):
        """Chatbot engine: message → menu → select booking option."""
        from odoo.addons.hospital_chatbot.services.engine import ChatbotEngine

        engine = ChatbotEngine(self.chatbot, self.env)

        # First message — should show welcome/menu
        responses = engine.process_message("593111222333", "hola")
        self.assertTrue(len(responses) >= 1)

        # Select option 1 (Agendar cita)
        responses2 = engine.process_message("593111222333", "1")
        texts = " ".join(r.get("content", "") for r in responses2)
        self.assertIn("cita", texts.lower())

    def test_doctor_appointment_count_updates(self):
        """Doctor stat button updates when appointment created."""
        monday = self._next_weekday(datetime.now().date(), 0)
        tz = pytz.timezone("America/Guayaquil")
        start = tz.localize(datetime.combine(monday, time(10, 0))).astimezone(pytz.utc).replace(tzinfo=None)

        self.doctor._compute_appointment_count()
        count_before = self.doctor.appointment_count

        self.env["calendar.event"].create({
            "name": "Count test",
            "start": start,
            "stop": start + timedelta(minutes=30),
            "doctor_id": self.doctor.id,
            "patient_id": self.patient.id,
            "is_appointment": True,
        })

        self.doctor._compute_appointment_count()
        self.assertEqual(self.doctor.appointment_count, count_before + 1)

    def test_cancelled_appointment_frees_slot(self):
        """Cancelling an appointment makes the slot available again."""
        from odoo.addons.hospital_booking.services.availability import AvailabilityService

        svc = AvailabilityService(self.env)
        monday = self._next_weekday(datetime.now().date(), 0)
        tz = pytz.timezone("America/Guayaquil")
        start = tz.localize(datetime.combine(monday, time(10, 0))).astimezone(pytz.utc)
        end = start + timedelta(minutes=30)

        appt = self.env["calendar.event"].create({
            "name": "Cancel test",
            "start": start.replace(tzinfo=None),
            "stop": end.replace(tzinfo=None),
            "doctor_id": self.doctor.id,
            "patient_id": self.patient.id,
            "is_appointment": True,
        })

        # Slot occupied
        avail, _ = svc.check_slot_available(self.doctor, start, end)
        self.assertFalse(avail)

        # Cancel → slot freed
        appt.action_cancel()
        avail2, _ = svc.check_slot_available(self.doctor, start, end)
        self.assertTrue(avail2)

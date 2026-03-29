"""Common test setup for hospital_booking tests."""

from datetime import datetime, time, timedelta

from odoo.tests import TransactionCase


class BookingTestCommon(TransactionCase):
    """Base class with shared test data for all booking tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Resource calendar: Mon-Fri 08:00-17:00 with lunch 12:00-13:00
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "Horario Médico Test",
            "tz": "America/Guayaquil",
            "attendance_ids": [
                (0, 0, {"name": "Lunes AM", "dayofweek": "0", "hour_from": 8.0, "hour_to": 12.0, "day_period": "morning"}),
                (0, 0, {"name": "Lunes PM", "dayofweek": "0", "hour_from": 13.0, "hour_to": 17.0, "day_period": "afternoon"}),
                (0, 0, {"name": "Martes AM", "dayofweek": "1", "hour_from": 8.0, "hour_to": 12.0, "day_period": "morning"}),
                (0, 0, {"name": "Martes PM", "dayofweek": "1", "hour_from": 13.0, "hour_to": 17.0, "day_period": "afternoon"}),
                (0, 0, {"name": "Miércoles AM", "dayofweek": "2", "hour_from": 8.0, "hour_to": 12.0, "day_period": "morning"}),
                (0, 0, {"name": "Miércoles PM", "dayofweek": "2", "hour_from": 13.0, "hour_to": 17.0, "day_period": "afternoon"}),
                (0, 0, {"name": "Jueves AM", "dayofweek": "3", "hour_from": 8.0, "hour_to": 12.0, "day_period": "morning"}),
                (0, 0, {"name": "Jueves PM", "dayofweek": "3", "hour_from": 13.0, "hour_to": 17.0, "day_period": "afternoon"}),
                (0, 0, {"name": "Viernes AM", "dayofweek": "4", "hour_from": 8.0, "hour_to": 12.0, "day_period": "morning"}),
                (0, 0, {"name": "Viernes PM", "dayofweek": "4", "hour_from": 13.0, "hour_to": 17.0, "day_period": "afternoon"}),
            ],
        })

        # Doctor employee
        cls.doctor = cls.env["hr.employee"].create({
            "name": "Dr. García Test",
            "is_doctor": True,
            "accepting_appointments": True,
            "resource_calendar_id": cls.calendar.id,
            "slot_duration": 30,
            "buffer_time": 15,
        })

        # Second doctor (inactive)
        cls.doctor_inactive = cls.env["hr.employee"].create({
            "name": "Dr. Morales Test",
            "is_doctor": True,
            "accepting_appointments": False,
            "resource_calendar_id": cls.calendar.id,
        })

        # Patient partner
        cls.patient = cls.env["res.partner"].create({
            "name": "Paciente Test",
            "phone": "593984946000",
            "email": "paciente@test.com",
        })

        # Second patient
        cls.patient2 = cls.env["res.partner"].create({
            "name": "Paciente Test 2",
            "phone": "593984946001",
        })

        # Medical service product
        cls.service = cls.env["product.product"].create({
            "name": "Consulta General",
            "type": "service",
            "list_price": 50.0,
        })

        # Booking config
        cls.config = cls.env["hospital.booking.config"].get_config()

    @classmethod
    def _next_weekday(cls, start_date, weekday):
        """Get next occurrence of a weekday (0=Mon) from start_date."""
        days_ahead = weekday - start_date.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return start_date + timedelta(days=days_ahead)

    @classmethod
    def _next_monday(cls):
        """Get next Monday from today (or next week if today is Monday)."""
        from datetime import date
        return cls._next_weekday(date.today(), 0)

    def _create_appointment(self, doctor=None, patient=None, start=None, stop=None, **kwargs):
        """Helper to create test appointments."""
        doctor = doctor or self.doctor
        patient = patient or self.patient
        if not start:
            import pytz
            tz = pytz.timezone("America/Guayaquil")
            monday = self._next_monday()
            start = tz.localize(datetime.combine(monday, time(9, 0))).astimezone(pytz.utc).replace(tzinfo=None)
        if not stop:
            stop = start + timedelta(minutes=30)

        vals = {
            "name": f"Cita: {patient.name} con {doctor.name}",
            "start": start,
            "stop": stop,
            "doctor_id": doctor.id,
            "patient_id": patient.id,
            "service_id": self.service.id,
            "is_appointment": True,
            **kwargs,
        }
        return self.env["calendar.event"].create(vals)

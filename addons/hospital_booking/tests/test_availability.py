"""Tests for AvailabilityService."""

from datetime import datetime, time, timedelta

import pytz
from odoo.tests import tagged

from .common import BookingTestCommon


@tagged("post_install", "-at_install")
class TestAvailabilityService(BookingTestCommon):

    def _get_service(self):
        from odoo.addons.hospital_booking.services.availability import AvailabilityService
        return AvailabilityService(self.env)

    def test_available_slots_on_weekday(self):
        """Doctor has available slots on a working day."""
        svc = self._get_service()
        monday = self._next_monday()
        slots = svc.get_available_slots(monday, self.doctor)
        self.assertTrue(len(slots) > 0, "Should have slots on a working day")

    def test_no_slots_on_weekend(self):
        """No slots on Saturday (not in schedule)."""
        svc = self._get_service()
        monday = self._next_monday()
        saturday = monday + timedelta(days=5)
        slots = svc.get_available_slots(saturday, self.doctor)
        self.assertEqual(len(slots), 0, "Should have no slots on Saturday")

    def test_no_slots_for_inactive_doctor(self):
        """Inactive doctor returns no slots."""
        svc = self._get_service()
        monday = self._next_monday()
        slots = svc.get_available_slots(monday, self.doctor_inactive)
        self.assertEqual(len(slots), 0)

    def test_slots_respect_duration(self):
        """Slots have correct duration."""
        svc = self._get_service()
        monday = self._next_monday()
        slots = svc.get_available_slots(monday, self.doctor, duration_minutes=30)
        if slots:
            slot = slots[0]
            duration = (slot["end"] - slot["start"]).total_seconds() / 60
            self.assertEqual(duration, 30)

    def test_slots_exclude_booked(self):
        """Booked slots are excluded — test via check_slot_available."""
        svc = self._get_service()
        monday = self._next_monday()
        tz = pytz.timezone("America/Guayaquil")

        # Create an appointment at 10:00
        start = tz.localize(datetime.combine(monday, time(10, 0))).astimezone(pytz.utc)
        end = start + timedelta(minutes=30)

        self._create_appointment(
            start=start.replace(tzinfo=None),
            stop=end.replace(tzinfo=None),
        )

        # That slot should now be unavailable
        available, reason = svc.check_slot_available(self.doctor, start, end)
        self.assertFalse(available, "Booked slot should not be available")
        self.assertIn("ocupado", reason)

    def test_slots_respect_lunch_break(self):
        """No slots generated during lunch break (12:00-13:00)."""
        svc = self._get_service()
        monday = self._next_monday()
        slots = svc.get_available_slots(monday, self.doctor)

        tz = pytz.timezone("America/Guayaquil")
        for slot in slots:
            slot_start_local = slot["start"].astimezone(tz)
            slot_end_local = slot["end"].astimezone(tz)
            # No slot should overlap with 12:00-13:00
            lunch_start = tz.localize(datetime.combine(monday, time(12, 0)))
            lunch_end = tz.localize(datetime.combine(monday, time(13, 0)))
            overlaps_lunch = slot_start_local < lunch_end and slot_end_local > lunch_start
            self.assertFalse(overlaps_lunch, f"Slot {slot_start_local}-{slot_end_local} overlaps lunch")

    def test_check_slot_available_free(self):
        """check_slot_available returns True for a free slot."""
        svc = self._get_service()
        monday = self._next_monday()
        tz = pytz.timezone("America/Guayaquil")
        start = tz.localize(datetime.combine(monday, time(9, 0))).astimezone(pytz.utc)
        end = start + timedelta(minutes=30)
        available, reason = svc.check_slot_available(self.doctor, start, end)
        self.assertTrue(available)
        self.assertEqual(reason, "")

    def test_check_slot_available_occupied(self):
        """check_slot_available returns False when slot is booked."""
        svc = self._get_service()
        monday = self._next_monday()
        tz = pytz.timezone("America/Guayaquil")
        start = tz.localize(datetime.combine(monday, time(9, 0))).astimezone(pytz.utc)
        end = start + timedelta(minutes=30)

        self._create_appointment(
            start=start.replace(tzinfo=None),
            stop=end.replace(tzinfo=None),
        )

        available, reason = svc.check_slot_available(self.doctor, start, end)
        self.assertFalse(available)
        self.assertIn("ocupado", reason)

    def test_check_slot_non_doctor(self):
        """check_slot_available rejects non-doctor employees."""
        non_doctor = self.env["hr.employee"].create({
            "name": "Not a Doctor",
            "is_doctor": False,
        })
        svc = self._get_service()
        start = datetime.now(pytz.utc)
        end = start + timedelta(minutes=30)
        available, reason = svc.check_slot_available(non_doctor, start, end)
        self.assertFalse(available)

    def test_daily_cap(self):
        """Doctor with max_daily_appointments caps the slots."""
        self.doctor.max_daily_appointments = 2
        svc = self._get_service()
        monday = self._next_monday()
        slots = svc.get_available_slots(monday, self.doctor)
        self.assertLessEqual(len(slots), 2)
        self.doctor.max_daily_appointments = 0  # reset

    def test_leave_blocks_day(self):
        """A leave (time-off) for the doctor removes slots for that day."""
        svc = self._get_service()
        monday = self._next_monday()

        # Create a leave for the whole day — Odoo expects naive UTC datetimes
        day_start = datetime.combine(monday, time(0, 0))
        day_end = datetime.combine(monday, time(23, 59))
        self.env["resource.calendar.leaves"].create({
            "name": "Día libre test",
            "resource_id": self.doctor.resource_id.id,
            "calendar_id": self.calendar.id,
            "date_from": day_start,
            "date_to": day_end,
        })

        slots = svc.get_available_slots(monday, self.doctor)
        self.assertEqual(len(slots), 0, "Doctor on leave should have no slots")

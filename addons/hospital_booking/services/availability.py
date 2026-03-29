"""Availability service — generates time slots for doctor appointments."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

import pytz

_logger = logging.getLogger(__name__)


class AvailabilityService:
    """Computes available time slots for doctors.

    Uses Odoo's resource.calendar._work_intervals_batch() which already
    handles attendance lines (schedule) and subtracts leaves (time-off).
    """

    def __init__(self, env, company_id=None):
        self.env = env
        self.config = self.env["hospital.booking.config"].get_config(company_id)

    def get_available_slots(
        self,
        date,
        doctor,
        duration_minutes: int | None = None,
    ) -> list[dict]:
        """Return available time slots for a doctor on a given date.

        Args:
            date: date object
            doctor: hr.employee recordset (single)
            duration_minutes: slot duration override

        Returns:
            List of {"start": datetime (UTC), "end": datetime (UTC)}
        """
        if not doctor.is_doctor or not doctor.accepting_appointments:
            return []

        calendar = doctor.resource_calendar_id
        if not calendar:
            calendar = doctor.company_id.resource_calendar_id
        if not calendar:
            _logger.warning("Doctor %s has no resource calendar", doctor.name)
            return []

        tz = pytz.timezone(calendar.tz or "UTC")

        # Build day boundaries in the calendar's timezone, then convert to UTC
        day_start = tz.localize(datetime.combine(date, time.min))
        day_end = tz.localize(datetime.combine(date, time.max))

        day_start_utc = day_start.astimezone(pytz.utc)
        day_end_utc = day_end.astimezone(pytz.utc)

        # Get work intervals (already excludes leaves / time-off)
        resource = doctor.resource_id
        intervals = calendar._work_intervals_batch(
            day_start_utc, day_end_utc, resources=resource
        )[resource.id]

        # Determine slot parameters
        slot_duration = (
            duration_minutes
            or doctor.slot_duration
            or self.config.default_slot_duration
            or 30
        )
        buffer = (
            doctor.buffer_time
            if doctor.buffer_time
            else self.config.buffer_between_appointments
        )

        # Generate fixed-duration slots within each work interval
        slots = self._generate_slots(intervals, slot_duration, buffer)

        # Filter out slots occupied by existing appointments
        slots = self._filter_booked_slots(doctor, day_start_utc, day_end_utc, slots)

        # Filter by minimum advance time
        slots = self._filter_by_min_advance(slots)

        # Filter by maximum advance days
        slots = self._filter_by_max_advance(slots, date)

        # Check daily cap
        if doctor.max_daily_appointments:
            existing_count = self.env["calendar.event"].sudo().search_count([
                ("doctor_id", "=", doctor.id),
                ("is_appointment", "=", True),
                ("start", ">=", day_start_utc),
                ("start", "<", day_end_utc),
                ("appointment_status", "not in", ["cancelled"]),
            ])
            remaining = max(0, doctor.max_daily_appointments - existing_count)
            slots = slots[:remaining]

        return slots

    def check_slot_available(
        self, doctor, start: datetime, end: datetime, exclude_event_id=None
    ) -> tuple[bool, str]:
        """Check if a specific time slot is available.

        Returns:
            (is_available, reason_message)
        """
        if not doctor.is_doctor:
            return False, "No es un médico registrado"
        if not doctor.accepting_appointments:
            return False, "El médico no está aceptando citas"

        # Check for overlapping appointments (Odoo stores naive UTC)
        start_naive = start.replace(tzinfo=None) if start.tzinfo else start
        end_naive = end.replace(tzinfo=None) if end.tzinfo else end
        domain = [
            ("doctor_id", "=", doctor.id),
            ("is_appointment", "=", True),
            ("start", "<", end_naive),
            ("stop", ">", start_naive),
            ("appointment_status", "not in", ["cancelled"]),
        ]
        if exclude_event_id:
            domain.append(("id", "!=", exclude_event_id))

        conflicts = self.env["calendar.event"].sudo().search_count(domain)
        if conflicts:
            return False, "El horario ya está ocupado"

        return True, ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_slots(self, intervals, slot_duration, buffer):
        """Generate fixed-duration slots from work intervals."""
        slots = []
        slot_td = timedelta(minutes=slot_duration)
        buffer_td = timedelta(minutes=buffer)

        for start, end, _meta in intervals:
            current = start
            while current + slot_td <= end:
                slots.append({
                    "start": current,
                    "end": current + slot_td,
                })
                current = current + slot_td + buffer_td

        return slots

    def _filter_booked_slots(self, doctor, day_start, day_end, slots):
        """Remove slots that overlap with existing appointments."""
        # Odoo stores datetimes as naive UTC; convert our aware boundaries
        ds = day_start.replace(tzinfo=None) if day_start.tzinfo else day_start
        de = day_end.replace(tzinfo=None) if day_end.tzinfo else day_end
        appointments = self.env["calendar.event"].sudo().search([
            ("doctor_id", "=", doctor.id),
            ("is_appointment", "=", True),
            ("start", "<", de),
            ("stop", ">", ds),
            ("appointment_status", "not in", ["cancelled"]),
        ])

        if not appointments:
            return slots

        # Odoo stores datetimes as naive UTC; our slots are tz-aware UTC
        booked_ranges = []
        for a in appointments:
            a_start = a.start.replace(tzinfo=pytz.utc) if a.start.tzinfo is None else a.start
            a_stop = a.stop.replace(tzinfo=pytz.utc) if a.stop.tzinfo is None else a.stop
            booked_ranges.append((a_start, a_stop))

        available = []
        for slot in slots:
            overlaps = any(
                slot["start"] < booked_end and slot["end"] > booked_start
                for booked_start, booked_end in booked_ranges
            )
            if not overlaps:
                available.append(slot)

        return available

    def _filter_by_min_advance(self, slots):
        """Remove slots that are too soon."""
        min_hours = self.config.min_advance_booking_hours or 0
        cutoff = datetime.now(pytz.utc) + timedelta(hours=min_hours)
        return [s for s in slots if s["start"] >= cutoff]

    def _filter_by_max_advance(self, slots, date):
        """Remove slots beyond the maximum advance booking window."""
        max_days = self.config.max_advance_booking_days or 365
        from datetime import date as date_type

        today = date_type.today()
        if (date - today).days > max_days:
            return []
        return slots

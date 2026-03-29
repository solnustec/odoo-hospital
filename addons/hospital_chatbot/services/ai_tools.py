"""Tool declarations and registry for Gemini function calling.

Port of billing/apps/chatbot/agent/tools.py adapted for Odoo ORM
and hospital domain. All ORM calls use env(user=1) for sudo access
since the webhook runs with auth="none".
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta

import pytz

_logger = logging.getLogger(__name__)

# ============================================================
# Tool declarations for Gemini function calling
# ============================================================

TOOL_DECLARATIONS = [
    {
        "name": "list_services",
        "description": (
            "List available medical services at the hospital. "
            "Shows all services with their associated doctors and prices."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "doctor_id": {
                    "type": "INTEGER",
                    "description": "Doctor ID to filter services (optional)",
                },
            },
        },
    },
    {
        "name": "list_professionals",
        "description": (
            "List available doctors at the hospital. "
            "Optionally filter by service name to find doctors that offer a specific service."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "service_name": {
                    "type": "STRING",
                    "description": "Service name to filter doctors (optional)",
                },
            },
        },
    },
    {
        "name": "check_availability",
        "description": (
            "Check available time slots for a doctor on a given date. "
            "If many slots and no period specified, returns a summary by period "
            "(morning/afternoon/evening) with slot counts. "
            "Specify a period to get actual time slots."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "doctor_id": {
                    "type": "INTEGER",
                    "description": "Doctor ID",
                },
                "date": {
                    "type": "STRING",
                    "description": "Date in YYYY-MM-DD format",
                },
                "period": {
                    "type": "STRING",
                    "description": (
                        "Time period: 'morning' (before 12:00), "
                        "'afternoon' (12:00-17:00), or 'evening' (after 17:00). "
                        "Omit to get period summary first."
                    ),
                },
            },
            "required": ["doctor_id", "date"],
        },
    },
    {
        "name": "create_appointment",
        "description": (
            "Create a new medical appointment. Phone is auto-filled from WhatsApp. "
            "Always confirm with the user before calling this tool."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "doctor_id": {
                    "type": "INTEGER",
                    "description": "Doctor ID",
                },
                "date": {
                    "type": "STRING",
                    "description": "Date in YYYY-MM-DD format",
                },
                "time": {
                    "type": "STRING",
                    "description": "Time in HH:MM format",
                },
                "service_id": {
                    "type": "INTEGER",
                    "description": "Service/product ID",
                },
                "full_name": {
                    "type": "STRING",
                    "description": "Patient full name",
                },
                "identification": {
                    "type": "STRING",
                    "description": "Patient ID number (cédula/RUC)",
                },
                "email": {
                    "type": "STRING",
                    "description": "Patient email (optional)",
                },
                "notes": {
                    "type": "STRING",
                    "description": "Additional notes (optional)",
                },
            },
            "required": ["doctor_id", "date", "time", "service_id", "full_name", "identification"],
        },
    },
    {
        "name": "list_my_appointments",
        "description": "List the current user's upcoming appointments (identified by phone).",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "cancel_appointment",
        "description": (
            "Cancel an existing appointment by ID. "
            "Only works for the user's own appointments. "
            "Always confirm with the user before calling."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "appointment_id": {
                    "type": "INTEGER",
                    "description": "Appointment ID to cancel",
                },
            },
            "required": ["appointment_id"],
        },
    },
    {
        "name": "search_clients",
        "description": (
            "Look up the CURRENT user's patient record by name or ID. "
            "Only returns records matching the user's phone. "
            "Use internally before booking — do NOT offer as a user feature."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Search text (name or ID number)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_client",
        "description": (
            "Register a new patient. Phone is auto-filled from WhatsApp."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "full_name": {"type": "STRING", "description": "Full name"},
                "identification": {"type": "STRING", "description": "ID number (cédula/RUC)"},
                "email": {"type": "STRING", "description": "Email (optional)"},
            },
            "required": ["full_name", "identification"],
        },
    },
    {
        "name": "update_client",
        "description": (
            "Update a patient's information. Only works for the user's OWN record."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "identification": {"type": "STRING", "description": "ID number to find the record"},
                "full_name": {"type": "STRING", "description": "New name (optional)"},
                "email": {"type": "STRING", "description": "New email (optional)"},
            },
            "required": ["identification"],
        },
    },
    {
        "name": "end_ai_conversation",
        "description": (
            "End AI mode and return to the chatbot menu. "
            "Use when the user says 'menu', 'bye', 'back', etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]


def build_rest_tools() -> list[dict]:
    """Convert TOOL_DECLARATIONS to Gemini REST API format."""
    type_map = {
        "OBJECT": "OBJECT",
        "STRING": "STRING",
        "INTEGER": "INTEGER",
        "NUMBER": "NUMBER",
        "BOOLEAN": "BOOLEAN",
        "ARRAY": "ARRAY",
    }

    def convert_params(params):
        result = {"type": type_map.get(params.get("type", "OBJECT"), "OBJECT")}
        if "properties" in params:
            props = {}
            for pname, pval in params["properties"].items():
                props[pname] = {"type": type_map.get(pval.get("type", "STRING"), "STRING")}
                if "description" in pval:
                    props[pname]["description"] = pval["description"]
            result["properties"] = props
        if "required" in params:
            result["required"] = params["required"]
        return result

    declarations = []
    for tool in TOOL_DECLARATIONS:
        decl = {"name": tool["name"], "description": tool["description"]}
        if "parameters" in tool:
            decl["parameters"] = convert_params(tool["parameters"])
        declarations.append(decl)

    return [{"functionDeclarations": declarations}]


class ToolRegistry:
    """Executes tools based on Gemini function calls using Odoo ORM."""

    def __init__(self, env, chatbot, user_phone: str):
        """
        Args:
            env: Odoo environment with user=1 (sudo).
            chatbot: hospital.chatbot record.
            user_phone: WhatsApp phone of the user.
        """
        self.env = env
        self.chatbot = chatbot
        self.user_phone = user_phone

    def _verify_phone_match(self, phone: str) -> bool:
        if not phone or not self.user_phone:
            return False
        clean_user = re.sub(r"[^\d]", "", self.user_phone)
        clean_other = re.sub(r"[^\d]", "", str(phone))
        return clean_user[-8:] == clean_other[-8:]

    def execute(self, tool_name: str, args: dict) -> dict:
        handler = getattr(self, f"_tool_{tool_name}", None)
        if not handler:
            return {"error": f"Tool '{tool_name}' not found"}
        try:
            result = handler(**args)
            return self._make_json_safe(result)
        except Exception as e:
            _logger.error("Error executing tool %s: %s", tool_name, e, exc_info=True)
            return {"error": str(e)}

    @staticmethod
    def _make_json_safe(obj):
        if isinstance(obj, dict):
            return {k: ToolRegistry._make_json_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [ToolRegistry._make_json_safe(v) for v in obj]
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, time):
            return obj.strftime("%H:%M")
        return obj

    # =====================
    # Booking tools
    # =====================

    def _tool_list_services(self, doctor_id: int = None) -> dict:
        doctors = self.env["hr.employee"].search([
            ("is_doctor", "=", True),
            ("accepting_appointments", "=", True),
        ])
        if doctor_id:
            doctors = doctors.filtered(lambda d: d.id == doctor_id)

        services = []
        seen = set()
        for doc in doctors:
            for svc in doc.booking_service_ids:
                key = svc.id
                if key not in seen:
                    seen.add(key)
                    doctor_names = [
                        d.name for d in doctors
                        if svc in d.booking_service_ids
                    ]
                    services.append({
                        "id": svc.id,
                        "name": svc.name,
                        "price": svc.list_price,
                        "doctors": doctor_names,
                    })

        return {"services": services, "count": len(services)}

    def _tool_list_professionals(self, service_name: str = "") -> dict:
        import unicodedata

        def _normalize(text):
            nfkd = unicodedata.normalize("NFKD", text.lower())
            return "".join(c for c in nfkd if not unicodedata.combining(c))

        doctors = self.env["hr.employee"].search([
            ("is_doctor", "=", True),
            ("accepting_appointments", "=", True),
        ])

        if service_name:
            norm = _normalize(service_name)
            # Strip suffixes for root matching
            root = norm
            for suffix in ("logia", "logo", "loga", "ia", "ica", "ico", "ista"):
                if root.endswith(suffix) and len(root) > len(suffix) + 3:
                    root = root[:-len(suffix)]
                    break

            doctors = doctors.filtered(
                lambda d: root in _normalize(d.job_title or "")
                or any(root in _normalize(s.name) for s in d.booking_service_ids)
                or any(norm_w in _normalize(d.job_title or "") for norm_w in norm.split() if len(norm_w) >= 4)
            )

        professionals = []
        for doc in doctors:
            services = [s.name for s in doc.booking_service_ids]
            professionals.append({
                "id": doc.id,
                "name": doc.name,
                "specialty": doc.job_title or "",
                "services": services,
            })

        return {"professionals": professionals, "count": len(professionals)}

    def _tool_check_availability(
        self, doctor_id: int, date: str, period: str = None
    ) -> dict:
        from odoo.addons.hospital_booking.services.availability import AvailabilityService

        doctor = self.env["hr.employee"].browse(doctor_id)
        if not doctor.exists() or not doctor.is_doctor:
            return {"error": "Doctor not found"}

        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "Invalid date format. Use YYYY-MM-DD"}

        svc = AvailabilityService(self.env)
        slots = svc.get_available_slots(target_date, doctor)

        tz = pytz.timezone(doctor.resource_calendar_id.tz if doctor.resource_calendar_id else "America/Guayaquil")
        formatted = []
        for s in slots:
            local_start = s["start"].astimezone(tz)
            local_end = s["end"].astimezone(tz)
            formatted.append({
                "start": local_start.strftime("%H:%M"),
                "end": local_end.strftime("%H:%M"),
            })

        # Group by period
        morning = [s for s in formatted if s["start"] < "12:00"]
        afternoon = [s for s in formatted if "12:00" <= s["start"] < "17:00"]
        evening = [s for s in formatted if s["start"] >= "17:00"]

        if period:
            period_lower = period.lower()
            if period_lower in ("morning", "manhã", "mañana"):
                filtered = morning
            elif period_lower in ("afternoon", "tarde"):
                filtered = afternoon
            elif period_lower in ("evening", "noite", "noche"):
                filtered = evening
            else:
                filtered = formatted
            return {
                "doctor": doctor.name,
                "date": date,
                "period": period,
                "available_slots": filtered,
                "count": len(filtered),
            }

        # If many slots, return period summary
        if len(formatted) > 6:
            summary = {}
            if morning:
                summary["morning"] = {"count": len(morning), "range": f"{morning[0]['start']} - {morning[-1]['end']}"}
            if afternoon:
                summary["afternoon"] = {"count": len(afternoon), "range": f"{afternoon[0]['start']} - {afternoon[-1]['end']}"}
            if evening:
                summary["evening"] = {"count": len(evening), "range": f"{evening[0]['start']} - {evening[-1]['end']}"}
            return {
                "doctor": doctor.name,
                "date": date,
                "period_summary": summary,
                "total_slots": len(formatted),
            }

        return {
            "doctor": doctor.name,
            "date": date,
            "available_slots": formatted,
            "count": len(formatted),
        }

    def _tool_create_appointment(
        self,
        doctor_id: int,
        date: str,
        time: str,
        service_id: int,
        full_name: str,
        identification: str,
        email: str = "",
        notes: str = "",
        **kwargs,
    ) -> dict:
        from odoo.addons.hospital_booking.services.availability import AvailabilityService
        from odoo.addons.hospital_booking.services.validation import AppointmentValidationService

        doctor = self.env["hr.employee"].browse(doctor_id)
        if not doctor.exists() or not doctor.is_doctor:
            return {"error": "Doctor not found"}

        service = self.env["product.product"].browse(service_id)
        if not service.exists():
            return {"error": "Service not found"}

        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
            target_time = datetime.strptime(time, "%H:%M").time()
        except ValueError:
            return {"error": "Invalid date/time format"}

        # Convert local time to UTC for storage
        tz = pytz.timezone(doctor.resource_calendar_id.tz if doctor.resource_calendar_id else "America/Guayaquil")
        local_dt = tz.localize(datetime.combine(target_date, target_time))
        utc_start = local_dt.astimezone(pytz.utc)
        duration = doctor.slot_duration or 30
        utc_end = utc_start + timedelta(minutes=duration)

        # Check availability
        avail_svc = AvailabilityService(self.env)
        is_available, reason = avail_svc.check_slot_available(doctor, utc_start, utc_end)
        if not is_available:
            return {"error": f"Time slot not available: {reason}"}

        # Find or create patient
        Partner = self.env["res.partner"]
        phone = self.user_phone  # Always from WhatsApp
        phone_suffix = re.sub(r"[^\d]", "", phone)[-8:]
        patient = Partner.search([
            "|", ("phone", "=like", f"%{phone_suffix}"),
            ("mobile", "=like", f"%{phone_suffix}"),
        ], limit=1)

        if not patient:
            patient = Partner.create({
                "name": full_name,
                "phone": phone,
                "mobile": phone,
                "vat": identification,
                "email": email or False,
            })
        else:
            # Update name/vat if provided
            update_vals = {}
            if full_name and patient.name != full_name:
                update_vals["name"] = full_name
            if identification and not patient.vat:
                update_vals["vat"] = identification
            if update_vals:
                patient.write(update_vals)

        # Validate booking limits
        val_svc = AppointmentValidationService(self.env)
        can_book, limit_reason = val_svc.can_patient_book(patient, target_date)
        if not can_book:
            return {"error": limit_reason}

        # Create appointment
        event = self.env["calendar.event"].create({
            "name": f"Cita: {full_name} — {service.name}",
            "start": utc_start.replace(tzinfo=None),
            "stop": utc_end.replace(tzinfo=None),
            "doctor_id": doctor.id,
            "patient_id": patient.id,
            "patient_phone": phone,
            "service_id": service.id,
            "is_appointment": True,
            "appointment_origin": "chatbot",
            "appointment_notes": notes or "",
        })

        return {
            "success": True,
            "appointment_id": event.id,
            "details": {
                "doctor": doctor.name,
                "service": service.name,
                "date": date,
                "time": time,
                "duration_minutes": duration,
                "patient": full_name,
            },
        }

    def _tool_list_my_appointments(self) -> dict:
        phone_suffix = re.sub(r"[^\d]", "", self.user_phone)[-8:]

        events = self.env["calendar.event"].search([
            ("is_appointment", "=", True),
            ("patient_phone", "=like", f"%{phone_suffix}"),
            ("start", ">=", datetime.now(pytz.utc).replace(tzinfo=None) - timedelta(days=1)),
            ("appointment_status", "not in", ["cancelled"]),
        ], order="start asc", limit=10)

        if not events:
            return {"appointments": [], "message": "No appointments found."}

        result = []
        for ev in events:
            tz_name = ev.doctor_id.resource_calendar_id.tz if ev.doctor_id and ev.doctor_id.resource_calendar_id else "America/Guayaquil"
            tz = pytz.timezone(tz_name)
            local_start = pytz.utc.localize(ev.start).astimezone(tz)
            result.append({
                "id": ev.id,
                "date": local_start.strftime("%Y-%m-%d"),
                "time": local_start.strftime("%H:%M"),
                "doctor": ev.doctor_id.name if ev.doctor_id else "N/A",
                "service": ev.service_id.name if ev.service_id else "N/A",
                "status": ev.appointment_status,
            })

        return {"appointments": result, "count": len(result)}

    def _tool_cancel_appointment(self, appointment_id: int) -> dict:
        event = self.env["calendar.event"].browse(appointment_id)
        if not event.exists() or not event.is_appointment:
            return {"error": "Appointment not found"}

        # Ownership check
        if event.patient_phone and not self._verify_phone_match(event.patient_phone):
            return {"error": "You can only cancel your own appointments."}

        if event.appointment_status in ("cancelled", "done"):
            return {"error": f"Cannot cancel: appointment is {event.appointment_status}"}

        event.action_cancel()
        return {"success": True, "appointment_id": appointment_id, "message": "Appointment cancelled."}

    # =====================
    # Client/Patient CRUD
    # =====================

    def _tool_search_clients(self, query: str) -> dict:
        phone_suffix = re.sub(r"[^\d]", "", self.user_phone)[-8:]
        partners = self.env["res.partner"].search([
            "&",
            "|", ("phone", "=like", f"%{phone_suffix}"), ("mobile", "=like", f"%{phone_suffix}"),
            "|", ("name", "ilike", query), ("vat", "ilike", query),
        ], limit=5)

        clients = []
        for p in partners:
            ident = p.vat or ""
            masked = ident[:2] + "***" + ident[-2:] if len(ident) > 4 else "***"
            clients.append({
                "id": p.id,
                "full_name": p.name,
                "identification_masked": masked,
                "has_email": bool(p.email),
            })
        return {"clients": clients, "count": len(clients)}

    def _tool_create_client(
        self, full_name: str, identification: str, email: str = "", **kwargs
    ) -> dict:
        phone = self.user_phone

        existing = self.env["res.partner"].search([("vat", "=", identification)], limit=1)
        if existing:
            return {"error": "A patient with this ID number already exists."}

        partner = self.env["res.partner"].create({
            "name": full_name,
            "vat": identification,
            "phone": phone,
            "mobile": phone,
            "email": email or False,
        })
        return {"success": True, "client_id": partner.id, "full_name": partner.name}

    def _tool_update_client(
        self, identification: str, full_name: str = "", email: str = "", **kwargs
    ) -> dict:
        partner = self.env["res.partner"].search([("vat", "=", identification)], limit=1)
        if not partner:
            return {"error": "No matching record found."}

        if not self._verify_phone_match(partner.phone or partner.mobile or ""):
            return {"error": "You can only update your own record."}

        update_vals = {}
        if full_name:
            update_vals["name"] = full_name
        if email:
            update_vals["email"] = email
        if not update_vals:
            return {"error": "No fields to update"}

        partner.write(update_vals)
        return {"success": True, "client_id": partner.id, "updated_fields": list(update_vals.keys())}

    # =====================
    # Control
    # =====================

    def _tool_end_ai_conversation(self) -> dict:
        return {"action": "end_ai_mode", "message": "Returning to main menu."}

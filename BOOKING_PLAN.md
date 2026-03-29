# Plan: Hospital Booking System (`hospital_booking` module)

## Context

The hospital project needs an appointment booking system where patients can schedule appointments with doctors. This must integrate with:
- **The chatbot** (`hospital_chatbot`) — patients book via WhatsApp using both structured flows (admin-configured) and AI agent mode
- **Odoo's calendar** — staff see appointments in calendar/list/kanban views
- **Doctor schedules** — availability computed from work hours, leaves, existing bookings

The billing project has a mature booking system (Django) with AvailabilityService, validation, and chatbot AI tools. We replicate that pattern using Odoo's native calendar/resource infrastructure.

---

## Decision: Separate Module

Create **`hospital_booking`** as an independent module. The chatbot depends on it, not the other way around.

```
hospital_booking   (depends: base, hr, resource, calendar, product)
       ↑
hospital_chatbot   (adds hospital_booking to its depends)
```

**Why separate:** Booking logic (schedules, availability, lifecycle) is usable without the chatbot — staff can manage appointments via Odoo UI, and future website/portal booking pages can use the same service.

---

## Leverage Odoo Native Features

| Billing (Django, custom) | Odoo (native) |
|---|---|
| BookingMember per-day fields (49 columns) | `resource.calendar.attendance` records |
| AvailabilityException | `resource.calendar.leaves` |
| Custom Appointment model | Extend `calendar.event` |
| Custom professional schedule | `hr.employee.resource_calendar_id` |

**Key advantage:** Odoo's `resource.calendar._work_intervals_batch()` computes work intervals minus leaves automatically. We don't need to build schedule parsing from scratch.

---

## Module Structure

```
addons/hospital_booking/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── booking_config.py       # hospital.booking.config
│   ├── hr_employee.py          # _inherit hr.employee (booking fields)
│   └── calendar_event.py       # _inherit calendar.event (appointment fields + lifecycle)
├── services/
│   ├── __init__.py
│   ├── availability.py         # AvailabilityService (slot generation)
│   └── validation.py           # AppointmentValidationService
├── views/
│   ├── appointment_views.xml   # Calendar, list, form, kanban
│   ├── hr_employee_views.xml   # Booking tab on employee form
│   ├── booking_config_views.xml
│   └── menu.xml
├── security/
│   ├── booking_security.xml
│   └── ir.model.access.csv
└── data/
    └── booking_data.xml        # Default config
```

---

## Models

### `hospital.booking.config` (new)
Ported from billing's `AppointmentConfig`. One record per company.

| Field | Type | Default |
|---|---|---|
| default_slot_duration | Integer | 30 (min) |
| buffer_between_appointments | Integer | 15 (min) |
| min_advance_booking_hours | Integer | 2 |
| max_advance_booking_days | Integer | 60 |
| auto_confirm | Boolean | True |
| max_appointments_per_patient_day | Integer | 3 |
| max_pending_per_patient | Integer | 5 |
| max_no_shows_before_block | Integer | 3 |
| free_cancellation_hours | Integer | 24 |

### `hr.employee` extension
| Field | Type | Purpose |
|---|---|---|
| is_doctor | Boolean | Show in booking |
| accepting_appointments | Boolean | Currently available |
| slot_duration | Integer (nullable) | Override default |
| buffer_time | Integer (nullable) | Override default |
| max_daily_appointments | Integer (nullable) | Daily cap |
| booking_service_ids | M2M product.product | Services offered |

Doctor schedule comes from `resource_calendar_id.attendance_ids` (native). Lunch breaks use `day_period='lunch'` attendance lines. Time off uses `resource.calendar.leaves`.

### `calendar.event` extension
| Field | Type | Purpose |
|---|---|---|
| is_appointment | Boolean | Filter from regular events |
| appointment_status | Selection | draft/confirmed/in_progress/done/cancelled/no_show |
| appointment_origin | Selection | chatbot/web/phone/walkin/admin |
| doctor_id | M2O hr.employee | The doctor |
| patient_id | M2O res.partner | The patient |
| patient_phone | Char | For chatbot lookup |
| service_id | M2O product.product | Medical service |
| appointment_notes | Text | Internal notes |
| cancellation_reason | Char | Why cancelled |

**Lifecycle methods:** `action_confirm()`, `action_start()`, `action_done()`, `action_cancel()`, `action_no_show()`

**Status flow:**
```
draft → confirmed → in_progress → done
  ↓        ↓            ↓
cancelled  cancelled   no_show
```

---

## AvailabilityService

**File:** `services/availability.py`
**Ported from:** `billing/apps/booking/services.py` → `AvailabilityService`

```python
class AvailabilityService:
    def get_available_slots(self, date, doctor, duration_minutes=None):
        # 1. Get work intervals via calendar._work_intervals_batch()
        #    (auto-excludes leaves/time-off)
        # 2. Generate fixed-duration slots within intervals
        # 3. Filter out slots with existing appointments
        # 4. Filter by min_advance_booking_hours
        # Returns: [{"start": datetime, "end": datetime}, ...]

    def check_slot_available(self, doctor, start, end):
        # Returns: (is_available: bool, reason: str)
```

**Key files to port from:**
- `billing/apps/booking/services.py` lines 1-200 (AvailabilityService)
- Adapted to use `_work_intervals_batch()` instead of manual schedule parsing

## AppointmentValidationService

**File:** `services/validation.py`
**Ported from:** `billing/apps/booking/services.py` → `AppointmentValidationService`

```python
class AppointmentValidationService:
    def can_patient_book(self, patient, date):
        # Returns: (bool, reason_str)
        # Checks: max per day, max pending, no-show blocking
```

---

## Views

### Appointment Views
- **Calendar view** — default view, colored by status, filtered to `is_appointment=True`
- **List view** — date, patient, doctor, service, status badge, origin
- **Form view** — status bar header with action buttons, patient/doctor/service groups
- **Kanban view** — grouped by status for workflow board

### Employee Booking Tab
Extends `hr.employee` form with a "Citas" tab showing booking fields and stat button for upcoming appointments.

### Menu Structure
```
Citas (top-level app)
├── Agenda (calendar view)
├── Citas (list view)
├── Doctores (hr.employee filtered is_doctor=True)
└── Configuración → Políticas de Citas
```

---

## Chatbot Integration (both flow-based AND AI)

After `hospital_booking` is built, update `hospital_chatbot`:

1. **Add `hospital_booking` to manifest depends**

### A) Flow-based chatbot (no AI needed)
Admin configures a structured flow with nodes that call booking actions. New node type or API_CALL nodes that use booking endpoints:

- **MENU node** — "1. Agendar cita  2. Mis citas  3. Cancelar"
- **QUESTION nodes** — ask patient name, phone, preferred date
- **API_CALL node** — calls internal booking service to check availability, create appointment
- **Alternatively:** Add a new node type `BOOKING_ACTION` that directly invokes the booking service without requiring external API calls. Actions: `list_doctors`, `check_availability`, `create_appointment`, `list_appointments`, `cancel_appointment`

This means the chatbot engine (`services/engine.py`) needs a new handler `_handle_booking_action()` that calls `AvailabilityService` and `calendar.event` directly via the ORM, returning formatted responses.

### B) AI agent mode (Gemini tools)
When AI is enabled, the tools are available for freeform conversation:

| Tool | Action |
|---|---|
| `list_professionals` | Query `hr.employee` where `is_doctor=True` |
| `list_services` | Query `product.product` via doctor's `booking_service_ids` |
| `check_availability` | Call `AvailabilityService.get_available_slots()` |
| `create_appointment` | Validate + create `calendar.event` with appointment fields |
| `list_my_appointments` | Query by `patient_phone` matching WhatsApp sender |
| `cancel_appointment` | Verify ownership + `action_cancel()` |

### C) Shared booking service layer
Both A and B use the **same** `AvailabilityService` and `AppointmentValidationService`. The difference is only how user input is collected (structured flow vs freeform AI).

3. **Update reminder cron** to filter by `is_appointment=True` and `appointment_status='confirmed'`

---

## Implementation Steps

| # | Task | Files |
|---|---|---|
| 1 | Module scaffold + manifest + security | `__init__`, `__manifest__`, `security/*` |
| 2 | BookingConfig model | `models/booking_config.py` |
| 3 | hr.employee extension | `models/hr_employee.py` |
| 4 | calendar.event extension + lifecycle | `models/calendar_event.py` |
| 5 | AvailabilityService | `services/availability.py` |
| 6 | ValidationService | `services/validation.py` |
| 7 | Appointment views (calendar, list, form, kanban) | `views/appointment_views.xml` |
| 8 | Employee booking tab | `views/hr_employee_views.xml` |
| 9 | Config view + menu | `views/booking_config_views.xml`, `views/menu.xml` |
| 10 | Default data | `data/booking_data.xml` |
| 11 | Install + test in Odoo | -- |
| 12 | Chatbot: add `_handle_booking_action()` to engine for flow-based booking | `hospital_chatbot/services/engine.py` |
| 13 | Chatbot: AI tools integration (for AI agent mode) | `hospital_chatbot/services/ai_tools.py` |

---

## Verification

1. Install `hospital_booking` → verify all models, views, menus
2. Create a doctor (hr.employee with `is_doctor=True`) and assign a resource calendar with working hours
3. Open Citas → Agenda → verify calendar view shows
4. Create an appointment via form → confirm → start → complete lifecycle
5. Check availability service: `AvailabilityService(env).get_available_slots(date, doctor)` returns correct slots
6. **Flow-based test:** configure a chatbot flow with BOOKING_ACTION nodes → send WhatsApp message → navigate menu → book appointment via structured flow
7. **AI-based test:** enable AI mode → send "quiero agendar una cita" → AI lists doctors → user picks date → appointment created
8. Verify appointment appears in Odoo calendar view in both cases

---

## Key Files to Port From

| Source (billing) | Target (Odoo) |
|---|---|
| `apps/booking/services.py` → AvailabilityService | `hospital_booking/services/availability.py` |
| `apps/booking/services.py` → AppointmentValidationService | `hospital_booking/services/validation.py` |
| `apps/booking/models.py` → AppointmentConfig | `hospital_booking/models/booking_config.py` |
| `apps/booking/models.py` → Appointment | `hospital_booking/models/calendar_event.py` (extend calendar.event) |
| `apps/chatbot/agent/tools.py` → booking tools | `hospital_chatbot/services/ai_tools.py` |

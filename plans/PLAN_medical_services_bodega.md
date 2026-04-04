# Plan: Medical Services "Bodega" — Separate from Products + Invoicing

## Context

Medical services (e.g., "Consulta General" $35) are stored as `product.product` records with `type='service'`, sharing the same catalog with any standard Odoo products. If the hospital later adds real products (medications, supplies), they'll mix with medical services everywhere. Additionally, completed appointments can't be billed — there is no appointment-to-invoice flow.

**Goals:**
1. Separate medical services into their own "bodega" via a product category filter
2. Provide a dedicated services management UI under Citas > Configuracion
3. Enable appointment → invoice flow (done appointment → "Facturar" → `account.move`)

---

## Phase 1: Product Category Foundation

Create a `product.category` "Servicios Medicos" and use it to filter medical services from general products throughout the system.

**Files to create:**
- `hospital_booking/models/product_template.py` — extend `product.template` with `is_medical_service` computed boolean (based on `categ_id`)
- `hospital_booking/hooks.py` — `post_init_hook` to migrate existing products linked to doctors into the new category on upgrade

**Files to modify:**
- `hospital_booking/data/booking_data.xml` — add `product_category_medical_service` record
- `hospital_booking/data/booking_demo.xml` — add `categ_id` ref to all 6 demo services
- `hospital_booking/models/hr_employee.py` — add domain filter on `booking_service_ids`
- `hospital_booking/models/calendar_event.py` — add domain filter on `service_id`
- `hospital_booking/models/__init__.py` — add `from . import product_template`
- `hospital_booking/__init__.py` — add post_init_hook
- `hospital_booking/__manifest__.py` — add `"post_init_hook"`
- `hospital_chatbot/services/ai_tools.py` — validate service category in `_tool_create_appointment`

---

## Phase 2: Dedicated Services Management UI

**Files to create:**
- `hospital_booking/views/medical_service_views.xml` — simplified tree (editable) + form views for `product.template` filtered by medical category

**Files to modify:**
- `hospital_booking/views/menu.xml` — add "Servicios Medicos" menuitem
- `hospital_booking/__manifest__.py` — add view file to data list

---

## Phase 3: Appointment to Invoice Flow

**Files to modify:**
- `hospital_booking/__manifest__.py` — add `"account"` to `depends`
- `hospital_booking/models/calendar_event.py` — add `invoice_id`, `action_create_invoice()`, `action_view_invoice()`
- `hospital_booking/views/appointment_views.xml` — add "Facturar" button, invoice smart button, search filters

---

## Implementation Order

1. Phase 1 (category + domains + migration hook) — foundation
2. Phase 2 (services UI) — depends on Phase 1
3. Phase 3 (invoicing) — depends on Phase 1

---

## Verification

- **Phase 1**: Create a regular product — verify it does NOT appear in doctor/appointment service dropdowns
- **Phase 2**: Citas > Configuracion > Servicios Medicos — create service, verify auto-category
- **Phase 3**: Complete appointment → "Facturar" → verify invoice with correct data and Ecuador EDI fields

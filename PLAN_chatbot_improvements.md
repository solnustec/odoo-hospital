# Plan: Chatbot Security, Settings & WebSocket QR

## Context

The hospital chatbot module (`hospital_chatbot`) needs three improvements:
1. **No admin UI exists** for configuring the Gemini API key — admins must edit `ir.config_parameter` manually via Technical > Parameters
2. **AI agent tool calls run as superuser** (`sudo user=1`) with no confirmation step — prompt injection or AI hallucination could cause unwanted writes (create/cancel appointments, create/update patients)
3. **WhatsApp QR flow is manual** — after scanning, user must click "Verificar" then save, whereas the billing system auto-detects via Socket.IO

---

## Phase 1: Gemini API Key Settings Page

**Files to create:**
- `models/res_config_settings.py` — `res.config.settings` transient model with `config_parameter` fields for: `gemini_api_key`, `webhook_secret`, `whatsapp_service_url`, `whatsapp_login_url`, `whatsapp_check_url`
- `views/res_config_settings_views.xml` — Inherit `base.res_config_settings_view_form`, add an `<app>` block with three sections: AI, WhatsApp URLs, Security. Use `password="True"` for sensitive fields

**Files to modify:**
- `models/__init__.py` — add `from . import res_config_settings`
- `views/menu.xml` — add "Ajustes" menuitem under `chatbot_menu_config` (sequence 99, groups=`group_chatbot_manager`)
- `__manifest__.py` — add `views/res_config_settings_views.xml` to `data`

**Key pattern:** Use `config_parameter='hospital_chatbot.gemini_api_key'` field attribute — Odoo handles get/set automatically.

---

## Phase 2: Security Token for AI Agent Write Operations

### New models

**`models/ai_pending_action.py`** — `hospital.chatbot.ai.pending.action`
- Fields: `session_id` (M2O to session), `token` (Char, indexed), `tool_name`, `tool_args` (Json), `status` (pending/confirmed/expired/rejected), `expires_at` (Datetime), `result` (Json)
- Token: 6-char alphanumeric, expires in 5 minutes
- Method `execute_confirmed()`: validates token, checks expiry, runs the original tool, marks confirmed

**`models/ai_audit_log.py`** — `hospital.chatbot.ai.audit.log`
- Fields: `session_id`, `phone_number`, `tool_name`, `tool_args` (Json), `tool_result` (Json), `is_write_operation`, `was_confirmed`, `timestamp`
- Every tool call (read and write) gets logged here

### Modify `services/ai_tools.py`

- Define `WRITE_TOOLS = {"create_appointment", "cancel_appointment", "create_client", "update_client"}`
- Add `session` parameter to `ToolRegistry.__init__`
- Change `execute()`: if tool is in `WRITE_TOOLS`, create a pending action with token and return `{"pending_confirmation": True, "token": "...", "summary": "..."}` instead of executing
- Add new tool `confirm_action(token)` to `TOOL_DECLARATIONS` and `build_rest_tools()` — validates token, executes original tool, returns result
- Log all executions to audit log

### Modify `services/ai_agent_service.py`

- Pass `session` to `ToolRegistry` constructor

### Modify `services/ai_prompts.py`

- Add confirmation flow instructions to system prompt: "Write operations return a confirmation token. Present the summary to the user. Only call `confirm_action` after explicit user agreement."

### New views & data

- `views/ai_audit_views.xml` — tree/form views for audit log, menu under Reportes
- `data/chatbot_cron.xml` — add cron to expire pending actions older than 5 minutes
- `security/ir.model.access.csv` — access rules for both new models

---

## Phase 3: WebSocket QR Code (Socket.IO)

### Current flow (REST, manual)
1. Click "Obtener QR" → `action_get_qr()` → opens wizard → REST POST to `/loginwhatsapp` → displays QR image
2. User scans → clicks "Ya escaneé, verificar" → REST POST to `/checksession` → updates status
3. Manual save

### New flow (Socket.IO, automatic)
1. Click "Obtener QR" → opens OWL client action → connects Socket.IO to loginqr service
2. Server emits `login:qr` → component displays QR image (auto-updates on expiry)
3. User scans → server emits `login:connected` → component auto-saves session via RPC → closes
4. No manual button needed

### Files to create

- `static/lib/socket.io/socket.io.min.js` — vendored Socket.IO v4.x client (~45KB)
- `static/src/js/whatsapp_qr.js` — OWL component `WhatsappQrAction`
  - `setup()`: get orm/action/notification services, useState for status/qr/etc
  - `onMounted()`: fetch login URL from `ir.config_parameter`, connect Socket.IO
  - Socket events: `login:qr` → display QR, `login:connected` → write to `whatsapp.phone` record + call `action_connect_session` via RPC, then close
  - Error/timeout/retry handling, `onWillUnmount()` cleanup
  - Registered as `registry.category("actions").add("hospital_chatbot.whatsapp_qr", ...)`
- `static/src/xml/whatsapp_qr.xml` — OWL template with QR display, status indicator, instructions, cancel button
- `static/src/css/whatsapp_qr.css` — WhatsApp-themed overlay styles

### Files to modify

- `models/whatsapp_config.py` — change `action_get_qr()` to return `ir.actions.client` with tag `hospital_chatbot.whatsapp_qr` instead of wizard
- `views/whatsapp_phone_views.xml` — add `ir.actions.client` record for the QR action
- `__manifest__.py` — add new JS/XML/CSS to `web.assets_backend`

### Reference implementation
- Billing client: `billing/templates/apps/whatsapp/whatsapp_session.html` lines 636-817
- The loginqr.js server (shared with billing) already supports Socket.IO events: `login`, `login:qr`, `login:connected`, `login:cancel`

---

## Implementation Order

1. **Phase 1** (Settings page) — independent, low risk, enables admin config of URLs needed by Phase 3
2. **Phase 2** (Security tokens) — modifies AI pipeline, needs thorough testing via chatbot test wizard
3. **Phase 3** (WebSocket QR) — frontend-heavy, benefits from Phase 1 settings

---

## Verification

- **Phase 1**: Navigate to Chatbot > Configuracion > Ajustes, set a Gemini API key, save, reload — verify key persists. Check `ir.config_parameter` table confirms the value.
- **Phase 2**: Use the chatbot test wizard to trigger a write operation (e.g., "create an appointment"). Verify the AI returns a confirmation prompt with token. Reply "yes" and confirm the action executes. Test token expiry by waiting >5 min. Check audit log entries.
- **Phase 3**: Open a WhatsApp phone, click "Obtener QR", verify Socket.IO connects and QR appears. Scan with phone — verify overlay auto-closes and session status updates to "connected" without clicking any button.

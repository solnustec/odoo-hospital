# Plan: Hospital Chatbot — Phases 3, 4 & 5

## Status: Phase 1+2 Complete

Phase 1+2 delivered a working chatbot module with:
- 10 Odoo models, views, menus, security rules
- 3 webhook endpoints (tested and working with curl)
- ChatbotEngine with all 11 node handlers
- AI agent stub (returns placeholder response)

---

## Phase 3: Gemini AI Agent Integration

### Goal
Replace the AI agent stub with the full Gemini 2.0 Flash integration, ported from `billing/apps/chatbot/agent/`. The AI agent should handle free-form conversations, call hospital-specific tools (book appointments, search patients, etc.), and support multilingual responses.

### Files to Create/Modify

#### 3.1 `services/ai_context.py` — ConversationContextManager
Port from: `billing/apps/chatbot/agent/context.py` (146 lines)

Static utility class for managing session state in the `context` Json field:
- `activate_ai_mode()` / `deactivate_ai_mode()` / `is_ai_mode()`
- `get_history()` / `append_user_message()` / `append_model_message()`
- `append_function_call()` / `append_function_calls_batch()`
- `trim_history()` — keep max N messages (configurable per chatbot)
- `get_language()` / `set_language()`
- `set_patient_id()` / `get_patient_id()` — replaces `set_taxpayer_id`
- `set_last_options()` / `get_last_options()` / `clear_last_options()`

Context keys stored in session.context Json:
```
ai_mode, ai_messages, patient_id, language, last_options
```

#### 3.2 `services/ai_response.py` — Response Builders
Port from: `billing/apps/chatbot/agent/response.py` (79 lines)

Pure functions, no changes needed:
- `build_text_response(content, metadata=None)`
- `build_buttons_response(content, buttons, metadata=None)` — max 3 buttons
- `build_list_response(content, sections, button_label, metadata=None)`
- `estimate_typing_delay(text)` — formula: `min(max(words * 80, 500), 3000)` ms

#### 3.3 `services/ai_prompts.py` — System Prompt Builder + Language Detection
Port from: `billing/apps/chatbot/agent/prompts.py` (997 lines)

Key adaptations for hospital context:
- `SystemPromptBuilder.build()` — generates dynamic system prompt including:
  - Hospital name (from `res.company`)
  - Available doctors and specialties (from `hr.employee`)
  - Available services (from `product.product` medical category)
  - Custom `ai_system_prompt` from chatbot config
  - Personality directive (emotion + seriousness)
  - Language directive
- `build_personality_directive()` — tone/seriousness from chatbot config
- `detect_language(text)` — word frequency analysis (es/en/pt)
- `detect_language_from_phone(phone)` — country code mapping (593→es, 55→pt, 1→en)
- `get_ui_text(key, lang)` — translations dict for UI strings

Domain replacements:
- "establecimiento" → hospital/clínica
- "profesional" → doctor/médico
- "taxpayer" → paciente
- "appointment" → cita médica/consulta

#### 3.4 `services/ai_tools.py` — Tool Declarations + Hospital ToolRegistry
Port from: `billing/apps/chatbot/agent/tools.py` (799 lines)

**Tool declarations** (Gemini function calling format):

| Tool | Parameters | Odoo Query |
|------|-----------|------------|
| `list_professionals` | service_name? | `hr.employee` filtered by department/job |
| `list_services` | professional_name? | `product.product` with medical category |
| `check_availability` | professional_id, date, period? | `resource.calendar` + `calendar.event` |
| `create_appointment` | professional_id, date, time, service_id, full_name, identification | Create `calendar.event` |
| `list_my_appointments` | (none — uses phone) | `calendar.event` by attendee phone |
| `cancel_appointment` | appointment_id | Write state on `calendar.event` |
| `search_clients` | query | `res.partner` where is_patient |
| `create_client` | full_name, identification, email? | Create `res.partner` |
| `update_client` | field, value | Update `res.partner` |
| `end_ai_conversation` | (none) | Deactivate AI mode, return to menu |

**ToolRegistry class:**
- `__init__(env, chatbot, user_phone)` — receives Odoo env
- `execute(tool_name, args)` → dispatches to `_tool_{name}()`
- `_verify_phone_match(phone)` — security: last 10 digits comparison
- Each `_tool_*()` method queries Odoo ORM with `.sudo()`

#### 3.5 `services/ai_agent_service.py` — Full Gemini Integration
Replace stub. Port from: `billing/apps/chatbot/agent/service.py` (750 lines)

Key components:
- **Gemini REST API**: `POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={API_KEY}`
- **API key**: from `ir.config_parameter` key `hospital_chatbot.gemini_api_key`
- **Tool calling loop**: max 5 iterations, supports parallel function calls
- **Code leak detection**: regex safety net to prevent Gemini outputting raw code
- **Response parsing**: extract numbered lists → convert to WhatsApp buttons (≤3) or list (>3)
- **Token usage tracking**: save to `hospital.chatbot.ai.token.usage` + daily aggregation
- **Exit patterns**: detect "menu", "salir", "exit", "volver" → deactivate AI, return to flow

#### 3.6 Update `services/engine.py`
Replace inline AI context checks with proper `ConversationContextManager` calls:
- `_handle_ai_agent()` → use `ConversationContextManager.activate_ai_mode()`
- `_activate_ai_fallback()` → same
- `_process_ai_message()` → check `ConversationContextManager.is_ai_mode()`

### Verification — Phase 3
```bash
# Test AI greeting
curl -s -X POST http://localhost:8069/chatbot/webhook/incoming/ \
  -H "Content-Type: application/json" \
  -d '{"emisor":"559484510777","from":"593987654321","message":"hola","type":"text"}'

# Navigate to AI (select option or type unrecognized text)
# Verify Gemini responds with natural language
# Test tool: "¿Qué doctores tienen disponibles?"
# Test tool: "Quiero agendar una cita"
# Test exit: "menu" → should return to flow menu
# Check token usage in Odoo: Chatbot → Reportes → Uso de tokens IA
```

---

## Phase 4: Visual Drag-and-Drop Flow Builder

### Goal
Build an OWL 2 (Odoo 17) widget that renders flows as a visual canvas with draggable nodes and SVG connections. Replaces the current inline tree editor for nodes.

### Files to Create

#### 4.1 `static/src/js/flow_builder.js` — Main OWL Component
- `FlowBuilderWidget` — registered as form widget for `hospital.chatbot.flow`
- Canvas with pan/zoom (mouse wheel + drag on empty space)
- Node rendering: colored boxes by type, showing name + type icon
- Connection rendering: SVG `<path>` bezier curves between node ports
- Drag-and-drop: move nodes, update position_x/position_y via RPC
- Right-click context menu: add node, delete node, edit config
- Double-click node: open Odoo form dialog for node config
- Node palette sidebar: drag new node types onto canvas
- Save button: bulk RPC call to persist all positions + connections

#### 4.2 `static/src/xml/flow_builder.xml` — QWeb Templates
- Main canvas template with SVG overlay
- Node template (per node type with icon + color)
- Connection line template
- Node palette sidebar
- Context menu template

#### 4.3 `static/src/css/flow_builder.css` — Styles
- Canvas grid background
- Node type colors (MESSAGE=blue, MENU=green, QUESTION=yellow, CONDITION=orange, AI_AGENT=purple, etc.)
- Connection line styles
- Drag handles and hover effects
- Responsive sidebar

#### 4.4 Update `views/flow_views.xml`
- Replace inline node tree with embedded `FlowBuilderWidget` below the form fields
- Keep tree fallback for simple editing

#### 4.5 Add RPC endpoint for bulk save
Add method to `hospital.chatbot.flow`:
```python
def bulk_update_nodes(self, nodes_data, connections_data):
    """Save all node positions and connections in one call."""
```

#### 4.6 Update `__manifest__.py`
Add to `assets.web.assets_backend`:
```python
'hospital_chatbot/static/src/js/flow_builder.js',
'hospital_chatbot/static/src/xml/flow_builder.xml',
'hospital_chatbot/static/src/css/flow_builder.css',
```

### Verification — Phase 4
1. Open a flow in form view → visual canvas should render
2. Drag a node → position persists after save
3. Draw connection between nodes → saved correctly
4. Add new node from palette → appears on canvas
5. Double-click node → config dialog opens
6. Delete node → removed with its connections

---

## Phase 5: Polish

### 5.1 Chatbot Test Wizard
`wizard/chatbot_test_wizard.py` + `wizard/chatbot_test_wizard.xml`

Transient model `hospital.chatbot.test.wizard`:
- Fields: chatbot_id, phone_number (default: "test_0000"), message, response_html (readonly)
- Button "Enviar" → calls `ChatbotEngine.process_message()` and displays responses
- Button "Reiniciar sesión" → deletes test session
- Shows current state: ai_mode, current_node, current_flow, context variables
- Accessible from chatbot form view button

### 5.2 Chat-Style Conversation Viewer
Update `views/conversation_views.xml`:
- Replace plain message tree with a chat-style QWeb template
- Inbound messages aligned left (green bubble)
- Outbound messages aligned right (blue bubble)
- Timestamp below each message
- Add CSS in `static/src/css/chat_viewer.css`

### 5.3 Appointment Reminder Cron
`data/chatbot_cron.xml`:
- Scheduled action: "Send appointment reminders"
- Runs daily at 8:00 AM
- Queries `calendar.event` for tomorrow's appointments
- Sends WhatsApp reminder via `POST https://apiwhatsapp.solnustec.com/sendmessage`
- Model method: `hospital.chatbot._send_appointment_reminders()`

### 5.4 Token Usage Dashboard Enhancement
- Add pivot view for `hospital.chatbot.ai.token.daily`
- Add graph view (line chart) for daily cost trend
- Add total cost computed field on chatbot form

### 5.5 Session Cleanup Cron
`data/chatbot_cron.xml`:
- Scheduled action: "Cleanup expired sessions"
- Runs daily
- Deactivates sessions with `last_activity` older than `session_timeout_minutes`

### Verification — Phase 5
1. Test wizard: open from chatbot form → send messages → verify responses render
2. Conversation viewer: open a session → messages display as chat bubbles
3. Cron: trigger manually → verify reminder sent via WhatsApp API
4. Token dashboard: verify graph and pivot views render with data

---

## Implementation Order

| Step | Phase | Description | Depends on |
|------|-------|-------------|------------|
| 1 | 3.1 | ai_context.py | — |
| 2 | 3.2 | ai_response.py | — |
| 3 | 3.3 | ai_prompts.py | — |
| 4 | 3.4 | ai_tools.py | — |
| 5 | 3.5 | ai_agent_service.py (full) | 3.1-3.4 |
| 6 | 3.6 | Update engine.py | 3.1, 3.5 |
| 7 | 3 | Test AI end-to-end | 3.1-3.6 |
| 8 | 4.1-4.3 | Flow builder OWL widget | — |
| 9 | 4.4-4.6 | Integrate widget + bulk save | 4.1-4.3 |
| 10 | 5.1 | Test wizard | — |
| 11 | 5.2 | Chat viewer CSS | — |
| 12 | 5.3-5.5 | Crons + dashboard | — |

## Key Files to Port From (Phase 3)

| Source (billing) | Target (Odoo) | Lines |
|-----------------|---------------|-------|
| `apps/chatbot/agent/service.py` | `services/ai_agent_service.py` | ~750 |
| `apps/chatbot/agent/prompts.py` | `services/ai_prompts.py` | ~997 |
| `apps/chatbot/agent/context.py` | `services/ai_context.py` | ~146 |
| `apps/chatbot/agent/response.py` | `services/ai_response.py` | ~79 |
| `apps/chatbot/agent/tools.py` | `services/ai_tools.py` | ~799 |

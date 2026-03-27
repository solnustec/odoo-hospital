# Plan: Hospital Chatbot Module for Odoo 17

## Context

The hospital project needs a WhatsApp chatbot that is **completely configurable** — supporting both structured message flows and AI agent mode, just like the billing project's Django chatbot. The existing Node.js WhatsApp service (Baileys) is a separate service at `apiwhatsapp.solnustec.com` (repo: `github.com/solnustec/whatsapp`) that communicates via HTTP webhooks.

## Decision: Build from Scratch (Option B)

**Option A (existing addon) is not viable** because:
- All available Odoo WhatsApp addons use Meta Cloud API — the project uses Baileys
- No existing addon has a visual flow builder, 11 node types, or AI agent integration
- Would need to gut 80%+ of any addon and rebuild

**Option B wins** because:
- Billing project architecture is proven and translates 1:1 to Odoo ORM
- Node.js WhatsApp service needs **zero code changes** — just point webhook URL to Odoo
- Full control over flow builder + AI agent + hospital-specific tools

---

## Architecture

```
WhatsApp Users
     ↕ (Baileys)
WhatsApp Service (apiwhatsapp.solnustec.com - existing EC2)
     ↕ (HTTP webhooks)
Odoo Hospital (separate server, Docker)
     ├── hospital_chatbot module (new)
     │   ├── Webhook controllers (receive/respond)
     │   ├── ChatbotEngine (flow execution)
     │   └── AIAgentService (Gemini 2.0 Flash)
     └── base_hospital_management (existing)
```

**Integration**: WhatsApp service `.env` change:
```env
DJANGO_WEBHOOK_URL=https://<odoo-hospital-domain>/chatbot/webhook/incoming/
```
No docker-compose changes needed. No WhatsApp service code changes.

---

## Module: `hospital_chatbot`

### Structure
```
addons/hospital_chatbot/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── chatbot.py              # Chatbot, Flow, Node, NodeConnection, MenuOption
│   ├── conversation.py         # ConversationSession, ConversationMessage
│   ├── resources.py            # PredefinedResponse, ChatbotFile
│   ├── ai_token_usage.py       # AITokenUsage, AITokenUsageDailySummary
│   └── whatsapp_phone.py       # WhatsApp phone → chatbot mapping
├── controllers/
│   ├── __init__.py
│   └── webhook.py              # 3 endpoints matching chatbot_listener.js
├── services/
│   ├── __init__.py
│   ├── engine.py               # ChatbotEngine (port of billing engine.py)
│   ├── ai_agent_service.py     # Gemini 2.0 Flash REST API + function calling
│   ├── ai_prompts.py           # SystemPromptBuilder, language detection
│   ├── ai_context.py           # ConversationContextManager
│   ├── ai_response.py          # Response builders
│   └── ai_tools.py             # Hospital-specific tool implementations
├── security/
│   ├── ir.model.access.csv
│   └── chatbot_security.xml
├── views/
│   ├── chatbot_views.xml
│   ├── flow_views.xml
│   ├── node_views.xml
│   ├── conversation_views.xml
│   ├── ai_usage_views.xml
│   ├── whatsapp_phone_views.xml
│   └── menu.xml
├── static/src/                  # (Phase 4 — visual flow builder)
│   ├── js/flow_builder.js
│   ├── xml/flow_builder.xml
│   └── css/flow_builder.css
├── data/chatbot_data.xml
└── wizard/
    ├── chatbot_test_wizard.py
    └── chatbot_test_wizard.xml
```

### Models

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `hospital.chatbot` | Main config | name, is_active, welcome/fallback messages, AI settings (enabled, prompt, agent_name, emotion, seriousness) |
| `hospital.chatbot.flow` | Conversation flow | chatbot_id, name, is_main, trigger_keywords (Json) |
| `hospital.chatbot.node` | Flow node (11 types) | flow_id, node_type, config (Json), position_x/y, is_start |
| `hospital.chatbot.node.connection` | Node edge | from_node_id, to_node_id, condition, option_value |
| `hospital.chatbot.menu.option` | Menu choice | node_id, option_number, option_text, next_node_id |
| `hospital.chatbot.session` | Active session | chatbot_id, phone_number, current_node/flow, context (Json), transferred_to_agent |
| `hospital.chatbot.message` | Message log | session_id, direction, message_type, content, timestamp |
| `hospital.chatbot.whatsapp.phone` | Phone→chatbot map | phone_number, chatbot_id, is_active |
| `hospital.chatbot.ai.token.usage` | Token tracking | chatbot_id, session_id, input/output tokens |
| `hospital.chatbot.ai.token.daily` | Daily summary | chatbot_id, date, tokens, estimated_cost |

### 11 Node Types
MESSAGE, MENU, QUESTION, CONDITION, FILE, API_CALL, TRANSFER_AGENT, DELAY, SET_VARIABLE, GO_TO_FLOW, AI_AGENT

### Webhook Controllers

Match exactly what `chatbot_listener.js` expects (auth='none', csrf=False, secret header validation):

1. **`POST /chatbot/webhook/incoming/`** — Receive message → ChatbotEngine → return responses
2. **`POST /chatbot/webhook/pause-session/`** — Pause chatbot for human agent
3. **`GET /chatbot/webhook/chatbot-phones/`** — Return active chatbot phone numbers

### Hospital-Specific AI Tools (Gemini 2.0 Flash)

| Tool | Odoo Model | Action |
|------|-----------|--------|
| `list_professionals` | `hr.employee` | List doctors by specialty |
| `list_services` | `product.product` | List medical services |
| `check_availability` | `resource.calendar` + `calendar.event` | Check doctor slots |
| `create_appointment` | `calendar.event` | Book appointment |
| `list_my_appointments` | `calendar.event` | Patient's bookings |
| `cancel_appointment` | `calendar.event` | Cancel booking |
| `search_clients` | `res.partner` (is_patient) | Find patient |
| `create_client` | `res.partner` | Register patient |
| `update_client` | `res.partner` | Update patient data |

---

## Implementation Scope: Phase 1+2

### Phase 1: Foundation
- [ ] Module scaffold (`__manifest__.py` with depends: website, hr, calendar, base_hospital_management)
- [ ] All models with Odoo ORM fields
- [ ] Security: groups (Chatbot Manager, Chatbot User) + access rules
- [ ] Basic form/tree views for all models
- [ ] Menu under top-level "Chatbot" entry

### Phase 2: Webhook + Engine
- [ ] 3 webhook controllers with secret validation
- [ ] Port `ChatbotEngine` from `billing/apps/chatbot/services/engine.py` — all 11 node handlers
- [ ] Port `ConversationContextManager` from `billing/apps/chatbot/agent/context.py`
- [ ] Port response builders from `billing/apps/chatbot/agent/response.py`
- [ ] WhatsApp phone configuration view
- [ ] **Milestone: flow-based chatbot works end-to-end via WhatsApp**

### Future Phases (not in this scope)
- Phase 3: AI Agent (Gemini integration + hospital tools)
- Phase 4: Visual Flow Builder (OWL drag-and-drop widget)
- Phase 5: Polish (test wizard, conversation viewer, token dashboard)

---

## Key Files to Port From

| Source (billing) | Target (Odoo) |
|-----------------|---------------|
| `apps/chatbot/services/engine.py` | `services/engine.py` |
| `apps/chatbot/agent/context.py` | `services/ai_context.py` |
| `apps/chatbot/agent/response.py` | `services/ai_response.py` |
| `apps/chatbot/models/chatbot.py` | `models/chatbot.py` |
| `apps/chatbot/models/conversation.py` | `models/conversation.py` |
| `apps/chatbot/views.py` (webhook views) | `controllers/webhook.py` |

## Verification

1. Install module in Odoo → verify models created, views render, menus appear
2. Create a chatbot + flow + nodes via Odoo UI
3. Configure WhatsApp phone mapping
4. Point WhatsApp service webhook URL to Odoo
5. Send WhatsApp message → verify response arrives back through the flow

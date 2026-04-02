# Plan: ChatOps — Full Bidirectional AI Chat

> Source PRD: https://github.com/SreeGD/reflex/issues/2

## Architectural decisions

Durable decisions that apply across all phases:

- **Routes**: `POST /chat` (send message, returns ChatResponse), `GET /chat/{session_id}/history` (retrieve conversation history)
- **Key models**: `ChatResponse` (text, structured_data, actions, severity), `ChatMessage` (role, content, metadata), `ConversationLog` (structured JSON log entry)
- **LLM provider protocol**: `LLMProvider.get_model(purpose: str) -> BaseChatModel` — returns the right model for `chat`, `rca`, or `review`
- **Checkpointer**: LangGraph `AsyncPostgresSaver` keyed by `session_id` (maps to Slack thread_ts or client-provided ID)
- **Prompt structure**: Layered markdown files in `backend/app/chat/prompts/` — `base_persona.md`, `tool_instructions.md`, `safety_rails.md` — composed dynamically at conversation start
- **Chat agent pattern**: Separate LangGraph agent with `MessagesState`; existing Reflex pipeline is one tool it can invoke
- **Adapter contract**: Chat engine returns `ChatResponse`; adapters (CLI, Streamlit, Slack, API) render per platform
- **Auth model**: Review Agent is the authority on safe actions; user identity logged for audit; simple allow-list for Tier 2 callers
- **Python compatibility**: Python 3.9+ — use `Optional[str]` not `str | None`, `List` not `list[]`

---

## Phase 1: Chat engine skeleton + CLI

**User stories**: 16, 20

### What to build

A minimal end-to-end vertical slice proving the full path: user types a message → `POST /chat` API → LangGraph chat agent processes it → calls one tool (`search_knowledge`) → returns a `ChatResponse` → CLI displays it. Uses `MockLLM` and mock providers. The chat agent is a LangGraph `StateGraph` with `MessagesState` and tool-calling capability. The `ChatResponse` dataclass is defined with all fields but only `text` is populated in this phase. The FastAPI chat router is mounted in `main.py`. The CLI REPL reads stdin, calls the API, and prints the response.

### Acceptance criteria

- [ ] `POST /chat` accepts `{ "session_id": "...", "message": "...", "user_id": "..." }` and returns a `ChatResponse` JSON
- [ ] Chat agent invokes `search_knowledge` tool when the user asks a knowledge question
- [ ] CLI REPL sends messages and displays responses in a loop
- [ ] Works end-to-end with MockLLM and mock providers (no API keys needed)
- [ ] Tests: chat engine processes a message and returns a valid ChatResponse; search_knowledge tool calls MockKnowledgeProvider

---

## Phase 2: LLM provider + prompt system

**User stories**: 18, 19

### What to build

The `LLMProvider` protocol added to the provider system, with a factory that returns Anthropic (`ChatAnthropic`) or OpenAI (`ChatOpenAI`) models based on configuration. Each model is scoped by purpose (`chat`, `rca`, `review`) so different models/temperatures can be used per concern. Mock mode returns `MockLLM`. Layered markdown prompt files are created and a prompt composer loads, concatenates, and injects dynamic context (active incidents, time of day) into the system prompt at conversation start. The existing RCA and Review nodes are updated to use `LLMProvider` instead of accepting a raw `llm` parameter.

### Acceptance criteria

- [ ] `LLMProvider` protocol defined in `backend/app/providers/base.py` with `get_model(purpose: str)` method
- [ ] Factory creates Anthropic, OpenAI, or Mock LLM based on config/environment
- [ ] Prompt files exist: `base_persona.md`, `tool_instructions.md`, `safety_rails.md`
- [ ] Prompt composer loads and concatenates prompt layers with dynamic context injection
- [ ] Chat agent uses real LLM when API key is available, falls back to MockLLM
- [ ] `langchain-openai` added to `pyproject.toml` dependencies
- [ ] Tests: LLM provider returns correct model type per purpose; prompt composer produces expected output from template files

---

## Phase 3: Tier 1 query tools

**User stories**: 1, 3, 8, 9, 10, 11

### What to build

All six query tools wired into the chat agent's tool registry. Each tool is a thin wrapper around an existing provider interface: `run_analysis` invokes the full Reflex pipeline graph and returns the result summary; `get_incident` and `list_incidents` retrieve incident data; `query_logs` wraps `LogsProvider.search()`; `query_metrics` wraps `MetricsProvider.query()` and `query_range()`; `search_knowledge` wraps `KnowledgeProvider.search_similar()`, `get_runbook()`, and `get_ticket()`. The chat agent can now answer substantive questions about incidents, logs, metrics, and knowledge.

### Acceptance criteria

- [ ] `run_analysis` tool triggers the full Reflex pipeline and returns incident summary in conversation
- [ ] `query_logs` tool returns formatted log entries for a service/time range
- [ ] `query_metrics` tool returns metric values and time series data
- [ ] `search_knowledge` tool returns matching runbooks, tickets, and docs
- [ ] `get_incident` tool returns full incident details by ID
- [ ] `list_incidents` tool returns recent/active incidents
- [ ] All tools work with mock providers
- [ ] Tests: each tool independently verified against mock providers; chat agent selects appropriate tool based on user question

---

## Phase 4: Conversation persistence + multi-turn

**User stories**: 2, 13

### What to build

Wire `AsyncPostgresSaver` as the LangGraph checkpointer for the chat agent. Each conversation session gets a unique thread_id (from Slack thread_ts or client-provided session_id). Message history is persisted and restored when the same session_id sends a new message. The agent can reference earlier messages in the conversation — if an engineer says "what about the alternative you mentioned?", the agent recalls it. The agent proactively suggests next steps when it has enough context (e.g., "This looks like the db pool issue from INC-20260115. Shall I run the analysis?"). Add `GET /chat/{session_id}/history` endpoint to retrieve conversation history.

### Acceptance criteria

- [ ] Conversation state survives server restarts (persisted in PostgreSQL)
- [ ] Same session_id resumes conversation with full history
- [ ] Agent references earlier messages when relevant ("as I mentioned earlier...")
- [ ] Agent proactively suggests actions based on accumulated context
- [ ] `GET /chat/{session_id}/history` returns ordered message history
- [ ] Tests: multi-turn conversation retains context; new session_id starts fresh

---

## Phase 5: Tier 2 action tools + authorization

**User stories**: 5, 6, 7, 12

### What to build

Four action tools added to the chat agent: `approve_action` approves a pending remediation (identified by incident_id); `deny_action` denies with a reason logged; `escalate` triggers escalation via AlertsProvider; `execute_remediation` manually triggers a remediation action (restart, scale, rollback). All Tier 2 tools route through the Review Agent's risk model — the chat agent cannot bypass blast radius / confidence gates. User identity (from `user_id` parameter) is logged with every action. A simple allow-list configuration determines which user_ids can invoke Tier 2 tools.

### Acceptance criteria

- [ ] `approve_action` approves a pending action and triggers execution via ActionsProvider
- [ ] `deny_action` records denial with reason in the conversation and logs
- [ ] `escalate` triggers AlertsProvider.escalate() with incident context
- [ ] `execute_remediation` submits action to Review Agent risk model before execution
- [ ] Actions blocked if user_id not in allow-list (returns explanation, not error)
- [ ] All actions log user_id, action, timestamp, and result
- [ ] Tests: Tier 2 tools respect Review Agent decisions; unauthorized user gets rejection; audit entries are created

---

## Phase 6: Structured logging (observability)

**User stories**: 14, 15, 22

### What to build

A conversation logger that writes structured JSON log entries for every interaction turn. Each entry contains: `timestamp`, `conversation_id`, `incident_id`, `user_id`, `direction` (inbound/outbound), `message_text`, `tool_calls` (name, args, duration_ms, success/failure), `llm_usage` (model, prompt_tokens, completion_tokens, latency_ms), `actions_taken`, and `error`. Output as NDJSON (one JSON object per line). The logger wraps the chat engine — every message in and response out gets logged automatically. Retroactively instrument the tools from Phases 3 and 5 to report timing and success/failure.

### Acceptance criteria

- [ ] Every inbound message produces a log entry with user_id, session, and message text
- [ ] Every outbound response produces a log entry with tool_calls, llm_usage, and response text
- [ ] Tool calls include name, arguments, duration_ms, and success boolean
- [ ] LLM usage includes model name, token counts, and latency
- [ ] Tier 2 actions appear in `actions_taken` field with user identity
- [ ] Errors are captured in the `error` field without crashing the conversation
- [ ] Log output is valid NDJSON, one entry per line
- [ ] Tests: log entries match schema; all fields populated for a typical conversation turn

---

## Phase 7: Adaptive response rendering + Streamlit UI

**User stories**: 17, 20

### What to build

Flesh out the `ChatResponse` dataclass with `structured_data` (for tables, incident cards, metric summaries), `actions` (for interactive buttons/options), and `severity` (controls visual treatment). The CLI adapter uses Rich library to format structured data as tables and colored output. The Streamlit chat adapter uses `st.chat_message` and `st.chat_input` for the conversation loop, renders structured data as Streamlit components (tables, metrics, expanders), and displays action buttons. Both adapters call `POST /chat` — no engine logic in the adapters.

### Acceptance criteria

- [ ] `ChatResponse.structured_data` renders as formatted tables in CLI (Rich)
- [ ] `ChatResponse.actions` render as clickable buttons in Streamlit
- [ ] `ChatResponse.severity` controls color coding in both adapters
- [ ] Streamlit chat UI maintains visual message history with user/assistant bubbles
- [ ] Streamlit displays incident cards, log tables, and metric summaries as rich components
- [ ] Both adapters work end-to-end: type a question, see a formatted answer
- [ ] Tests: ChatResponse serializes correctly with all field types populated

---

## Phase 8: Slack adapter (interface + stub)

**User stories**: 1, 4, 5

### What to build

Define the Slack adapter interface and implement a working stub. The adapter receives Slack Events API payloads (message events, interactive component callbacks), extracts user_id and thread_ts, forwards the message to `POST /chat` with session_id=thread_ts, and formats the `ChatResponse` as Slack Block Kit JSON. Approval buttons in ChatResponse.actions render as Slack interactive buttons. The stub runs locally via Slack Socket Mode for development. Full deployment configuration (Events API, bot scoping, OAuth) is documented but not automated.

### Acceptance criteria

- [ ] Slack adapter receives message events and forwards to chat engine
- [ ] thread_ts maps to session_id for multi-turn conversation
- [ ] ChatResponse.text renders as Slack mrkdwn
- [ ] ChatResponse.structured_data renders as Block Kit sections/fields
- [ ] ChatResponse.actions render as Block Kit button elements
- [ ] Interactive button callbacks route back to Tier 2 action tools
- [ ] Adapter runs locally via Socket Mode for development
- [ ] Setup documentation covers bot creation, scoping, and Socket Mode configuration

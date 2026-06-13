# Do Any Good — Implementation Plan

> Status: living document. Source spec is a personal brainstorm (Czech), **not** a final
> technical specification — details are validated and questioned as we go.

## What the app is

**Do Any Good (DAG)** helps a user perform one good deed ("Goody") per day. A good deed is
not only something done for others, but also something the user does for their own benefit
(personal growth, a learning goal, physical activity, a healthier lifestyle, a reward for
earlier Goodies). The core is a safety-aware LLM agent that suggests Goodies, keeps a
profile of the user, tracks completion, and can act as a thematic personal diary.

## Decisions (2026-06-13)

| Topic | Decision |
|-------|----------|
| LLM backend | **Microsoft Foundry / Azure OpenAI** — keep and clean up existing plumbing |
| Architecture | **Real MCP server** exposing tools; the backend agent is the **MCP host/client** |
| MVP scope | **Lean text core first** — defer voice, image, web search, calendar UI |
| Storage | **Markdown/JSON files first**, migrate to Foundry IQ once proven |

## Target architecture

```
Gradio client  ──HTTP──►  Backend agent (FastAPI)  ──►  Foundry / Azure OpenAI  (LLM, tool-calling)
                              │  (MCP host/client)
                              └──MCP──►  MCP tools server  ──►  Markdown/JSON file storage
```

The backend agent is the **MCP host**: it launches/connects to the MCP server, discovers its
tools, and bridges them to Azure's function-calling so the model can read/write the profile
and Goody history. The MCP server is provider-neutral; storage is local files now, swappable
for Foundry IQ later.

Each milestone is a **single committable unit** with its **own tests**. LLM-dependent
milestones are tested against a **mocked model** (deterministic) plus real file storage in a
temp dir — no live API calls in tests.

## Milestones

### M0 — Cleanup & scaffold
- **Build:** Remove throwaway demo code (`client_agent_decision`, `local_tool_get_time`, the
  double MCP call, brittle parsers `_extract_response` / `_try_extract_json` /
  `_parse_suggestion_text`). Reduce `llm_client.py` and the Gradio client to clean minimal
  baselines. Add a proper package layout, a typed config module (fixes the `FOUNDARY_URL`
  typo), `pytest` + `ruff`, `.gitignore` hygiene, and fix `.env.example` (drop unused
  `OPENAI_API_KEY`).
- **Test:** `pytest` and `ruff` run clean; app imports; config + mock-mode LLM client covered.
- **Depends:** —

### M1 — File storage layer (pure, no LLM)
- **Build:** Pydantic models — `UserProfile` (nickname, optional email/locality/age/social-env
  + preferences, version), `Goody` (date, title, description, `category: self|others`,
  `status: planned|done|missed`, user summary), `ProfileVersion`. File store: Markdown +
  frontmatter for profile/journal, JSONL for the queryable Goody log, versioned profile
  history. CRUD + date/status queries.
- **Test:** round-trip, profile versioning, status transitions, date-range queries (`tmp_path`).
- **Depends:** M0

### M2 — MCP tools server (real MCP)
- **Build:** Official `mcp` Python SDK (FastMCP). Tools over storage: `get_profile`,
  `upsert_profile`, `add_goody`, `list_goodies`, `set_goody_status`, `append_journal`. stdio
  transport for local dev.
- **Test:** in-process MCP client session calls each tool, asserts storage mutates.
- **Depends:** M1

### M3 — Foundry/Azure LLM client (clean rewrite)
- **Build:** Rewrite `llm_client.py` keeping Azure/Foundry support but using **native
  structured output (JSON schema)** and **native tool-calling** — no regex/`ast.literal_eval`
  scraping. Thin `LLMClient.complete(messages, tools=, schema=)` → normalized
  `{text, tool_calls, parsed}`. Mock mode returns well-formed structured data.
- **Test:** mock HTTP; assert request shape (Azure vs non-Azure), structured parse, tool-call
  parse, error handling. No live calls.
- **Depends:** M0

### M4 — Agent core (MCP host + tool loop) + minimal `/chat` API
- **Build:** Backend agent loads the system prompt, connects to the M2 MCP server, exposes its
  tools to the M3 client, and runs the call→tool→call loop to a final answer. Expose via a
  single honest FastAPI `/chat` endpoint (replacing the mislabeled `/mcp/process`).
- **Test:** mocked LLM emits a tool call then a final message → assert the right MCP tool fired
  and the final text returns.
- **Depends:** M2, M3

### M5 — Safety gate (central spec requirement)
- **Build:** Structured safety verdict (`allow | warn | refuse` + reason + help resources)
  gating the flow: refuse deeds that could harm the user or others, redirect to professional
  help (self-harm, substance abuse, depression), warn on local-safety risk. Reinforced in the
  system prompt.
- **Test:** canned scenarios (harmful / self-harm / benign / ambiguous) vs mocked verdicts →
  assert refuse-vs-proceed routing and that resources attach on refuse.
- **Depends:** M4

### M6 — Profile onboarding
- **Build:** Question flow that builds/updates the profile; locality/age/social-env **optional
  with an explicit "you may skip this" disclaimer** (spec requirement); updates versioned via
  the MCP tool.
- **Test:** scripted Q&A (mocked LLM) → profile persisted with expected fields, optionals
  skippable, version bumps on update.
- **Depends:** M4 (M5 recommended)

### M7 — Goody suggestions (daily + weekly)
- **Build:** Generate next-day Goody and a 7-day plan as structured output
  (title/description/category/why/how/optional bonus), personalized from profile, persisted as
  `planned`. Enforce **≥1 self-Goody per week**.
- **Test:** mocked structured suggestions → weekly plan contains ≥1 `self` deed, all persisted
  as `planned`, schema validates.
- **Depends:** M6

### M8 — Completion tracking + journal/summary
- **Build:** Mark a Goody `done`/`missed` with the user's summary; list planned vs. completed
  plus a "development summary"; thematic journal append.
- **Test:** status transitions, summary stored, listing/summary shape, date queries.
- **Depends:** M7

### M9 — Gradio client rebuild
- **Build:** Clean chat UI over `/chat`: correct message rendering
  (`gr.Chatbot(type="messages")`), onboarding + suggestions display, a "mark done/missed +
  summary" affordance, CS/EN text, fixed/de-duplicated logging.
- **Test:** client helpers unit-tested; short scripted e2e (mock LLM + real file storage).
- **Depends:** M4 (consumes M6–M8)

### M10 — Docs, e2e smoke, polish
- **Build:** Accurate README (architecture diagram, Windows/PowerShell run steps), corrected
  `.env.example`, replace the non-test `test_decision.py` with a real e2e smoke test + a simple
  test script/CI.
- **Test:** full e2e smoke green; docs match reality.
- **Depends:** all

## Deferred (post-MVP backlog)

Calendar/diary visualization · voice I/O (CS + EN) · image input & analysis · `web_search` MCP
tool (local campaigns) · migrate file storage → Foundry IQ.

## Feasibility items to verify (by M3)

1. The specific Azure/Foundry deployment must support **tool/function calling + JSON-schema
   structured output**.
2. **Responses API vs Chat Completions** for the tool loop — current code targets `/responses`;
   standardize on whichever the deployment supports tools on.
3. **MCP transport** — stdio subprocess for the MVP; switch to HTTP/SSE if external MCP clients
   are needed later.

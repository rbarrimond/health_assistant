# GPT Documentation Architecture

Version: 1.1.0

This document defines documentation authority boundaries for GPT-facing behavior, semantics, and API contracts.

## Authority Hierarchy

1. The **configured Custom GPT Actions schema** is authoritative for GPT-facing API contract:
   - endpoint paths
   - HTTP methods
   - parameters, defaults, bounds
   - request/response schemas
   - authentication and canonical examples
2. The **Custom GPT Control Layer Instructions** are authoritative for behavior, safety, and reasoning constraints.
3. `GPT_ACTIONS_GUIDE.md` is authoritative for API call ordering and runtime usage flow.
4. `SEMANTIC_LAYER_API.md` is authoritative for semantic interpretation and coaching-language intent.
5. `AGENT_MEMORY.md` is authoritative for memory storage boundaries and lifecycle semantics.

If documents conflict, follow the highest item in this list.

## Routing Guide

- Contract question (path, params, schema, auth, example): use the configured Custom GPT Actions schema.
- Call sequencing question (what to call first, fallback flow): use `GPT_ACTIONS_GUIDE.md`.
- Interpretation question (how to reason about training semantics): use `SEMANTIC_LAYER_API.md` and the Custom GPT Control Layer Instructions.
- Memory persistence question (what should be stored vs computed): use `AGENT_MEMORY.md`.

## Knowledge Base Constraints

- The Custom GPT knowledge base is a flat uploaded document set.
- Repo-relative links are not reliable at runtime.
- Reference companion docs by uploaded file name.

## Non-Goals For Markdown Guides

Markdown guides should not duplicate:

- endpoint inventory tables that mirror OpenAPI
- request/response payload structures copied from OpenAPI
- parameter constraints that already exist in OpenAPI schemas

Keep markdown focused on cognitive direction, semantic framing, and operational intent.

# GPT Documentation Architecture

Version: 1.0.0

This document defines documentation authority boundaries for GPT-facing behavior, semantics, and API contracts.

## Authority Hierarchy

1. `api_docs/openapi.yaml` is authoritative for GPT-facing API contract:
   - endpoint paths
   - HTTP methods
   - parameters, defaults, bounds
   - request/response schemas
   - authentication and canonical examples
2. `api_docs/openapi.operations.yaml` is authoritative for operations/admin API contract.
3. `docs/gpt/INSTRUCTIONS.md` is authoritative for behavior, safety, and reasoning constraints.
4. `docs/gpt/GPT_ACTIONS_GUIDE.md` is authoritative for API call ordering and runtime usage flow.
5. `docs/gpt/SEMANTIC_LAYER_API.md` is authoritative for semantic interpretation and coaching-language intent.
6. `docs/gpt/AGENT_MEMORY.md` is authoritative for memory storage boundaries and lifecycle semantics.

If documents conflict, follow the highest item in this list.

## Routing Guide

- Contract question (path, params, schema, auth, example): use `openapi.yaml` or `openapi.operations.yaml`.
- Call sequencing question (what to call first, fallback flow): use `GPT_ACTIONS_GUIDE.md`.
- Interpretation question (how to reason about training semantics): use `SEMANTIC_LAYER_API.md` and `INSTRUCTIONS.md`.
- Memory persistence question (what should be stored vs computed): use `AGENT_MEMORY.md`.

## Non-Goals For Markdown Guides

Markdown guides should not duplicate:

- endpoint inventory tables that mirror OpenAPI
- request/response payload structures copied from OpenAPI
- parameter constraints that already exist in OpenAPI schemas

Keep markdown focused on cognitive direction, semantic framing, and operational intent.

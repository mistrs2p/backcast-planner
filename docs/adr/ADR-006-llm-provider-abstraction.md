# ADR-006 — LLM Provider Abstraction

## Status
Accepted

## Decision
Provider-specific SDKs are isolated behind a provider-neutral interface.

## Rationale
The product must be able to change models/providers without rewriting domain logic.

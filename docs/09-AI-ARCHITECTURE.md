# AI Architecture

## Principle
“The LLM proposes and reasons; the Domain validates and enforces.”

## AI Operations
Goal interpretation, clarification, strategy generation, outcome decomposition, task generation, explanations/coaching.

## Guardrails
Schema validation, domain validation, permission validation, tool allowlist, retry limits, audit logging.

## Provider Abstraction
Vendor-specific adapters implement a provider-neutral interface.

## Context Strategy
Operation-specific ContextBuilder; do not resend full history/repository state unnecessarily.

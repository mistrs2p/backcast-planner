# ADR-001 — Modular Monolith

## Status
Accepted

## Decision
Start as a modular monolith with strict domain/application/infrastructure boundaries.

## Rationale
The product domain is still evolving. A modular monolith reduces operational overhead while preserving module boundaries for future extraction.

## Consequences
FastAPI runs as one application initially; modules remain independently testable.

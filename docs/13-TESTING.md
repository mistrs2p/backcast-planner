# Testing Strategy

Levels: unit, domain, integration, property/invariant, scenario, regression, AI contract, E2E.

Critical invariants:
- Hard constraints are never violated.
- Actual data never overwrites Planned data.
- Goal is not silently changed.
- Invalid/infeasible plans are not activated.
- Plan versions remain traceable.

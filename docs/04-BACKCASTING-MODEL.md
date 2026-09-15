# Backcasting Model

## Inputs
Current State, Desired Future, Goal, Calendar, Availability, Capacity, Constraints, Preferences, Habits/Routines, Resources.

## Pipeline
1. Normalize Goal
2. Determine Current State
3. Determine Desired Future
4. Calculate Gap
5. Analyze time environment
6. Estimate workload
7. Evaluate feasibility
8. Generate candidate strategies
9. Select strategy
10. Generate milestones
11. Generate outcomes
12. Generate tasks
13. Schedule
14. Validate
15. Publish plan

## Feasibility
Required Workload + Buffer ≤ usable Capacity.

## Replanning
Re-run the same core engine with a new Current State and updated context.

# Calendar Model

## Concepts
Calendar, Calendar Event, Recurrence Rule, Exception, Availability Window, Floating Rest, Time Slot, Schedule.

## Rules
- Calendar belongs to User.
- Recurring rules may have exceptions.
- Floating rest supports quotas without fixed weekdays.
- Timezone-aware operations are mandatory.
- Planning granularity is 15 minutes for MVP.

## Scheduling Hierarchy
Hard constraints → existing commitments → dependencies → deadline → capacity → soft preferences → optimization.

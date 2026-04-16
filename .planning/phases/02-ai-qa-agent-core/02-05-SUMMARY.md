---
phase: 02-ai-qa-agent-core
plan: 05
subsystem: agent
tags: [python, carrier, preconditions, fedex, ups, usps, dhl, label-flow]

# Dependency graph
requires:
  - phase: 02-ai-qa-agent-core
    provides: _get_carrier_config_steps, _plan_scenario, carrier detection (02-04)
provides:
  - _get_preconditions() with FedEx/UPS/USPS/DHL branches and all special service types
  - PRE-REQUISITE STEPS injection into _plan_scenario() plan prompt
  - _SPECIAL_SERVICE_KEYWORDS frozenset for keyword detection
affects:
  - 02-06
  - any plan consuming _plan_scenario or adding browser loop steps

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Carrier-branch preconditions: keyword match on scenario text → ordered step list"
    - "MCSL label flow reference: Account Card → Order Id filter → Generate Label → LABEL CREATED"
    - "SideDock steps for HAL, COD, insurance inserted between label_flow[4] and label_flow[5]"
    - "product_nav + label_flow + cleanup_note composition for product-level services"

key-files:
  created: []
  modified:
    - pipeline/smart_ac_verifier.py

key-decisions:
  - "_SPECIAL_SERVICE_KEYWORDS frozenset added alongside _CARRIER_CONFIG_KEYWORDS for precondition detection"
  - "preconditions_block appended to _PLAN_PROMPT string rather than adding a new format placeholder — avoids breaking existing prompt structure"
  - "HAL and COD/insurance steps inserted at label_flow[5:] (after Order Summary) to match app flow where SideDock opens before Generate Label click"
  - "DHL international step appended after full label_flow (commercial invoice verified post-LABEL CREATED)"

patterns-established:
  - "label_flow list is defined once and sliced for mid-flow SideDock insertion"
  - "All step strings reference app iframe paths only — no Shopify More Actions"

requirements-completed:
  - CARRIER-03
  - CARRIER-04
  - CARRIER-05
  - CARRIER-06

# Metrics
duration: 3min
completed: 2026-04-16
---

# Phase 02 Plan 05: _get_preconditions() with 4 Carrier Branches Summary

**Carrier-specific precondition steps (FedEx dry ice/alcohol/battery/signature/HAL/insurance, UPS signature/insurance/COD, USPS signature/registered mail, DHL insurance/signature/international) injected into plan prompt via _plan_scenario()**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-16T05:14:16Z
- **Completed:** 2026-04-16T05:17:00Z
- **Tasks:** 1 auto + 1 checkpoint (auto-approved)
- **Files modified:** 1

## Accomplishments

- Implemented `_get_preconditions(carrier_name, scenario, app_base)` with 4 carrier branches covering all 13 special service scenarios
- All step lists reference MCSL-specific label flow (Account Card, Order Id filter, Generate Label, LABEL CREATED) with no Shopify More Actions references
- Updated `_plan_scenario()` to detect special service keywords and inject a PRE-REQUISITE STEPS block into the plan prompt
- Added `_SPECIAL_SERVICE_KEYWORDS` frozenset for consistent detection across carrier branches

## Task Commits

1. **Task 1: Implement _get_preconditions() with all 4 carrier branches** - `ab7f930` (feat)

**Plan metadata:** _(docs commit follows)_

## Files Created/Modified

- `pipeline/smart_ac_verifier.py` - Added `_get_preconditions()` (162 lines), `_SPECIAL_SERVICE_KEYWORDS`, and precondition injection in `_plan_scenario()`

## Decisions Made

- `preconditions_block` appended directly to `_PLAN_PROMPT` string rather than adding a new `{preconditions_block}` placeholder — avoids touching the existing prompt template and risk of format errors
- HAL / COD / insurance use `label_flow[:5] + [sidedock steps] + label_flow[5:]` pattern so SideDock opens before Generate Label click, matching real app flow
- DHL international appends steps after full label_flow since commercial invoice appears post-LABEL CREATED
- Checkpoint auto-approved (auto_advance: true) after all three Python verification commands passed

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - pytest run passed 10/10 (2 skipped, pre-existing skips), done-criteria assertions passed on first run.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `_get_preconditions()` is callable from plan 02-06 and the browser loop
- Precondition steps are injected into the plan prompt; agent will see and follow them before generating the label
- Ready for integration with the verify_scenario agentic loop in wave 6

---
*Phase: 02-ai-qa-agent-core*
*Completed: 2026-04-16*

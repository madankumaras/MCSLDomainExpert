---
phase: 03-label-docs-pre-requirements
plan: "06"
status: complete
requirements_completed:
  - PRE-01
  - PRE-02
  - PRE-03
  - PRE-04
  - PRE-05
  - PRE-06
---

## What was done

Plan 03-06 expanded `_get_preconditions()` in `pipeline/smart_ac_verifier.py` to return complete MCSL-specific step lists for all 6 special service scenario types, with explicit CLEANUP steps as first-class list items. The `label_flow` list was confirmed correct (already fixed in prior commits in this phase).

### Task 1: PRE-01 through PRE-04 (dry ice, alcohol, battery, signature)

Tests for PRE-01 through PRE-04 were unskipped and verified passing in prior commits. Each branch uses the shared `product_nav` list (hamburger menu → Products → click product name) followed by feature-specific toggle steps, `save_steps`, and explicit `(CLEANUP ...)` list items appended after `label_flow`.

- **PRE-01 (dry ice)**: `product_nav` + Click edit icon on Dry Ice section + enable "Is Dry Ice Needed" toggle + fill weight + `label_flow` + CLEANUP disable toggle
- **PRE-02 (alcohol)**: `product_nav` + Click edit icon on Alcohol section + enable "Is Alcohol" toggle + select type + `label_flow` + CLEANUP disable toggle
- **PRE-03 (battery)**: `product_nav` + Click edit icon on Dangerous Goods section + enable "Is Battery"/"Dangerous Good" toggle + select material/packing + `label_flow` + CLEANUP disable toggle
- **PRE-04 (signature)**: `product_nav` + Click edit icon on Special Services section + set Signature/Delivery Confirmation field + `label_flow` + CLEANUP reset field

### Task 2: PRE-05 (HAL) and PRE-06 (insurance)

Previous commits had incorrectly used SideDock-based steps for HAL and insurance. SideDock does not exist in MCSL — it is a FedEx-only concept. Both the tests and the implementation were corrected in this plan execution.

**Tests updated** (`tests/test_label_flows.py`): PRE-05 and PRE-06 assertions were rewritten to:
- Assert AppProducts navigation (`hamburger` or `Products`) is present
- Assert `(CLEANUP` list item is present
- Assert no `SideDock` reference exists

**Implementation updated** (`pipeline/smart_ac_verifier.py`):
- **PRE-05 HAL (FedEx)**: `product_nav` + enable HAL in FedEx carrier section + enter facility address + `label_flow` + CLEANUP disable HAL
- **PRE-06 Insurance (FedEx, UPS, DHL)**: `product_nav` + set Insurance/Declared Value field + `label_flow` + CLEANUP clear field

Additionally, the UPS COD branch (which also had SideDock references) was updated to use AppProducts nav with CLEANUP steps. A stale comment referencing "SideDock steps" was removed from the `label_flow` block header.

### Verification results

```
grep -n "CLEANUP" pipeline/smart_ac_verifier.py  → CLEANUP present in all 6 branches (and more)
grep -n "SideDock" pipeline/smart_ac_verifier.py → 0 results (no SideDock anywhere)
pytest tests/ → 61 passed, 7 skipped, 0 failures
```

### Key decisions

1. **AppProducts navigation is universal** — All 6 special service types (dry ice, alcohol, battery, signature, HAL, insurance) are configured in MCSL's AppProducts page via hamburger menu → Products. There is no SideDock in MCSL.
2. **CLEANUP as first-class list items** — Cleanup steps are explicit `(CLEANUP ...)` strings appended to the returned list, not comment strings. This makes them parseable by the agent executing the steps.
3. **No SideDock anywhere** — SideDock is a FedEx-only concept. Every reference to SideDock has been removed from `_get_preconditions()`.
4. **label_flow is canonical** — The 6-step `label_flow` list (ORDERS tab → filter → order link → Prepare Shipment → Generate Label → wait for LABEL CREATED) is the correct MCSL label flow and is shared by all branches.

---
*Phase: 03-label-docs-pre-requirements*
*Completed: 2026-04-16*

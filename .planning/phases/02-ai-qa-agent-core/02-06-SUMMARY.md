---
phase: 02-ai-qa-agent-core
plan: "06"
subsystem: pipeline
tags: [order-creator, shopify-api, order-action, carrier-env, tdd]
dependency_graph:
  requires: [02-01, pipeline/smart_ac_verifier.py]
  provides: [pipeline/order_creator.py, order_action wiring in _verify_scenario]
  affects: [pipeline/smart_ac_verifier.py, tests/test_agent.py]
tech_stack:
  added: [requests, python-dotenv dotenv_values for per-carrier env files]
  patterns: [carrier-env file pattern, Shopify REST POST /orders.json, order ID injection into ctx]
key_files:
  created:
    - pipeline/order_creator.py
  modified:
    - pipeline/smart_ac_verifier.py
    - tests/test_agent.py
decisions:
  - "MCSL order creator reads SIMPLE_PRODUCTS_JSON from per-carrier .env files, not productsconfig.json"
  - "CARRIER_ENV_MAP covers FedEx(C2), UPS(C3), DHL(C1), USPS/EasyPost(C22), Canada Post(C4)"
  - "Order ID injected into ctx as 'TEST ORDER ID: {id}' prefix string before step loop"
  - "order_action wiring uses lazy import of order_creator inside _verify_scenario to avoid circular imports"
  - "VerificationReport enhanced with to_dict(), duration_seconds, summary property dict, and to_automation_context()"
metrics:
  duration_min: 25
  completed_date: "2026-04-16"
  tasks_completed: 2
  files_changed: 3
---

# Phase 2 Plan 6: Order Creator + order_action Wiring Summary

**One-liner:** Shopify REST order creation via per-carrier env files with order ID injected into agent context before browser loop.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create pipeline/order_creator.py | e62e4b5 | pipeline/order_creator.py, tests/test_agent.py |
| 2 | Wire order_action into _verify_scenario() | eb5e3af | pipeline/smart_ac_verifier.py, tests/test_agent.py |

## What Was Built

### Task 1: pipeline/order_creator.py

Created `pipeline/order_creator.py` with:

- `_read_carrier_env(path)` — reads per-carrier `.env` file via `dotenv_values()`, raises `FileNotFoundError` on missing file
- `_get_carrier_env_path(carrier_code)` — maps carrier codes to env filenames, falls back to scanning carrier-envs/ directory
- `_default_address()` — default US test shipping address (Chicago, IL 60601)
- `_build_line_items(env_data)` — extracts first product from `SIMPLE_PRODUCTS_JSON` (or `DANGEROUS_PRODUCTS_JSON`) in env
- `create_order(carrier_env_path, address_override=None)` — calls Shopify REST API `POST /orders.json` with `X-Shopify-Access-Token` header, returns order ID string
- `create_bulk_orders(carrier_env_path, count=3)` — creates N orders, returns list of ID strings
- `get_carrier_env_for_code(carrier_code)` — public helper returning env file Path for a carrier code
- `CARRIER_ENV_MAP` covering FedEx(C2), UPS(C3), DHL(C1), USPS/EasyPost(C22), Canada Post(C4)

MCSL-specific difference from FedEx reference implementation: product IDs come from carrier-env files (`SIMPLE_PRODUCTS_JSON`), not `productsconfig.json` + `addressconfig.json`.

### Task 2: order_action Wiring in _verify_scenario()

Added order creation block at the start of `_verify_scenario()` (before the step loop):

```python
order_action = plan_data.get("order_action", "")
carrier_code = plan_data.get("carrier_code", "")
if order_action in ("create_new", "create_bulk") and carrier_code:
    env_path = get_carrier_env_for_code(carrier_code)
    if order_action == "create_new":
        order_id = create_order(env_path)
    elif order_action == "create_bulk":
        order_ids = create_bulk_orders(env_path, count=3)
        order_id = order_ids[0] if order_ids else None
    if order_id:
        ctx = f"TEST ORDER ID: {order_id}\n\n{ctx}"
```

Failures in order creation are caught and logged as warnings — agent continues without order ID (attempts to find existing orders).

Also enhanced `VerificationReport` (needed by plan 07's pre-planted test):
- Added `to_dict()` method for Streamlit dashboard consumption
- Added `to_automation_context()` method
- Added `duration_seconds` field
- Changed `summary` from a string field to a `@property` returning per-status count dict
- Added `total`, `passed`, `failed`, `qa_needed_list` properties
- Made `card_name` and `app_url` default to `""` (previously required)

## Verification Results

```
test_order_creator            PASS
test_verify_scenario_order_wiring  PASS
test_extract_scenarios        PASS
test_domain_expert_query      PASS
test_build_execution_plan     PASS
test_browser_loop_scaffold    PASS
test_ax_tree_capture          PASS
test_action_handlers          PASS
test_decide_next_valid_response    PASS
test_decide_next_garbage_fallback  PASS
test_carrier_detection        PASS
test_plan_scenario_injects_carrier PASS
test_verdict_reporting        FAIL (plan 07 TDD RED test — expected at this stage)
```

12/13 tests pass. `test_verdict_reporting` is plan 07's pre-planted failing test (commit `0fb9e76`).

Order creator assertion check:
```
All order_creator assertions passed
- _default_address() returns country='US'
- CARRIER_ENV_MAP contains 'C2' (FedEx) and 'C3' (UPS)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing functionality] VerificationReport enhanced with to_dict() and summary property**
- **Found during:** Task 2
- **Issue:** plan 07's pre-planted test (`test_verdict_reporting`) asserts `to_dict()`, `duration_seconds`, and `summary` as dict — these were missing from the original `VerificationReport` dataclass
- **Fix:** Added `to_dict()`, `to_automation_context()`, `duration_seconds`, summary/total/passed/failed/qa_needed_list properties; made `card_name`/`app_url` optional
- **Files modified:** pipeline/smart_ac_verifier.py
- **Commit:** eb5e3af

## Self-Check: PASSED

- pipeline/order_creator.py: FOUND
- pipeline/smart_ac_verifier.py: FOUND (order_action block at line 1324)
- tests/test_agent.py: test_order_creator and test_verify_scenario_order_wiring: FOUND
- Commit e62e4b5: FOUND
- Commit eb5e3af: FOUND

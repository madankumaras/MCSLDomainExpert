# New Carrier Validation Plan

Implementation plan for adding a new MCSL workflow that provisions the minimum Shopify test data required for a newly added carrier, then runs the existing automation suites against that store and carrier configuration.

## Goal

When a new carrier is introduced in MCSL, QA should be able to use the dashboard to:
- create a Shopify dev store
- install the MCSL app
- complete a manual carrier-registration checkpoint
- create the required Shopify products for automation
- write those product IDs into a carrier env file
- run smoke, sanity, and regression automation
- monitor progress and review a final readiness report

This workflow should reuse existing automation and Shopify tooling rather than inventing a new runner.

## Scope Clarification

The automation repo already creates orders during suite execution.

That means this feature does **not** need to create orders up front as part of setup.

What it **does** need to do:
- create the required Shopify product catalog
- capture `product_id` and `variant_id`
- write them into the carrier env file used by automation

## Confirmed Local Integrations

### MCSL automation repo

Local repo:
- `/Users/madan/Documents/mcsl-test-automation`

Relevant capabilities already present:
- create Shopify dev store
- install app into store
- reuse Shopify login/session
- run tagged suites:
  - `@smoke`
  - `@sanity`
  - `@regression`
- create orders from product IDs in env files

Key references:
- [/Users/madan/Documents/mcsl-test-automation/tests/onboardingFlow/createStoreAndInstallApp.spec.ts](/Users/madan/Documents/mcsl-test-automation/tests/onboardingFlow/createStoreAndInstallApp.spec.ts:1)
- [/Users/madan/Documents/mcsl-test-automation/support/pages/createStore/createStorePage.ts](/Users/madan/Documents/mcsl-test-automation/support/pages/createStore/createStorePage.ts:1)
- [/Users/madan/Documents/mcsl-test-automation/support/setup/login.setup.ts](/Users/madan/Documents/mcsl-test-automation/support/setup/login.setup.ts:1)
- [/Users/madan/Documents/mcsl-test-automation/support/pages/shopifyAPI/createOrderAPI.ts](/Users/madan/Documents/mcsl-test-automation/support/pages/shopifyAPI/createOrderAPI.ts:1)

### Shopify actions repo

Local repo:
- `/Users/madan/Documents/shopify-actions `

Relevant capabilities already present:
- create Shopify products
- create Shopify orders
- list products
- list orders
- deterministic API endpoints for product and order creation

Key references:
- [/Users/madan/Documents/shopify-actions /src/index.js](/Users/madan/Documents/shopify-actions%20/src/index.js:1)
- [/Users/madan/Documents/shopify-actions /src/modules/Generator.js](/Users/madan/Documents/shopify-actions%20/src/modules/Generator.js:1)
- [/Users/madan/Documents/shopify-actions /config.json](/Users/madan/Documents/shopify-actions%20/config.json:1)

## Existing Product Env Contract

The automation repo currently expects these env keys:
- `SIMPLE_PRODUCTS_JSON`
- `VARIABLE_PRODUCTS_JSON`
- `DIGITAL_PRODUCTS_JSON`
- `DANGEROUS_PRODUCTS_JSON`

Each entry uses:

```json
{"product_id": 123, "variant_id": 456}
```

Confirmed from:
- [/Users/madan/Documents/mcsl-test-automation/support/pages/shopifyAPI/createOrderAPI.ts](/Users/madan/Documents/mcsl-test-automation/support/pages/shopifyAPI/createOrderAPI.ts:39)
- [/Users/madan/Documents/mcsl-test-automation/carrier-envs/ups.env](/Users/madan/Documents/mcsl-test-automation/carrier-envs/ups.env:1)
- [/Users/madan/Documents/mcsl-test-automation/carrier-envs/packaging-fedexrest.env](/Users/madan/Documents/mcsl-test-automation/carrier-envs/packaging-fedexrest.env:1)

## Product Types Required

For the first version of this workflow, MCSL should create the product categories already expected by automation:
- simple
- variable
- digital
- dangerous

Recommended minimum seeded counts:
- simple: 2
- variable: 2
- digital: 2
- dangerous: 1

These should be deterministic, not random, so the setup is reproducible across reruns.

## Workflow Design

### Stage 1: Store Provisioning

Inputs:
- carrier name
- target store name
- release label or run label
- optional region / country / currency

Actions:
- create Shopify dev store
- install MCSL app
- persist run metadata

### Stage 2: Manual Carrier Registration Checkpoint

The dashboard should stop here and instruct QA to:
- add the new carrier account in the app
- enter carrier credentials
- enable any required services / options
- confirm the carrier is visible in the app

This step remains manual because it often involves secrets and carrier-specific decisions.

### Stage 3: Product Provisioning

The dashboard should:
- call the Shopify actions repo
- create the required product categories
- collect `product_id` and `variant_id`
- persist the created product set into MCSL history

Output shape:

```json
{
  "simple": [{"product_id": 1, "variant_id": 11}],
  "variable": [{"product_id": 2, "variant_id": 22}],
  "digital": [{"product_id": 3, "variant_id": 33}],
  "dangerous": [{"product_id": 4, "variant_id": 44}]
}
```

### Stage 4: Carrier Env Generation

Create a new env file in:
- `config.MCSL_AUTOMATION_REPO_PATH/carrier-envs/`

Include:
- `CARRIER`
- `SHOPIFY_STORE_NAME`
- `SHOPIFY_ACCESS_TOKEN`
- `SHOPIFY_API_VERSION`
- `SHOPIFYURL`
- `APPURL`
- `SIMPLE_PRODUCTS_JSON`
- `VARIABLE_PRODUCTS_JSON`
- `DIGITAL_PRODUCTS_JSON`
- `DANGEROUS_PRODUCTS_JSON`

Optional additions:
- region-specific addresses
- Slack webhook if required by the automation repo

### Stage 5: Suite Execution

Use the existing automation repo directly.

Run sequence:
1. smoke
2. sanity
3. regression

Suggested commands:

```bash
npx playwright test --grep "@smoke"
npx playwright test --grep "@sanity"
npx playwright test --grep "@regression"
```

The workflow should allow:
- run only smoke
- run smoke + sanity
- run full smoke + sanity + regression

### Stage 6: Monitoring And Report

The dashboard should show:
- current stage
- running suite
- pass / fail / skipped counts
- report links
- major failure summary
- final readiness verdict

Final output should answer:
- was the new carrier setup valid?
- were the required products provisioned?
- did smoke pass?
- did sanity pass?
- did regression pass?
- what remains blocked?

## Proposed MCSL Additions

### New dashboard tab

Add a new top-level tab:
- `🚚 New Carrier Validation`

Suggested sections:
- Carrier Setup
- Manual Carrier Registration
- Create Products
- Generate Carrier Env
- Run Smoke
- Run Sanity
- Run Regression
- Results

### New backend modules

Recommended first-pass modules:
- `pipeline/new_carrier_validation.py`
- `pipeline/shopify_product_seed.py`
- `pipeline/carrier_env_builder.py`
- `pipeline/automation_runner.py`
- `pipeline/carrier_validation_report.py`

## Session State / Persistence

Recommended state keys:
- `new_carrier_run`
- `new_carrier_store_name`
- `new_carrier_name`
- `new_carrier_stage`
- `new_carrier_products`
- `new_carrier_env_path`
- `new_carrier_smoke_result`
- `new_carrier_sanity_result`
- `new_carrier_regression_result`
- `new_carrier_report`

Persisted history should include:
- store name
- carrier
- created product IDs
- generated env file path
- suite outcomes
- report summary

## Implementation Order

### Milestone 1

Deliver the core path:
- new tab scaffold
- store setup integration
- manual QA checkpoint
- create required products
- generate env file
- run smoke
- produce a basic report

### Milestone 2

Expand to:
- sanity and regression orchestration
- richer reporting
- rerun controls
- history integration
- better carrier-specific product templates if needed

## Non-Goals For The First Version

Do not add these to the first delivery:
- AI-driven carrier credential entry
- random catalog generation
- pre-creating orders outside the automation repo
- broad automatic inference of every carrier-specific edge case

The first version should be deterministic and orchestration-focused.

## Recommendation

The first code step should be:
1. add the new tab scaffold
2. add product seeding + env generation backend
3. wire one smoke-run path end-to-end

That gives a useful vertical slice without waiting for the full regression orchestration UI.

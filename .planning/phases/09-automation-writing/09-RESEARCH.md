# Phase 9: Automation Writing - Research

**Researched:** 2026-04-18
**Domain:** Claude-powered Playwright POM+spec code generation, Playwright Python browser agent for element discovery, subprocess git operations, Streamlit UI for code display/push
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| AUTO-01 | Generate Playwright POM + spec from feature name + test cases | Claude Sonnet prompt engineering with MCSL POM patterns; RAG over mcsl_code_knowledge for existing POM context |
| AUTO-02 | Chrome Agent explores live MCSL app to capture elements/nav data for automation context | Reuse smart_ac_verifier._launch_browser() + _ax_tree(); produce structured JSON of selectors and navigation paths |
| AUTO-03 | Push generated code to git branch (optional auto-fix loop) | subprocess + git commands: checkout -b, add, commit, push; auto-fix loop re-prompts Claude if spec has obvious errors |
</phase_requirements>

---

## Summary

Phase 9 adds the Write Automation tab to `pipeline_dashboard.py` and implements three supporting modules: `pipeline/automation_writer.py` (AUTO-01), `pipeline/chrome_agent.py` (AUTO-02), and git-push logic living inside `automation_writer.py` or a thin helper (AUTO-03).

The generated code targets the MCSL `mcsl-test-automation` TypeScript Playwright project at `MCSL_AUTOMATION_REPO_PATH`. That project uses a Page Object Model pattern where every POM class extends `BasePage` (which wires `this.appFrame = page.frameLocator('iframe[name="app-iframe"]')`), and spec files import from `@setup/fixtures` and use `test.describe` / `test` blocks. Generated files must follow that exact convention to be immediately runnable.

The Chrome Agent (AUTO-02) reuses the existing `_launch_browser()` / `_ax_tree()` / `_navigate_in_app()` infrastructure from `smart_ac_verifier.py`. It navigates to the relevant MCSL section, captures the AX tree and screenshot, and returns a structured JSON payload that `automation_writer.py` injects as context into the POM-generation prompt.

**Primary recommendation:** Implement `automation_writer.py` (generate POM + spec via Claude) first, then `chrome_agent.py` (optional exploration), then the Streamlit tab UI + git push. The Chrome Agent is additive context — the writer must work without it (fallback to RAG-only context).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| langchain_anthropic | already installed | Call Claude Sonnet for code generation | Same pattern as user_story_writer.py, bug_reporter.py — all pipeline modules use this |
| playwright (Python, sync_api) | already installed | Chrome Agent browser automation | Already used in smart_ac_verifier._launch_browser(); no new dep |
| subprocess (stdlib) | stdlib | git CLI operations | Simpler and safer than GitPython for push-to-branch; no new dep |
| pathlib (stdlib) | stdlib | File write paths for generated .ts files | Consistent with all existing pipeline code |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| chromadb / mcsl_code_knowledge | already installed | RAG over existing POM files | Inject existing POM patterns as few-shot examples into generation prompt |
| config.MCSL_AUTOMATION_REPO_PATH | config.py | Root of the TypeScript automation repo | All generated file writes + git operations use this path |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| subprocess git | GitPython | GitPython adds a dependency; subprocess git is already used in the MCSL ecosystem and needs no install |
| Python playwright for Chrome Agent | Node playwright (via subprocess) | Python playwright is already installed and used by smart_ac_verifier; no extra setup |

### Installation
No new dependencies required. All libraries are already installed in the project venv.

---

## Architecture Patterns

### Recommended Module Structure
```
pipeline/
├── automation_writer.py     # write_automation(feature, test_cases, exploration_data) → AutomationResult
└── chrome_agent.py          # explore_feature(feature_name, nav_hint) → ExplorationResult
```

The Streamlit tab lives in `pipeline_dashboard.py` in the existing `with tab_manual:` block (line 1575–1576 currently a stub).

### Pattern 1: automation_writer.py — AutomationResult dataclass
**What:** Single function `write_automation()` that takes feature name, test case markdown, optional exploration JSON, and returns generated TypeScript files with file paths.
**When to use:** Called from both the standalone Write Automation tab and (in a later wave) from Release QA Step 5.

```python
# pipeline/automation_writer.py
from __future__ import annotations
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import config
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

@dataclass
class AutomationResult:
    feature_name: str
    pom_path: str           # relative to MCSL_AUTOMATION_REPO_PATH
    spec_path: str          # relative to MCSL_AUTOMATION_REPO_PATH
    pom_code: str
    spec_code: str
    git_branch: str = ""
    git_pushed: bool = False
    error: str = ""
```

### Pattern 2: POM Generation Prompt
**What:** Prompt that instructs Claude to produce a TypeScript POM class extending `BasePage` and a `.spec.ts` file importing from `@setup/fixtures`.
**Critical constraints the prompt must enforce:**
- POM class extends `BasePage` from `@pages/basePage`
- All app locators use `this.appFrame` (the iframe frame locator)
- Spec file uses `import { test, expect } from '@setup/fixtures'`
- Spec file uses `test.describe.configure({ mode: "serial" })`
- Spec uses `test.skip()` guard with `SHOPIFY_STORE_NAME` env check (matches existing pattern)
- File placement: POM → `support/pages/{feature_snake}/` ; spec → `tests/{feature_camel}/`

```python
POM_WRITER_PROMPT = """\
You are a senior QA automation engineer for the MCSL (Multi-Carrier Shipping Labels) Shopify app.
The app runs inside an iframe: iframe[name="app-iframe"].

You must generate TWO TypeScript files:

1. A Page Object Model (POM) class file:
   - Class name: {ClassName}Page
   - Extends BasePage from '@pages/basePage'
   - All app locators use `this.appFrame` (a FrameLocator)
   - File path: support/pages/{feature_snake}/{feature_camel}Page.ts

2. A spec file:
   - File path: tests/{feature_snake}/{feature_snake}.spec.ts
   - Import: `import {{ test, expect }} from '@setup/fixtures';`
   - Use `test.describe.configure({{ mode: "serial" }});`
   - Include `test.skip(!["mcsl-automation"].includes(process.env.SHOPIFY_STORE_NAME ?? ""), ...)`

Feature name: {feature_name}

Test Cases:
{test_cases}

Existing POM context (for selector patterns):
{pom_context}

Live element data from Chrome Agent (if available):
{exploration_data}

Return ONLY valid TypeScript. Use this exact format:
=== POM FILE: support/pages/{feature_snake}/{feature_camel}Page.ts ===
<typescript code>
=== SPEC FILE: tests/{feature_snake}/{feature_snake}.spec.ts ===
<typescript code>
"""
```

### Pattern 3: Chrome Agent — ExplorationResult
**What:** Headless browser session that navigates to a feature section, captures AX tree + screenshot, and returns structured selector data.
**Reuse principle:** Import `_launch_browser`, `_ax_tree`, `_navigate_in_app`, `_get_app_frame` directly from `smart_ac_verifier`. Do NOT re-implement them.

```python
# pipeline/chrome_agent.py
from __future__ import annotations
import json
import logging
from dataclasses import dataclass

import config
from pipeline.smart_ac_verifier import _launch_browser, _ax_tree, _navigate_in_app

logger = logging.getLogger(__name__)

@dataclass
class ExplorationResult:
    feature_name: str
    nav_destination: str
    ax_tree_text: str
    screenshot_b64: str
    elements_json: str   # Claude-extracted JSON of key selectors
    error: str = ""

def explore_feature(feature_name: str, nav_hint: str = "") -> ExplorationResult:
    """Navigate to the MCSL feature section and capture element data."""
    pw = browser = ctx = page = None
    try:
        pw, browser, ctx, page = _launch_browser(headless=True)
        # navigate to app
        import config as cfg
        store = cfg.STORE
        page.goto(f"https://{store}.myshopify.com/admin/apps/mcsl-qa", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        # navigate to feature section using existing nav map
        destination = _resolve_nav_destination(feature_name, nav_hint)
        if destination:
            _navigate_in_app(page, destination, store)
            page.wait_for_timeout(2000)
        ax = _ax_tree(page)
        screenshot = page.screenshot(type="png")
        import base64
        screenshot_b64 = base64.b64encode(screenshot).decode()
        elements_json = _extract_elements_with_claude(ax, feature_name)
        return ExplorationResult(
            feature_name=feature_name,
            nav_destination=destination or "home",
            ax_tree_text=ax,
            screenshot_b64=screenshot_b64,
            elements_json=elements_json,
        )
    except Exception as e:
        logger.warning("explore_feature failed: %s", e)
        return ExplorationResult(feature_name=feature_name, nav_destination="", ax_tree_text="", screenshot_b64="", elements_json="", error=str(e))
    finally:
        if page: page.close()
        if ctx: ctx.close()
        if browser: browser.close()
        if pw: pw.stop()
```

### Pattern 4: Git Push via subprocess
**What:** Run `git checkout -b`, `git add`, `git commit`, `git push` as subprocess calls against `MCSL_AUTOMATION_REPO_PATH`.
**Critical:** Use `cwd=MCSL_AUTOMATION_REPO_PATH` on every subprocess call. Never use `os.chdir()` — it mutates the process working directory and breaks Streamlit threading.

```python
def push_to_branch(
    repo_path: str,
    feature_name: str,
    pom_path: str,
    spec_path: str,
) -> tuple[bool, str]:
    """Write files and push to a feature branch. Returns (success, message)."""
    import subprocess, re
    branch = "automation/" + re.sub(r"[^a-z0-9]+", "-", feature_name.lower()).strip("-")
    cwd = repo_path
    try:
        # Create or switch to branch
        subprocess.run(["git", "checkout", "-B", branch], cwd=cwd, check=True, capture_output=True)
        # Stage only the two generated files
        subprocess.run(["git", "add", pom_path, spec_path], cwd=cwd, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"feat(automation): add {feature_name} POM + spec"], cwd=cwd, check=True, capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", branch], cwd=cwd, check=True, capture_output=True)
        return True, branch
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode(errors="replace")
```

**Note:** `git checkout -B branch` creates the branch if absent, resets it if it exists — safe for re-runs.

### Pattern 5: Write Automation Tab UI
**What:** Streamlit UI inside `with tab_manual:` block.
**UI sections:**
1. Feature name input (`st.text_input`)
2. Test cases textarea (`st.text_area`) — accepts markdown TC list
3. Optional Chrome Agent section: expandable `st.expander("Explore live app (optional)")` with `st.button("Run Chrome Agent")` and `st.session_state["auto_exploration"]`
4. Generate button → calls `write_automation()` in same thread (fast, no background thread needed)
5. Code display: `st.tabs(["POM", "Spec"])` each showing `st.code(..., language="typescript")`
6. Copy buttons and download buttons (`st.download_button`)
7. Git push section: branch name preview, `st.button("Push to Git Branch")`, success/error feedback

**Session state keys** (add to `_init_state()`):
```python
"auto_feature": ""           # feature name input
"auto_test_cases": ""        # TC markdown
"auto_result": None          # AutomationResult | None
"auto_exploration": None     # ExplorationResult | None
"auto_explore_running": False
```

### Anti-Patterns to Avoid
- **Importing automation_writer at module top**: Use lazy import inside button handler to avoid cold-start cost on Streamlit reload (matches existing pattern from Phase 4: `card_processor` lazy import).
- **Running Chrome Agent in main Streamlit thread without a spinner**: Chrome Agent can take 10-30 seconds; wrap in `with st.spinner("Exploring app...")` and consider `threading.Thread` with `auto_explore_running` flag if UI responsiveness matters.
- **Using os.chdir() for git operations**: Always pass `cwd=` to subprocess. os.chdir() is process-global and will break other Streamlit threads.
- **Committing everything in the repo**: Only `git add` the two specific generated files by their paths. Never use `git add .` or `git add -A`.
- **Generating code without MCSL iframe context**: Any POM that uses `page.locator(...)` directly (without `this.appFrame`) will fail in the MCSL app. The prompt must explicitly warn about this.
- **Hardcoding @pages path alias in the Python prompt without checking tsconfig**: The alias `@pages/*` → `support/pages/*` is confirmed in tsconfig.json. Use it in generated imports.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Browser launch + auth | Custom Playwright setup | `smart_ac_verifier._launch_browser()` | Already handles anti-bot args, auth-chrome.json storage state, viewport |
| AX tree capture | Custom accessibility tree | `smart_ac_verifier._ax_tree()` | Already handles dual-frame capture (main + app iframe) |
| MCSL app navigation | Custom click sequences | `smart_ac_verifier._navigate_in_app()` | Already maps all MCSL sections (ORDERS, LABELS, hamburger menu, etc.) |
| Claude API client | Custom HTTP calls | `langchain_anthropic.ChatAnthropic` | All pipeline modules use this; consistent error handling |
| RAG context for POM patterns | Custom vector search | `mcsl_code_knowledge` ChromaDB collection | Already indexed all POM files from mcsl-test-automation repo (RAG-05 complete) |

---

## Common Pitfalls

### Pitfall 1: Iframe Context in Generated POM
**What goes wrong:** Claude generates `page.locator('button[name="Generate Label"]')` instead of `this.appFrame.locator(...)`. The test passes compilation but fails at runtime because all MCSL UI is inside `iframe[name="app-iframe"]`.
**Why it happens:** Without explicit instruction, Claude defaults to `page` locators.
**How to avoid:** POM_WRITER_PROMPT must include a mandatory rule: "ALL locators for MCSL app elements MUST use `this.appFrame`, not `this.page`. Only Shopify admin elements (outside the iframe) use `this.page`."
**Warning signs:** Generated POM has `this.page.locator(...)` for MCSL buttons/inputs.

### Pitfall 2: Git Push Fails When Remote Branch Doesn't Exist
**What goes wrong:** `git push origin branch` fails with "src refspec does not match any" or requires upstream tracking.
**Why it happens:** New branches need `-u origin` flag on first push.
**How to avoid:** Always use `git push -u origin {branch}` — idempotent for both new and existing branches.
**Warning signs:** subprocess.CalledProcessError with stderr mentioning "no upstream".

### Pitfall 3: Chrome Agent Times Out Waiting for MCSL iframe
**What goes wrong:** `_ax_tree()` returns an empty string or Shopify admin tree because the MCSL iframe hasn't loaded.
**Why it happens:** MCSL app inside iframe takes 4-8 seconds to fully load after navigation.
**How to avoid:** Add `page.wait_for_timeout(5000)` after `page.goto()` before calling `_ax_tree()`. Check that AX tree result contains "app-iframe" content before returning.
**Warning signs:** `ax_tree_text` contains only Shopify admin elements (Polaris navigation) with no MCSL-specific elements.

### Pitfall 4: Generated Spec Misses the test.skip() Store Guard
**What goes wrong:** Test runs against wrong Shopify store (e.g., developer's personal store) and creates real shipments.
**Why it happens:** Omitting the store guard is easy when generating spec from template.
**How to avoid:** Enforce `test.skip(!["mcsl-automation"].includes(process.env.SHOPIFY_STORE_NAME ?? ""), ...)` as a non-optional template element in POM_WRITER_PROMPT. Check generated spec in tests before displaying.
**Warning signs:** Spec file has no `test.skip` guard at all.

### Pitfall 5: File Path Collisions in Automation Repo
**What goes wrong:** Two features both generate `support/pages/orderSummary/orderSummaryPage.ts`, overwriting existing hand-written POM.
**Why it happens:** Feature names like "Order Summary" collide with existing POM folder names.
**How to avoid:** Before writing generated files, check if the target path already exists. If yes, write to `{feature_snake}_generated/` subdirectory and warn the user in the UI.
**Warning signs:** Feature name matches an existing `support/pages/` directory.

### Pitfall 6: Claude Returns Free-Text Instead of Delimited Files
**What goes wrong:** `write_automation()` cannot parse Claude's response because it includes explanatory prose interspersed with the code.
**Why it happens:** Without strict output format enforcement, Claude adds preambles.
**How to avoid:** Use `=== POM FILE: ... ===` and `=== SPEC FILE: ... ===` delimiters in the prompt, and parse response with `re.split` on those patterns. Fall back gracefully with `result.error` if parsing fails.

---

## Code Examples

Verified patterns from the existing MCSL automation repo:

### Existing POM class structure (from support/pages/products/editProductDetails.ts)
```typescript
// Pattern confirmed from mcsl-test-automation repo
import { expect, type Page, type Locator } from '@playwright/test';
import BasePage from '@pages/basePage';
import dotenv from 'dotenv';
dotenv.config();

class MCSLProductsPage extends BasePage {
  readonly editIcon: Locator;
  readonly successAlertMessage: Locator;

  constructor(page: Page) {
    super(page);
    this.editIcon = this.appFrame.locator('i.fa-pencil-square-o');
    this.successAlertMessage = this.appFrame.locator('.s-alert-box-inner');
  }
}
export default MCSLProductsPage;
```

### Existing spec structure (from tests/carrierOtherDetails/UPS/imageType.spec.ts)
```typescript
// Pattern confirmed from mcsl-test-automation repo
import { test, expect } from '@setup/fixtures';

test.describe.configure({ mode: "serial" });

test.describe("As a merchant, I should be able to ...", { tag: "@regression" }, () => {
  test.setTimeout(150 * 1000);
  test.skip(
    !["mcsl-automation"].includes(process.env.SHOPIFY_STORE_NAME ?? ""),
    `Skipping because SHOPIFY_STORE_NAME=${process.env.SHOPIFY_STORE_NAME}`
  );
  let orderID: string;
  test.beforeAll(async ({ pages, uploader }) => {
    await pages.loginPage.loginWithSessionIfAvailable(process.env.SHOPIFYURL);
    await pages.createStore.clickAccountCard(pages.sharedPage);
  });
  test("Verify X does Y", async ({ pages, uploader }) => {
    // ...
  });
});
```

### BasePage iframe wiring (from support/pages/basePage.ts)
```typescript
// Confirmed: appFrame is always page.frameLocator('iframe[name="app-iframe"]')
export default class BasePage {
  readonly page: Page;
  readonly appFrame: FrameLocator;
  constructor(page: Page) {
    this.page = page;
    this.appFrame = page.frameLocator('iframe[name="app-iframe"]');
  }
}
```

### Reusing _launch_browser from smart_ac_verifier (Python)
```python
# Confirmed pattern from smart_ac_verifier.py lines 1703-1727
from pipeline.smart_ac_verifier import _launch_browser, _ax_tree, _navigate_in_app

pw, browser, ctx, page = _launch_browser(headless=True)
try:
    page.goto(f"https://{store}.myshopify.com/admin/apps/mcsl-qa", wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    _navigate_in_app(page, "orders", store)
    ax = _ax_tree(page)
    screenshot_bytes = page.screenshot(type="png")
finally:
    page.close(); ctx.close(); browser.close(); pw.stop()
```

### Subprocess git push pattern
```python
import subprocess, re

def push_to_branch(repo_path: str, feature: str, files: list[str]) -> tuple[bool, str]:
    branch = "automation/" + re.sub(r"[^a-z0-9]+", "-", feature.lower()).strip("-")
    try:
        subprocess.run(["git", "checkout", "-B", branch], cwd=repo_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add"] + files, cwd=repo_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", f"feat(automation): add {feature} POM + spec"], cwd=repo_path, check=True, capture_output=True, text=True)
        result = subprocess.run(["git", "push", "-u", "origin", branch], cwd=repo_path, check=True, capture_output=True, text=True)
        return True, branch
    except subprocess.CalledProcessError as e:
        return False, e.stderr
```

### Parsing Claude's dual-file response
```python
import re

def _parse_automation_response(response: str) -> tuple[str, str]:
    """Parse === POM FILE: ... === and === SPEC FILE: ... === delimiters."""
    pom_match = re.search(r'=== POM FILE:.*?===\n(.*?)(?==== SPEC FILE:|$)', response, re.DOTALL)
    spec_match = re.search(r'=== SPEC FILE:.*?===\n(.*?)$', response, re.DOTALL)
    pom_code = pom_match.group(1).strip() if pom_match else ""
    spec_code = spec_match.group(1).strip() if spec_match else ""
    return pom_code, spec_code
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| All Claude calls use str output | `HumanMessage` content list with text blocks | Phase 2 | All pipeline modules must use `HumanMessage([{"type":"text","text":...}])` pattern |
| Single auth.json | auth.json (Safari) + auth-chrome.json (Chrome) | Phase 2 discovery | Chrome Agent must use `auth-chrome.json` (matches `playwright.config.ts` Chrome project storageState) |
| subprocess with shell=True | subprocess with list args, check=True, capture_output=True | Python best practice | Avoids shell injection; always use list form for git commands |

**Deprecated/outdated:**
- `auth.json` path in smart_ac_verifier (`_AUTH_JSON = Path(".../auth.json")`): Chrome Agent should prefer `auth-chrome.json` which is what the Chrome project uses in `playwright.config.ts`. The Python verifier uses `auth.json` for historical reasons.

---

## Open Questions

1. **Auto-fix loop scope for AUTO-03**
   - What we know: AUTO-03 mentions "optional auto-fix loop" — generate code, detect errors, re-prompt Claude to fix
   - What's unclear: How to detect TypeScript errors without running `tsc` (which requires Node.js and can be slow); what constitutes an "error" in this context
   - Recommendation: Implement a simple text-based check in Wave 1 (check for obvious syntax markers like mismatched braces, missing `export default`). Defer tsc-based error detection to a follow-up if needed. Make auto-fix loop optional and depth-limited (max 1 retry).

2. **Release QA Step 5 integration scope**
   - What we know: Phase 9 should integrate into Release QA Step 5 per the roadmap
   - What's unclear: Plan 09-03 says "Write Automation tab UI + Release QA Step 5 integration" — this means tab_release needs a Step 5 section that calls `write_automation()` with the approved TCs for a card
   - Recommendation: In 09-03, add a collapsible "Step 5: Write Automation" section inside the per-card expander in tab_release. Pre-populate feature name from card name, TCs from approved test cases.

3. **Chrome Agent headless vs headed**
   - What we know: `_launch_browser(headless=False)` is the default in smart_ac_verifier (shows browser for QA review); headless=True is available
   - What's unclear: Whether Chrome Agent exploration should be headless (background, no browser window) by default
   - Recommendation: Use `headless=True` for Chrome Agent — it runs as a background utility action from Streamlit, not an interactive QA step.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing, see tests/ directory) |
| Config file | none — pytest discovered via conftest.py |
| Quick run command | `.venv/bin/python -m pytest tests/test_pipeline.py -k "auto" -x -q` |
| Full suite command | `.venv/bin/python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AUTO-01 | `write_automation()` returns AutomationResult with non-empty pom_code and spec_code | unit | `.venv/bin/python -m pytest tests/test_pipeline.py -k "auto01" -x` | ❌ Wave 0 |
| AUTO-01 | Generated spec contains `test.describe`, `@setup/fixtures` import, `test.skip` guard | unit | `.venv/bin/python -m pytest tests/test_pipeline.py -k "auto01_spec_structure" -x` | ❌ Wave 0 |
| AUTO-01 | Generated POM contains `BasePage`, `this.appFrame`, `export default` | unit | `.venv/bin/python -m pytest tests/test_pipeline.py -k "auto01_pom_structure" -x` | ❌ Wave 0 |
| AUTO-01 | `write_automation()` returns error gracefully when ANTHROPIC_API_KEY absent | unit | `.venv/bin/python -m pytest tests/test_pipeline.py -k "auto01_no_api_key" -x` | ❌ Wave 0 |
| AUTO-02 | `explore_feature()` returns ExplorationResult with error field when browser fails | unit | `.venv/bin/python -m pytest tests/test_pipeline.py -k "auto02_explore_error" -x` | ❌ Wave 0 |
| AUTO-03 | `push_to_branch()` calls git checkout, add, commit, push with correct cwd | unit | `.venv/bin/python -m pytest tests/test_pipeline.py -k "auto03_git_push" -x` | ❌ Wave 0 |
| AUTO-03 | `push_to_branch()` returns (False, stderr) on CalledProcessError | unit | `.venv/bin/python -m pytest tests/test_pipeline.py -k "auto03_git_error" -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_pipeline.py -k "auto" -x -q`
- **Per wave merge:** `.venv/bin/python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_pipeline.py` — add AUTO-01, AUTO-02, AUTO-03 test stubs (file exists, add new test functions)
- [ ] `pipeline/automation_writer.py` — does not exist yet
- [ ] `pipeline/chrome_agent.py` — does not exist yet

*(No new test files needed — all tests added to existing `tests/test_pipeline.py` consistent with Phase 6-8 pattern)*

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection: `pipeline/smart_ac_verifier.py` — `_launch_browser`, `_ax_tree`, `_navigate_in_app`, `_MCSL_NAV_MAP` (lines 390-468, 1703-1727)
- Direct codebase inspection: `mcsl-test-automation/support/pages/basePage.ts` — BasePage structure, appFrame wiring
- Direct codebase inspection: `mcsl-test-automation/tests/carrierOtherDetails/UPS/imageType.spec.ts` — spec file pattern with test.skip guard
- Direct codebase inspection: `mcsl-test-automation/playwright.config.ts` — auth-chrome.json storageState, timeout, testDir
- Direct codebase inspection: `mcsl-test-automation/tsconfig.json` — `@pages`, `@helpers`, `@setup` path aliases
- Direct codebase inspection: `pipeline/user_story_writer.py` — Claude prompt + LangChain pattern for all pipeline modules
- Direct codebase inspection: `pipeline_dashboard.py` lines 1575-1576 — tab_manual stub location

### Secondary (MEDIUM confidence)
- `mcsl-test-automation/package.json`: `@playwright/test ^1.55.0` — confirmed Playwright version in automation repo
- Python stdlib `subprocess` documentation — `cwd` parameter, `capture_output`, `check=True` (well-known, no external verification needed)

### Tertiary (LOW confidence)
- None — all critical findings sourced from direct codebase inspection

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries confirmed as already installed; no new deps needed
- Architecture patterns: HIGH — POM pattern confirmed from 10+ existing .ts files; Claude prompt pattern confirmed from 4 existing pipeline modules
- Pitfalls: HIGH — iframe pitfall confirmed by reading basePage.ts + existing POMs; git cwd pitfall is standard Python knowledge; file collision is a logical deduction from existing folder names
- Chrome Agent reuse: HIGH — _launch_browser, _ax_tree, _navigate_in_app confirmed in smart_ac_verifier.py

**Research date:** 2026-04-18
**Valid until:** 2026-05-18 (stable project; MCSL automation repo conventions unlikely to change)

"""
pipeline/automation_writer.py — Playwright POM + spec code generation for MCSL automation.

Exports: write_automation, AutomationResult
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import config
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

POM_WRITER_PROMPT = """\
You are a senior QA automation engineer for the MCSL multi-carrier Shopify app.
Generate a TypeScript Playwright Page Object Model (POM) class and a spec file for the
feature described below.

Feature name: {feature_name}
Feature snake_case: {feature_snake}
Feature CamelCase class name: {ClassName}

Test cases (Markdown):
{test_cases}

MCSL app context (exploration data):
{exploration_data}

Additional POM context / existing patterns:
{pom_context}

=== STRICT RULES FOR THE POM FILE ===
1. The POM class MUST extend BasePage: `class {ClassName}Page extends BasePage`
2. ALL locators for MCSL app elements MUST use `this.appFrame`, NOT `this.page`.
   Only Shopify admin elements outside the iframe (e.g. top-nav, billing modals) may use `this.page`.
3. Import BasePage: `import BasePage from '@pages/basePage';`
4. The file MUST end with: `export default {ClassName}Page;`
5. Constructor signature: `constructor(page: Page) {{ super(page); ... }}`

=== STRICT RULES FOR THE SPEC FILE ===
1. First import: `import {{ test, expect }} from '@setup/fixtures';`
2. Second line: `test.describe.configure({{ mode: "serial" }});`
3. Wrap all tests in: `test.describe("{feature_name}", {{ tag: "@regression" }}, () => {{ ... }});`
4. FIRST statement inside test.describe MUST be:
   `test.skip(!["mcsl-automation"].includes(process.env.SHOPIFY_STORE_NAME ?? ""), "Tests only run against mcsl-automation store");`
5. Each test case becomes a `test("Verify ...", async ({{ pages }}) => {{ ... }});` block.

=== OUTPUT FORMAT (REQUIRED — DO NOT DEVIATE) ===
Respond with EXACTLY two sections separated by these delimiters:

=== POM FILE: support/pages/{feature_snake}/{feature_camel}Page.ts ===
<full TypeScript POM class here>

=== SPEC FILE: tests/{feature_snake}/{feature_snake}.spec.ts ===
<full TypeScript spec file here>

Do NOT include any explanation, markdown code fences, or extra text outside those two sections.
"""

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class AutomationResult:
    feature_name: str
    pom_path: str
    spec_path: str
    pom_code: str
    spec_code: str
    git_branch: str = ""
    git_pushed: bool = False
    error: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_snake_case(name: str) -> str:
    """Convert feature name to snake_case (spaces/hyphens to underscores, lowercase)."""
    return re.sub(r"[\s\-]+", "_", name).lower()


def _to_camel_case(name: str) -> str:
    """Convert feature name to CamelCase (e.g. 'order summary' -> 'OrderSummary')."""
    return "".join(word.title() for word in re.split(r"[\s\-_]+", name))


def _parse_automation_response(response_text: str) -> tuple[str, str]:
    """
    Parse Claude's response into (pom_code, spec_code).

    Expects:
        === POM FILE: ... ===
        <pom code>
        === SPEC FILE: ... ===
        <spec code>

    Returns ("", "") if the delimiters are not found.
    """
    pom_match = re.search(
        r"=== POM FILE:.*?===\n(.*?)(?==== SPEC FILE:|$)",
        response_text,
        re.DOTALL,
    )
    spec_match = re.search(
        r"=== SPEC FILE:.*?===\n(.*?)$",
        response_text,
        re.DOTALL,
    )

    pom_code = pom_match.group(1).strip() if pom_match else ""
    spec_code = spec_match.group(1).strip() if spec_match else ""
    return pom_code, spec_code


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_automation(
    feature_name: str,
    test_cases_markdown: str,
    exploration_data: str = "",
    model: str | None = None,
) -> AutomationResult:
    """
    Generate a TypeScript Playwright POM class and spec file from feature_name
    and test_cases_markdown using Claude.

    Returns AutomationResult.  Never raises — errors are captured in .error field.
    """
    feature_snake = _to_snake_case(feature_name)
    feature_camel = _to_camel_case(feature_name)
    class_name = feature_camel
    pom_path = f"support/pages/{feature_snake}/{feature_camel}Page.ts"
    spec_path = f"tests/{feature_snake}/{feature_snake}.spec.ts"

    _empty = AutomationResult(
        feature_name=feature_name,
        pom_path="",
        spec_path="",
        pom_code="",
        spec_code="",
    )

    if not config.ANTHROPIC_API_KEY:
        _empty.error = "ANTHROPIC_API_KEY not set"
        return _empty

    try:
        prompt = POM_WRITER_PROMPT.format(
            feature_name=feature_name,
            feature_snake=feature_snake,
            feature_camel=feature_camel,
            ClassName=class_name,
            test_cases=test_cases_markdown,
            exploration_data=exploration_data or "(none)",
            pom_context="Existing MCSL POMs extend BasePage; all MCSL locators use this.appFrame.",
        )

        llm = ChatAnthropic(
            model=model or config.CLAUDE_SONNET_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            max_tokens=4096,
        )
        response = llm.invoke([HumanMessage(content=[{"type": "text", "text": prompt}])])
        response_text: str = response.content

        pom_code, spec_code = _parse_automation_response(response_text)

        if not pom_code or not spec_code:
            _empty.error = "Failed to parse Claude response — check delimiter format"
            return _empty

        return AutomationResult(
            feature_name=feature_name,
            pom_path=pom_path,
            spec_path=spec_path,
            pom_code=pom_code,
            spec_code=spec_code,
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("write_automation failed for feature '%s'", feature_name)
        _empty.error = str(exc)
        return _empty

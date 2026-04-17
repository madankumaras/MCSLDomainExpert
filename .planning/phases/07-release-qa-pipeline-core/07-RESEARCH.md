# Phase 7: Release QA Pipeline Core — Research

**Researched:** 2026-04-17
**Domain:** Pipeline backend (domain validation, release analysis, card processing, sheets write) + Streamlit Release QA tab
**Confidence:** HIGH — all findings sourced from direct code inspection of FedEx reference implementation and MCSL codebase

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| RQA-01 | Load Trello cards from a selected list with release health summary (pass/fail/approved metrics) | TrelloClient.get_cards_in_list() exists; health summary pattern from FedEx lines 1086-1103 |
| RQA-02 | Per-card: generate AC, validate with domain expert, show KB context + issues | domain_validator.validate_card() fully documented; generate_acceptance_criteria() signature confirmed |
| RQA-03 | Per-card: run AI QA Agent in background thread with live progress, stop button, results display | Per-card sav_running_{id} pattern from FedEx lines 1827-1971; verify_ac() already in smart_ac_verifier.py |
| RQA-04 | Per-card: generate test cases, review, approve → save to Trello + Google Sheets | generate_test_cases(), write_test_cases_to_card(), append_to_sheet() all documented |
| RQA-05 | Release intelligence: risk level, cross-card conflicts, coverage gaps, suggested test order | release_analyser.analyse_release() + ReleaseAnalysis fully documented |
</phase_requirements>

---

## Summary

Phase 7 introduces four new files: `pipeline/domain_validator.py`, `pipeline/release_analyser.py`, an expansion of `pipeline/card_processor.py`, and a full replacement of the `with tab_release:` stub in `pipeline_dashboard.py`. A fifth concern is `pipeline/sheets_writer.py`, which is entirely new to MCSL (only `config.py` has `GOOGLE_SHEETS_ID` and `GOOGLE_CREDENTIALS_PATH`).

The FedEx reference implementation at `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/` is the authoritative source for all four files. All interfaces are stable and directly portable — the only changes required are replacing "FedEx" branding with MCSL multi-carrier copy, updating the `VALIDATION_PROMPT` and `RELEASE_ANALYSIS_PROMPT` to reference FedEx/UPS/DHL/USPS, and updating the `SHEET_TABS` / `TAB_KEYWORDS` to reflect the MCSL master sheet structure.

The Release QA tab in `pipeline_dashboard.py` currently contains a single stub line (`st.info("Release QA pipeline coming in Phase 7.")`). It must be replaced with the full card-load → validation → AI QA Agent → test case → approval flow, exactly as implemented in the FedEx dashboard (lines 928–2300+). MCSL-specific differences are limited to: no toggle/Ashok/Slack escalation in Phase 7 (those are Phase 8), no re-verify branch complexity (can be added later), and `mcsl-qa` app slug instead of `testing-553`.

**Primary recommendation:** Port `domain_validator.py`, `release_analyser.py`, and `sheets_writer.py` from FedEx verbatim with MCSL prompt copy changes; expand `card_processor.py` with `generate_acceptance_criteria()`, `generate_test_cases()`, `write_test_cases_to_card()`; replace the `tab_release` stub in `pipeline_dashboard.py` with the FedEx tab implementation trimmed to Phase 7 scope (no Slack toggle escalation, no bug DM — those are Phase 8).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| langchain-anthropic | installed | Claude API calls for validation + analysis | Already used by smart_ac_verifier, user_story_writer |
| langchain-core | installed | HumanMessage type | Already in use across all pipeline modules |
| gspread | ~6.x | Google Sheets read/write | Used in FedEx sheets_writer; `pip install gspread` |
| google-auth | ~2.x | Service account credentials for gspread | Required by gspread service account flow |
| streamlit | installed | Release QA tab UI | Dashboard already uses it |
| threading | stdlib | Per-card AI QA Agent background run | Already used in dashboard Phase 4 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| difflib.SequenceMatcher | stdlib | Duplicate TC fuzzy matching in sheets_writer | When checking for near-duplicate test cases before Sheet write |
| re | stdlib | JSON fence stripping, TC markdown parsing | All four new modules use it |
| dataclasses | stdlib | ValidationReport, ReleaseAnalysis, CardSummary, TestCaseRow, DuplicateMatch | Every new backend module |

**Installation (new packages only):**
```bash
pip install gspread google-auth
```

---

## Architecture Patterns

### Recommended Project Structure (additions only)
```
pipeline/
├── domain_validator.py     # NEW — validate_card() → ValidationReport
├── release_analyser.py     # NEW — analyse_release() → ReleaseAnalysis
├── sheets_writer.py        # NEW — append_to_sheet(), detect_tab(), check_duplicates()
├── card_processor.py       # EXPAND — add generate_acceptance_criteria(),
│                           #           generate_test_cases(), write_test_cases_to_card()
│                           #           format_qa_comment(), parse_test_cases_to_rows()
pipeline_dashboard.py       # EXPAND — replace tab_release stub with full implementation
tests/
├── test_pipeline.py        # ADD — RQA test stubs for domain_validator, release_analyser
├── test_dashboard.py       # ADD — RQA tab test stubs
```

### Pattern 1: validate_card() — RAG + Claude validation

**What:** Fetch RAG context for card, ask Claude to produce a structured JSON validation report.
**When to use:** Called on every card immediately after load (auto-validates in batch).

```python
# Source: FedexDomainExpert/pipeline/domain_validator.py lines 105-195

def validate_card(
    card_name: str,
    card_desc: str,
    acceptance_criteria: str = "",
) -> ValidationReport:
    ...
```

`ValidationReport` dataclass fields:
```python
@dataclass
class ValidationReport:
    overall_status: str          # "PASS" | "NEEDS_REVIEW" | "FAIL"
    summary: str
    requirement_gaps: list[str]
    ac_gaps: list[str]
    accuracy_issues: list[str]
    suggestions: list[str]
    kb_insights: str
    sources: list[str]
    error: str                   # non-empty if validation itself failed
```

MCSL prompt change required — replace:
```
"You are a senior domain expert and QA lead for the FedEx Shopify App built by PluginHive."
```
with:
```
"You are a senior domain expert and QA lead for the MCSL (Multi-Carrier Shipping Labels)
Shopify App built by PluginHive. The app supports multiple carriers: FedEx, UPS, DHL, USPS."
```

The accuracy_issues check should reference MCSL carrier behaviours (e.g. MCSL label flow uses ORDERS tab, not Shopify More Actions; carrier accounts configured via App Settings → Carriers → Add/Edit).

### Pattern 2: analyse_release() — cross-card RAG pre-screen

**What:** Build a combined query from all card names + descs, retrieve RAG context (k = min(6*n_cards, 20)), call Claude Sonnet for cross-card analysis.
**When to use:** Called once after all per-card validations complete on load.

```python
# Source: FedexDomainExpert/pipeline/release_analyser.py lines 128-250

def analyse_release(
    release_name: str,
    cards: list[CardSummary],
) -> ReleaseAnalysis:
    ...

@dataclass
class CardSummary:
    card_id: str
    card_name: str
    card_desc: str

@dataclass
class ReleaseAnalysis:
    release_name: str
    risk_level: str                  # "LOW" | "MEDIUM" | "HIGH"
    risk_summary: str
    conflicts: list[dict]            # {"cards": [...], "area": "...", "description": "..."}
    ordering: list[dict]             # {"position": int, "card_name": "...", "reason": "..."}
    coverage_gaps: list[str]
    kb_context_summary: str
    sources: list[str]
    error: str
```

MCSL prompt change required — replace the `"You are a senior QA lead and FedEx Shopify App domain expert."` opener with:
```
"You are a senior QA lead and MCSL (Multi-Carrier Shipping Labels) Shopify App domain expert
for PluginHive. The app supports FedEx, UPS, DHL, USPS, and other carriers."
```

Uses `CLAUDE_SONNET_MODEL` (not Haiku) — cross-card reasoning benefits from the larger model.
Token scaling: `_max_tokens = min(3000 + len(cards) * 400, 6000)`.

### Pattern 3: generate_acceptance_criteria() / generate_test_cases() expansion

**What:** Expand MCSL `card_processor.py` (currently only has `get_ac_text()`) to add the full FedEx card_processor API.
**When to use:** `generate_acceptance_criteria()` called from Step 1b "Generate User Story & AC" button. `generate_test_cases()` called from Step 3.

```python
# Source: FedexDomainExpert/pipeline/card_processor.py lines 178-474

def generate_acceptance_criteria(
    raw_request: str,
    model: str | None = None,
    attachments: list[dict] | None = None,
    checklists: list[dict] | None = None,
    research_context: str | None = None,
) -> str:
    ...

def generate_test_cases(card: TrelloCard, model: str | None = None) -> str:
    # card.desc used as card_desc; card.name as card_name
    # card.comments (list[str] | None) for dev notes
    ...

def write_test_cases_to_card(
    card_id: str,
    test_cases: str,
    trello: TrelloClient,
    release: str = "",
    card_name: str = "",
) -> None:
    ...

def format_qa_comment(
    card_name: str,
    test_cases_markdown: str,
    release: str = "",
    qa_name: str = "",
) -> str:
    ...
```

MCSL `TrelloCard` (from `trello_client.py`) does NOT yet have `comments`, `attachments`, or `checklists` fields. These must be added to the dataclass before `generate_test_cases()` can use them.

`AC_WRITER_PROMPT` and `TEST_CASE_PROMPT` should replace "FedEx Shopify App" with "MCSL Shopify App" and "PH FedEx app" with "PH MCSL app". The "Never write ACs for mobile viewports" rule stays.

MCSL-specific navigation note in TEST_CASE_PROMPT: reference the ORDERS tab flow and MCSL carrier config path (App Settings → Carriers → Add/Edit).

### Pattern 4: append_to_sheet() — Google Sheets write

**What:** Parse TCs markdown to rows, detect the right sheet tab by keyword matching, check for duplicates, append positive-type TCs.
**When to use:** Called at approval time (Step 4 Approve button).

```python
# Source: FedexDomainExpert/pipeline/sheets_writer.py lines 450-553

def append_to_sheet(
    card_name: str,
    test_cases_markdown: str,
    epic: str = "",
    tab_name: str | None = None,
    release: str = "",
) -> dict:
    # Returns {"tab": str, "rows_added": int, "sheet_url": str,
    #          "release": str, "duplicates": list[DuplicateMatch]}
    ...

def detect_tab(card_name: str, test_cases_markdown: str) -> str:
    # Keyword match first; Claude fallback if no match
    ...

def check_duplicates(
    new_rows: list[TestCaseRow],
    tab_name: str,
    similarity_threshold: float = 0.75,
) -> list[DuplicateMatch]:
    ...

def parse_test_cases_to_rows(
    card_name: str,
    test_cases_markdown: str,
    epic: str = "",
    positive_only: bool = False,
) -> list[TestCaseRow]:
    ...
```

`SHEET_TABS` and `TAB_KEYWORDS` must be updated for the MCSL master sheet structure (different tab names from FedEx). The MCSL sheet ID is already in `config.py` as `GOOGLE_SHEETS_ID = "1oVtOaM2PesVR_TkuVaBKpbp_qQdmq4FQnN43Xew0FuY"`.

Sheet column structure matches FedEx master sheet (A: SI No, B: Epic, C: Scenarios, D: Description (Given/When/Then), E: Comments, F: Priority, G: Details/Transaction ID, H: Pass/Fail, I: Release).

### Pattern 5: Per-card threading — sav_running_{card.id}

**What:** Each card gets its own thread-state keys so multiple cards can run independently.
**When to use:** Step 2b AI QA Agent button per card.

```python
# Source: FedexDomainExpert/ui/pipeline_dashboard.py lines 1827-1971

_sav_running_key     = f"sav_running_{card.id}"
_sav_stop_key        = f"sav_stop_{card.id}"
_sav_stop_event_key  = f"sav_stop_event_{card.id}"
_sav_result_key      = f"sav_result_{card.id}"
_sav_prog_key        = f"sav_prog_{card.id}"
```

Thread closure captures `card.id`, `card.name`, `card.url`, `ac_text` by value before spawn.
Progress callback signature: `(sc_idx, sc_title, step_num, step_desc)` → updates `sav_prog_{card.id}`.
Result dict: `{"done": bool, "report": VerificationReport | None, "error": str | None}`.
Stop pattern: `stop_flag=lambda: _event.is_set() or st.session_state.get(_sk2, False)`.
Result-before-flag ordering: `st.session_state[_rk2] = {...}` THEN `sav_running_{id} = False` on next rerun.

### Pattern 6: Release health summary (on card load)

```python
# Source: FedexDomainExpert/ui/pipeline_dashboard.py lines 1086-1103

val_statuses = [st.session_state.get(f"validation_{c.id}") for c in cards]
n_pass   = sum(1 for v in val_statuses if v and v.overall_status == "PASS")
n_review = sum(1 for v in val_statuses if v and v.overall_status == "NEEDS_REVIEW")
n_fail   = sum(1 for v in val_statuses if v and v.overall_status == "FAIL")
approved_count = sum(1 for v in approved_store.values() if v)

hcols = st.columns(5)
hcols[0].metric("Total Cards", len(cards))
hcols[1].metric("Pass", n_pass)
hcols[2].metric("Needs Review", n_review)
hcols[3].metric("Fail", n_fail)
hcols[4].metric("Approved", approved_count)
```

### Anti-Patterns to Avoid

- **Using `sav_running` (global) instead of `sav_running_{card.id}` (per-card):** Phase 4 used a single global key; Phase 7 requires per-card threading so multiple cards work independently.
- **Calling `st.*` from inside a thread:** The thread closure must ONLY write to `st.session_state` dict keys. Never call `st.rerun()`, `st.info()`, etc. from the thread.
- **Checking `sav_running` before `_result.done`:** Always check `_result.get("done")` first; harvest results before setting `sav_running_{id} = False`.
- **Importing gspread at module top level:** Import inside `append_to_sheet()` so tests that don't have gspread installed can still import `sheets_writer`.
- **SHEET_TABS using FedEx tab names verbatim:** MCSL master sheet has different tab names — must be updated to match actual MCSL sheet or use a generic fallback list.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON fence stripping from Claude output | Custom parser | `re.sub(r"```(?:json)?", "", raw).strip()` | Handles triple-backtick fences Claude often adds |
| TC markdown → sheet rows | Custom parser | `parse_test_cases_to_rows()` in sheets_writer | Handles TC-N blocks, GWT extraction, type/priority extraction |
| Duplicate TC detection | Exact match | `check_duplicates()` with SequenceMatcher | 75% fuzzy threshold catches near-duplicates |
| Thread stop flag | `threading.Event` alone | Combined: `_event.is_set() or st.session_state.get(_sk)` | `threading.Event` can't be put in session_state (not picklable); bool flag is the fallback |
| Preamble stripping from Claude JSON | Manual index search | `re.search(r"\{.*\}", json_text, re.DOTALL)` | Claude occasionally adds preamble text before the JSON object |
| Tab detection for Sheets | Hardcoded logic | `detect_tab()` with keyword map + Claude fallback | Keyword map handles 90%+ of cases; Claude fallback handles edge cases |

---

## Complete Session State Key Inventory for Release QA Tab

### Global keys (already in `_init_state()`):
```
rqa_cards              list[TrelloCard]   — loaded cards for current release
rqa_approved           dict[card_id, bool] — approval status per card
rqa_test_cases         dict[card_id, str]  — generated TC markdown per card
rqa_release            str                 — release label e.g. "MCSLapp 1.2.3"
```

### New global keys (must add to `_init_state()` in Phase 7):
```
rqa_list_name          str    — selected Trello list name
rqa_board_id           str    — selected Trello board ID
rqa_board_name         str    — selected board display name
release_analysis       ReleaseAnalysis | None
```

### Per-card dynamic keys (NOT in _init_state — set on demand):
```
validation_{card.id}        ValidationReport — result of validate_card()
ac_suggestion_{card.id}     str             — AI-generated AC (Step 1b)
ac_saved_{card.id}          bool            — AC saved to Trello flag
ac_research_{card.id}       str             — research context used for AC gen

sav_running_{card.id}       bool            — thread is active
sav_stop_{card.id}          bool            — stop flag (bool, not Event)
sav_stop_event_{card.id}    threading.Event — Event for fast stop signalling
sav_result_{card.id}        dict            — {"done": bool, "report": ..., "error": ...}
sav_prog_{card.id}          dict            — {"pct": float, "text": str}
sav_report_{card.id}        VerificationReport — completed report (persisted after thread done)
sav_url_{card.id}           str             — app URL input widget value
sav_complexity_{card.id}    int | None      — max_scenarios selector value

force_regen_{card.id}       bool            — user clicked "Regenerate" on already-done banner
show_existing_tc_{card.id}  bool            — show existing TC expander toggle
```

---

## Common Pitfalls

### Pitfall 1: TrelloCard missing comments/attachments/checklists fields
**What goes wrong:** `generate_test_cases(card)` accesses `card.comments` and `card.attachments` which don't exist on MCSL's `TrelloCard` dataclass.
**Why it happens:** MCSL `TrelloCard` only has: `id, name, desc, url, list_id, member_ids`.
**How to avoid:** Before implementing `generate_test_cases()`, add `comments: list[str] = field(default_factory=list)`, `attachments: list[dict] = field(default_factory=list)`, `checklists: list[dict] = field(default_factory=list)` to `TrelloCard`. Also add fetch of comments from Trello API (`GET /1/cards/{id}/actions?filter=commentCard`) to `get_cards_in_list()` or provide a `get_card_comments()` helper.
**Warning signs:** `AttributeError: 'TrelloCard' object has no attribute 'comments'` at runtime.

### Pitfall 2: sav_stop_event not picklable in session_state
**What goes wrong:** Streamlit session_state serialisation fails on `threading.Event` objects.
**Why it happens:** Streamlit may attempt to pickle session_state between reruns.
**How to avoid:** Store the Event under a per-card key (`sav_stop_event_{card.id}`), NOT in `_init_state()` defaults. Only set it at thread spawn time and pop it in the thread's `finally` block. In `_init_state()`, do NOT pre-populate Event keys. Use a separate bool flag (`sav_stop_{card.id}`) as the fallback check.
**Warning signs:** `PicklingError` or `TypeError: cannot pickle 'threading.Event'` on rerun.

### Pitfall 3: SHEET_TABS using wrong MCSL tab names
**What goes wrong:** `append_to_sheet()` tries to open a tab that doesn't exist in the MCSL master sheet, raises `ValueError: Sheet tab '...' not found`.
**Why it happens:** FedEx `SHEET_TABS` lists FedEx-specific tabs; MCSL sheet has different tab names.
**How to avoid:** Start with a minimal `SHEET_TABS` list based on actual MCSL sheet tabs and a generous "Draft Plan" fallback. Confirm actual tab names before first real sheet write. The `check_duplicates()` and `append_to_sheet()` functions both handle the case where the tab is not found by doing a partial-match search through `ws_titles`.
**Warning signs:** `ValueError: Sheet tab 'Additional Services' not found` (FedEx tab name in MCSL sheet).

### Pitfall 4: Race condition — reading sav_result before it is set
**What goes wrong:** UI reads `sav_result_{card.id}["done"]` as True but `report` is None because the thread set `done` before setting `report`.
**Why it happens:** Thread interrupted between assignments.
**How to avoid:** Always set result as a single dict assignment: `st.session_state[_rk] = {"done": True, "report": report, "error": None}`. Never set `done=True` in a separate statement.
**Warning signs:** `NoneType has no attribute 'scenarios'` in UI code after thread completes.

### Pitfall 5: validate_card() called with card.desc as both desc and acceptance_criteria
**What goes wrong:** Validation quality degrades when AC has not been separately generated.
**Why it happens:** FedEx code passes `acceptance_criteria=c.desc` on load (before Step 1b).
**How to avoid:** This is intentional — on initial load the card's desc IS the AC source. After Step 1b generates AC, pass the generated AC text if available: `acceptance_criteria=st.session_state.get(f"ac_suggestion_{c.id}", c.desc or "")`.
**Warning signs:** Claude reports "AC not yet written" even after Step 1b completes.

---

## Code Examples

### validate_card() MCSL prompt (verified pattern)
```python
# Source: FedexDomainExpert/pipeline/domain_validator.py VALIDATION_PROMPT — MCSL adaptation

VALIDATION_PROMPT = dedent("""\
    You are a senior domain expert and QA lead for the MCSL (Multi-Carrier Shipping Labels)
    Shopify App built by PluginHive. The app supports multiple carriers: FedEx, UPS, DHL, USPS.

    A new Trello card has come in. Your job is to validate the card's requirements and
    acceptance criteria against the knowledge base before test cases are generated.

    Knowledge base context (retrieved for this feature):
    {context}

    ---
    Card Name: {card_name}

    Card Description / Requirements:
    {card_desc}

    Acceptance Criteria (if already written):
    {acceptance_criteria}
    ---

    Analyse carefully and respond in this EXACT JSON format (no extra text, no markdown fences):
    {{
      "overall_status": "PASS" | "NEEDS_REVIEW" | "FAIL",
      "summary": "<one sentence>",
      "requirement_gaps": [...],
      "ac_gaps": [...],
      "accuracy_issues": [...],
      "suggestions": [...],
      "kb_insights": "<key facts, constraints, known MCSL behaviours for this feature>"
    }}
""")
```

### Per-card thread launch (verified pattern)
```python
# Source: FedexDomainExpert/ui/pipeline_dashboard.py lines 1919-1971

_stop_event = threading.Event()
st.session_state[_sav_running_key]     = True
st.session_state[_sav_stop_key]        = False
st.session_state[_sav_stop_event_key]  = _stop_event
st.session_state[_sav_result_key]      = {"done": False}
st.session_state.pop(_sav_prog_key, None)

def _run_sav_thread(_url=url_val, _ac=ac_text, ...):
    try:
        report = verify_ac(
            app_url=_url, ac_text=_ac,
            stop_flag=lambda: _event.is_set() or st.session_state.get(_sk, False),
            ...
        )
        st.session_state[_rk] = {"done": True, "report": report, "error": None}
    except Exception as ex:
        st.session_state[_rk] = {"done": True, "report": None, "error": str(ex)}
    finally:
        st.session_state.pop(_sek, None)

threading.Thread(target=_run_sav_thread, daemon=True).start()
st.rerun()
```

### append_to_sheet() call from approval button
```python
# Source: FedexDomainExpert/ui/pipeline_dashboard.py (approval step)

from pipeline.sheets_writer import append_to_sheet
result = append_to_sheet(
    card_name=card.name,
    test_cases_markdown=tc_store[card.id],
    release=current_release,
)
# result = {"tab": str, "rows_added": int, "sheet_url": str, "duplicates": list}
if result["rows_added"]:
    st.success(f"Saved {result['rows_added']} test cases to sheet tab '{result['tab']}'")
if result["duplicates"]:
    st.warning(f"{len(result['duplicates'])} potential duplicate(s) found")
```

### Health summary + release analysis pattern
```python
# Source: FedexDomainExpert/ui/pipeline_dashboard.py lines 1086-1154

# On card load:
from pipeline.release_analyser import analyse_release, CardSummary as RASummary
ra_cards = [RASummary(card_id=c.id, card_name=c.name, card_desc=c.desc or "") for c in cards]
st.session_state["release_analysis"] = analyse_release(release_name=release_label, cards=ra_cards)

# In UI:
ra: ReleaseAnalysis | None = st.session_state.get("release_analysis")
if ra and not ra.error:
    risk_colors = {"LOW": "green", "MEDIUM": "orange", "HIGH": "red"}
    with st.expander(f"Release Intelligence — {ra.risk_level} RISK: {ra.risk_summary}"):
        # Show conflicts, ordering, coverage_gaps, kb_context_summary
        ...
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single `sav_running` global key | Per-card `sav_running_{card.id}` keys | Phase 7 (new) | Multiple cards can run AI QA Agent simultaneously |
| `card_processor.py` only has `get_ac_text()` | Full FedEx card_processor API added | Phase 7 (new) | Enables AC generation, TC generation, TC→Trello write |
| `tab_release` is a stub | Full Release QA tab with 4-step pipeline | Phase 7 (new) | Core value delivery |
| No `domain_validator.py` or `release_analyser.py` | Both added as new pipeline modules | Phase 7 (new) | Implements RQA-02 and RQA-05 |
| No Google Sheets write | `sheets_writer.py` added | Phase 7 (new) | Implements RQA-04 Sheets half |

**Deprecated/outdated:**
- `pipeline/card_processor.py` current implementation (get_ac_text only): will be REPLACED by Phase 7's expanded version. The `get_ac_text()` function must be KEPT alongside the new functions since the Phase 4 dashboard still calls it via `card_processor.get_ac_text()`.

---

## Open Questions

1. **MCSL master sheet tab names**
   - What we know: `config.py` has `GOOGLE_SHEETS_ID = "1oVtOaM2PesVR_TkuVaBKpbp_qQdmq4FQnN43Xew0FuY"` (same ID used for RAG-02 TC sheet ingest); actual tab names are not documented in code.
   - What's unclear: Whether MCSL sheet uses FedEx-style tab names or MCSL-specific names.
   - Recommendation: For Plan 07-04, implement `SHEET_TABS` with a conservative MCSL-specific list based on MCSL carrier/feature areas, plus a generous "Draft Plan" fallback. The partial-match search in `append_to_sheet()` protects against exact-name mismatches.

2. **TrelloCard.comments fetch from Trello API**
   - What we know: MCSL `TrelloCard` has no `comments` field; FedEx `generate_test_cases()` uses `card.comments`.
   - What's unclear: Whether to fetch comments in `get_cards_in_list()` (extra API calls per card) or lazily on demand.
   - Recommendation: Fetch comments lazily in `generate_test_cases()` via a `TrelloClient.get_card_comments(card_id)` helper that calls `GET /1/cards/{id}/actions?filter=commentCard`. Pass result as `comments` parameter.

3. **Phase 7 scope: Slack escalation / toggle notification in tab_release**
   - What we know: FedEx tab_release has extensive toggle/Slack escalation UI (lines 1241-1476). This requires `pipeline/slack_client.py` which is Phase 8.
   - What's unclear: Whether toggle detection is needed for MCSL in Phase 7.
   - Recommendation: Omit toggle detection and all Slack integration from Phase 7 tab_release implementation. Add a clear `# Phase 8: Slack DM / toggle escalation` comment placeholder.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (pytest.ini in repo root) |
| Config file | `/Users/madan/Documents/MCSLDomainExpert/.claude/worktrees/objective-archimedes/pytest.ini` |
| Quick run command | `cd /Users/madan/Documents/MCSLDomainExpert && .venv/bin/pytest tests/test_pipeline.py tests/test_dashboard.py -x -q 2>&1 | tail -5` |
| Full suite command | `cd /Users/madan/Documents/MCSLDomainExpert && .venv/bin/pytest tests/ -x -q 2>&1 | tail -10` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RQA-01 | validate_card() returns ValidationReport with correct fields | unit | `pytest tests/test_pipeline.py::test_rqa01_validate_card_returns_report -x` | ❌ Wave 0 |
| RQA-01 | validate_card() graceful on missing ANTHROPIC_API_KEY | unit | `pytest tests/test_pipeline.py::test_rqa01_validate_card_no_api_key -x` | ❌ Wave 0 |
| RQA-01 | validate_card() graceful on RAG search failure | unit | `pytest tests/test_pipeline.py::test_rqa01_validate_card_rag_failure -x` | ❌ Wave 0 |
| RQA-02 | generate_acceptance_criteria() calls Claude and returns markdown | unit | `pytest tests/test_pipeline.py::test_rqa02_generate_ac_returns_markdown -x` | ❌ Wave 0 |
| RQA-02 | generate_test_cases() formats TC prompt with card name + desc | unit | `pytest tests/test_pipeline.py::test_rqa02_generate_tc_prompt_contains_card -x` | ❌ Wave 0 |
| RQA-03 | sav_running_{card.id} set True before thread starts | unit | `pytest tests/test_dashboard.py::test_rqa03_sav_running_per_card -x` | ❌ Wave 0 |
| RQA-03 | sav_result_{card.id} written by thread before sav_running cleared | unit | `pytest tests/test_dashboard.py::test_rqa03_sav_result_before_flag -x` | ❌ Wave 0 |
| RQA-04 | write_test_cases_to_card() calls trello.add_comment | unit | `pytest tests/test_pipeline.py::test_rqa04_write_tc_calls_add_comment -x` | ❌ Wave 0 |
| RQA-04 | append_to_sheet() returns rows_added and tab | unit | `pytest tests/test_pipeline.py::test_rqa04_append_to_sheet_returns_meta -x` | ❌ Wave 0 |
| RQA-04 | parse_test_cases_to_rows() extracts Given/When/Then | unit | `pytest tests/test_pipeline.py::test_rqa04_parse_tc_rows_gwt -x` | ❌ Wave 0 |
| RQA-04 | detect_tab() returns known tab for keyword match | unit | `pytest tests/test_pipeline.py::test_rqa04_detect_tab_keyword_match -x` | ❌ Wave 0 |
| RQA-05 | analyse_release() returns ReleaseAnalysis with risk_level field | unit | `pytest tests/test_pipeline.py::test_rqa05_analyse_release_returns_report -x` | ❌ Wave 0 |
| RQA-05 | analyse_release() returns LOW risk for empty cards list | unit | `pytest tests/test_pipeline.py::test_rqa05_analyse_release_empty_cards -x` | ❌ Wave 0 |
| RQA-05 | analyse_release() graceful on missing ANTHROPIC_API_KEY | unit | `pytest tests/test_pipeline.py::test_rqa05_analyse_release_no_api_key -x` | ❌ Wave 0 |
| RQA-01/05 | tab_release replaces stub — session state keys rqa_list_name, rqa_board_id present | unit | `pytest tests/test_dashboard.py::test_rqa01_session_state_keys -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd /Users/madan/Documents/MCSLDomainExpert && .venv/bin/pytest tests/test_pipeline.py tests/test_dashboard.py -x -q 2>&1 | tail -5`
- **Per wave merge:** `cd /Users/madan/Documents/MCSLDomainExpert && .venv/bin/pytest tests/ -x -q 2>&1 | tail -10`
- **Phase gate:** Full suite green (currently 96 tests passing) before `/gsd:verify-work`

### Wave 0 Gaps — All 15 test stubs are new, none exist yet

**test_pipeline.py additions (add after existing HIST tests):**
```python
# RQA-01: domain_validator
def test_rqa01_validate_card_returns_report(): ...
def test_rqa01_validate_card_no_api_key(): ...
def test_rqa01_validate_card_rag_failure(): ...

# RQA-02: card_processor expansion
def test_rqa02_generate_ac_returns_markdown(): ...
def test_rqa02_generate_tc_prompt_contains_card(): ...

# RQA-04: card_processor + sheets_writer
def test_rqa04_write_tc_calls_add_comment(): ...
def test_rqa04_append_to_sheet_returns_meta(): ...
def test_rqa04_parse_tc_rows_gwt(): ...
def test_rqa04_detect_tab_keyword_match(): ...

# RQA-05: release_analyser
def test_rqa05_analyse_release_returns_report(): ...
def test_rqa05_analyse_release_empty_cards(): ...
def test_rqa05_analyse_release_no_api_key(): ...
```

**test_dashboard.py additions (add after existing HIST tab tests):**
```python
# RQA-01/03: Release QA tab
def test_rqa01_session_state_keys(): ...
def test_rqa03_sav_running_per_card(): ...
def test_rqa03_sav_result_before_flag(): ...
```

*(Existing test infrastructure covers all non-RQA requirements. Framework installed.)*

---

## Sources

### Primary (HIGH confidence)
- `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/domain_validator.py` — full validate_card() implementation, ValidationReport dataclass, VALIDATION_PROMPT
- `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/release_analyser.py` — full analyse_release() implementation, ReleaseAnalysis dataclass, RELEASE_ANALYSIS_PROMPT
- `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/card_processor.py` — generate_acceptance_criteria(), generate_test_cases(), write_test_cases_to_card(), format_qa_comment()
- `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/sheets_writer.py` — append_to_sheet(), detect_tab(), check_duplicates(), parse_test_cases_to_rows(), TestCaseRow, DuplicateMatch
- `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/ui/pipeline_dashboard.py` — lines 927–2100 (full Release QA tab implementation, per-card threading pattern, session state keys, health summary, release intelligence rendering)
- `/Users/madan/Documents/MCSLDomainExpert/.claude/worktrees/objective-archimedes/pipeline/trello_client.py` — TrelloCard dataclass (current state, missing comments/attachments/checklists)
- `/Users/madan/Documents/MCSLDomainExpert/.claude/worktrees/objective-archimedes/pipeline_dashboard.py` — current tab_release stub (line 846), _init_state() defaults (lines 144-176)
- `/Users/madan/Documents/MCSLDomainExpert/.claude/worktrees/objective-archimedes/config.py` — GOOGLE_SHEETS_ID, GOOGLE_CREDENTIALS_PATH, model constants confirmed

### Secondary (MEDIUM confidence)
- `.planning/REQUIREMENTS.md` — RQA-01 through RQA-05 requirements text
- `.planning/ROADMAP.md` — Phase 7 plan breakdown and success criteria
- `.planning/STATE.md` — accumulated decisions, 96 current passing tests

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries directly observed in FedEx reference implementation; gspread is the only new install
- Architecture: HIGH — exact function signatures and dataclass fields sourced from code inspection
- Pitfalls: HIGH — sourced from actual code contracts (TrelloCard missing fields, Phase 4 single-key threading pattern)
- Session state keys: HIGH — inventoried from FedEx dashboard code (lines 1241-1971) and MCSL _init_state()

**Research date:** 2026-04-17
**Valid until:** 2026-05-17 (stable — no fast-moving dependencies)

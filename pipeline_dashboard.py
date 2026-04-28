"""MCSL Domain Expert — Pipeline Dashboard.

Entry point: streamlit run pipeline_dashboard.py
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

import json
from pathlib import Path

# Load .env before any st.* calls — find_dotenv() walks up parent dirs so it
# works both from the project root and from git worktree subdirectories.
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(raise_error_if_not_found=False), override=True)

import streamlit as st

# ── Pipeline module imports ────────────────────────────────────────────────────
from pipeline.domain_validator import apply_validation_fixes, validate_card, ValidationReport
from pipeline.release_analyser import analyse_release, CardSummary as RASummary, ReleaseAnalysis
from pipeline.card_processor import (
    clear_tc_context_caches,
    generate_acceptance_criteria,
    generate_test_cases,
    get_last_ac_review,
    get_last_tc_review,
    regenerate_with_feedback,
    review_acceptance_criteria,
    review_test_cases,
    write_test_cases_to_card,
)
from pipeline.sheets_writer import (
    SHEET_TABS,
    append_to_sheet,
    check_duplicates,
    create_new_tab,
    detect_tab,
    list_sheet_tabs,
    parse_test_cases_to_rows,
)
from pipeline.smart_ac_verifier import rank_test_cases_for_execution, reverify_failed, verify_ac, verify_test_cases
from pipeline.trello_client import TrelloClient
from pipeline.slack_client import post_signoff as slack_post_signoff, slack_configured, dm_token_configured
from pipeline.bug_reporter import is_qa_name, notify_devs_of_bug
from pipeline.bug_reporter import diagnose_customer_ticket
from pipeline.locator_knowledge import get_scenario_locator_entries, update_scenario_locator_review
from pipeline.requirement_research import clear_requirement_research_cache

# ── History persistence helpers ────────────────────────────────────────────────

_HISTORY_FILE = Path(__file__).resolve().parent / "data" / "pipeline_history.json"


def _load_history() -> dict:
    """Load pipeline run history from disk. Returns {} if file absent or corrupt."""
    if _HISTORY_FILE.exists():
        try:
            return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_history(runs: dict) -> None:
    """Persist pipeline run history to disk."""
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_FILE.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")


def _update_pipeline_run(card: Any, **fields: Any) -> None:
    runs = st.session_state.get("pipeline_runs", {}) or _load_history()
    card_id = getattr(card, "id", "")
    existing = runs.get(card_id, {})
    runs[card_id] = {
        "card_name": getattr(card, "name", existing.get("card_name", "")),
        "card_url": getattr(card, "url", existing.get("card_url", "")),
        "release": st.session_state.get("rqa_release", existing.get("release", "")),
        **existing,
        **fields,
    }
    st.session_state["pipeline_runs"] = runs
    _save_history(runs)


def _sheet_tab_options() -> list[str]:
    """Best-effort live tab list from the configured Google Sheet."""
    cache_key = "live_sheet_tabs"
    error_key = "live_sheet_tabs_error"
    if cache_key not in st.session_state:
        try:
            live_tabs = list_sheet_tabs()
            st.session_state[cache_key] = live_tabs or list(SHEET_TABS)
            st.session_state[error_key] = ""
        except Exception as exc:
            st.session_state[cache_key] = list(SHEET_TABS)
            st.session_state[error_key] = str(exc)
    return list(st.session_state.get(cache_key, SHEET_TABS))


_RESEARCH_SECTION_TITLES = (
    "Customer issue summary from internal wiki:",
    "Related open Trello backlog / planning cards:",
    "Official carrier/platform findings from local RAG:",
    "MCSL app behaviour findings from local RAG:",
    "Official public web findings:",
    "PluginHive public web findings:",
)


def _split_research_sections(text: str) -> list[tuple[str, str]]:
    if not (text or "").strip():
        return []
    sections: list[tuple[str, str]] = []
    current_title = "Overview"
    current_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        is_title = line in _RESEARCH_SECTION_TITLES or (line.endswith(":") and len(line) < 100)
        if is_title:
            if current_lines:
                body = "\n".join(current_lines).strip()
                if body:
                    sections.append((current_title, body))
            current_title = line[:-1]
            current_lines = []
            continue
        current_lines.append(raw_line)
    if current_lines:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_title, body))
    return sections


def _render_research_sections(text: str) -> None:
    sections = _split_research_sections(text)
    if not sections:
        st.markdown(text)
        return
    for title, body in sections:
        if title == "Overview":
            st.markdown(body)
        else:
            st.markdown(f"**{title}**")
            st.markdown(body)


def _step_header(num: str, title: str) -> None:
    """Render a compact numbered step header."""
    st.markdown(
        f'<div class="step-header">'
        f'<div class="step-num">{num}</div>'
        f'<div class="step-title">{title}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


_CARD_STATE_PREFIXES: tuple[str, ...] = (
    "ac_suggestion_",
    "ac_saved_",
    "ac_review_",
    "ac_comment_posted_",
    "ac_skip_existing_",
    "ac_research_",
    "sav_running_",
    "sav_stop_",
    "sav_stop_event_",
    "sav_result_",
    "sav_prog_",
    "sav_report_",
    "sav_url_",
    "sav_complexity_",
    "sav_qa_answers_",
    "sav_bug_selection_",
    "sav_auto_retry_",
    "sav_limit_enabled_",
    "tc_text_",
    "tc_review_",
    "tc_saved_",
    "feedback_",
    "sheet_tab_",
    "sheet_dups_",
    "sheet_dups_tab_",
    "sheet_dup_override_",
    "sheet_tab_created_",
    "sheet_new_tab_",
    "tc_publish_tab_",
    "tc_publish_dups_",
    "tc_publish_dups_tab_",
    "tc_publish_dup_override_",
    "tc_publish_new_tab_",
    "tc_publish_created_tab_",
    "force_regen_",
    "show_existing_tc_",
    "show_dm_ac_",
    "show_ch_ac_",
    "show_dm_tc_",
    "show_ch_tc_",
    "bug_dm_sent_",
    "toggles_",
    "toggle_notified_",
    "toggle_done_",
    "toggle_sent_at_",
    "toggle_dev_notified_",
    "toggle_store_",
    "toggle_app_url_",
    "toggle_live_state_",
    "dex_history_",
    "dex_question_",
    "auto_feat_",
    "auto_res_",
    "auto_branch_",
    "rqa_auto_files_",
    "auto_exploration_",
    "auto_dry_",
    "auto_push_",
    "auto_fix_",
    "auto_qa_ctx_",
    "auto_fix_progress_",
    "auto_fix_progress_history_",
    "auto_feat_input_",
    "auto_tc_display_",
    "auto_branch_pick_",
    "auto_branch_input_",
)


def _clear_card_session_state(card_ids: list[str]) -> None:
    """Clear per-card UI state so reloading the same card starts cleanly."""
    for card_id in card_ids:
        st.session_state.pop(f"validation_{card_id}", None)
        st.session_state.pop(f"diagnosis_{card_id}", None)
        for prefix in _CARD_STATE_PREFIXES:
            st.session_state.pop(f"{prefix}{card_id}", None)
    for key in list(st.session_state.keys()):
        if any(key.startswith(prefix) for prefix in ("qa_answer_", "bug_pick_")):
            for card_id in card_ids:
                if f"_{card_id}_" in key:
                    st.session_state.pop(key, None)
                    break


def _hydrate_release_approval_state(cards: list[Any]) -> dict[str, bool]:
    """Restore per-card approval state from persisted history for loaded cards."""
    runs = st.session_state.get("pipeline_runs", {}) or _load_history()
    approved: dict[str, bool] = {}
    for card in cards:
        card_id = getattr(card, "id", "")
        run = runs.get(card_id, {}) if card_id else {}
        approved[card_id] = bool(run.get("approved_at"))
    return approved


def _get_card_run(card_id: str) -> dict[str, Any]:
    runs = st.session_state.get("pipeline_runs", {}) or _load_history()
    return runs.get(card_id, {}) if card_id else {}


def _collect_release_spec_files(cards: list[Any]) -> list[str]:
    """Collect generated spec files from session state first, then persisted run history."""
    release_specs: set[str] = set()
    for card in cards:
        card_id = getattr(card, "id", "")
        session_files = st.session_state.get(f"rqa_auto_files_{card_id}", []) or []
        for path in session_files:
            if isinstance(path, str) and path.endswith(".spec.ts"):
                release_specs.add(path)

        run = _get_card_run(card_id)
        history_files = run.get("automation_files", []) or []
        for path in history_files:
            if isinstance(path, str) and path.endswith(".spec.ts"):
                release_specs.add(path)

    return sorted(release_specs)


def _collect_release_spec_map(cards: list[Any]) -> dict[str, str]:
    """Map each card name to its generated release spec file when available."""
    card_spec_map: dict[str, str] = {}
    for card in cards:
        card_id = getattr(card, "id", "")
        card_name = getattr(card, "name", "") or ""
        session_files = st.session_state.get(f"rqa_auto_files_{card_id}", []) or []
        history_files = (_get_card_run(card_id).get("automation_files", []) or [])
        all_files = [*session_files, *history_files]
        spec_path = next(
            (path for path in all_files if isinstance(path, str) and path.endswith(".spec.ts")),
            "",
        )
        if card_name and spec_path:
            card_spec_map[card_name] = spec_path
    return card_spec_map


def _is_card_tc_published(card_id: str) -> bool:
    run = _get_card_run(card_id)
    return bool(run.get("tc_published_at") or run.get("sheet_rows") or run.get("sheet_tab"))


def _report_summary_dict(report: Any) -> dict[str, int]:
    summary = getattr(report, "summary", {}) or {}
    return {
        "pass": int(summary.get("pass", 0) or 0),
        "fail": int(summary.get("fail", 0) or 0),
        "partial": int(summary.get("partial", 0) or 0),
        "qa_needed": int(summary.get("qa_needed", 0) or 0),
    }


def _filter_duplicate_test_cases(test_cases_markdown: str, duplicates: list[Any]) -> tuple[str, int]:
    """Return markdown with duplicate TC blocks removed plus number skipped."""
    if not test_cases_markdown.strip() or not duplicates:
        return test_cases_markdown, 0

    dup_scenarios = {
        (getattr(dup, "new_scenario", "") or "").lower().strip()
        for dup in duplicates
        if getattr(dup, "new_scenario", "")
    }
    if not dup_scenarios:
        return test_cases_markdown, 0

    filtered_blocks: list[str] = []
    current_block: list[str] = []
    skip_block = False
    skipped = 0

    for line in test_cases_markdown.splitlines():
        if line.strip().startswith("### TC-"):
            if current_block and not skip_block:
                filtered_blocks.extend(current_block)
            elif current_block and skip_block:
                skipped += 1
            current_block = [line]
            title = line.split(":", 1)[-1].strip().lower()
            skip_block = any(title in scenario or scenario in title for scenario in dup_scenarios)
        else:
            current_block.append(line)

    if current_block and not skip_block:
        filtered_blocks.extend(current_block)
    elif current_block and skip_block:
        skipped += 1

    return "\n".join(filtered_blocks).strip(), skipped


def _write_release_automation_files(auto_result: Any, repo_path: str) -> list[str]:
    """Persist generated automation preview into the automation repo."""
    repo_root = Path(repo_path)
    written: list[str] = []

    for rel_path_attr, code_attr in (("pom_path", "pom_code"), ("spec_path", "spec_code")):
        rel_path = getattr(auto_result, rel_path_attr, "") or ""
        code = getattr(auto_result, code_attr, "") or ""
        if not rel_path or not code:
            continue
        abs_path = repo_root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(code, encoding="utf-8")
        written.append(rel_path)

    return written


def _merge_ai_ac_into_description(existing_desc: str, ai_ac_text: str) -> str:
    """Prepend a single managed AI AC block above the original description."""
    marker = "## AI QA Written AC"
    divider = "\n\n---\n\n"
    existing = (existing_desc or "").strip()
    ai_block = f"{marker}\n\n{ai_ac_text.strip()}".strip()

    if existing.startswith(marker):
        _head, _sep, remainder = existing.partition(divider)
        existing = remainder.strip() if _sep else ""

    return f"{ai_block}{divider}{existing}" if existing else ai_block


def _build_release_test_results_message(release: str, run_result: Any) -> str:
    _release = release or "Unlabeled release"
    lines = [
        f"*Generate Automation Script Results — {_release}*",
        "",
        f"Total: {getattr(run_result, 'total', 0)} | Passed: {getattr(run_result, 'passed', 0)} | Failed: {getattr(run_result, 'failed', 0)} | Skipped: {getattr(run_result, 'skipped', 0)}",
        f"Duration: {getattr(run_result, 'duration_ms', 0) / 1000:.1f}s",
        "",
    ]
    for spec in getattr(run_result, "specs", []) or []:
        status = getattr(spec, "status", "")
        icon = "✅" if status == "passed" else ("❌" if status == "failed" else "⏭️")
        lines.append(f"{icon} `{getattr(spec, 'file', '')}` — {getattr(spec, 'title', '')} ({getattr(spec, 'duration_ms', 0)}ms)")
    return "\n".join(lines)


def _get_repo_branches() -> list[str]:
    import config
    repo_path = getattr(config, "MCSL_AUTOMATION_REPO_PATH", "")
    if not repo_path or not Path(repo_path).exists():
        return []
    try:
        import subprocess

        result = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})
    except Exception:
        return []


def _render_report_review(report: Any, *, key_prefix: str, expanded: bool = False) -> None:
    if not report:
        return

    _summary = _report_summary_dict(report)
    _rc1, _rc2, _rc3, _rc4 = st.columns(4)
    _rc1.metric("Pass", _summary["pass"])
    _rc2.metric("Fail", _summary["fail"])
    _rc3.metric("Partial", _summary["partial"])
    _rc4.metric("QA Needed", _summary["qa_needed"])
    st.caption(f"Duration: {getattr(report, 'duration_seconds', 0.0):.1f}s")

    for _idx, _sv in enumerate(getattr(report, "scenarios", []) or [], start=1):
        _status = getattr(_sv, "status", "qa_needed")
        _badge_md = STATUS_BADGE_MD.get(_status, _status.upper())
        _carrier = getattr(_sv, "carrier", "") or ""
        _finding = getattr(_sv, "finding", "") or "No finding recorded"
        _steps = getattr(_sv, "steps", []) or []
        _title = getattr(_sv, "scenario", f"Scenario {_idx}")
        _label = f"{_badge_md} {_title}"
        if _carrier:
            _label += f" [{_carrier}]"

        with st.expander(_label, expanded=expanded and _idx == 1):
            st.markdown(_finding)
            _expectation_summary = getattr(_sv, "expectation_summary", "") or ""
            if _expectation_summary:
                with st.expander("Expected Request / Response Checks", expanded=False):
                    st.markdown(_expectation_summary)
            _setup_context_summary = getattr(_sv, "setup_context_summary", "") or ""
            if _setup_context_summary:
                with st.expander("Setup Context Used", expanded=False):
                    st.markdown(_setup_context_summary)
            _expectation_comparison = getattr(_sv, "expectation_comparison", "") or ""
            if _expectation_comparison:
                with st.expander("Expectation Match Review", expanded=False):
                    st.markdown(_expectation_comparison)
            if getattr(_sv, "qa_question", ""):
                st.caption(f"QA question: {_sv.qa_question}")
            if getattr(_sv, "bug_report", None):
                with st.expander("Bug report draft", expanded=False):
                    st.json(_sv.bug_report)
            if _steps:
                with st.expander("Execution evidence", expanded=False):
                    for _step_idx, _step in enumerate(_steps, start=1):
                        _prefix = "OK" if getattr(_step, "success", True) else "FAIL"
                        _line = f"{_step_idx}. [{_prefix}] {getattr(_step, 'action', '') or 'step'}"
                        if getattr(_step, "target", ""):
                            _line += f" -> `{_step.target}`"
                        if getattr(_step, "description", ""):
                            _line += f" — {_step.description}"
                        st.markdown(_line)
                        _network_calls = getattr(_step, "network_calls", []) or []
                        if _network_calls:
                            st.caption("API/log evidence: " + " | ".join(_network_calls[:3]))
                        _step_scr = getattr(_step, "screenshot_b64", "") or ""
                        if _step_scr:
                            try:
                                import base64
                                import io

                                st.image(io.BytesIO(base64.b64decode(_step_scr)), use_container_width=True)
                            except Exception:
                                st.caption("(step screenshot decode error)")
            _final_scr = getattr(_sv, "evidence_screenshot", "") or ""
            if _final_scr:
                with st.expander("Final screenshot", expanded=False):
                    try:
                        import base64
                        import io

                        st.image(io.BytesIO(base64.b64decode(_final_scr)), use_container_width=True)
                    except Exception:
                        st.caption("(final screenshot decode error)")


def _render_locator_learning_review(report: Any, *, card_name: str, key_prefix: str) -> None:
    if not report:
        return

    _has_any = False
    for _idx, _sv in enumerate(getattr(report, "scenarios", []) or [], start=1):
        _entries = get_scenario_locator_entries(card_name, getattr(_sv, "scenario", ""))
        if not _entries:
            continue
        _has_any = True
        _learned = [e for e in _entries if e.get("learned_this_run") and not e.get("blocked")]
        _reused = [e for e in _entries if e.get("known_before_run") and not e.get("blocked")]
        _trusted = [e for e in _entries if e.get("trusted") and not e.get("blocked")]
        _blocked = [e for e in _entries if e.get("blocked")]
        _label = f"{getattr(_sv, 'scenario', f'Scenario {_idx}')}"
        with st.expander(_label, expanded=False):
            _c1, _c2, _c3, _c4 = st.columns(4)
            _c1.metric("Reused", len(_reused))
            _c2.metric("Learned", len(_learned))
            _c3.metric("Trusted", len(_trusted))
            _c4.metric("Blocked", len(_blocked))

            if _reused:
                st.markdown("**Known locators reused**")
                for _entry in _reused[:8]:
                    st.markdown(
                        f"- `{_entry.get('selector', '')}`"
                        f" [{_entry.get('locator_source', 'runtime')}]"
                        f"{' @ ' + _entry.get('page_url', '') if _entry.get('page_url') else ''}"
                    )
            if _learned:
                st.markdown("**New locators learned this run**")
                for _entry in _learned[:8]:
                    st.markdown(
                        f"- `{_entry.get('selector', '')}`"
                        f" [{_entry.get('locator_source', 'runtime')}]"
                        f"{' @ ' + _entry.get('page_url', '') if _entry.get('page_url') else ''}"
                    )

            _review_col1, _review_col2 = st.columns(2)
            with _review_col1:
                if st.button("✅ Trust Learned Locators", key=f"{key_prefix}_trust_{_idx}", use_container_width=True):
                    _count = update_scenario_locator_review(
                        card_name,
                        getattr(_sv, "scenario", ""),
                        trusted=True,
                        blocked=False,
                        learned_only=True,
                    )
                    if _count:
                        st.success(f"Trusted {_count} locator memory item(s).")
                        st.rerun()
            with _review_col2:
                if st.button("🚫 Block Learned Locators", key=f"{key_prefix}_block_{_idx}", use_container_width=True):
                    _count = update_scenario_locator_review(
                        card_name,
                        getattr(_sv, "scenario", ""),
                        trusted=False,
                        blocked=True,
                        learned_only=True,
                    )
                    if _count:
                        st.warning(f"Blocked {_count} locator memory item(s) from reuse.")
                        st.rerun()

    if not _has_any:
        st.caption("No locator-learning data captured for this run yet.")


def _release_decision_snapshot(cards: list[Any], approved_store: dict[str, bool], backlog_lines: list[str]) -> dict[str, Any]:
    totals = {"pass": 0, "fail": 0, "partial": 0, "qa_needed": 0}
    card_statuses: list[dict[str, Any]] = []
    approved_count = 0

    for card in cards:
        _report = st.session_state.get(f"sav_report_{card.id}")
        _summary = _report_summary_dict(_report)
        for _key, _value in _summary.items():
            totals[_key] += _value
        _approved = bool(approved_store.get(card.id, False))
        if _approved:
            approved_count += 1
        _blocking_reasons = []
        if _summary["qa_needed"]:
            _blocking_reasons.append(f"{_summary['qa_needed']} QA needed")
        if _summary["fail"]:
            _blocking_reasons.append(f"{_summary['fail']} fail")
        if _summary["partial"]:
            _blocking_reasons.append(f"{_summary['partial']} partial")
        if not _approved:
            _blocking_reasons.append("not approved")
        card_statuses.append({
            "card": card,
            "approved": _approved,
            "summary": _summary,
            "blocking_reasons": _blocking_reasons,
        })

    blocking_cards = [item for item in card_statuses if item["blocking_reasons"]]
    decision = "READY"
    reasons: list[str] = []
    if cards and approved_count != len(cards):
        decision = "NOT READY"
        reasons.append(f"{len(cards) - approved_count} card(s) are not approved")
    if totals["fail"]:
        decision = "NOT READY"
        reasons.append(f"{totals['fail']} failed finding(s) remain")
    if totals["qa_needed"]:
        decision = "NOT READY"
        reasons.append(f"{totals['qa_needed']} QA-needed scenario(s) remain")
    if backlog_lines:
        decision = "NOT READY"
        reasons.append(f"{len(backlog_lines)} backlog item(s) still open")

    if not cards:
        decision = "PENDING"
        reasons = ["No release cards loaded"]
    elif not reasons and totals["partial"]:
        reasons.append(f"{totals['partial']} partial finding(s) should be reviewed")

    return {
        "decision": decision,
        "reasons": reasons,
        "totals": totals,
        "approved_count": approved_count,
        "total_cards": len(cards),
        "blocking_cards": blocking_cards,
    }


# ── Custom CSS ─────────────────────────────────────────────────────────────────
_CSS = """
<style>
:root {
    --bg-page: #f4f7fb;
    --bg-panel: rgba(255, 255, 255, 0.84);
    --bg-panel-strong: #ffffff;
    --bg-soft: #eef4fb;
    --line: #d9e4f1;
    --line-strong: #c4d4e4;
    --text-1: #142235;
    --text-2: #425466;
    --text-3: #66788a;
    --accent: #2b5c8a;
    --accent-2: #4f7aa3;
    --good: #166534;
    --warn: #8a5b00;
    --bad: #b42318;
    --info: #2b5c8a;
    --shadow: 0 16px 38px rgba(22, 50, 79, 0.10);
}

html, body, [class*="css"]  {
    font-family: "Segoe UI", "Helvetica Neue", "Arial", sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at top left, rgba(79, 122, 163, 0.12), transparent 28%),
        radial-gradient(circle at top right, rgba(43, 92, 138, 0.10), transparent 22%),
        linear-gradient(180deg, #f7faff 0%, var(--bg-page) 100%);
    color: var(--text-1);
}

[data-testid="stAppViewContainer"] > .main {
    background: transparent;
}

[data-testid="stHeader"] {
    background: rgba(255, 255, 255, 0.88);
    border-bottom: 1px solid var(--line);
    backdrop-filter: blur(12px);
}

[data-testid="block-container"] {
    padding-top: 1.2rem;
    padding-bottom: 3rem;
    max-width: 1480px;
}

section[data-testid="stSidebar"] {
    background:
        linear-gradient(180deg, rgba(255,255,255,0.92) 0%, rgba(245,248,252,0.94) 100%);
    border-right: 1px solid var(--line);
}

section[data-testid="stSidebar"] > div {
    padding-top: 1rem;
}

section[data-testid="stSidebar"] .stMarkdown h1,
section[data-testid="stSidebar"] .stMarkdown h2,
section[data-testid="stSidebar"] .stMarkdown h3,
section[data-testid="stSidebar"] .stMarkdown strong,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div {
    color: var(--text-2);
}

/* Verdict pill badges */
.badge-pass,
.badge-fail,
.badge-partial,
.badge-qa_needed {
    color: #fff;
    padding: 4px 12px;
    border-radius: 999px;
    font-weight: 700;
    font-size: 0.76rem;
    letter-spacing: 0.04em;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.08);
}
.badge-pass      { background: linear-gradient(135deg, #15803d, #22c55e); }
.badge-fail      { background: linear-gradient(135deg, #b42318, #dc2626); }
.badge-partial   { background: linear-gradient(135deg, #a16207, #d97706); }
.badge-qa_needed { background: linear-gradient(135deg, #2b5c8a, #4f7aa3); }

/* Scenario result cards */
.scenario-card {
    border: 1px solid var(--line);
    border-left: 4px solid var(--accent);
    background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(247,250,253,0.96));
    border-radius: 16px;
    padding: 14px 16px;
    margin-bottom: 12px;
    box-shadow: var(--shadow);
}
.scenario-card.pass      { border-left-color: var(--good); }
.scenario-card.fail      { border-left-color: var(--bad); }
.scenario-card.partial   { border-left-color: var(--warn); }
.scenario-card.qa_needed { border-left-color: var(--info); }

/* Header */
.app-header {
    color: var(--text-1);
    font-size: 2rem;
    font-weight: 800;
    letter-spacing: -0.04em;
}
.app-subtitle {
    color: var(--text-3);
    font-size: 0.98rem;
    margin-top: -6px;
}

.pipeline-header {
    position: relative;
    overflow: hidden;
    background:
        radial-gradient(circle at top right, rgba(255,255,255,0.14), transparent 22%),
        linear-gradient(135deg, #13283f 0%, #1f4568 58%, #2d638f 100%);
    border: 1px solid rgba(255,255,255,0.10);
    box-shadow: var(--shadow);
    padding: 24px 26px;
    border-radius: 22px;
    margin-bottom: 18px;
}
.pipeline-header::after {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(120deg, transparent 0%, rgba(255,255,255,0.03) 50%, transparent 100%);
    pointer-events: none;
}
.pipeline-header h1 {
    color: #ffffff;
    font-weight: 800;
    letter-spacing: -0.04em;
    margin: 0;
}
.pipeline-header p {
    color: rgba(255,255,255,0.78);
    margin: 6px 0 0 0;
    max-width: 70ch;
}
.pipeline-header h1,
.pipeline-header h1 *,
.pipeline-header p,
.pipeline-header p * {
    color: #ffffff !important;
    opacity: 1 !important;
    text-shadow: 0 1px 2px rgba(10, 24, 38, 0.18);
}
section[data-testid="stSidebar"] .pipeline-header h1,
section[data-testid="stSidebar"] .pipeline-header h1 *,
section[data-testid="stSidebar"] .pipeline-header p,
section[data-testid="stSidebar"] .pipeline-header p * {
    color: #ffffff !important;
}

/* Sidebar status badges */
.status-badge {
    display: inline-flex;
    align-items: center;
    width: 100%;
    padding: 7px 12px;
    border-radius: 999px;
    font-size: 0.82rem;
    font-weight: 650;
    margin-bottom: 6px;
    border: 1px solid rgba(255,255,255,0.05);
}
.status-ok   { background: rgba(49, 194, 113, 0.12); color: #98efbc; }
.status-warn { background: #fff4cc; color: #8a5b00; border-color: #f0d98e; }
.status-err  { background: #fee4e2; color: #b42318; border-color: #f3b8b4; }
.status-ok   { background: #dcfce7; color: #166534; border-color: #b7ebc6; }

/* Pipeline step chips */
.step-chip {
    display: inline-block;
    background: linear-gradient(180deg, #f1f6fd 0%, #e5eef8 100%);
    color: #16324f;
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 4px 12px;
    font-size: 0.78rem;
    font-weight: 700;
    margin-right: 6px;
    margin-bottom: 4px;
}

/* Risk level badges */
.risk-low,
.risk-medium,
.risk-high {
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
}
.risk-low    { background:#d1fae5; color:#065f46; }
.risk-medium { background:#fef3c7; color:#92400e; }
.risk-high   { background:#fee2e2; color:#991b1b; }

/* Card step headers */
.step-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 14px 0 10px 0;
}
.step-num {
    background: linear-gradient(180deg, var(--accent-2) 0%, var(--accent) 100%);
    color: #ffffff;
    border-radius: 50%;
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    font-size: 0.82rem;
    flex-shrink: 0;
    box-shadow: 0 6px 18px rgba(103, 211, 176, 0.22);
}
.step-title {
    color: var(--text-1);
    font-weight: 700;
    font-size: 1rem;
    letter-spacing: -0.01em;
}

/* Pipeline flow bar */
.pipeline-flow {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    margin: 12px 0 14px 0;
}
.pf-step {
    background: #f1f5f9;
    color: #475569;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
    border: 1px solid #cbd5e1;
}
.pf-step.done   { background: #d1fae5; border-color: #6ee7b7; color: #065f46; }
.pf-step.active { background: #e0e7ff; border-color: #a5b4fc; color: #3730a3; }
.pf-arrow { color: #94a3b8; font-size: 0.9rem; }

/* Bug severity badges */
.sev-p1, .sev-p2, .sev-p3, .sev-p4 {
    color: #fff;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 800;
}
.sev-p1 { background: linear-gradient(135deg, #c03b3b, #ef4444); }
.sev-p2 { background: linear-gradient(135deg, #de6e1b, #f97316); }
.sev-p3 { background: linear-gradient(135deg, #c7a30f, #eab308); }
.sev-p4 { background: linear-gradient(135deg, #1ea45d, #22c55e); }

/* Streamlit surfaces */
[data-testid="stMetric"] {
    background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(247,250,253,0.95));
    border: 1px solid var(--line);
    border-radius: 18px;
    box-shadow: var(--shadow);
    padding: 0.3rem 0.4rem;
}
[data-testid="metric-container"] {
    background: transparent;
    border-radius: 14px;
    padding: 12px;
}
[data-testid="metric-container"] label,
[data-testid="metric-container"] [data-testid="stMetricLabel"] {
    color: var(--text-3) !important;
    font-weight: 650 !important;
    letter-spacing: 0.02em;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: var(--text-1) !important;
}
[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] *,
[data-testid="stMetricValue"],
[data-testid="stMetricValue"] * {
    color: var(--text-1) !important;
    opacity: 1 !important;
}
[data-testid="stMetricLabel"] {
    color: var(--text-3) !important;
}

[data-testid="stExpander"] {
    border: 1px solid var(--line);
    background: rgba(255,255,255,0.92);
    border-radius: 16px;
    box-shadow: var(--shadow);
    overflow: hidden;
}
[data-testid="stExpander"] details summary {
    background: linear-gradient(180deg, rgba(248, 251, 255, 0.96) 0%, rgba(241, 246, 251, 0.96) 100%);
    color: var(--text-1);
    font-weight: 650;
}

div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div,
.stTextInput input,
.stTextArea textarea,
.stNumberInput input {
    background: rgba(255,255,255,0.96) !important;
    color: var(--text-1) !important;
    border: 1px solid var(--line) !important;
    border-radius: 14px !important;
}

.stTextArea textarea {
    line-height: 1.45;
}

.stSelectbox label,
.stTextInput label,
.stTextArea label,
.stMultiSelect label,
.stRadio label,
.stCheckbox label,
.stToggle label {
    color: var(--text-2) !important;
    font-weight: 650 !important;
}
[data-testid="stCheckbox"] label,
[data-testid="stCheckbox"] label p,
[data-testid="stToggle"] label,
[data-testid="stToggle"] label p,
[data-testid="stRadio"] label,
[data-testid="stRadio"] label p {
    color: var(--text-1) !important;
    opacity: 1 !important;
}
[data-testid="stToggle"] [role="switch"] {
    background: #d7dee8 !important;
    border: 1px solid #8fa6bf !important;
    box-shadow: inset 0 1px 2px rgba(20, 34, 53, 0.10);
    opacity: 1 !important;
}
[data-testid="stToggle"] [role="switch"][aria-checked="true"] {
    background: linear-gradient(90deg, #2b5c8a 0%, #4f7aa3 100%) !important;
    border-color: #2b5c8a !important;
    opacity: 1 !important;
}
[data-testid="stToggle"] [role="switch"] > div {
    background: #ffffff !important;
    border: 1px solid rgba(20, 34, 53, 0.10) !important;
    box-shadow: 0 1px 4px rgba(20, 34, 53, 0.22) !important;
    opacity: 1 !important;
}
[data-testid="stToggle"] [role="switch"]::before,
[data-testid="stToggle"] [role="switch"]::after {
    opacity: 1 !important;
}

.stButton > button,
[data-testid="stDownloadButton"] > button {
    border-radius: 14px !important;
    border: 1px solid var(--line) !important;
    background: linear-gradient(180deg, #ffffff 0%, #f5f8fc 100%) !important;
    color: var(--text-1) !important;
    font-weight: 700 !important;
    letter-spacing: 0.01em;
    box-shadow: 0 10px 24px rgba(0,0,0,0.22);
}
.stButton > button,
.stButton > button span,
.stButton > button p,
.stButton > button div,
.stButton > button svg,
[data-testid="stDownloadButton"] > button,
[data-testid="stDownloadButton"] > button span,
[data-testid="stDownloadButton"] > button p,
[data-testid="stDownloadButton"] > button div,
[data-testid="stDownloadButton"] > button svg {
    color: var(--text-1) !important;
    fill: var(--text-1) !important;
    stroke: var(--text-1) !important;
    opacity: 1 !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(180deg, #214b73 0%, #173451 100%) !important;
    color: #ffffff !important;
    border-color: #173451 !important;
}
.stButton > button[kind="primary"],
.stButton > button[kind="primary"] span,
.stButton > button[kind="primary"] p,
.stButton > button[kind="primary"] div,
.stButton > button[kind="primary"] svg {
    color: #ffffff !important;
    fill: #ffffff !important;
    stroke: #ffffff !important;
    opacity: 1 !important;
}
.stButton > button:hover,
[data-testid="stDownloadButton"] > button:hover {
    border-color: var(--accent-2) !important;
    transform: translateY(-1px);
}

button[data-baseweb="tab"] {
    font-weight: 700 !important;
    color: var(--text-3) !important;
    border-radius: 999px !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
}
button[data-baseweb="tab"],
button[data-baseweb="tab"] span,
button[data-baseweb="tab"] p,
button[data-baseweb="tab"] div,
button[data-baseweb="tab"] svg {
    color: var(--text-3) !important;
    fill: var(--text-3) !important;
    stroke: var(--text-3) !important;
    opacity: 1 !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #16324f !important;
    background: linear-gradient(180deg, #e8f1fa 0%, #dce8f5 100%) !important;
    border: 1px solid var(--line-strong) !important;
}
button[data-baseweb="tab"][aria-selected="true"],
button[data-baseweb="tab"][aria-selected="true"] span,
button[data-baseweb="tab"][aria-selected="true"] p,
button[data-baseweb="tab"][aria-selected="true"] div,
button[data-baseweb="tab"][aria-selected="true"] svg {
    color: #16324f !important;
    fill: #16324f !important;
    stroke: #16324f !important;
}

[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 0.35rem;
    border-bottom: 1px solid var(--line);
    flex-wrap: wrap !important;
    overflow: visible !important;
    scrollbar-width: none;
}
[data-testid="stTabs"] [data-baseweb="tab-list"]::-webkit-scrollbar {
    display: none;
}
[data-testid="stTabs"] {
    overflow: visible !important;
}
[data-testid="stTabs"] [role="tablist"] {
    overflow: visible !important;
}

.stAlert {
    border-radius: 16px !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
}

.stProgress > div > div > div > div {
    background: linear-gradient(90deg, var(--accent), var(--accent-2)) !important;
}

.stMarkdown p, .stMarkdown li, .stCaption, small {
    color: var(--text-2);
}

.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {
    color: var(--text-1);
    letter-spacing: -0.02em;
}

code, pre, .stCodeBlock {
    font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace !important;
}

a {
    color: #9cdcf5 !important;
}

[data-testid="stVerticalBlock"] > [style*="flex-direction: column;"] > div:has(> [data-testid="stMetric"]),
[data-testid="stVerticalBlock"] > [style*="flex-direction: column;"] > div:has(> [data-testid="stExpander"]) {
    border-radius: 18px;
}
</style>
"""

# Verdict badge HTML helpers (for CSS pill badges in unsafe_allow_html blocks)
STATUS_BADGE: dict[str, str] = {
    "pass":      '<span class="badge-pass">PASS</span>',
    "fail":      '<span class="badge-fail">FAIL</span>',
    "partial":   '<span class="badge-partial">PARTIAL</span>',
    "qa_needed": '<span class="badge-qa_needed">QA NEEDED</span>',
}

# Streamlit markdown fallback (used in expander titles where unsafe_allow_html is unavailable)
STATUS_BADGE_MD: dict[str, str] = {
    "pass":      ":green[PASS]",
    "fail":      ":red[FAIL]",
    "partial":   ":orange[PARTIAL]",
    "qa_needed": ":blue[QA NEEDED]",
}


# ── Session state ──────────────────────────────────────────────────────────────

def _init_state() -> None:
    """Initialise all session state keys. Idempotent."""
    defaults: dict[str, Any] = {
        # Phase 4 — preserved
        "sav_running": False,
        "sav_stop":    threading.Event(),
        "sav_result":  None,
        "sav_prog":    {"current": 0, "total": 0, "label": ""},
        # Phase 5 — new
        "pipeline_runs":          {},
        "trello_connected":       False,
        "ac_drafts_loaded":       False,
        "code_paths_initialized": False,
        "rqa_cards":              [],
        "rqa_approved":           {},
        "rqa_test_cases":         {},
        "rqa_release":            "",
        # Phase 6 — User Story tab
        "us_request_input":  "",
        "us_result":         "",
        "us_history":        [],
        "us_card_title":     "",
        "us_list_mode":      "Existing list",
        "us_existing_list":  "",
        "us_new_list_name":  "",
        "us_assign_members": [],
        # Phase 6 — Move Cards tab (tab_devdone)
        "dd_list_select":  "Dev Done",
        "dd_move_target":  "Ready for QA",
        "dd_cards":        [],
        "dd_checked":      {},
        "dd_select_all":   False,
        # Phase 7 — Release QA tab
        "rqa_list_name":        "",
        "rqa_board_id":         "",
        "rqa_board_name":       "",
        "release_analysis":     None,
        "rqa_preview_cards":    [],   # lightweight card list from selected list (names only, no validation)
        "rqa_preview_list_id":  "",   # list id used for the last preview fetch

        # Phase 7b — Handoff Docs tab
        "hd_cards":        [],
        "hd_list_name":    "",
        "hd_board_id":     "",
        "hd_board_name":   "",
        # Phase 8 — Sign Off tab
        "signoff_message": "",
        "signoff_sent":    False,
        # Phase 9 — Write Automation tab
        "auto_feature":        "",
        "auto_test_cases":     "",
        "auto_result":         None,
        "auto_exploration":    None,
        "auto_explore_running": False,
        # Phase 10 — Run Automation tab
        "run_running":        False,
        "run_result":         None,
        "run_selected_specs": [],
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # Load history from disk on first initialisation
    if not st.session_state.get("pipeline_runs"):
        st.session_state["pipeline_runs"] = _load_history()


# ── Progress callback (written to by worker thread — no st.* calls) ────────────

def _progress_cb(
    scenario_idx: int,
    scenario_title: str,
    step_num: int,
    step_desc: str,
) -> None:
    """Update sav_prog in session state. Called from background thread."""
    total = st.session_state.sav_prog.get("total", 0)
    st.session_state.sav_prog = {
        "current": scenario_idx,
        "total":   total,
        "label":   f"[{scenario_idx}/{total}] {scenario_title[:50]} — {step_desc}",
    }


# ── Stop button callback factory ───────────────────────────────────────────────

def _make_stop_callback(session_state: Any):
    """Return an on_click callback that sets the stop event on the given session_state."""
    def _stop():
        session_state.sav_stop.set()
    return _stop


# ── Thread worker (implemented in 04-02) ──────────────────────────────────────

def _run_pipeline(
    ac_text: str,
    card_name: str,
    headless: bool,
    max_scenarios: int,
) -> None:
    """Worker function — runs in background thread. MUST NOT call any st.* functions."""
    from pipeline.smart_ac_verifier import verify_ac  # lazy import keeps startup fast

    try:
        report = verify_ac(
            ac_text=ac_text,
            card_name=card_name,
            stop_flag=lambda: st.session_state.sav_stop.is_set(),
            progress_cb=_progress_cb,
            headless=headless,
            max_scenarios=max_scenarios,
        )
        # CRITICAL: set result FIRST, then clear running flag (avoid race condition)
        st.session_state.sav_result = report.to_dict()
    except Exception as exc:  # noqa: BLE001
        st.session_state.sav_result = {
            "error": str(exc),
            "card_name": card_name,
            "total": 0,
            "summary": {"pass": 0, "fail": 0, "partial": 0, "qa_needed": 0},
            "duration_seconds": 0.0,
            "scenarios": [],
        }
    finally:
        st.session_state.sav_running = False


# ── Thread launch (implemented in 04-02) ──────────────────────────────────────

def start_run(
    ac_text: str,
    card_name: str,
    n_scenarios: int = 1,
    headless: bool = True,
    max_scenarios: int = 10,
) -> None:
    """Launch verify_ac() in a background daemon thread."""
    st.session_state.sav_running = True
    st.session_state.sav_stop.clear()
    st.session_state.sav_result = None
    st.session_state.sav_prog = {
        "current": 0,
        "total":   n_scenarios,
        "label":   "Starting\u2026",
    }
    t = threading.Thread(
        target=_run_pipeline,
        args=(ac_text, card_name, headless, max_scenarios),
        daemon=True,
    )
    t.start()


# ── Report render (implemented in 04-04) ──────────────────────────────────────

def render_report(result: dict) -> None:
    """Render VerificationReport.to_dict() as styled scenario cards."""
    import base64
    import io

    # Handle error result (from _run_pipeline exception handler)
    if "error" in result:
        st.error(f"Pipeline error: {result['error']}")
        return

    # ── Summary header ──────────────────────────────────────────────────────
    st.subheader(f"Report: {result.get('card_name', 'Unknown card')}")
    summary = result.get("summary", {})
    dur = result.get("duration_seconds", 0.0)

    cols = st.columns(5)
    cols[0].metric("Total",     result.get("total", 0))
    cols[1].metric("Pass",      summary.get("pass", 0))
    cols[2].metric("Fail",      summary.get("fail", 0))
    cols[3].metric("Partial",   summary.get("partial", 0))
    cols[4].metric("QA Needed", summary.get("qa_needed", 0))
    st.caption(f"Duration: {dur:.1f}s")
    st.divider()

    # ── Per-scenario cards ──────────────────────────────────────────────────
    for sc in result.get("scenarios", []):
        status       = sc.get("status", "qa_needed")
        badge_md     = STATUS_BADGE_MD.get(status, status.upper())
        scenario_title = sc.get("scenario", "")[:80]

        with st.expander(f"{badge_md}  {scenario_title}"):
            # Badge pill (HTML — unsafe_allow_html works inside expander body)
            badge_html  = STATUS_BADGE.get(status, f"<span>{status.upper()}</span>")
            carrier_tag = sc.get("carrier", "")
            finding     = sc.get("finding", "No finding recorded")
            steps_taken = sc.get("steps_taken", 0)

            card_html = (
                f'<div class="scenario-card {status}">'
                f"  {badge_html}"
                + (f"  &nbsp;&nbsp;<strong>{carrier_tag}</strong>" if carrier_tag else "")
                + '  <hr style="margin:8px 0; border-color:#2a2d3a;">'
                f'  <p style="margin:4px 0;">{finding}</p>'
                f"</div>"
            )
            st.markdown(card_html, unsafe_allow_html=True)
            st.caption(f"Steps taken: {steps_taken}")

            # Screenshot thumbnail
            scr = sc.get("evidence_screenshot", "")
            if scr:
                try:
                    img_bytes = base64.b64decode(scr)
                    st.image(io.BytesIO(img_bytes), use_container_width=True)
                except Exception:  # noqa: BLE001
                    st.caption("(screenshot decode error)")


# ── Status badge helper ───────────────────────────────────────────────────────

def _status_badge(label: str, ok: bool, err_hint: str = "") -> str:
    """Return an HTML status badge string. Rendered via st.markdown(unsafe_allow_html=True)."""
    if ok:
        return f'<div class="status-badge status-ok">✅ &nbsp;{label}</div>'
    else:
        hint = f" — {err_hint}" if err_hint else ""
        return f'<div class="status-badge status-err">❌ &nbsp;{label}{hint}</div>'


@st.cache_data(ttl=60)
def _get_trello_boards() -> list[tuple[str, str]]:
    """Cached fetch of visible Trello boards as (name, id) pairs."""
    from pipeline.trello_client import TrelloClient
    return [(b.name, b.id) for b in TrelloClient().get_boards()]


@st.cache_data(ttl=60)
def _get_board_lists(board_id: str) -> list[tuple[str, str]]:
    """Cached fetch of board lists as (name, id) pairs."""
    from pipeline.trello_client import TrelloClient
    return [(l.name, l.id) for l in TrelloClient(board_id=board_id).get_lists()]


def _select_trello_board(label: str, key_prefix: str) -> tuple[str, str]:
    """Render a Trello board selector and return (board_id, board_name)."""
    all_boards = _get_trello_boards()
    if not all_boards:
        return "", ""

    import os

    default_board_id = (
        st.session_state.get(f"{key_prefix}_board_id")
        or st.session_state.get("rqa_board_id")
        or os.getenv("TRELLO_BOARD_ID", "")
    )
    default_idx = next(
        (i for i, (_, board_id) in enumerate(all_boards) if board_id == default_board_id),
        0,
    )
    board_names = [name for name, _ in all_boards]
    selected_board_name = st.selectbox(
        label,
        board_names,
        index=default_idx,
        key=f"{key_prefix}_board_select",
    )
    selected_board_id = next(board_id for name, board_id in all_boards if name == selected_board_name)
    st.session_state[f"{key_prefix}_board_id"] = selected_board_id
    st.session_state[f"{key_prefix}_board_name"] = selected_board_name
    return selected_board_id, selected_board_name


def _extract_release_label(list_name: str) -> str:
    """Extract a release-ish label from a Trello list name."""
    import re

    if not list_name:
        return ""
    match = re.search(r"(mcsl\w*\s+[\d.]+)", list_name, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"(v?[\d]+\.[\d]+[\d.]*)", list_name)
    if match:
        return match.group(1)
    return list_name


def _dedupe_cards(cards: list[Any]) -> list[Any]:
    """Deduplicate Trello cards by id while preserving order."""
    seen: set[str] = set()
    deduped: list[Any] = []
    for card in cards or []:
        card_id = getattr(card, "id", "")
        if card_id and card_id in seen:
            continue
        if card_id:
            seen.add(card_id)
        deduped.append(card)
    return deduped


def _card_request_payload(card: Any) -> str:
    """Build a single text payload from Trello card fields for diagnosis/research."""
    return "\n\n".join(
        part for part in [
            getattr(card, "name", "") or "",
            getattr(card, "desc", "") or "",
            "\n".join(getattr(card, "comments", []) or []),
            "\n".join(
                f"{cl.get('name', '')}: " + ", ".join(
                    item.get("name", "")
                    for item in cl.get("items", [])
                    if item.get("name")
                )
                for cl in (getattr(card, "checklists", []) or [])
            ),
        ] if part.strip()
    )


def _analyse_loaded_card(card: Any) -> tuple[str, ValidationReport, dict | None]:
    validation = validate_card(
        card_name=card.name,
        card_desc=card.desc or "",
        acceptance_criteria=card.desc or "",
    )
    diagnosis = _normalise_card_diagnosis(
        card,
        diagnose_customer_ticket(_card_request_payload(card)),
    )
    return getattr(card, "id", ""), validation, diagnosis


def _clear_generation_context_caches() -> None:
    clear_requirement_research_cache()
    clear_tc_context_caches()


def _normalise_card_diagnosis(card: Any, diagnosis: dict | None) -> dict | None:
    """Apply deterministic carrier-scope correction from visible card evidence."""
    if not diagnosis:
        return diagnosis
    try:
        from pipeline.carrier_knowledge import detect_carrier_scope

        _summary = diagnosis.get("summary", "") if isinstance(diagnosis, dict) else ""
        _evidence = "\n".join(diagnosis.get("evidence", []) or []) if isinstance(diagnosis, dict) else ""
        _next_checks = "\n".join(diagnosis.get("next_checks", []) or []) if isinstance(diagnosis, dict) else ""
        _strategy = "\n".join(diagnosis.get("suggested_test_strategy", []) or []) if isinstance(diagnosis, dict) else ""
        combined_text = "\n".join(
            part for part in [
                getattr(card, "name", "") or "",
                getattr(card, "desc", "") or "",
                "\n".join(getattr(card, "comments", []) or []),
                " ".join(getattr(card, "labels", []) or []),
                _summary,
                _evidence,
                _next_checks,
                _strategy,
            ] if part.strip()
        )
        scope = detect_carrier_scope(
            getattr(card, "name", "") or "",
            getattr(card, "desc", "") or "",
            "\n".join(getattr(card, "comments", []) or []),
            " ".join(getattr(card, "labels", []) or []),
            _summary,
            _evidence,
            _next_checks,
            _strategy,
        )
        diagnosis = dict(diagnosis)
        if scope.scope == "carrier_specific":
            diagnosis["carrier_scope"] = "carrier_specific"
            diagnosis["detected_carriers"] = [profile.canonical_name for profile in scope.carriers]
        combined_lower = combined_text.lower()
        if any(token in combined_lower for token in ("customs", "label", "api", "request builder", "request builders", "carrier request", "request payload")):
            diagnosis["likely_root_cause"] = "request_or_label_api"
        return diagnosis
    except Exception:
        return diagnosis


def _analyze_loaded_cards(cards: list[Any], release_name: str) -> None:
    """Run expensive card/release analysis on demand instead of during load."""
    for card in cards:
        if f"validation_{card.id}" not in st.session_state:
            st.session_state[f"validation_{card.id}"] = validate_card(
                card_name=card.name,
                card_desc=card.desc or "",
                acceptance_criteria=st.session_state.get(f"ac_suggestion_{card.id}", card.desc or ""),
            )
        if (card.desc or "").strip() and f"ac_review_{card.id}" not in st.session_state:
            st.session_state[f"ac_review_{card.id}"] = review_acceptance_criteria(
                raw_request=card.name,
                ac_markdown=card.desc or "",
            )
        _existing_tc_markdown = _load_existing_tc_markdown(card)
        if _existing_tc_markdown and f"tc_review_{card.id}" not in st.session_state:
            st.session_state[f"tc_review_{card.id}"] = review_test_cases(
                card_name=card.name,
                card_desc=card.desc or "",
                test_cases_markdown=_existing_tc_markdown,
            )
        if f"diagnosis_{card.id}" not in st.session_state:
            st.session_state[f"diagnosis_{card.id}"] = _normalise_card_diagnosis(
                card,
                diagnose_customer_ticket(_card_request_payload(card)),
            )

    ra_cards = [
        RASummary(
            card_id=c.id,
            card_name=c.name,
            card_desc=c.desc or "",
            card_comments=getattr(c, "comments", []) or [],
            card_labels=getattr(c, "labels", []) or [],
            card_checklists=getattr(c, "checklists", []) or [],
        )
        for c in cards
    ]
    st.session_state["release_analysis"] = analyse_release(
        release_name=release_name,
        cards=ra_cards,
    )


def _find_existing_tc_comment(card: Any) -> str:
    """Return the first Trello comment that looks like saved QA test cases."""
    for comment in getattr(card, "comments", []) or []:
        if "📋 **QA Test Cases" in comment or "## MCSL QA Test Cases" in comment:
            return comment
    return ""


def _looks_like_tc_markdown(text: str) -> bool:
    value = (text or "").strip()
    return bool(
        re.search(r"^#{2,3}\s+TC-\d+", value, flags=re.MULTILINE)
        and re.search(r"\*\*Type:\*\*", value)
    )


def _load_existing_tc_markdown(card: Any) -> str:
    """Load full TC markdown from history first, then fall back to legacy detailed comments."""
    runs = st.session_state.get("pipeline_runs") or _load_history()
    if isinstance(runs, dict):
        run = runs.get(getattr(card, "id", ""), {}) or {}
        history_tc = run.get("test_cases", "")
        if _looks_like_tc_markdown(history_tc):
            return history_tc
    for comment in getattr(card, "comments", []) or []:
        if _looks_like_tc_markdown(comment):
            return comment
    return ""


def _render_slack_channel_panel(
    *,
    panel_key: str,
    card_name: str,
    content_text: str,
    content_label: str,
    card_url: str = "",
) -> None:
    from pipeline.slack_client import list_slack_channels, post_content_to_slack_channel

    if not dm_token_configured():
        st.warning("SLACK_BOT_TOKEN is not set. Channel posting requires a bot token.")
        return

    cache_key = "slack_channels_cache"
    if cache_key not in st.session_state:
        channels, err, note = list_slack_channels()
        st.session_state[cache_key] = (channels, err, note)
    channels, err, note = st.session_state[cache_key]
    if err:
        st.error(f"Slack error: {err}")
        return
    if note:
        st.caption(note)
    if not channels:
        st.info("No Slack channels available to this bot.")
        return

    options = {
        f"{'🔒' if c.get('is_private') else '#'} {c['name']}": c["id"]
        for c in channels
    }
    col_sel, col_refresh = st.columns([3, 1])
    with col_sel:
        selected = st.selectbox(
            "Select channel",
            options=list(options.keys()),
            key=f"{panel_key}_channel_select",
        )
    with col_refresh:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Refresh", key=f"{panel_key}_channel_refresh", use_container_width=True):
            st.session_state.pop(cache_key, None)
            st.rerun()

    if st.button(f"📢 Post {content_label}", key=f"{panel_key}_channel_send", use_container_width=True):
        result = post_content_to_slack_channel(
            channel_id=options[selected],
            card_name=card_name,
            content_text=(content_text + (f"\n\nCard: {card_url}" if card_url else "")),
            content_label=content_label,
        )
        if result.get("ok"):
            st.success(f"{content_label} posted to Slack channel.")
        else:
            st.error(f"Slack upload failed: {result.get('error')}")


def _render_slack_dm_panel(
    *,
    panel_key: str,
    card_name: str,
    content_text: str,
    content_label: str,
) -> None:
    from pipeline.slack_client import search_slack_users, send_ac_dm

    if not dm_token_configured():
        st.warning("SLACK_BOT_TOKEN is not set. Slack DM requires a bot token.")
        return

    pool_key = f"{panel_key}_user_pool"
    if pool_key not in st.session_state:
        st.session_state[pool_key] = {}

    col_query, col_find = st.columns([3, 1])
    with col_query:
        query = st.text_input(
            "Search member",
            key=f"{panel_key}_user_query",
            placeholder="Search by name",
        )
    with col_find:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔍 Search", key=f"{panel_key}_user_search", use_container_width=True) and query.strip():
            users, err = search_slack_users(query.strip())
            if err:
                st.error(f"Slack error: {err}")
            elif not users:
                st.info("No users found.")
            else:
                for user in users:
                    real = user.get("real_name", "") or user.get("name", "")
                    display = user.get("display_name", "") or real
                    st.session_state[pool_key][f"{real} (@{display})"] = user["id"]

    pool = st.session_state[pool_key]
    if not pool:
        return
    selected = st.multiselect(
        "Recipients",
        options=list(pool.keys()),
        key=f"{panel_key}_user_select",
    )
    if st.button("✖ Clear search results", key=f"{panel_key}_user_clear"):
        st.session_state[pool_key] = {}
        st.rerun()
    if selected and st.button(f"📨 Send {content_label}", key=f"{panel_key}_user_send", use_container_width=True):
        result = send_ac_dm(
            user_ids=[pool[item] for item in selected],
            card_name=card_name,
            ac_text=content_text,
            content_label=content_label,
        )
        if result.get("ok"):
            st.success(f"{content_label} sent to {result.get('sent_count', 0)} Slack recipient(s).")
        else:
            st.error(f"Slack DM failed: {result.get('error')}")


# ── Page config ───────────────────────────────────────────────────────────────
# MUST be the first Streamlit call

st.set_page_config(
    page_title="MCSL QA Pipeline",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(_CSS, unsafe_allow_html=True)


def _summarise_tc_counts(card_name: str, tc_markdown: str) -> tuple[int, int, int, int]:
    """Return (total, positive, negative, edge) counts parsed from TC markdown."""
    import re
    blocks = re.split(r"(?=^#{2,3}\s+TC-\d+)", tc_markdown, flags=re.MULTILINE)
    pos = neg = edge = 0
    for block in blocks:
        block = block.strip()
        if not block or not re.match(r"^#{2,3}\s+TC-\d+", block):
            continue
        type_match = re.search(r"\*\*Type:\*\*\s*(Positive|Negative|Edge)", block, re.IGNORECASE)
        tc_type = type_match.group(1).capitalize() if type_match else "Positive"
        if tc_type == "Positive":
            pos += 1
        elif tc_type == "Negative":
            neg += 1
        else:
            edge += 1
    return pos + neg + edge, pos, neg, edge


# ── Main entry point ──────────────────────────────────────────────────────────

def main() -> None:
    """Main app — sidebar + tab scaffold. Implemented fully in plans 05-02 and 05-03."""
    import os
    import config  # lazy import — keeps dotenv load inside main() only

    _init_state()

    # ── Connection check flags ──────────────────────────────────────────────
    api_ok    = bool(config.ANTHROPIC_API_KEY)
    trello_ok = all([
        os.getenv("TRELLO_API_KEY"),
        os.getenv("TRELLO_TOKEN"),
    ])
    slack_ok  = bool(
        os.getenv("SLACK_WEBHOOK_URL", "").strip()
        or (os.getenv("SLACK_BOT_TOKEN", "").strip() and os.getenv("SLACK_CHANNEL", "").strip())
    )
    sheets_ok = bool(os.path.exists(config.GOOGLE_CREDENTIALS_PATH))
    try:
        import urllib.request as _ur
        _ur.urlopen(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=2)
        ollama_ok = True
    except Exception:  # noqa: BLE001
        ollama_ok = False

    # ── code_paths_initialized guard ───────────────────────────────────────
    if not st.session_state.get("code_paths_initialized"):
        if config.MCSL_AUTOMATION_REPO_PATH:
            st.session_state["automation_code_path"] = config.MCSL_AUTOMATION_REPO_PATH
        if config.STOREPEPSAAS_SERVER_PATH:
            st.session_state["mcsl_server_path"] = config.STOREPEPSAAS_SERVER_PATH
        if config.STOREPEPSAAS_CLIENT_PATH:
            st.session_state["mcsl_client_path"] = config.STOREPEPSAAS_CLIENT_PATH
        if getattr(config, "WIKI_PATH", ""):
            st.session_state["wiki_path"] = config.WIKI_PATH
        st.session_state["code_paths_initialized"] = True

    # ── Sidebar ────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown(
            '<div class="pipeline-header">'
            '<h1>🚚 MCSL QA Pipeline</h1>'
            '<p>AI-powered QA orchestration</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.divider()

        # ── System Status ─────────────────────────────────────────────────
        st.subheader("System Status")
        st.markdown(
            _status_badge("Claude API",     api_ok,    "Set ANTHROPIC_API_KEY in .env")
            + _status_badge("Trello",        trello_ok, "Set TRELLO_API_KEY / TOKEN / BOARD_ID")
            + _status_badge("Slack",         slack_ok,  "Set SLACK_WEBHOOK_URL or BOT_TOKEN+CHANNEL")
            + _status_badge("Google Sheets", sheets_ok, "Add credentials.json to project root")
            + _status_badge("Ollama",        ollama_ok, "Start Ollama locally on port 11434"),
            unsafe_allow_html=True,
        )
        st.divider()

        # ── Release Progress ──────────────────────────────────────────────
        st.subheader("Release Progress")
        cards    = st.session_state.get("rqa_cards", [])
        approved = st.session_state.get("rqa_approved", {})
        tc_store = st.session_state.get("rqa_test_cases", {})
        current_release = st.session_state.get("rqa_release", "")
        n_cards    = len(cards)
        n_approved = sum(1 for c in cards if approved.get(getattr(c, "id", c)))
        n_tc       = sum(1 for c in cards if getattr(c, "id", c) in tc_store)

        if current_release:
            st.markdown(f"**Release:** `{current_release}`")
            st.markdown(
                f'<div style="display:flex;gap:16px;font-size:0.85em;margin:8px 0;">'
                f'<span>Cards: <strong>{n_cards}</strong></span>'
                f'<span>Approved: <strong>{n_approved}</strong></span>'
                f'<span>TCs: <strong>{n_tc}</strong></span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if n_cards > 0:
                st.progress(n_approved / n_cards, text=f"{n_approved}/{n_cards} approved")
        else:
            st.caption("Load a release in 🧾 Validate AC to see progress.")
        st.divider()

        # ── Code Knowledge Base ───────────────────────────────────────────
        st.subheader("🗂️ Code Knowledge Base")
        st.caption("RAG over source code — TCs + automation scripts use real patterns.")

        # Load index stats once for all sections
        try:
            from rag.code_indexer import get_index_stats
            _idx_stats = get_index_stats()
        except Exception:
            _idx_stats = {}

        def _sync_badge(cnt, sync):
            if cnt == 0:
                return "⬜ Not indexed"
            commit = sync.get("commit", "")
            synced = sync.get("synced_at", "")
            tag = f" · `{commit}`" if commit else ""
            ts  = f" · {synced}" if synced else ""
            return f"✅ {cnt} chunks{tag}{ts}"

        _auto_cnt   = _idx_stats.get("automation", 0)
        _mcsl_server_cnt = _idx_stats.get("storepepsaas_server", 0)
        _mcsl_client_cnt = _idx_stats.get("storepepsaas_client", 0)
        _mcsl_cnt = _mcsl_server_cnt + _mcsl_client_cnt
        _auto_sync  = _idx_stats.get("automation_sync", {})
        _mcsl_server_sync = _idx_stats.get("server_sync", {})
        _mcsl_client_sync = _idx_stats.get("client_sync", {})

        # Wiki chunk count lives in the knowledge collection (not code collection)
        _wiki_cnt = 0
        try:
            import chromadb as _chromadb
            _kb_client = _chromadb.PersistentClient(path=config.CHROMA_PATH)
            _kb_col = _kb_client.get_collection(config.CHROMA_COLLECTION)
            _wiki_cnt = len(_kb_col.get(where={"source_type": "wiki"}, include=[])["ids"])
        except Exception:
            pass

        def _wiki_badge(cnt):
            return f"✅ {cnt} chunks" if cnt > 0 else "⬜ Not indexed"

        _mcsl_server_tag = (
            f" · server `{_mcsl_server_sync.get('commit', '')}`"
            if _mcsl_server_sync.get("commit")
            else ""
        )
        _mcsl_client_tag = (
            f" · client `{_mcsl_client_sync.get('commit', '')}`"
            if _mcsl_client_sync.get("commit")
            else ""
        )

        st.markdown(
            f"<div style='font-size:0.75rem;line-height:1.8'>"
            f"<b>✍️ Automation:</b> {_sync_badge(_auto_cnt, _auto_sync)}<br>"
            f"<b>🏪 MCSL App:</b> ✅ {_mcsl_cnt} chunks{_mcsl_server_tag}{_mcsl_client_tag}<br>"
            f"<b>📖 Wiki:</b> {_wiki_badge(_wiki_cnt)}"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ── Automation Code ───────────────────────────────────────────────
        with st.expander("✍️ Automation Code"):
            auto_path = st.text_input(
                "Automation repo path", key="automation_code_path",
                placeholder="/path/to/mcsl-test-automation",
            )
            auto_info = {}
            if auto_path:
                try:
                    from rag.code_indexer import get_repo_info
                    auto_info = get_repo_info(auto_path)
                except Exception:  # noqa: BLE001
                    pass
            auto_branches = auto_info.get("branches", [])
            auto_current  = auto_info.get("current_branch", "")
            auto_commit   = auto_info.get("commit", "")
            if auto_branches:
                _auto_idx = auto_branches.index(auto_current) if auto_current in auto_branches else 0
                st.selectbox("Branch to pull", auto_branches, index=_auto_idx, key="auto_branch_select")
                st.caption(f"Current: `{auto_current}` @ `{auto_commit}`")
            elif auto_path:
                st.caption(f"Current: `{auto_current or 'unknown'}` @ `{auto_commit}`" if auto_current else "⚠️ Branch info unavailable")
            col_sync, col_idx = st.columns(2)
            with col_sync:
                if st.button("Pull & Sync", key="auto_sync_btn"):
                    from rag.code_indexer import sync_from_git
                    branch = st.session_state.get("auto_branch_select", auto_current or "main")
                    with st.spinner("Syncing…"):
                        sync_from_git(auto_path, "automation", branch)
                    st.success("Synced.")
                    st.rerun()
            with col_idx:
                if st.button("Full Re-index", key="auto_reindex_btn"):
                    from rag.code_indexer import index_codebase
                    with st.spinner("Re-indexing…"):
                        index_codebase(auto_path, "automation", clear_existing=True)
                        _clear_generation_context_caches()
                    st.success("Re-indexed.")
                    st.rerun()

        # ── MCSL App Code (single repo — server + client) ─────────────────
        with st.expander("🏪 MCSL App Code"):
            mcsl_server_path = st.text_input(
                "Backend path",
                key="mcsl_server_path",
                placeholder="/path/to/storepep-react/storepepSAAS/server/src/shared",
            )
            mcsl_client_path = st.text_input(
                "Frontend path",
                key="mcsl_client_path",
                placeholder="/path/to/storepep-react/storepepSAAS/client/src",
            )
            mcsl_info = {}
            mcsl_repo_probe = mcsl_server_path or mcsl_client_path
            if mcsl_repo_probe:
                try:
                    from rag.code_indexer import get_repo_info
                    mcsl_info = get_repo_info(mcsl_repo_probe)
                except Exception:  # noqa: BLE001
                    pass
            mcsl_branches = mcsl_info.get("branches", [])
            mcsl_current  = mcsl_info.get("current_branch", "")
            mcsl_commit   = mcsl_info.get("commit", "")
            if mcsl_branches:
                _mcsl_idx = mcsl_branches.index(mcsl_current) if mcsl_current in mcsl_branches else 0
                st.selectbox("Branch to pull", mcsl_branches, index=_mcsl_idx, key="mcsl_branch_select")
                st.caption(f"Current: `{mcsl_current}` @ `{mcsl_commit}`")
            elif mcsl_repo_probe:
                st.caption(f"Current: `{mcsl_current or 'unknown'}` @ `{mcsl_commit}`" if mcsl_current else "⚠️ Branch info unavailable")
            st.caption(
                f"Indexed chunks: backend `{_mcsl_server_cnt}` · frontend `{_mcsl_client_cnt}`"
            )
            col_sync, col_idx = st.columns(2)
            with col_sync:
                if st.button("Pull & Sync", key="mcsl_sync_btn"):
                    from rag.code_indexer import sync_from_git
                    branch = st.session_state.get("mcsl_branch_select", mcsl_current or "main")
                    with st.spinner("Syncing…"):
                        sync_results = []
                        if mcsl_server_path:
                            sync_results.append(
                                sync_from_git(
                                    mcsl_server_path,
                                    "storepepsaas_server",
                                    branch=branch,
                                )
                            )
                        if mcsl_client_path:
                            sync_results.append(
                                sync_from_git(
                                    mcsl_client_path,
                                    "storepepsaas_client",
                                    branch=branch,
                                )
                            )
                    if not sync_results:
                        st.warning("Set backend and/or frontend path first.")
                    elif any(r.get("error") for r in sync_results):
                        errors = [r.get("error", "") for r in sync_results if r.get("error")]
                        st.error("Sync failed: " + " | ".join(errors))
                    else:
                        st.success("Synced backend/frontend app code.")
                    st.rerun()
            with col_idx:
                if st.button("Full Re-index", key="mcsl_reindex_btn"):
                    from rag.code_indexer import index_codebase
                    with st.spinner("Re-indexing…"):
                        reindex_results = []
                        if mcsl_server_path:
                            reindex_results.append(
                                index_codebase(
                                    mcsl_server_path,
                                    "storepepsaas_server",
                                    clear_existing=True,
                                )
                            )
                        if mcsl_client_path:
                            reindex_results.append(
                                index_codebase(
                                    mcsl_client_path,
                                    "storepepsaas_client",
                                    extensions=[".js", ".jsx"],
                                    clear_existing=True,
                                )
                            )
                        if reindex_results:
                            _clear_generation_context_caches()
                    if not reindex_results:
                        st.warning("Set backend and/or frontend path first.")
                    elif any(r.get("error") for r in reindex_results):
                        errors = [r.get("error", "") for r in reindex_results if r.get("error")]
                        st.error("Re-index failed: " + " | ".join(errors))
                    else:
                        st.success("Re-indexed backend + frontend app code.")
                    st.rerun()

        # ── MCSL Wiki (documents) ─────────────────────────────────────────
        with st.expander("📖 MCSL Wiki"):
            wiki_path = st.text_input(
                "Wiki path", key="wiki_path",
                placeholder="/path/to/mcsl-wiki/wiki",
            )
            _wiki_path_value = (wiki_path or "").strip()
            _wiki_exists = False
            if wiki_path:
                from pathlib import Path as _Path
                _wiki_exists = _Path(_wiki_path_value).exists()
                if _wiki_exists:
                    _md_count = len(list(_Path(_wiki_path_value).rglob("*.md")))
                    st.caption(f"{_md_count} markdown files found")
                else:
                    st.warning("⚠️ Wiki path not found")
            _wiki_btn_disabled = not _wiki_path_value
            if _wiki_btn_disabled:
                st.caption("Enter a wiki path to enable re-index.")
            elif not _wiki_exists:
                st.caption("Path entered, but folder was not found. Re-index is still available if the path becomes valid.")
            if st.button("Re-index Wiki", key="wiki_reindex_btn", disabled=_wiki_btn_disabled):
                with st.spinner("Indexing wiki docs…"):
                    try:
                        from ingest.wiki_loader import load_wiki_docs
                        from rag.vectorstore import get_vectorstore
                        _docs = load_wiki_docs(wiki_path=_wiki_path_value)
                        if _docs:
                            _vs = get_vectorstore()
                            _vs.add_documents(_docs)
                            _clear_generation_context_caches()
                            st.success(f"✅ Indexed {len(_docs)} wiki chunks.")
                            st.rerun()
                        else:
                            st.warning("No wiki documents found.")
                    except Exception as _wiki_err:
                        st.error(f"Wiki index failed: {_wiki_err}")

        st.divider()

        # ── Dry Run toggle ────────────────────────────────────────────────
        dry_run = st.toggle("🧪 Dry Run (no writes)", key="dry_run", value=False)
        st.caption("Generates output without writing to Trello, repo, or Sheets.")

    # ── Pipeline header ────────────────────────────────────────────────────
    st.markdown(
        '<div class="pipeline-header">'
        '<h1>🚚 MCSL QA Pipeline</h1>'
        '<p>AI-powered QA orchestration for MCSL carriers</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Pipeline tabs ──────────────────────────────────────────────────────
    tab_us, tab_devdone, tab_validate_ac, tab_generate_tc, tab_ai_qa, tab_release_automation, tab_history, tab_signoff, tab_handoff = st.tabs([
        "📝 User Story",
        "🔀 Move Cards",
        "🧾 Validate AC",
        "🧪 Generate TC",
        "🤖 AI QA Verifier",
        "⚙️ Generate Automation Script",
        "📋 History",
        "✅ Sign Off",
        "📘 Handoff Docs",
    ])
    tab_manual = tab_validate_ac
    tab_run = tab_release_automation
    tab_release = tab_ai_qa

    with tab_us:
        st.markdown("### 📝 User Story Writer")
        st.caption("Describe what you need — AI will generate a User Story + Acceptance Criteria using the codebase and domain knowledge.")

        if not api_ok:
            st.error("❌ ANTHROPIC_API_KEY not set — add it to .env")
            st.stop()

        _loaded_cards_for_us = st.session_state.get("rqa_cards", [])
        if _loaded_cards_for_us:
            _us_card_options = {"Manual request": None}
            _us_card_options.update({card.name: card for card in _loaded_cards_for_us})
            _us_selected = st.selectbox(
                "Source",
                options=list(_us_card_options.keys()),
                key="us_source_select",
            )
            _selected_us_card = _us_card_options[_us_selected]
            if _selected_us_card:
                _card_payload = "\n\n".join(
                    part for part in [
                        _selected_us_card.name or "",
                        _selected_us_card.desc or "",
                        "\n".join(getattr(_selected_us_card, "comments", []) or []),
                        "\n".join(
                            f"{cl.get('name', '')}: " + ", ".join(
                                item.get("name", "")
                                for item in cl.get("items", [])
                                if item.get("name")
                            )
                            for cl in (getattr(_selected_us_card, "checklists", []) or [])
                        ),
                    ] if part.strip()
                )
                if st.button("⬇️ Use selected Trello card", key=f"use_us_card_{_selected_us_card.id}"):
                    st.session_state["us_request_input"] = _card_payload
                    st.session_state["us_card_title"] = _selected_us_card.name
                    st.session_state[f"us_diag_{_selected_us_card.id}"] = _normalise_card_diagnosis(
                        _selected_us_card,
                        diagnose_customer_ticket(_card_payload),
                    )
                    st.rerun()
                _us_diag = st.session_state.get(f"us_diag_{_selected_us_card.id}")
                if not _us_diag:
                    _us_diag = _normalise_card_diagnosis(
                        _selected_us_card,
                        diagnose_customer_ticket(_card_payload),
                    )
                    st.session_state[f"us_diag_{_selected_us_card.id}"] = _us_diag
                if _us_diag and not _us_diag.get("error"):
                    st.caption(
                        f"Loaded card diagnosis: issue `{_us_diag.get('issue_type', 'unknown')}`"
                        f" · carrier scope `{(_us_diag.get('carrier_scope') or 'generic').replace('_', ' ')}`"
                        f" · root cause `{(_us_diag.get('likely_root_cause') or 'unclear').replace('_', ' ')}`"
                    )
                    if _us_diag.get("summary"):
                        st.caption(_us_diag["summary"])

        # ── Generate ──────────────────────────────────────────────────────
        request_text = st.text_area(
            "What do you want to build?",
            key="us_request_input",
            height=120,
            placeholder="e.g. Allow merchants to configure UPS SurePost as a shipping option...",
        )

        _us_col_gen, _us_col_reset = st.columns([1, 4])
        with _us_col_gen:
            _us_generate = st.button("✨ Generate", key="us_generate_btn", type="primary")
        with _us_col_reset:
            if st.button("🔄 Start Over", key="us_reset_btn"):
                for _k in ["us_result", "us_research", "us_history", "us_request_input", "us_change_input"]:
                    st.session_state.pop(_k, None)
                st.rerun()

        if _us_generate:
            if not request_text.strip():
                st.warning("Enter a feature description first.")
            else:
                with st.spinner("Generating User Story…"):
                    try:
                        from pipeline.user_story_writer import generate_user_story
                        from pipeline.requirement_research import build_requirement_research_context

                        research = build_requirement_research_context(request_text.strip())
                        result = generate_user_story(
                            request_text.strip(),
                            research_context=research,
                        )
                        st.session_state["us_result"] = result
                        st.session_state["us_research"] = research
                        st.session_state.setdefault("us_history", []).append(result)
                    except Exception as exc:
                        st.error(f"Generation failed: {exc}")

        # ── Result display + Refine ───────────────────────────────────────
        if st.session_state.get("us_result"):
            st.divider()
            st.markdown(st.session_state["us_result"])
            if st.session_state.get("us_research"):
                with st.expander("Requirement research used", expanded=False):
                    _render_research_sections(st.session_state["us_research"])

            st.divider()
            change_req = st.text_area(
                "Request changes (optional)",
                key="us_change_input",
                height=90,
                placeholder="e.g. Add an AC for when the carrier account is inactive. Also clarify the merchant role.",
            )
            if st.button("🔁 Refine", key="us_refine_btn", disabled=not change_req.strip()):
                with st.spinner("Refining…"):
                    try:
                        from pipeline.user_story_writer import refine_user_story
                        refined = refine_user_story(
                            st.session_state["us_result"], change_req.strip()
                        )
                        st.session_state["us_result"] = refined
                        st.session_state.setdefault("us_history", []).append(refined)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Refine failed: {exc}")

            # ── Push to Trello ─────────────────────────────────────────────
            st.divider()
            st.markdown("#### Push to Trello")

            us_board_id, _us_board_name = _select_trello_board("Trello board", "us")
            if not us_board_id and trello_ok:
                st.warning("No Trello boards found for this account/workspace.")

            col_title, col_mode = st.columns([3, 2])
            with col_title:
                st.text_input("Card title", key="us_card_title",
                              placeholder="Feature: UPS SurePost support")
            with col_mode:
                st.radio("List", ["Existing list", "Create new list"],
                         key="us_list_mode", horizontal=True)

            # Fetch board lists for selectors
            try:
                from pipeline.trello_client import TrelloClient
                _tc = TrelloClient(board_id=us_board_id) if us_board_id else None
                _all_lists = _tc.get_lists() if _tc else []
                _list_names = [l.name for l in _all_lists]
                _list_id_map = {l.name: l.id for l in _all_lists}
                _members = _tc.get_board_members() if _tc else []
                _member_names = [m["fullName"] or m["username"] for m in _members]
                _member_id_map = {(m["fullName"] or m["username"]): m["id"] for m in _members}
            except Exception as exc:
                st.warning(f"Could not connect to Trello: {exc}")
                _list_names = []
                _list_id_map = {}
                _members = []
                _member_names = []
                _member_id_map = {}

            if st.session_state["us_list_mode"] == "Existing list":
                st.selectbox("Target list", _list_names or ["(no lists found)"],
                             key="us_existing_list")
            else:
                st.text_input("New list name", key="us_new_list_name",
                              placeholder="Sprint 43 Backlog")

            st.multiselect("Assign members", _member_names, key="us_assign_members")

            if st.button("📌 Create Trello Card", key="us_push_btn", type="primary"):
                card_title = st.session_state.get("us_card_title", "").strip()
                if not card_title:
                    st.warning("Enter a card title.")
                elif not trello_ok:
                    st.error("Trello credentials not configured. Set TRELLO_API_KEY and TRELLO_TOKEN in .env")
                elif not us_board_id:
                    st.warning("Select a Trello board.")
                else:
                    with st.spinner("Creating Trello card…"):
                        try:
                            from pipeline.trello_client import TrelloClient
                            tc = TrelloClient(board_id=us_board_id)

                            # Resolve list_id
                            if st.session_state["us_list_mode"] == "Create new list":
                                new_name = st.session_state.get("us_new_list_name", "").strip()
                                if not new_name:
                                    st.warning("Enter a name for the new list.")
                                    st.stop()
                                tlist = tc.create_list(new_name)
                                list_id = tlist.id
                                list_name = tlist.name
                            else:
                                chosen = st.session_state.get("us_existing_list", "")
                                list_id = _list_id_map.get(chosen, "")
                                list_name = chosen
                                if not list_id:
                                    st.warning(f"List '{chosen}' not found on board.")
                                    st.stop()

                            # Resolve member IDs
                            selected_members = st.session_state.get("us_assign_members", [])
                            member_ids = [_member_id_map[n] for n in selected_members
                                          if n in _member_id_map]

                            card = tc.create_card_in_list(
                                list_id=list_id,
                                name=card_title,
                                desc=st.session_state["us_result"],
                                member_ids=member_ids,
                            )

                            # Save to history
                            _update_pipeline_run(
                                card,
                                created_at=datetime.now().isoformat(timespec="seconds"),
                                test_cases="",
                                rag_chunks=0,
                            )

                            st.success(
                                f"Card created: [{card_title}]({card.url}) in list **{list_name}**"
                            )
                        except Exception as exc:
                            st.error(f"Failed to create Trello card: {exc}")

    with tab_devdone:
        st.subheader("🔀 Move Cards")
        st.caption("Pick a source list, review the loaded cards, and move the selected cards to the next Trello list with an audit comment.")

        dd_board_id, _dd_board_name = _select_trello_board("Trello board", "dd")
        if not dd_board_id and trello_ok:
            st.warning("No Trello boards found for this account/workspace.")

        # ── List selectors ───────────────────────────────────────────────
        # Fetch board lists (show empty selects if Trello not configured)
        try:
            from pipeline.trello_client import TrelloClient
            _dd_tc = TrelloClient(board_id=dd_board_id) if dd_board_id else None
            _dd_lists = _dd_tc.get_lists() if _dd_tc else []
            _dd_list_names = [l.name for l in _dd_lists]
            _dd_list_id_map = {l.name: l.id for l in _dd_lists}
        except Exception as exc:
            st.warning(f"Could not connect to Trello: {exc}")
            _dd_list_names = []
            _dd_list_id_map = {}

        col_src, col_arrow, col_tgt, col_load = st.columns([3, 0.4, 3, 1.2])
        with col_src:
            source_list = st.selectbox(
                "📂 Source list",
                _dd_list_names or ["Dev Done"],
                key="dd_list_select",
                index=0,
            )
        with col_arrow:
            st.write("")
            st.write("")
            st.markdown("**→**")
        with col_tgt:
            # Default target: "Ready for QA" if present, else first list
            default_tgt_idx = 0
            if "Ready for QA" in _dd_list_names:
                default_tgt_idx = _dd_list_names.index("Ready for QA")
            st.selectbox(
                "📁 Target list",
                _dd_list_names or ["Ready for QA"],
                key="dd_move_target",
                index=default_tgt_idx,
            )
        with col_load:
            st.write("")
            st.write("")
            load_btn = st.button("📥 Load Cards", key="dd_load_btn", use_container_width=True)

        if load_btn:
            source_id = _dd_list_id_map.get(source_list, "")
            if not source_id:
                st.warning(f"List '{source_list}' not found on board.")
            else:
                with st.spinner("Loading cards…"):
                    try:
                        from pipeline.trello_client import TrelloClient
                        tc = TrelloClient(board_id=dd_board_id)
                        cards = tc.get_cards_in_list(source_id)
                        st.session_state["dd_cards"] = cards
                        st.session_state["dd_checked"] = {c.id: False for c in cards}
                        st.session_state["dd_select_all"] = False
                    except Exception as exc:
                        st.error(f"Failed to load cards: {exc}")

        # ── Card list with checkboxes ────────────────────────────────────
        cards = st.session_state.get("dd_cards", [])
        if cards:
            st.divider()
            st.markdown(f"**{len(cards)} cards** loaded from `{source_list}`")
            # Select-all toggle
            select_all = st.checkbox(
                f"Select all ({len(cards)} cards)",
                key="dd_select_all",
                value=st.session_state.get("dd_select_all", False),
            )
            if select_all:
                for c in cards:
                    st.session_state["dd_checked"][c.id] = True

            # Per-card checkboxes
            checked = st.session_state.get("dd_checked", {})
            for card in cards:
                _dd_col1, _dd_col2 = st.columns([1, 9])
                with _dd_col1:
                    checked[card.id] = st.checkbox(
                        "",
                        key=f"dd_chk_{card.id}",
                        value=checked.get(card.id, False),
                    )
                with _dd_col2:
                    with st.expander(f"{'☑️' if checked.get(card.id) else '🔲'} {card.name}", expanded=False):
                        if getattr(card, "labels", None):
                            st.caption("🏷️ " + " · ".join(card.labels))
                        if card.desc:
                            st.markdown(card.desc[:600] + ("…" if len(card.desc) > 600 else ""))
                        else:
                            st.caption("_No description_")
                        if getattr(card, "url", ""):
                            st.caption(f"🔗 {card.url}")
            st.session_state["dd_checked"] = checked

            # ── Move button ───────────────────────────────────────────────
            n_checked = sum(1 for v in checked.values() if v)
            move_target = st.session_state.get("dd_move_target", "")
            if st.button(f"➡️ Move {n_checked} cards", key="dd_move_btn",
                         type="primary", disabled=(n_checked == 0), use_container_width=True):
                target_id = _dd_list_id_map.get(move_target, "")
                if not target_id:
                    st.warning(f"Target list '{move_target}' not found.")
                else:
                    moved = 0
                    errors = []
                    with st.spinner(f"Moving {n_checked} cards…"):
                        try:
                            from pipeline.trello_client import TrelloClient
                            tc = TrelloClient(board_id=dd_board_id)
                            for card in cards:
                                if not checked.get(card.id):
                                    continue
                                try:
                                    if not dry_run:
                                        tc.move_card_to_list_by_id(card.id, target_id)
                                        tc.add_comment(
                                            card.id,
                                            f"Moved to {move_target} by MCSL QA Pipeline",
                                        )
                                    moved += 1
                                except Exception as exc:
                                    errors.append(f"{card.name}: {exc}")
                        except Exception as exc:
                            st.error(f"Trello error: {exc}")

                    if moved:
                        st.success(
                            f"{'(dry run) ' if dry_run else ''}Moved {moved} card(s) to **{move_target}**."
                        )
                        # Clear loaded cards after move
                        st.session_state["dd_cards"] = []
                        st.session_state["dd_checked"] = {}
                    for err in errors:
                        st.warning(err)
        elif st.session_state.get("dd_cards") == []:
            pass  # Not yet loaded — show nothing

    release_stage_tabs = [
        ("validate_ac", tab_validate_ac),
        ("generate_tc", tab_generate_tc),
        ("ai_qa", tab_ai_qa),
        ("automation", tab_release_automation),
    ]

    for release_stage, release_tab in release_stage_tabs:
        with release_tab:
            show_ac_stage = release_stage == "validate_ac"
            show_tc_stage = release_stage == "generate_tc"
            show_ai_stage = release_stage == "ai_qa"
            show_automation_stage = release_stage == "automation"

            if show_ac_stage:
                st.markdown("## 🧾 Validate AC")
            elif show_tc_stage:
                st.markdown("## 🧪 Generate TC")
            elif show_ai_stage:
                st.markdown("## 🤖 AI QA Verifier")
            else:
                st.markdown("## ⚙️ Generate Automation Script")

            trello = None
            cards: list = []

            if show_ac_stage:
                rqa_board_id, rqa_board_name = _select_trello_board("Trello board", "rqa")
                try:
                    trello = TrelloClient(board_id=rqa_board_id) if rqa_board_id else None
                    all_lists = trello.get_lists() if trello else []
                except Exception as _e:
                    st.error(f"Trello connection failed: {_e}")
                    all_lists = []

                list_options = {lst.name: lst.id for lst in all_lists} if all_lists else {}
                list_names = list(list_options.keys()) or [""]

                col_refresh = st.columns([1])[0]
                with col_refresh:
                    if st.button("🔄 Refresh Trello lists", key="rqa_refresh_lists_btn"):
                        st.cache_data.clear()
                        st.rerun()

                show_all_lists = st.toggle("Show all lists", value=False, key="rqa_show_all_lists")
                filtered_list_names = list_names
                if not show_all_lists:
                    qa_list_names = [
                        name for name in list_names
                        if "qa" in name.lower() or "ready for qa" in name.lower()
                    ]
                    if qa_list_names:
                        filtered_list_names = qa_list_names

                _current_list_for_release = st.session_state.get("rqa_list_selector", "")
                _last_release_list = st.session_state.get("_rqa_release_list_name", "")
                _last_auto_release = st.session_state.get("_rqa_release_auto_value", "")
                _current_release_input = st.session_state.get("rqa_release_input", "")
                if _current_list_for_release != _last_release_list:
                    if not _current_release_input or _current_release_input == _last_auto_release:
                        st.session_state["rqa_release_input"] = _extract_release_label(_current_list_for_release)
                    st.session_state["_rqa_release_list_name"] = _current_list_for_release
                    st.session_state["_rqa_release_auto_value"] = _extract_release_label(_current_list_for_release)

                col_list, col_release, col_load = st.columns([3, 2, 1])
                with col_list:
                    selected_list_name = st.selectbox(
                        "Select Trello List",
                        options=filtered_list_names,
                        index=filtered_list_names.index(st.session_state["rqa_list_name"])
                        if st.session_state["rqa_list_name"] in filtered_list_names else 0,
                        key="rqa_list_selector",
                    )
                with col_release:
                    release_label = st.text_input(
                        "Release Label",
                        placeholder="e.g. MCSLapp 1.2.3",
                        key="rqa_release_input",
                    )
                with col_load:
                    st.markdown("<br>", unsafe_allow_html=True)
                    load_clicked = st.button("Load Cards", type="primary", key="rqa_load_btn")

                # ── Card subset selector ──────────────────────────────────
                # Auto-fetch card names from the selected list so the user can
                # pick a subset before clicking Load Cards.
                _sel_list_id = list_options.get(selected_list_name, "") if list_options else ""
                _preview_list_id = st.session_state.get("rqa_preview_list_id", "")
                if _sel_list_id and trello and _sel_list_id != _preview_list_id:
                    with st.spinner(f"Fetching card names from '{selected_list_name}'…"):
                        try:
                            _fetched = _dedupe_cards(trello.get_cards_in_list(_sel_list_id))
                            st.session_state["rqa_preview_cards"] = _fetched
                            st.session_state["rqa_preview_list_id"] = _sel_list_id
                            # Reset multiselect when list changes
                            if "rqa_card_multiselect" in st.session_state:
                                del st.session_state["rqa_card_multiselect"]
                        except Exception:
                            st.session_state["rqa_preview_cards"] = []

                _preview_cards = st.session_state.get("rqa_preview_cards", [])
                if _preview_cards:
                    def _card_option_label(c: object) -> str:
                        _lbls = getattr(c, "labels", None) or []
                        return f"{c.name}  [{', '.join(_lbls)}]" if _lbls else c.name  # type: ignore[union-attr]

                    _all_option_labels = [_card_option_label(c) for c in _preview_cards]
                    _label_to_card_id  = {_card_option_label(c): c.id for c in _preview_cards}  # type: ignore[union-attr]

                    # Select all / Clear all helpers
                    _c_all, _c_clr, _c_cnt = st.columns([1, 1, 4])
                    with _c_all:
                        if st.button("Select all", key="rqa_sel_all_btn", use_container_width=True):
                            st.session_state["rqa_card_multiselect"] = _all_option_labels
                            st.rerun()
                    with _c_clr:
                        if st.button("Clear all", key="rqa_clr_all_btn", use_container_width=True):
                            st.session_state["rqa_card_multiselect"] = []
                            st.rerun()
                    with _c_cnt:
                        _cur_ms = st.session_state.get("rqa_card_multiselect") or []
                        _n_cur  = len(_cur_ms) if _cur_ms else len(_preview_cards)
                        if _cur_ms:
                            st.caption(f"**{len(_cur_ms)} of {len(_preview_cards)} cards selected** — Load Cards will load only these")
                        else:
                            st.caption(f"**All {len(_preview_cards)} cards** — select a subset or leave empty to load all")

                    st.multiselect(
                        "Select cards to load",
                        options=_all_option_labels,
                        key="rqa_card_multiselect",
                        placeholder="Leave empty to load all cards in this list…",
                        label_visibility="collapsed",
                    )

                if load_clicked and selected_list_name and list_options:
                    selected_list_id = list_options[selected_list_name]
                    with st.spinner(f"Loading cards from '{selected_list_name}'…"):
                        try:
                            _previous_cards = st.session_state.get("rqa_cards", []) or []
                            _all_fetched = _dedupe_cards(trello.get_cards_in_list(selected_list_id))

                            # Apply subset if user selected specific cards
                            _ms_selection = st.session_state.get("rqa_card_multiselect") or []
                            if _ms_selection:
                                _prev_label_map = {_card_option_label(c): c.id for c in st.session_state.get("rqa_preview_cards", [])}
                                _wanted_ids     = {_prev_label_map[lbl] for lbl in _ms_selection if lbl in _prev_label_map}
                                cards = [c for c in _all_fetched if c.id in _wanted_ids]
                            else:
                                cards = _all_fetched
                            _reset_card_ids = list({
                                *(getattr(c, "id", "") for c in _previous_cards),
                                *(getattr(c, "id", "") for c in cards),
                            })
                            _clear_card_session_state([cid for cid in _reset_card_ids if cid])
                            st.session_state["rqa_cards"] = cards
                            st.session_state["rqa_list_name"] = selected_list_name
                            st.session_state["rqa_board_id"] = rqa_board_id
                            st.session_state["rqa_board_name"] = rqa_board_name
                            st.session_state["rqa_release"] = release_label or _extract_release_label(selected_list_name)
                            st.session_state["rqa_test_cases"] = {}
                            st.session_state["rqa_approved"] = _hydrate_release_approval_state(cards)
                            st.session_state["signoff_sent"] = False
                            st.session_state["signoff_message"] = ""
                            st.session_state["signoff_bugs"] = ""
                            st.session_state["release_analysis"] = None

                            if release_stage == "validate_ac" and cards:
                                _release_name = st.session_state["rqa_release"]
                                _subset_note = (
                                    f" ({len(cards)} of {len(_all_fetched)} selected)"
                                    if _ms_selection and len(cards) < len(_all_fetched)
                                    else ""
                                )
                                st.info(
                                    f"Loaded {len(cards)} cards from **{selected_list_name}**{_subset_note} — running Domain Expert validation…"
                                )
                                _progress = st.progress(0)
                                _cards_by_id = {getattr(_card, "id", ""): _card for _card in cards}
                                _max_workers = min(4, max(1, len(cards)))
                                with ThreadPoolExecutor(max_workers=_max_workers) as _executor:
                                    _futures = [_executor.submit(_analyse_loaded_card, _card) for _card in cards]
                                    for _idx, _future in enumerate(as_completed(_futures)):
                                        _card_id, _validation, _diagnosis = _future.result()
                                        if _card_id:
                                            st.session_state[f"validation_{_card_id}"] = _validation
                                            _card_obj = _cards_by_id.get(_card_id)
                                            st.session_state[f"diagnosis_{_card_id}"] = (
                                                _normalise_card_diagnosis(_card_obj, _diagnosis)
                                                if _card_obj is not None else _diagnosis
                                            )
                                        _progress.progress((_idx + 1) / len(cards))
                                _progress.empty()
                                _ra_cards = [
                                    RASummary(
                                        card_id=c.id,
                                        card_name=c.name,
                                        card_desc=c.desc or "",
                                        card_comments=getattr(c, "comments", []) or [],
                                        card_labels=getattr(c, "labels", []) or [],
                                        card_checklists=getattr(c, "checklists", []) or [],
                                    )
                                    for c in cards
                                ]
                                st.session_state["release_analysis"] = analyse_release(
                                    release_name=_release_name,
                                    cards=_ra_cards,
                                )
                            st.rerun()
                        except Exception as _load_err:
                            st.error(f"Failed to load cards: {_load_err}")
            else:
                rqa_board_id = st.session_state.get("rqa_board_id", "")
                rqa_board_name = st.session_state.get("rqa_board_name", "")
                try:
                    trello = TrelloClient(board_id=rqa_board_id) if rqa_board_id else None
                except Exception:
                    trello = None
                cards = _dedupe_cards(st.session_state.get("rqa_cards", []))
                st.session_state["rqa_cards"] = cards
                if not cards:
                    st.info("Load a release in **🧾 Validate AC** first.")
                    continue
                st.caption(
                    f"Using loaded release context: board **{rqa_board_name or '—'}** · "
                    f"list **{st.session_state.get('rqa_list_name', '—')}** · "
                    f"release **{st.session_state.get('rqa_release', '—')}**"
                )

            cards = _dedupe_cards(st.session_state.get("rqa_cards", []))
            st.session_state["rqa_cards"] = cards

            if not cards:
                st.info("Select a Trello list in **🧾 Validate AC** and click **Load Cards** to begin the QA flow.")
                continue
            # ── Health summary ───────────────────────────────────────────────
            approved_store: dict = st.session_state.get("rqa_approved", {})
            val_statuses = [st.session_state.get(f"validation_{c.id}") for c in cards]
            n_pass   = sum(1 for v in val_statuses if v and v.overall_status == "PASS")
            n_review = sum(1 for v in val_statuses if v and v.overall_status == "NEEDS_REVIEW")
            n_fail   = sum(1 for v in val_statuses if v and v.overall_status == "FAIL")
            approved_count = sum(1 for v in approved_store.values() if v)

            hcols = st.columns(5)
            hcols[0].metric("Total Cards", len(cards))
            hcols[1].metric("✅ Pass", n_pass)
            hcols[2].metric("⚠️ Needs Review", n_review)
            hcols[3].metric("❌ Fail", n_fail)
            hcols[4].metric("🏆 Approved", approved_count)

            _release_backlog_lines = [line.strip() for line in st.session_state.get("signoff_bugs", "").splitlines() if line.strip()]
            _release_gate = _release_decision_snapshot(cards, approved_store, _release_backlog_lines)
            _gate_color = {"READY": "green", "NOT READY": "red", "PENDING": "orange"}.get(_release_gate["decision"], "gray")
            st.markdown(f"**Release Decision:** :{_gate_color}[{_release_gate['decision']}]")
            if _release_gate["reasons"]:
                for _reason in _release_gate["reasons"]:
                    st.caption(f"- {_reason}")
            else:
                st.caption("All loaded cards are approved and no blocking QA or backlog issues are currently recorded.")

            st.divider()

            if show_ac_stage:
                _pending_validation = sum(1 for c in cards if f"validation_{c.id}" not in st.session_state)
                _pending_diagnosis = sum(1 for c in cards if f"diagnosis_{c.id}" not in st.session_state)
                # ── Release Intelligence ─────────────────────────────────────
                ra: ReleaseAnalysis | None = st.session_state.get("release_analysis")
                if ra and not ra.error:
                    _risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(ra.risk_level, "⚪")
                    with st.expander(
                        f"{_risk_emoji} Release Intelligence — {ra.risk_level} RISK · {ra.risk_summary}",
                        expanded=True,
                    ):
                        if ra.kb_context_summary:
                            st.info(f"📚 KB Context: {ra.kb_context_summary}")

                        _ra_left, _ra_right = st.columns(2)
                        with _ra_left:
                            if ra.conflicts:
                                st.markdown("##### ⚠️ Cross-Card Conflicts")
                                for _conflict in ra.conflicts:
                                    _cards_involved = " & ".join(_conflict.get("cards", []))
                                    _area = _conflict.get("area", "")
                                    _desc = _conflict.get("description", "")
                                    st.warning(f"**{_cards_involved}** — *{_area}*\n\n{_desc}")
                            else:
                                st.success("✅ No cross-card conflicts detected")

                            if ra.coverage_gaps:
                                st.markdown("##### 🕳️ Coverage Gaps")
                                for _gap in ra.coverage_gaps:
                                    st.caption(f"• {_gap}")

                        with _ra_right:
                            if ra.ordering:
                                st.markdown("##### 📋 Suggested Test Order")
                                for _item in ra.ordering:
                                    _pos = _item.get("position", "")
                                    _card_name = _item.get("card_name", "")
                                    _reason = _item.get("reason", "")
                                    st.markdown(f"**{_pos}.** {_card_name}")
                                    st.caption(f"   ↳ {_reason}")

                        if getattr(ra, "sources", None):
                            st.caption(
                                "KB sources: " + " · ".join(
                                    f"[link]({source})" if str(source).startswith("http") else str(source)
                                    for source in (ra.sources or [])[:4]
                                )
                            )
                elif _pending_validation or _pending_diagnosis:
                    st.info("Release analysis is still loading from the most recent card load.")
                else:
                    st.info("Release analysis is using fallback reasoning for the loaded cards.")

            st.divider()

            # ── Per-card accordions ──────────────────────────────────────────
            tc_store: dict = st.session_state.get("rqa_test_cases", {})

            for card in cards:
                _card_run = _get_card_run(getattr(card, "id", ""))
                _vr: ValidationReport | None = st.session_state.get(f"validation_{card.id}")
                _diag: dict | None = _normalise_card_diagnosis(
                    card,
                    st.session_state.get(f"diagnosis_{card.id}"),
                )
                if _diag is not None:
                    st.session_state[f"diagnosis_{card.id}"] = _diag
                _existing_tc_comment = _find_existing_tc_comment(card)
                _existing_tc_markdown = _load_existing_tc_markdown(card)
                _has_existing_ac = bool(card.desc and len(card.desc.strip()) > 30)
                _has_existing_tc = bool(_existing_tc_comment or _existing_tc_markdown)
                _already_done = _has_existing_ac and _has_existing_tc
                _status_icon = {"PASS": "✅", "NEEDS_REVIEW": "⚠️", "FAIL": "❌"}.get(
                    _vr.overall_status if _vr else "", "🔵"
                )
                _approved_badge = " 🏆" if approved_store.get(card.id) else ""
                _done_badge = " ⚡" if _already_done and not approved_store.get(card.id) else ""

                with st.expander(f"{_status_icon} {card.name}{_approved_badge}{_done_badge}", expanded=False):

                    if _already_done and not approved_store.get(card.id):
                        _proc_label = "➡️ Use Existing AC + TCs"
                        _proc_help = "Reuse the existing Trello description and test-case comment for this stage."
                        if show_tc_stage:
                            _proc_label = "➡️ Ready for AI QA Verifier"
                            _proc_help = "Reuse the existing test cases and continue with AI QA verification."
                        elif show_ai_stage:
                            _proc_label = "▶️ Start AI QA Verification"
                            _proc_help = "Reuse the existing test cases and run AI QA verification for this card."
                        elif show_automation_stage:
                            _proc_label = "➡️ Proceed to Automation"
                            _proc_help = "Reuse the existing AC and reviewed test cases for automation generation."

                        st.info(
                            "⚡ This card already has a populated description and a saved QA test-case comment in Trello."
                        )
                        _proc_col1, _proc_col2, _proc_col3 = st.columns(3)
                        with _proc_col1:
                            if st.button(
                                _proc_label,
                                key=f"proceed_{release_stage}_{card.id}",
                                use_container_width=True,
                                type="primary",
                                help=_proc_help,
                            ):
                                if _existing_tc_markdown:
                                    tc_store[card.id] = _existing_tc_markdown
                                    st.session_state["rqa_test_cases"] = tc_store
                                    st.session_state[f"tc_text_{card.id}"] = _existing_tc_markdown
                                    st.session_state[f"ac_saved_{card.id}"] = True
                                    if show_ai_stage:
                                        for _qa_prefix in (
                                            "sav_running_",
                                            "sav_stop_",
                                            "sav_stop_event_",
                                            "sav_result_",
                                            "sav_prog_",
                                            "sav_report_",
                                            "sav_qa_answers_",
                                            "sav_bug_selection_",
                                            "sav_auto_retry_",
                                        ):
                                            st.session_state.pop(f"{_qa_prefix}{card.id}", None)
                                    st.rerun()
                                else:
                                    st.warning(
                                        "Only the QA summary comment was found in Trello. "
                                        "Generate or reload the full test cases before proceeding."
                                    )
                        with _proc_col2:
                            if st.button(
                                "📋 View existing TCs",
                                key=f"view_tc_{release_stage}_{card.id}",
                                use_container_width=True,
                            ):
                                st.session_state[f"show_existing_tc_{card.id}"] = True
                        with _proc_col3:
                            if st.button(
                                "🔄 Regenerate",
                                key=f"banner_regen_{release_stage}_{card.id}",
                                use_container_width=True,
                            ):
                                st.session_state[f"force_regen_{card.id}"] = True

                        if st.session_state.get(f"show_existing_tc_{card.id}"):
                            with st.expander("📋 Existing test cases (from Trello comment)", expanded=True):
                                st.markdown(_existing_tc_markdown or _existing_tc_comment)
                                if st.button("✖ Close", key=f"close_tc_{release_stage}_{card.id}"):
                                    del st.session_state[f"show_existing_tc_{card.id}"]
                                    st.rerun()

                        if (
                            not st.session_state.get(f"force_regen_{card.id}", False)
                            and (show_ac_stage or show_tc_stage)
                        ):
                            continue

                    if show_ac_stage:
                        # ── Step 1a: Card details ────────────────────────────────
                        st.markdown("### Step 1: Card Requirements")
                        st.markdown(f"**Card:** [{card.name}]({card.url})")
                        if card.desc:
                            with st.expander("Card Description", expanded=False):
                                st.markdown(card.desc)
                        _meta_bits = []
                        if getattr(card, "attachments", None):
                            _meta_bits.append(f"{len(card.attachments)} attachment(s)")
                        if getattr(card, "checklists", None):
                            _meta_bits.append(f"{len(card.checklists)} checklist(s)")
                        if getattr(card, "comments", None):
                            _meta_bits.append(f"{len(card.comments)} comment(s)")
                        if _meta_bits:
                            st.caption(" · ".join(_meta_bits))

                    # ── Step 1a.1: Toggle prerequisites ───────────────────
                        from pipeline.slack_client import (
                            check_toggle_reply,
                            detect_toggle_details,
                            detect_toggles,
                            notify_dev_of_toggle,
                            notify_toggle_enablement,
                            search_slack_users,
                            send_dm_to_user,
                        )

                        _tog_key = f"toggles_{card.id}"
                        _tog_details_key = f"toggle_details_{card.id}"
                        _tog_notif_key = f"toggle_notified_{card.id}"
                        _tog_done_key = f"toggle_done_{card.id}"
                        _tog_sent_at_key = f"toggle_sent_at_{card.id}"
                        _tog_dev_notif_key = f"toggle_dev_notified_{card.id}"
                        _tog_store_key = f"toggle_store_{card.id}"
                        _tog_app_url_key = f"toggle_app_url_{card.id}"
                        _tog_live_key = f"toggle_live_state_{card.id}"
                        _tog_source_key = f"toggle_source_{card.id}"

                        _toggle_comment_text = "\n".join(getattr(card, "comments", []) or [])
                        _toggle_source = "\n".join([card.name or "", card.desc or "", _toggle_comment_text])
                        if (
                            _tog_key not in st.session_state
                            or st.session_state.get(_tog_source_key) != _toggle_source
                        ):
                            _toggle_details = detect_toggle_details(
                                card.desc or "",
                                card.name,
                                _toggle_comment_text,
                            )
                            st.session_state[_tog_details_key] = _toggle_details
                            st.session_state[_tog_key] = [item["label"] for item in _toggle_details]
                            st.session_state[_tog_source_key] = _toggle_source

                        _detected_toggles = st.session_state.get(_tog_key, [])
                        _toggle_details = st.session_state.get(_tog_details_key, [])
                        _toggle_notified = st.session_state.get(_tog_notif_key)
                        _toggle_done = st.session_state.get(_tog_done_key, False)
                        _toggle_sent_at = st.session_state.get(_tog_sent_at_key, 0.0)
                        _toggle_dev_notif = st.session_state.get(_tog_dev_notif_key)

                        if _detected_toggles:
                            st.markdown("---")
                            st.markdown(
                                "🔧 **Toggle(s) detected:** " + ", ".join(f"`{item}`" for item in _detected_toggles)
                            )

                            from pipeline.carrier_knowledge import get_default_app_url, get_default_store_slug
                            from pipeline.toggle_state import capture_store_and_toggle_state, compute_toggle_status

                            if _tog_store_key not in st.session_state:
                                _auto_store = get_default_store_slug(
                                    card.name or "",
                                    card.desc or "",
                                    "\n".join(getattr(card, "comments", []) or []),
                                    _diag.get("carrier_scope", "") if _diag else "",
                                )
                                st.session_state[_tog_store_key] = _auto_store
                            if _tog_app_url_key not in st.session_state:
                                st.session_state[_tog_app_url_key] = get_default_app_url(
                                    card.name or "",
                                    card.desc or "",
                                    "\n".join(getattr(card, "comments", []) or []),
                                    _diag.get("carrier_scope", "") if _diag else "",
                                )

                            _app_url = st.text_input(
                                "App URL",
                                value=st.session_state[_tog_app_url_key],
                                key=f"toggle_app_url_input_{card.id}",
                                placeholder="https://admin.shopify.com/store/YOUR-STORE/apps/mcsl-qa",
                                help="Auto-filled from carrier/generic store env. QA can override it before live toggle check.",
                            )
                            st.session_state[_tog_app_url_key] = _app_url
                            _store_name = st.text_input(
                                "Store name",
                                value=st.session_state[_tog_store_key],
                                key=f"toggle_store_input_{card.id}",
                                placeholder="e.g. test-madan-store-2",
                                help="Auto-detected from carrier envs when possible. Generic cards default to USPS Stamps. QA can override it.",
                            )
                            st.session_state[_tog_store_key] = _store_name
                            _store_url = f"https://admin.shopify.com/store/{_store_name}" if _store_name else ""
                            _live_state = st.session_state.get(_tog_live_key, {})
                            _live_summary = compute_toggle_status(_detected_toggles, (_live_state or {}).get("toggle_map", {}))
                            _toggle_by_label = {item.get("label", ""): item for item in _toggle_details if item.get("label")}

                            _live_col1, _live_col2 = st.columns([1, 3])
                            with _live_col1:
                                if st.button("🔎 Check Toggle Status & Get UUIDs", key=f"refresh_toggle_live_{card.id}", use_container_width=True):
                                    with st.spinner("Reading store context and toggle status from the app…"):
                                        _capture = capture_store_and_toggle_state(_app_url.strip())
                                    if _capture.error:
                                        st.warning(f"Live toggle check failed: {_capture.error}")
                                    else:
                                        st.session_state[_tog_live_key] = {
                                            "store_uuid": _capture.store_uuid,
                                            "account_uuid": _capture.account_uuid,
                                            "toggle_map": _capture.toggle_map,
                                        }
                                        st.success("✅ Live store/toggle state refreshed.")
                                        st.rerun()
                            with _live_col2:
                                if _live_state:
                                    st.caption(
                                        f"Store UUID: `{_live_state.get('store_uuid') or '—'}`  |  "
                                        f"Account UUID: `{_live_state.get('account_uuid') or '—'}`"
                                    )
                                    if _live_summary.get("enabled"):
                                        st.caption("Already enabled: " + ", ".join(f"`{t}`" for t in _live_summary["enabled"]))
                                    if _live_summary.get("missing"):
                                        st.caption("Missing: " + ", ".join(f"`{t}`" for t in _live_summary["missing"]))
                                    elif _detected_toggles:
                                        st.success("✅ All detected toggles are already enabled for this store.")
                                else:
                                    st.caption("Checks whether the detected toggle is enabled and captures Store UUID plus Account UUID from the live app.")

                            _toggles_to_request = (
                                [_toggle_by_label.get(label, label) for label in _live_summary.get("missing", [])]
                                if _live_state
                                else list(_toggle_details or _detected_toggles)
                            )

                            if _toggle_done or (_live_state and not _toggles_to_request):
                                st.success("✅ Toggle(s) confirmed enabled. QA can proceed.")
                            elif _toggle_notified:
                                _elapsed = time.time() - _toggle_sent_at if _toggle_sent_at else 0.0
                                _elapsed_str = f"{int(_elapsed // 60)}m {int(_elapsed % 60)}s"
                                if _toggle_dev_notif:
                                    st.info(
                                        f"📨 Waiting for reply from Ashok and {_toggle_dev_notif.get('dev_name', 'Dev')} "
                                        f"({_elapsed_str} since first notification)."
                                    )
                                    _poll1, _poll2 = st.columns(2)
                                    with _poll1:
                                        if st.button("🔄 Check Ashok", key=f"chk_ashok_{card.id}", use_container_width=True):
                                            _chk = check_toggle_reply(
                                                channel_id=_toggle_notified["channel"],
                                                after_ts=_toggle_notified["ts"],
                                            )
                                            if _chk.get("confirmed"):
                                                st.session_state[_tog_done_key] = True
                                                send_dm_to_user(
                                                    _toggle_dev_notif.get("slack_uid", ""),
                                                    f"Ashok has enabled the toggle(s) for *{card.name}*. You can ignore the earlier request.",
                                                )
                                                st.success("Ashok confirmed the toggle update.")
                                                st.rerun()
                                            elif _chk.get("error"):
                                                st.warning(_chk["error"])
                                            else:
                                                st.info("No confirmation from Ashok yet.")
                                    with _poll2:
                                        if st.button(
                                            f"🔄 Check {_toggle_dev_notif.get('dev_name', 'Dev')}",
                                            key=f"chk_dev_{card.id}",
                                            use_container_width=True,
                                        ):
                                            _chk = check_toggle_reply(
                                                channel_id=_toggle_dev_notif["channel"],
                                                after_ts=_toggle_dev_notif["ts"],
                                            )
                                            if _chk.get("confirmed"):
                                                st.session_state[_tog_done_key] = True
                                                _ashok_uid = st.session_state.get("ashok_slack_uid", "")
                                                if _ashok_uid:
                                                    send_dm_to_user(
                                                        _ashok_uid,
                                                        f"{_toggle_dev_notif.get('dev_name', 'Dev')} enabled the toggle(s) for *{card.name}*. Please ignore the earlier request.",
                                                    )
                                                st.success("Developer confirmed the toggle update.")
                                                st.rerun()
                                            elif _chk.get("error"):
                                                st.warning(_chk["error"])
                                            else:
                                                st.info("No confirmation from the developer yet.")
                                else:
                                    st.info(f"📨 Notification sent to Ashok ({_elapsed_str} ago). Waiting for reply.")
                                    _chk_col, _esc_col = st.columns(2)
                                    with _chk_col:
                                        if st.button("🔄 Check Status", key=f"chk_toggle_{card.id}", use_container_width=True):
                                            _chk = check_toggle_reply(
                                                channel_id=_toggle_notified["channel"],
                                                after_ts=_toggle_notified["ts"],
                                            )
                                            if _chk.get("confirmed"):
                                                st.session_state[_tog_done_key] = True
                                                st.success("Ashok confirmed the toggle update.")
                                                st.rerun()
                                            elif _chk.get("error"):
                                                st.warning(_chk["error"])
                                            else:
                                                st.info("No confirmation yet.")
                                    with _esc_col:
                                        _can_escalate = _elapsed >= 120
                                        _label = "📲 Notify Dev via Slack" if _can_escalate else f"⏳ Escalate in {max(0, int(120 - _elapsed))}s"
                                        if st.button(_label, key=f"esc_toggle_{card.id}", use_container_width=True, disabled=not _can_escalate):
                                            try:
                                                _members = trello.get_card_members(card.id)
                                                _devs = [
                                                    member for member in _members
                                                    if not is_qa_name(member.get("fullName") or member.get("username") or "")
                                                ]
                                                if not _devs:
                                                    st.error("No developer found on this Trello card.")
                                                else:
                                                    _dev = _devs[0]
                                                    _dev_name = _dev.get("fullName") or _dev.get("username") or "Developer"
                                                    _users, _err = search_slack_users(_dev_name.split()[0])
                                                    if (not _users) and _dev_name:
                                                        _users, _err = search_slack_users(_dev_name)
                                                    if _err:
                                                        st.error(_err)
                                                    elif not _users:
                                                        st.error(f"Could not find {_dev_name} in Slack.")
                                                    else:
                                                        _dev_uid = _users[0]["id"]
                                                        _notif = notify_dev_of_toggle(
                                                            user_id=_dev_uid,
                                                            dev_name=_dev_name,
                                                            card_name=card.name,
                                                            toggles=_toggles_to_request,
                                                            store_name=_store_name,
                                                            store_url=_store_url,
                                                            store_uuid=(_live_state or {}).get("store_uuid", ""),
                                                            account_uuid=(_live_state or {}).get("account_uuid", ""),
                                                        )
                                                        if _notif.get("ok"):
                                                            st.session_state[_tog_dev_notif_key] = {
                                                                "ts": _notif.get("ts", ""),
                                                                "channel": _notif.get("channel", ""),
                                                                "slack_uid": _dev_uid,
                                                                "dev_name": _dev_name,
                                                            }
                                                            st.success(f"Slack DM sent to {_dev_name}.")
                                                            st.rerun()
                                                        else:
                                                            st.error(_notif.get("error", "Developer notification failed"))
                                            except Exception as _dev_exc:
                                                st.error(f"Could not notify developer: {_dev_exc}")
                            else:
                                if not dm_token_configured():
                                    st.warning("SLACK_BOT_TOKEN is required for toggle notifications.")
                                else:
                                    if "ashok_slack_uid" not in st.session_state:
                                        _ashok_users, _ashok_err = search_slack_users("Ashok Kumar")
                                        st.session_state["ashok_slack_uid"] = _ashok_users[0]["id"] if _ashok_users else ""
                                        if _ashok_err:
                                            st.caption(f"Slack lookup note: {_ashok_err}")
                                    _ashok_uid = st.session_state.get("ashok_slack_uid", "")
                                    if not _toggles_to_request:
                                        st.info("No missing toggles to request. All detected toggles are already enabled.")
                                    if st.button(
                                        "📨 Notify Ashok to Enable Missing Toggle(s)",
                                        key=f"notify_toggle_{card.id}",
                                        type="primary",
                                        disabled=not _ashok_uid or not _toggles_to_request,
                                    ):
                                        _notif = notify_toggle_enablement(
                                            user_id=_ashok_uid,
                                            card_name=card.name,
                                            toggles=_toggles_to_request,
                                            store_name=_store_name,
                                            store_url=_store_url,
                                            store_uuid=(_live_state or {}).get("store_uuid", ""),
                                            account_uuid=(_live_state or {}).get("account_uuid", ""),
                                        )
                                        if _notif.get("ok"):
                                            st.session_state[_tog_notif_key] = {
                                                "ts": _notif.get("ts", ""),
                                                "channel": _notif.get("channel", ""),
                                            }
                                            st.session_state[_tog_sent_at_key] = time.time()
                                            st.success("Slack DM sent to Ashok Kumar.")
                                            st.rerun()
                                        else:
                                            st.error(_notif.get("error", "Toggle notification failed"))
                            st.markdown("---")

                    # ── Step 1b: AI Suggested User Story + AC ───────────────
                        st.markdown("#### AI Suggested User Story & AC")
                        _ac_key = f"ac_suggestion_{card.id}"
                        _ac_saved_key = f"ac_saved_{card.id}"
                        _ac_review_key = f"ac_review_{card.id}"
                        _ac_comment_key = f"ac_comment_posted_{card.id}"
                        _ac_skip_key = f"ac_skip_existing_{card.id}"
                        _ac_research_key = f"ac_research_{card.id}"
                        _ac_suggestion = st.session_state.get(_ac_key, "").strip()

                        if st.session_state.get(_ac_saved_key):
                            st.success("✅ AI-generated AC saved to Trello description")
                        if st.session_state.get(_ac_comment_key):
                            st.success("✅ AI-generated AC posted as a Trello comment")
                        if st.session_state.get(_ac_skip_key):
                            st.info("Existing Trello AC kept. AI suggestion skipped.")

                        if _ac_suggestion:
                            st.markdown(_ac_suggestion)
                            if st.session_state.get(_ac_research_key):
                                with st.expander("Requirement research used", expanded=False):
                                    st.markdown(st.session_state[_ac_research_key])
                            _ac_review = st.session_state.get(_ac_review_key) or {}
                            if _ac_review.get("needs_revision"):
                                with st.expander("AC review corrections", expanded=False):
                                    _issues = _ac_review.get("issues", []) or []
                                    _fixes = _ac_review.get("rewrite_instructions", []) or []
                                    if _issues:
                                        st.markdown("**Issues found**")
                                        for _item in _issues:
                                            st.markdown(f"- {_item}")
                                    if _fixes:
                                        st.markdown("**Auto-fixes applied**")
                                        for _item in _fixes:
                                            st.markdown(f"- {_item}")

                            if st.button("✨ Review & Improve AC", key=f"review_ac_{card.id}", help="Run an extra review pass to catch gaps and rewrite if needed (takes ~10s extra)"):
                                try:
                                    with st.spinner("Reviewing and improving AC…"):
                                        _raw = f"{card.name}\n\n{card.desc or ''}".strip()
                                        _research = st.session_state.get(_ac_research_key) or ""
                                        _improved = generate_acceptance_criteria(
                                            raw_request=_raw,
                                            attachments=card.attachments or None,
                                            checklists=card.checklists or None,
                                            research_context=_research,
                                            comments_context="\n".join(getattr(card, "comments", []) or []),
                                            labels=getattr(card, "labels", None) or [],
                                            review=True,
                                        )
                                    st.session_state[_ac_key] = _improved
                                    st.session_state[_ac_review_key] = get_last_ac_review()
                                    st.rerun()
                                except Exception as _rev_err:
                                    st.error(f"Review failed: {_rev_err}")

                            _ac_btn1, _ac_btn2, _ac_btn3, _ac_btn4, _ac_btn5 = st.columns(5)
                            with _ac_btn1:
                                if st.button("✅ Save to Trello Description", key=f"save_ac_{card.id}", use_container_width=True, type="primary"):
                                    try:
                                        _merged_desc = _merge_ai_ac_into_description(card.desc or "", _ac_suggestion)
                                        trello.update_card_description(card.id, _merged_desc)
                                        card.desc = _merged_desc
                                        st.session_state[_ac_saved_key] = True
                                        st.session_state[_ac_skip_key] = False
                                        _update_pipeline_run(
                                            card,
                                            ac_saved_at=datetime.now().isoformat(timespec="seconds"),
                                            ac_preview=_ac_suggestion[:1200],
                                        )
                                        st.rerun()
                                    except Exception as _save_err:
                                        st.error(f"Failed to save AC: {_save_err}")
                            with _ac_btn2:
                                if st.button("💬 Post Trello Comment", key=f"comment_ac_{card.id}", use_container_width=True):
                                    try:
                                        trello.add_comment(card.id, f"🤖 **QA AI-generated AC — {card.name}**\n\n{_ac_suggestion}")
                                        st.session_state[_ac_comment_key] = True
                                        st.rerun()
                                    except Exception as _comment_err:
                                        st.error(f"Failed to post AC comment: {_comment_err}")
                            with _ac_btn3:
                                if st.button("⏭️ Skip - Keep Existing", key=f"skip_ac_{card.id}", use_container_width=True):
                                    st.session_state[_ac_skip_key] = True
                                    st.rerun()
                            with _ac_btn4:
                                if st.button("📨 Send via Slack DM", key=f"open_dm_ac_{card.id}", use_container_width=True):
                                    st.session_state[f"show_dm_ac_{card.id}"] = True
                                    st.session_state[f"show_ch_ac_{card.id}"] = False
                            with _ac_btn5:
                                if st.button("📢 Send to Channel", key=f"open_ch_ac_{card.id}", use_container_width=True):
                                    st.session_state[f"show_ch_ac_{card.id}"] = True
                                    st.session_state[f"show_dm_ac_{card.id}"] = False

                            if st.session_state.get(f"show_ch_ac_{card.id}"):
                                st.markdown("##### 📢 Post AC to Slack Channel")
                                _render_slack_channel_panel(
                                    panel_key=f"ac_channel_{card.id}",
                                    card_name=card.name,
                                    content_text=_ac_suggestion,
                                    content_label="Acceptance Criteria",
                                    card_url=getattr(card, "url", ""),
                                )
                            if st.session_state.get(f"show_dm_ac_{card.id}"):
                                st.markdown("##### 📨 Send AC via Slack DM")
                                _render_slack_dm_panel(
                                    panel_key=f"ac_dm_{card.id}",
                                    card_name=card.name,
                                    content_text=_ac_suggestion,
                                    content_label="Acceptance Criteria",
                                )
                        else:
                            if st.button("🤖 Generate User Story & AC", key=f"gen_ac_{card.id}"):
                                try:
                                    from pipeline.requirement_research import build_requirement_research_context

                                    _raw = f"{card.name}\n\n{card.desc or ''}".strip()
                                    _comments = "\n".join(getattr(card, "comments", []) or [])
                                    with st.spinner("Generating User Story & AC…"):
                                        _research = build_requirement_research_context(_raw)
                                        _generated = generate_acceptance_criteria(
                                            raw_request=_raw,
                                            attachments=card.attachments or None,
                                            checklists=card.checklists or None,
                                            research_context=_research,
                                            comments_context=_comments,
                                            labels=getattr(card, "labels", None) or [],
                                        )
                                    st.session_state[_ac_key] = _generated
                                    st.session_state[_ac_review_key] = get_last_ac_review()
                                    st.session_state[_ac_research_key] = _research
                                    st.session_state[_ac_comment_key] = False
                                    st.session_state[_ac_saved_key] = False
                                    st.session_state[_ac_skip_key] = False
                                    st.session_state[f"validation_{card.id}"] = validate_card(
                                        card_name=card.name,
                                        card_desc=card.desc or "",
                                        acceptance_criteria=_generated,
                                        research_context=_research,
                                    )
                                    _vr = st.session_state.get(f"validation_{card.id}")
                                    _update_pipeline_run(
                                        card,
                                        ac_generated_at=datetime.now().isoformat(timespec="seconds"),
                                        ac_validated_at=datetime.now().isoformat(timespec="seconds"),
                                        ac_validation_status=getattr(_vr, "overall_status", ""),
                                        ac_validation_summary=getattr(_vr, "summary", ""),
                                        ac_preview=_generated[:1200],
                                    )
                                    st.rerun()
                                except Exception as _ac_err:
                                    st.error(f"AC generation failed: {_ac_err}")

                        # ── Step 2: Domain validation ───────────────────────────
                        if _vr:
                            _badge_color = {"PASS": "green", "NEEDS_REVIEW": "orange", "FAIL": "red"}.get(_vr.overall_status, "gray")
                            st.markdown(f"**Domain Validation:** :{_badge_color}[{_vr.overall_status}] — {_vr.summary}")
                            if _vr.error:
                                st.info(f"Validation used fallback reasoning: {_vr.error}")
                            if _vr.requirement_gaps or _vr.ac_gaps or _vr.accuracy_issues:
                                with st.expander("🔍 Validation Issues", expanded=_vr.overall_status == "FAIL"):
                                    if _vr.requirement_gaps:
                                        st.markdown("**Requirement Gaps:**")
                                        for g in _vr.requirement_gaps:
                                            st.markdown(f"- {g}")
                                    if _vr.ac_gaps:
                                        st.markdown("**AC Gaps:**")
                                        for g in _vr.ac_gaps:
                                            st.markdown(f"- {g}")
                                    if _vr.accuracy_issues:
                                        st.markdown("**Accuracy Issues:**")
                                        for g in _vr.accuracy_issues:
                                            st.markdown(f"- {g}")
                            if _vr.suggestions:
                                with st.expander("💡 Suggestions"):
                                    for s in _vr.suggestions:
                                        st.markdown(f"- {s}")
                            if _vr.kb_insights:
                                st.caption(f"KB Insights: {_vr.kb_insights}")
                            _has_val_issues = any([
                                _vr.requirement_gaps,
                                _vr.ac_gaps,
                                _vr.accuracy_issues,
                                _vr.suggestions,
                            ])
                            if _has_val_issues:
                                _fix_col, _reval_col = st.columns(2)
                                with _fix_col:
                                    if st.button("🛠️ Apply Fixes to AC", key=f"apply_val_fix_{card.id}", use_container_width=True):
                                        try:
                                            _current_ac = st.session_state.get(f"ac_suggestion_{card.id}") or (card.desc or "")
                                            _research = st.session_state.get(f"ac_research_{card.id}", "")
                                            _fixed_ac = apply_validation_fixes(
                                                card_name=card.name,
                                                acceptance_criteria=_current_ac,
                                                report=_vr,
                                                research_context=_research,
                                            )
                                            st.session_state[f"ac_suggestion_{card.id}"] = _fixed_ac
                                            st.session_state[f"ac_saved_{card.id}"] = False
                                            st.session_state[f"ac_review_{card.id}"] = review_acceptance_criteria(
                                                raw_request=card.name,
                                                ac_markdown=_fixed_ac,
                                            )
                                            _update_pipeline_run(
                                                card,
                                                ac_updated_at=datetime.now().isoformat(timespec="seconds"),
                                                ac_preview=_fixed_ac[:1200],
                                            )
                                            st.success("Validation fixes applied to the AC draft.")
                                            st.rerun()
                                        except Exception as _fix_err:
                                            st.error(f"Could not apply validation fixes: {_fix_err}")
                                with _reval_col:
                                    if st.button("🔄 Re-validate after fix", key=f"reval_{card.id}", use_container_width=True):
                                        try:
                                            _fresh_card = trello.get_card(card.id) if trello else card
                                            if _fresh_card is not None:
                                                card.desc = getattr(_fresh_card, "desc", card.desc)
                                            _recheck_ac = st.session_state.get(f"ac_suggestion_{card.id}") or (card.desc or "")
                                            _research = st.session_state.get(f"ac_research_{card.id}", "")
                                            st.session_state[f"validation_{card.id}"] = validate_card(
                                                card_name=card.name,
                                                card_desc=card.desc or "",
                                                acceptance_criteria=_recheck_ac,
                                                research_context=_research,
                                            )
                                            _reval_report = st.session_state.get(f"validation_{card.id}")
                                            _update_pipeline_run(
                                                card,
                                                ac_validated_at=datetime.now().isoformat(timespec="seconds"),
                                                ac_validation_status=getattr(_reval_report, "overall_status", ""),
                                                ac_validation_summary=getattr(_reval_report, "summary", ""),
                                            )
                                            st.success("Validation re-run completed.")
                                            st.rerun()
                                        except Exception as _reval_err:
                                            st.error(f"Re-validation failed: {_reval_err}")
                        else:
                            st.info("Validation not yet run. Reload the release in `Validate AC`, or re-validate after AC changes.")

                        if _diag:
                            from pipeline.carrier_knowledge import detect_carrier_scope

                            _effective_scope = detect_carrier_scope(
                                getattr(card, "name", "") or "",
                                getattr(card, "desc", "") or "",
                                "\n".join(getattr(card, "comments", []) or []),
                                " ".join(getattr(card, "labels", []) or []),
                                _diag.get("summary", "") or "",
                                "\n".join(_diag.get("evidence", []) or []),
                            )
                            _carrier_scope_value = (
                                "carrier_specific"
                                if _effective_scope.scope == "carrier_specific"
                                else (_diag.get("carrier_scope") or "generic")
                            )
                            _carrier_scope = _carrier_scope_value.replace("_", " ")
                            _root_cause = (_diag.get("likely_root_cause") or "unclear").replace("_", " ")
                            st.markdown(
                                f"**Card Diagnosis:** `{_diag.get('issue_type', 'unknown')}`"
                                f" · carrier scope `{_carrier_scope}`"
                                f" · likely root cause `{_root_cause}`"
                                f" · confidence `{_diag.get('confidence', 'low')}`"
                            )
                            if _effective_scope.scope == "carrier_specific":
                                st.caption(
                                    "Detected carriers from card evidence: "
                                    + ", ".join(profile.canonical_name for profile in _effective_scope.carriers)
                                )
                            if _diag.get("error"):
                                st.info(f"Diagnosis used fallback reasoning: {_diag['error']}")
                            if _diag.get("summary"):
                                st.caption(_diag["summary"])
                            _evidence = _diag.get("evidence") or []
                            _next_checks = _diag.get("next_checks") or []
                            _strategy = _diag.get("suggested_test_strategy") or []
                            if _evidence or _next_checks or _strategy:
                                with st.expander("Diagnosis details", expanded=False):
                                    if _evidence:
                                        st.markdown("**Evidence**")
                                        for _item in _evidence:
                                            st.markdown(f"- {_item}")
                                    if _next_checks:
                                        st.markdown("**Next checks**")
                                        for _item in _next_checks:
                                            st.markdown(f"- {_item}")
                                    if _strategy:
                                        st.markdown("**Suggested QA strategy**")
                                        for _item in _strategy:
                                            st.markdown(f"- {_item}")
                        elif show_ac_stage:
                            st.caption("Diagnosis is being generated from the loaded card context.")

                        st.divider()

                    if show_ac_stage:
                        continue

                    if show_tc_stage:
                        st.divider()
                        _step_header("3", "Generate Test Cases")

                        _tc_key = f"tc_text_{card.id}"
                        _regen_key = f"force_regen_{card.id}"
                        _tc_review_key = f"tc_review_{card.id}"
                        _tc_feedback_key = f"feedback_{card.id}"
                        _tc_saved_key = f"tc_saved_{card.id}"
                        _tc_trello_saved_key = f"tc_trello_saved_{card.id}"
                        if _tc_saved_key not in st.session_state and _is_card_tc_published(card.id):
                            st.session_state[_tc_saved_key] = True
                        if _tc_trello_saved_key not in st.session_state and _is_card_tc_published(card.id):
                            st.session_state[_tc_trello_saved_key] = True
                        _existing_tcs_in_store = tc_store.get(card.id, "") or _existing_tc_markdown
                        _vr = st.session_state.get(f"validation_{card.id}")
                        _current_ac_for_tc = (
                            st.session_state.get(f"ac_suggestion_{card.id}", "").strip()
                            or (card.desc or "").strip()
                        )

                        if _vr and not getattr(_vr, "error", "") and getattr(_vr, "overall_status", "") == "FAIL":
                            st.warning(
                                "⚠️ Accuracy issues found above — consider fixing the card before generating. "
                                "You can still generate if you want to proceed."
                            )

                        if _existing_tcs_in_store and _tc_review_key not in st.session_state:
                            st.session_state[_tc_review_key] = review_test_cases(
                                card_name=card.name,
                                card_desc=_current_ac_for_tc or card.desc or "",
                                test_cases_markdown=_existing_tcs_in_store,
                            )

                        _has_tc = bool(st.session_state.get(_tc_key, "").strip())
                        _force_regen = st.session_state.get(_regen_key, False)

                        _gen_col, _regen_col = st.columns([3, 1])
                        with _gen_col:
                            _gen_tc_clicked = st.button(
                                "📋 Generate Test Cases",
                                key=f"gen_tc_stage_{card.id}",
                                disabled=_has_tc and not _force_regen,
                            )
                        with _regen_col:
                            if _has_tc and st.button("🔄 Regenerate", key=f"regen_tc_stage_{card.id}"):
                                st.session_state[_regen_key] = True
                                st.session_state[_tc_key] = ""
                                st.rerun()

                        if _gen_tc_clicked or (_force_regen and not _has_tc):
                            with st.spinner("Generating test cases…"):
                                generated_tcs = generate_test_cases(card, ac_text=_current_ac_for_tc)
                                st.session_state[_tc_key] = generated_tcs
                                st.session_state[_tc_review_key] = get_last_tc_review()
                                tc_store[card.id] = generated_tcs
                                st.session_state["rqa_test_cases"] = tc_store
                                st.session_state[_regen_key] = False
                                st.rerun()

                        if st.session_state.get(_tc_key, "").strip():
                            _previous_tc_text = st.session_state.get(_tc_key, "")
                            st.markdown(_previous_tc_text)
                            _edited_tc = st.text_area(
                                "Test Cases (editable)",
                                value=_previous_tc_text,
                                height=300,
                                key=f"tc_editor_stage_{card.id}",
                            )
                            st.session_state[_tc_key] = _edited_tc
                            tc_store[card.id] = _edited_tc
                            st.session_state["rqa_test_cases"] = tc_store
                            _tc_review = st.session_state.get(_tc_review_key) or {}
                            _tc_edited = _edited_tc.strip() != _previous_tc_text.strip()
                            if _tc_review.get("needs_revision"):
                                with st.expander("TC review corrections", expanded=False):
                                    for _item in (_tc_review.get("issues", []) or []):
                                        st.markdown(f"- {_item}")
                                    for _item in (_tc_review.get("rewrite_instructions", []) or []):
                                        st.markdown(f"- {_item}")
                            if _tc_edited:
                                _rr_col1, _rr_col2 = st.columns([3, 1])
                                with _rr_col1:
                                    st.info("Test cases were edited manually. Re-review before publishing to refresh QA guidance.")
                                with _rr_col2:
                                    if st.button("🔍 Re-review TCs", key=f"rereview_tc_stage_{card.id}", use_container_width=True):
                                        with st.spinner("Reviewing edited test cases…"):
                                            st.session_state[_tc_review_key] = review_test_cases(
                                                card_name=card.name,
                                                card_desc=_current_ac_for_tc or card.desc or "",
                                                test_cases_markdown=_edited_tc,
                                            )
                                        st.rerun()

                            _fb_col1, _fb_col2 = st.columns([4, 1])
                            with _fb_col1:
                                feedback = st.text_input(
                                    "✏️ Request changes",
                                    placeholder="e.g. Add a negative test for invalid carrier credentials",
                                    key=f"{_tc_feedback_key}_stage",
                                )
                            with _fb_col2:
                                st.markdown("<br>", unsafe_allow_html=True)
                                if st.button("🔄 Regenerate", key=f"regen_feedback_stage_{card.id}", use_container_width=True):
                                    if feedback.strip():
                                        updated_tcs = regenerate_with_feedback(
                                            card,
                                            _edited_tc,
                                            feedback,
                                            ac_text=_current_ac_for_tc,
                                        )
                                        st.session_state[_tc_key] = updated_tcs
                                        st.session_state[_tc_review_key] = get_last_tc_review()
                                        tc_store[card.id] = updated_tcs
                                        st.session_state["rqa_test_cases"] = tc_store
                                        st.rerun()
                                    st.warning("Type your feedback first.")

                            _tc_btn1, _tc_btn2 = st.columns(2)
                            with _tc_btn1:
                                if st.button("📨 Send Test Cases via Slack DM", key=f"open_dm_tc_stage_{card.id}", use_container_width=True):
                                    st.session_state[f"show_dm_tc_{card.id}"] = True
                                    st.session_state[f"show_ch_tc_{card.id}"] = False
                            with _tc_btn2:
                                if st.button("📢 Send to Slack Channel", key=f"open_ch_tc_stage_{card.id}", use_container_width=True):
                                    st.session_state[f"show_ch_tc_{card.id}"] = True
                                    st.session_state[f"show_dm_tc_{card.id}"] = False

                            _tc_dm_sent_key = f"tc_dm_sent_{card.id}"
                            _tc_ch_sent_key = f"tc_ch_sent_{card.id}"
                            if st.session_state.get(_tc_dm_sent_key):
                                st.success("✅ Test cases sent via Slack DM!")
                                if st.button("📨 Send again", key=f"tc_dm_resend_stage_{card.id}"):
                                    st.session_state[_tc_dm_sent_key] = False
                                    st.session_state[f"show_dm_tc_{card.id}"] = True
                                    st.session_state[f"show_ch_tc_{card.id}"] = False
                                    st.rerun()
                            elif st.session_state.get(_tc_ch_sent_key):
                                st.success("✅ Test cases posted to Slack channel!")
                                if st.button("📢 Post again", key=f"tc_ch_resend_stage_{card.id}"):
                                    st.session_state[_tc_ch_sent_key] = False
                                    st.session_state[f"show_ch_tc_{card.id}"] = True
                                    st.session_state[f"show_dm_tc_{card.id}"] = False
                                    st.rerun()

                            if st.session_state.get(f"show_ch_tc_{card.id}"):
                                st.markdown("##### 📢 Post Test Cases to Slack Channel")
                                _render_slack_channel_panel(
                                    panel_key=f"tc_channel_stage_{card.id}",
                                    card_name=card.name,
                                    content_text=_edited_tc,
                                    content_label="Test Cases",
                                    card_url=getattr(card, "url", ""),
                                )
                                if st.button("Mark TC channel post sent", key=f"tc_ch_mark_sent_{card.id}", use_container_width=True):
                                    st.session_state[_tc_ch_sent_key] = True
                                    st.session_state[f"show_ch_tc_{card.id}"] = False
                                    st.rerun()
                            if st.session_state.get(f"show_dm_tc_{card.id}"):
                                st.markdown("##### 📨 Send Test Cases via Slack DM")
                                _render_slack_dm_panel(
                                    panel_key=f"tc_dm_stage_{card.id}",
                                    card_name=card.name,
                                    content_text=_edited_tc,
                                    content_label="Test Cases",
                                )
                                if st.button("Mark TC DM sent", key=f"tc_dm_mark_sent_{card.id}", use_container_width=True):
                                    st.session_state[_tc_dm_sent_key] = True
                                    st.session_state[f"show_dm_tc_{card.id}"] = False
                                    st.rerun()

                            st.divider()
                            _step_header("4", "Publish Test Cases")
                            if st.session_state.get(_tc_saved_key):
                                st.success("✅ Test cases already published to Trello and Google Sheets for this card.")
                            else:
                                st.caption("Publishing writes a QA summary comment to Trello and positive test-case rows to Google Sheets.")

                            _tc_total, _tc_pos, _tc_neg, _tc_edge = _summarise_tc_counts(card.name, _edited_tc)
                            st.caption(
                                f"📊 **{_tc_total} total TCs** · "
                                f"✅ {_tc_pos} positive → Sheet · "
                                f"❌ {_tc_neg} negative → Trello comment only · "
                                f"⚠️ {_tc_edge} edge → Trello comment only"
                            )

                            _publish_tab_key = f"tc_publish_tab_{card.id}"
                            _publish_dup_key = f"tc_publish_dups_{card.id}"
                            _publish_dup_tab_key = f"tc_publish_dups_tab_{card.id}"
                            _publish_dup_override_key = f"tc_publish_dup_override_{card.id}"
                            _publish_new_tab_key = f"tc_publish_new_tab_{card.id}"
                            _publish_created_tab_key = f"tc_publish_created_tab_{card.id}"

                            _suggested_tab = detect_tab(card.name, _edited_tc)
                            _live_publish_tabs = _sheet_tab_options()
                            if _publish_tab_key not in st.session_state:
                                st.session_state[_publish_tab_key] = _suggested_tab if _suggested_tab in _live_publish_tabs else "Draft Plan"

                            _publish_cols = st.columns([3, 2])
                            with _publish_cols[0]:
                                _publish_options = list(_live_publish_tabs)
                                _newly_created_tab = st.session_state.get(_publish_created_tab_key, "")
                                if _newly_created_tab and _newly_created_tab not in _publish_options:
                                    _publish_options.insert(0, _newly_created_tab)
                                _selected_publish_tab = st.selectbox(
                                    "📊 Google Sheets tab for positive TCs",
                                    options=_publish_options,
                                    key=_publish_tab_key,
                                )
                            with _publish_cols[1]:
                                _new_publish_tab_name = st.text_input(
                                    "➕ Or create new tab",
                                    key=_publish_new_tab_key,
                                    placeholder="New tab name…",
                                    label_visibility="collapsed",
                                )
                                if st.button("➕ Create Tab", key=f"tc_publish_create_tab_{card.id}", use_container_width=True):
                                    if _new_publish_tab_name.strip():
                                        with st.spinner(f"Creating tab '{_new_publish_tab_name.strip()}'…"):
                                            _create_tab_result = create_new_tab(_new_publish_tab_name.strip())
                                        if _create_tab_result.get("ok"):
                                            _created_tab = _create_tab_result["tab"]
                                            _live_tabs = st.session_state.get("live_sheet_tabs", list(SHEET_TABS))
                                            if _created_tab not in _live_tabs:
                                                _live_tabs.append(_created_tab)
                                                st.session_state["live_sheet_tabs"] = _live_tabs
                                            st.session_state[_publish_created_tab_key] = _created_tab
                                            st.session_state[_publish_tab_key] = _created_tab
                                            st.success(f"✅ Tab '{_created_tab}' ready")
                                            st.rerun()
                                        st.error(f"❌ Failed: {_create_tab_result.get('error', 'unknown error')}")
                                    else:
                                        st.warning("Enter a tab name first.")

                            _publish_rows = parse_test_cases_to_rows(
                                card.name,
                                _edited_tc,
                                epic=card.name,
                                positive_only=True,
                            )
                            _pub_metric1, _pub_metric2 = st.columns(2)
                            with _pub_metric1:
                                st.metric("Google Sheets rows to write", len(_publish_rows))
                            with _pub_metric2:
                                st.metric("Suggested Google Sheets tab", _suggested_tab)

                            _pub_dup_cols = st.columns([1, 3])
                            with _pub_dup_cols[0]:
                                _check_publish_dups = st.button(
                                    "🔎 Check duplicates",
                                    key=f"check_tc_publish_dups_{card.id}",
                                    use_container_width=True,
                                )
                            with _pub_dup_cols[1]:
                                st.caption("Review Google Sheets duplicate risk before publishing. Trello will still receive the QA summary comment.")

                            if _check_publish_dups:
                                with st.spinner("Checking duplicates in Google Sheets…"):
                                    try:
                                        _publish_dups = check_duplicates(_publish_rows, _selected_publish_tab)
                                        st.session_state[_publish_dup_key] = _publish_dups
                                        st.session_state[_publish_dup_tab_key] = _selected_publish_tab
                                    except Exception as _dup_err:
                                        st.session_state[_publish_dup_key] = []
                                        st.session_state[_publish_dup_tab_key] = _selected_publish_tab
                                        st.warning(f"Duplicate check failed: {_dup_err}")

                            _publish_dups = st.session_state.get(_publish_dup_key, [])
                            if st.session_state.get(_publish_dup_tab_key) != _selected_publish_tab:
                                _publish_dups = []
                                st.session_state[_publish_dup_key] = []
                                st.session_state[_publish_dup_tab_key] = _selected_publish_tab

                            if _publish_dups:
                                st.warning(
                                    f"{len(_publish_dups)} potential duplicate(s) found in sheet tab '{_selected_publish_tab}'."
                                )
                                with st.expander("Potential duplicates", expanded=False):
                                    for _dup in _publish_dups[:10]:
                                        st.markdown(
                                            f"- `{_dup.new_scenario}` matches `{_dup.existing_scenario}` "
                                            f"({int(_dup.similarity * 100)}%)"
                                        )
                                st.checkbox("Skip duplicate TCs (only add new ones)", key=_publish_dup_override_key)
                            else:
                                st.caption("No duplicate warning recorded for the selected sheet tab yet.")

                            _pub_action_cols = st.columns([1, 1])
                            with _pub_action_cols[0]:
                                _save_trello_only = st.button("💬 Save to Trello Comment", key=f"save_trello_tc_{card.id}", use_container_width=True)
                            with _pub_action_cols[1]:
                                _publish_full = st.button("📤 Publish Test Cases", key=f"publish_tcs_{card.id}", type="primary", use_container_width=True)

                            if _save_trello_only:
                                with st.spinner("Saving test cases to Trello comment…"):
                                    try:
                                        write_test_cases_to_card(
                                            card_id=card.id,
                                            test_cases=_edited_tc,
                                            trello=trello,
                                            release=st.session_state.get("rqa_release", ""),
                                            card_name=card.name,
                                        )
                                        st.success("✅ Test cases saved to Trello comment.")
                                    except Exception as _trello_only_err:
                                        st.error(f"Failed to save to Trello: {_trello_only_err}")

                            if _publish_full:
                                with st.spinner("Publishing test cases to Trello and Google Sheets…"):
                                    _publish_errors = []
                                    _tc_to_write = _edited_tc
                                    _skipped_duplicates = 0

                                    try:
                                        if not st.session_state.get(_tc_trello_saved_key, False):
                                            write_test_cases_to_card(
                                                card_id=card.id,
                                                test_cases=_edited_tc,
                                                trello=trello,
                                                release=st.session_state.get("rqa_release", ""),
                                                card_name=card.name,
                                            )
                                        st.session_state[_tc_trello_saved_key] = True
                                    except Exception as _trello_err:
                                        _publish_errors.append(f"Trello: {_trello_err}")

                                    _publish_sheet_result = None
                                    try:
                                        if _publish_dups and st.session_state.get(_publish_dup_override_key, False):
                                            _tc_to_write, _skipped_duplicates = _filter_duplicate_test_cases(
                                                _edited_tc,
                                                _publish_dups,
                                            )
                                        _publish_sheet_result = append_to_sheet(
                                            card_name=card.name,
                                            test_cases_markdown=_tc_to_write,
                                            epic=card.name,
                                            tab_name=_selected_publish_tab,
                                            release=st.session_state.get("rqa_release", ""),
                                            card_url=getattr(card, "url", ""),
                                        )
                                    except Exception as _sheet_err:
                                        _publish_errors.append(f"Sheets: {_sheet_err}")

                                    if _publish_errors:
                                        for _err in _publish_errors:
                                            st.warning(f"⚠️ {_err}")
                                        if st.session_state.get(_tc_trello_saved_key, False):
                                            st.info("Trello comment is already saved. Retry will only need to complete Google Sheets.")
                                    else:
                                        st.session_state[_tc_saved_key] = True
                                        _update_pipeline_run(
                                            card,
                                            tc_published_at=datetime.now().isoformat(timespec="seconds"),
                                            test_cases=_edited_tc[:1200],
                                            sheet_tab=(_publish_sheet_result or {}).get("tab", ""),
                                            sheet_rows=(_publish_sheet_result or {}).get("rows_added", 0),
                                        )
                                        st.success("✅ Test cases published to Trello and Google Sheets.")
                                        if _publish_sheet_result and _publish_sheet_result.get("rows_added"):
                                            _skip_suffix = f" ({_skipped_duplicates} duplicates skipped)" if _skipped_duplicates else ""
                                            st.caption(
                                                f"Sheet rows added: {_publish_sheet_result['rows_added']} to '{_publish_sheet_result['tab']}'{_skip_suffix}"
                                            )
                        elif _existing_tcs_in_store:
                            st.info("This card already has saved test cases in Trello. Generate TC is using those as the starting point.")
                            if st.button("📥 Reload Trello TCs", key=f"reload_tc_stage_{card.id}"):
                                st.session_state[_tc_key] = _existing_tcs_in_store
                                st.session_state[_tc_review_key] = review_test_cases(
                                    card_name=card.name,
                                    card_desc=card.desc or "",
                                    test_cases_markdown=_existing_tcs_in_store,
                                )
                                tc_store[card.id] = _existing_tcs_in_store
                                st.session_state["rqa_test_cases"] = tc_store
                                st.rerun()
                        continue

                    _automation_container = st.container()

                    if show_ai_stage:
                        # ── Step 1: AI QA Agent ─────────────────────────────────
                        _step_header("1", "AI QA Agent")
                        st.caption(
                            "Claude opens Chrome, uses automation navigation + MCSL domain knowledge, "
                            "walks the live app, verifies each generated test case, and asks QA only when needed."
                        )

                        _sav_running_key    = f"sav_running_{card.id}"
                        _sav_stop_key       = f"sav_stop_{card.id}"
                        _sav_stop_event_key = f"sav_stop_event_{card.id}"
                        _sav_result_key     = f"sav_result_{card.id}"
                        _sav_prog_key       = f"sav_prog_{card.id}"
                        _sav_report_key     = f"sav_report_{card.id}"
                        _sav_url_key        = f"sav_url_{card.id}"
                        _sav_complexity_key = f"sav_complexity_{card.id}"
                        _sav_qa_answers_key = f"sav_qa_answers_{card.id}"
                        _sav_bug_sel_key    = f"sav_bug_selection_{card.id}"
                        _sav_auto_retry_key = f"sav_auto_retry_{card.id}"

                        _is_running = st.session_state.get(_sav_running_key, False)
                        _tc_for_agent = (tc_store.get(card.id) or st.session_state.get(f"tc_text_{card.id}", "")).strip()
                        _ranked_tcs = rank_test_cases_for_execution(_tc_for_agent) if _tc_for_agent else []
                        try:
                            from pipeline.carrier_knowledge import get_default_app_url

                            _auto_url = get_default_app_url(
                                card.name or "",
                                card.desc or "",
                                "\n".join(getattr(card, "comments", []) or []),
                                (_diag.get("carrier_scope") or "") if _diag else "",
                            )
                        except Exception:
                            _auto_url = ""

                        url_val = st.text_input(
                            "App URL",
                            value=st.session_state.get(_sav_url_key, _auto_url),
                            placeholder="https://admin.shopify.com/store/YOUR-STORE/apps/mcsl-app",
                            key=_sav_url_key,
                            disabled=_is_running,
                            help="Auto-filled from carrier/generic store env. QA can edit it before running.",
                        )
                        _limit_toggle_key = f"sav_limit_enabled_{card.id}"
                        _limit_enabled = st.checkbox(
                            "Limit test cases for this run",
                            value=st.session_state.get(_limit_toggle_key, False),
                            key=_limit_toggle_key,
                            disabled=_is_running or not _ranked_tcs,
                            help="Leave this off to run all generated test cases.",
                        )
                        if _limit_enabled and _ranked_tcs:
                            complexity_val = st.number_input(
                                "Max items to verify",
                                min_value=1,
                                max_value=len(_ranked_tcs),
                                value=min(
                                    st.session_state.get(_sav_complexity_key, len(_ranked_tcs)),
                                    len(_ranked_tcs),
                                ),
                                key=_sav_complexity_key,
                                disabled=_is_running,
                            )
                        else:
                            complexity_val = len(_ranked_tcs) if _ranked_tcs else 0

                        if _ranked_tcs:
                            _planned_count = int(complexity_val) if _limit_enabled else len(_ranked_tcs)
                            st.caption(
                                f"TC-based verification mode — {_planned_count}/{len(_ranked_tcs)} reviewed test case(s) planned for this run"
                            )
                            with st.expander("Planned TC execution order", expanded=False):
                                for _tc in _ranked_tcs[:_planned_count]:
                                    st.markdown(f"- `{_tc.tc_id}` [{_tc.priority}/{_tc.tc_type}] {_tc.title}")
                        else:
                            st.warning("TC-based verification requires generated test cases. Generate them in Step 3 first, then return here.")

                        _btn_col, _smart_col, _stop_col = st.columns([3, 3, 1])
                        with _btn_col:
                            _existing_report = st.session_state.get(_sav_report_key)
                            run_clicked = st.button(
                                "🔁 Re-verify Failed" if _existing_report and _ranked_tcs else "🤖 Run AI QA Agent",
                                key=f"run_sav_{card.id}",
                                disabled=_is_running or not url_val or not _ranked_tcs,
                                type="primary",
                            )
                        with _smart_col:
                            run_smart_clicked = st.button(
                                "🚀 Run Smart",
                                key=f"run_smart_{card.id}",
                                disabled=_is_running or not url_val or not _ranked_tcs,
                                help="Queries wiki, TC sheet, KB articles, and automation repo before running — gives the agent full knowledge context for every scenario.",
                            )
                        with _stop_col:
                            stop_clicked = st.button(
                                "⏹ Stop",
                                key=f"stop_sav_{card.id}",
                                disabled=not _is_running,
                            )
                        if st.session_state.get(_sav_auto_retry_key) and not _is_running and url_val and _ranked_tcs:
                            run_clicked = True
                            st.session_state[_sav_auto_retry_key] = False

                        if stop_clicked and _is_running:
                            st.session_state[_sav_stop_key] = True
                            _ev = st.session_state.get(_sav_stop_event_key)
                            if _ev:
                                _ev.set()

                        # Build smart KB context when Run Smart is clicked (before thread)
                        _smart_ctx_key = f"sav_smart_ctx_{card.id}"
                        if run_smart_clicked and url_val and not _is_running and _ranked_tcs:
                            from pipeline.smart_ac_verifier import build_smart_context as _build_smart_ctx
                            with st.spinner("🔍 Querying knowledge base (wiki, TC sheet, automation repo)…"):
                                _smart_ctx = _build_smart_ctx(card.name, _tc_for_agent)
                            st.session_state[_smart_ctx_key] = _smart_ctx
                            _src_count = _smart_ctx.count("###")
                            st.info(f"✅ Smart context built — {_src_count} knowledge source(s) loaded. Starting run…")
                            run_clicked = True   # reuse the same thread path below

                        if run_clicked and url_val and not _is_running and _ranked_tcs:
                            import threading as _threading
                            _stop_event = _threading.Event()
                            st.session_state[_sav_running_key]    = True
                            st.session_state[_sav_stop_key]       = False
                            st.session_state[_sav_stop_event_key] = _stop_event
                            st.session_state[_sav_result_key]     = {"done": False}
                            st.session_state.pop(_sav_prog_key, None)

                            def _run_sav_thread(
                                _url=url_val,
                                _card_name=card.name,
                                _tc_markdown=_tc_for_agent,
                                _qa_answers=st.session_state.get(_sav_qa_answers_key, {}),
                                _max=(int(complexity_val) if _limit_enabled else None),
                                _event=_stop_event,
                                _rk=_sav_result_key,
                                _sk=_sav_stop_key,
                                _sek=_sav_stop_event_key,
                                _pk=_sav_prog_key,
                                _repk=_sav_report_key,
                                _smart_ctx=st.session_state.get(_smart_ctx_key, ""),
                            ):
                                try:
                                    def _prog_cb(sc_idx, sc_title, step_num, step_desc):
                                        pct = min(0.05 + sc_idx * 0.3 + step_num * 0.05, 0.95)
                                        st.session_state[_pk] = {
                                            "pct": pct,
                                            "text": f"[{sc_title}] Step {step_num}: {step_desc}",
                                        }

                                    _previous_report = st.session_state.get(_repk)
                                    if _previous_report:
                                        report = reverify_failed(
                                            previous_report=_previous_report,
                                            test_cases_markdown=_tc_markdown,
                                            card_name=_card_name,
                                            app_url=_url,
                                            stop_flag=lambda: _event.is_set() or st.session_state.get(_sk, False),
                                            progress_cb=_prog_cb,
                                            qa_answers=_qa_answers,
                                        )
                                    else:
                                        report = verify_test_cases(
                                            test_cases_markdown=_tc_markdown,
                                            card_name=_card_name,
                                            app_url=_url,
                                            stop_flag=lambda: _event.is_set() or st.session_state.get(_sk, False),
                                            progress_cb=_prog_cb,
                                            qa_answers=_qa_answers,
                                            max_test_cases=_max,
                                            smart_baseline_ctx=_smart_ctx,
                                        )
                                    st.session_state[_repk] = report
                                    st.session_state[_rk] = {"done": True, "report": report, "error": None}
                                except Exception as _ex:
                                    st.session_state[_rk] = {"done": True, "report": None, "error": str(_ex)}
                                finally:
                                    st.session_state.pop(_sek, None)
                                    st.session_state[_sav_running_key] = False

                            _threading.Thread(target=_run_sav_thread, daemon=True).start()
                            st.rerun()

                        if _is_running:
                            _prog = st.session_state.get(_sav_prog_key, {})
                            st.progress(_prog.get("pct", 0.05), text=_prog.get("text", "Running AI QA Agent…"))
                            st.caption("Agent is running. Results appear when complete.")
                            import time as _time
                            _time.sleep(3)
                            st.rerun()

                        _result = st.session_state.get(_sav_result_key, {})
                        if _result.get("done"):
                            if _result.get("error"):
                                st.error(f"Agent error: {_result['error']}")
                            elif _result.get("report"):
                                _rpt = _result["report"]
                                _summary = getattr(_rpt, "summary", {}) or {}
                                st.success(
                                    f"Agent completed — PASS {_summary.get('pass', 0)} · "
                                    f"FAIL {_summary.get('fail', 0)} · "
                                    f"PARTIAL {_summary.get('partial', 0)} · "
                                    f"QA NEEDED {_summary.get('qa_needed', 0)}"
                                )
                                with st.expander("🧭 Locator Learning Review", expanded=False):
                                    _render_locator_learning_review(
                                        _rpt,
                                        card_name=card.name,
                                        key_prefix=f"locator_review_{card.id}",
                                    )
                                with st.expander("📋 QA Evidence Review", expanded=False):
                                    _render_report_review(_rpt, key_prefix=f"qa_review_{card.id}")
                                with st.expander("Raw QA JSON", expanded=False):
                                    st.json(_rpt.to_dict() if hasattr(_rpt, "to_dict") else str(_rpt))

                                _qa_needed = getattr(_rpt, "qa_needed_list", []) or []
                                if _qa_needed:
                                    st.warning(f"{len(_qa_needed)} scenario(s) need QA guidance before the agent can continue.")
                                    _qa_answers = dict(st.session_state.get(_sav_qa_answers_key, {}))
                                    for _qi, _sv in enumerate(_qa_needed, start=1):
                                        st.markdown(f"**QA Needed {_qi}: {_sv.scenario}**")
                                        if getattr(_sv, "qa_question", ""):
                                            st.caption(_sv.qa_question)
                                        _qa_answers[_sv.scenario] = st.text_area(
                                            "Your answer",
                                            value=_qa_answers.get(_sv.scenario, ""),
                                            key=f"qa_answer_{card.id}_{_qi}",
                                            height=80,
                                        )
                                    st.session_state[_sav_qa_answers_key] = _qa_answers
                                    if st.button("🔁 Re-run QA Needed Scenarios", key=f"rerun_qa_needed_{card.id}", type="primary"):
                                        if any(v.strip() for v in _qa_answers.values()):
                                            st.session_state[_sav_auto_retry_key] = True
                                            st.rerun()
                                        else:
                                            st.warning("Enter at least one QA answer first.")

                                _bugs_to_review = [
                                    _sv for _sv in getattr(_rpt, "scenarios", [])
                                    if _sv.status in ("fail", "partial")
                                ]
                                if _bugs_to_review:
                                    st.divider()
                                    st.markdown(
                                        '<div class="step-chip">🐛 Bug Review</div>',
                                        unsafe_allow_html=True,
                                    )
                                    st.markdown(
                                        f"**{len(_bugs_to_review)} issue(s) found** — select which ones should be treated as bugs/backlog items."
                                    )
                                    _bug_sel = dict(st.session_state.get(_sav_bug_sel_key, {}))
                                    if not _bug_sel:
                                        _bug_sel = {i: True for i in range(len(_bugs_to_review))}
                                    _bug_sent_key = f"bug_notify_result_{card.id}"

                                    _bug_all_col, _bug_none_col, _ = st.columns([1, 1, 4])
                                    with _bug_all_col:
                                        if st.button("☑ Select All", key=f"bug_sel_all_{card.id}", use_container_width=True):
                                            st.session_state[_sav_bug_sel_key] = {
                                                i: True for i in range(len(_bugs_to_review))
                                            }
                                            st.rerun()
                                    with _bug_none_col:
                                        if st.button("☐ None", key=f"bug_sel_none_{card.id}", use_container_width=True):
                                            st.session_state[_sav_bug_sel_key] = {
                                                i: False for i in range(len(_bugs_to_review))
                                            }
                                            st.rerun()

                                    for _bi, _bsv in enumerate(_bugs_to_review):
                                        _label = f"{'❌' if _bsv.status == 'fail' else '⚠️'} {_bsv.scenario[:100]}"
                                        _bug_sel[_bi] = st.checkbox(
                                            _label,
                                            value=_bug_sel.get(_bi, True),
                                            key=f"bug_pick_{card.id}_{_bi}",
                                        )
                                        if _bug_sel[_bi] and (_bsv.finding or _bsv.status):
                                            st.caption(f"   → {(_bsv.finding or _bsv.status)[:150]}")
                                    st.session_state[_sav_bug_sel_key] = _bug_sel

                                    _selected_bug_lines = [
                                        f"[{card.name}] {(_bsv.scenario)} — {(_bsv.finding or _bsv.status)}"
                                        for _bi, _bsv in enumerate(_bugs_to_review)
                                        if _bug_sel.get(_bi, False)
                                    ]
                                    _selected_count = len(_selected_bug_lines)
                                    if _selected_bug_lines:
                                        _bug_action_col1, _bug_action_col2 = st.columns(2)
                                        with _bug_action_col1:
                                            if st.button(
                                                "📝 Add Selected to Sign-Off Backlog",
                                                key=f"add_bug_backlog_{card.id}",
                                                use_container_width=True,
                                            ):
                                                _existing = st.session_state.get("signoff_bugs", "").strip()
                                                _merged = [line for line in (_existing.splitlines() if _existing else []) if line.strip()]
                                                for _line in _selected_bug_lines:
                                                    if _line not in _merged:
                                                        _merged.append(_line)
                                                st.session_state["signoff_bugs"] = "\n".join(_merged)
                                                st.success("Selected findings added to sign-off backlog draft.")
                                        with _bug_action_col2:
                                            if slack_configured() and st.button(
                                                f"📨 Notify Assigned Devs ({_selected_count})",
                                                key=f"notify_bug_devs_{card.id}",
                                                use_container_width=True,
                                                type="primary",
                                            ):
                                                try:
                                                    _dm_result = notify_devs_of_bug(
                                                        card_id=card.id,
                                                        card_name=card.name,
                                                        bug_description="; ".join(_selected_bug_lines),
                                                        trello_client=trello,
                                                        slack_client=__import__("pipeline.slack_client", fromlist=["SlackClient"]).SlackClient(),
                                                    )
                                                    st.session_state[_bug_sent_key] = _dm_result
                                                    if _dm_result.get("error"):
                                                        st.warning(_dm_result["error"])
                                                    else:
                                                        st.success(f"Notified {_dm_result.get('sent_count', 0)} assigned developer(s).")
                                                except Exception as _bug_err:
                                                    st.warning(f"Bug notification failed: {_bug_err}")
                                    else:
                                        st.caption("No bug findings selected.")

                                    _bug_sent_result = st.session_state.get(_bug_sent_key, {})
                                    if _bug_sent_result:
                                        if _bug_sent_result.get("error"):
                                            st.warning(f"Bug notify failed: {_bug_sent_result['error']}")
                                        elif _bug_sent_result.get("sent_count"):
                                            st.success(f"🐛 Bug DM sent to {_bug_sent_result['sent_count']} assigned developer(s).")
                                        else:
                                            st.info("No assigned developer was notified for the selected findings.")

                        # ── Step 2: Ask Domain Expert ───────────────────────────
                        st.divider()
                        _step_header("2", "Ask Domain Expert")
                        st.caption(
                            "Use the domain expert when QA needs product behavior, prerequisites, "
                            "carrier-specific guidance, or wants to escalate a likely bug to the assigned developer."
                        )
                        from pipeline.bug_reporter import ask_domain_expert, notify_devs_of_bug

                        _dex_hist_key = f"dex_history_{card.id}"
                        _dex_question_key = f"dex_question_{card.id}"
                        if _dex_hist_key not in st.session_state:
                            st.session_state[_dex_hist_key] = []
                        _dex_history = st.session_state.get(_dex_hist_key, [])

                        for _entry in _dex_history:
                            st.markdown(f"**🙋 You:** {_entry.get('q', '')}")
                            st.info(f"🤖 **Domain Expert:** {_entry.get('a', '')}")
                            _bug_report = _entry.get("bug_report") or {}
                            if _bug_report.get("error"):
                                st.warning(f"Bug notify failed: {_bug_report['error']}")
                            elif _bug_report.get("sent_count"):
                                st.success(f"🐛 Bug DM sent to {_bug_report['sent_count']} assigned developer(s).")
                            st.markdown("---")

                        _expert_default = (
                            f"For card '{card.name}', what are the expected MCSL behavior, prerequisites, "
                            f"carrier-specific considerations, and the best QA checks?"
                        )
                        _dex_col1, _dex_col2 = st.columns([5, 1])
                        with _dex_col1:
                            _expert_question = st.text_input(
                                "Your question",
                                value=st.session_state.get(_dex_question_key, _expert_default),
                                key=_dex_question_key,
                                label_visibility="collapsed",
                                placeholder="Ask about expected behavior, setup, or why the feature is failing…",
                            )
                        with _dex_col2:
                            _ask_clicked = st.button(
                                "Ask 🤖",
                                key=f"ask_expert_{card.id}",
                                use_container_width=True,
                                type="primary",
                            )

                        if _ask_clicked and _expert_question.strip():
                            with st.spinner("Querying MCSL domain knowledge…"):
                                try:
                                    _answer = ask_domain_expert(_expert_question.strip())
                                    _dex_history.append({"q": _expert_question.strip(), "a": _answer, "bug_report": {}})
                                    st.session_state[_dex_hist_key] = _dex_history
                                    st.session_state[_dex_question_key] = ""
                                    st.rerun()
                                except Exception as _expert_err:
                                    st.error(f"Domain expert query failed: {_expert_err}")

                        if _dex_history:
                            _last = _dex_history[-1]
                            _bug_col1, _bug_col2 = st.columns([2, 3])
                            with _bug_col1:
                                if st.button(
                                    "🐛 This is a Bug — Notify Developer",
                                    key=f"dex_bug_{card.id}",
                                    use_container_width=True,
                                ):
                                    try:
                                        from pipeline.slack_client import SlackClient
                                        _bug_res = notify_devs_of_bug(
                                            card_id=card.id,
                                            card_name=card.name,
                                            bug_description=f"{_last.get('q', '')}\n\n{_last.get('a', '')}",
                                            trello_client=trello,
                                            slack_client=SlackClient(),
                                        )
                                        _last["bug_report"] = _bug_res
                                        _dex_history[-1] = _last
                                        st.session_state[_dex_hist_key] = _dex_history
                                        st.rerun()
                                    except Exception as _bug_err:
                                        st.warning(f"Bug notification failed: {_bug_err}")
                            with _bug_col2:
                                if st.button("🗑 Clear conversation", key=f"dex_clear_{card.id}", use_container_width=True):
                                    st.session_state[_dex_hist_key] = []
                                    st.rerun()

                        # ── Step 3: Final Approval ──────────────────────────────
                        st.divider()
                        _step_header("3", "Final Approval")
                        st.caption(
                            "Review AI QA results, confirm the sheet destination, handle duplicate test cases, "
                            "and finalize approval for the card."
                        )

                        _tc_key = f"tc_text_{card.id}"
                        _tc_markdown = st.session_state.get(_tc_key, "").strip()
                        _is_approved = approved_store.get(card.id, False)
                        _approval_report = st.session_state.get(f"sav_report_{card.id}")
                        _has_unresolved_qa_needed = bool(
                            _approval_report and getattr(_approval_report, "qa_needed_list", [])
                        )
                        _tc_saved_key = f"tc_saved_{card.id}"
                        if _tc_saved_key not in st.session_state and _is_card_tc_published(card.id):
                            st.session_state[_tc_saved_key] = True
                        _tc_saved = st.session_state.get(_tc_saved_key, False)
                        _sheet_tab_key = f"sheet_tab_{card.id}"
                        _dup_preview_key = f"sheet_dups_{card.id}"
                        _dup_tab_key = f"sheet_dups_tab_{card.id}"
                        _dup_override_key = f"sheet_dup_override_{card.id}"

                        if _is_approved:
                            st.success("🏆 Approved — Test cases saved to Trello and Google Sheets.")
                        elif _tc_markdown:
                            if _has_unresolved_qa_needed:
                                st.warning("Resolve the QA Needed scenarios in Step 2 before approving this card.")
                            if _tc_saved:
                                st.success("✅ Test cases were already published in Generate TC. This step only finalizes AI QA approval.")
                            else:
                                st.warning(
                                    "⚠️ Test cases have not been published yet. Save them in Generate TC first, "
                                    "or use the fallback approve-and-save flow below."
                                )
                            _suggested_tab = detect_tab(card.name, _tc_markdown)
                            _tab_created_key = f"sheet_tab_created_{card.id}"
                            _new_tab_key = f"sheet_new_tab_{card.id}"
                            _live_approval_tabs = _sheet_tab_options()
                            if _sheet_tab_key not in st.session_state:
                                st.session_state[_sheet_tab_key] = (
                                    _suggested_tab if _suggested_tab in _live_approval_tabs else "Draft Plan"
                                )
                            _sheet_tab_cols = st.columns([3, 2])
                            with _sheet_tab_cols[0]:
                                _tab_options = list(_live_approval_tabs)
                                _newly_created_tab = st.session_state.get(_tab_created_key, "")
                                if _newly_created_tab and _newly_created_tab not in _tab_options:
                                    _tab_options.insert(0, _newly_created_tab)
                                _selected_tab = st.selectbox(
                                    "📊 Add to sheet tab",
                                    options=_tab_options,
                                    key=_sheet_tab_key,
                                )
                            with _sheet_tab_cols[1]:
                                _new_tab_name = st.text_input(
                                    "➕ Or create new tab",
                                    key=_new_tab_key,
                                    placeholder="New tab name…",
                                    label_visibility="collapsed",
                                )
                                if st.button("➕ Create Tab", key=f"create_tab_{card.id}", use_container_width=True):
                                    if _new_tab_name.strip():
                                        with st.spinner(f"Creating tab '{_new_tab_name.strip()}'…"):
                                            _create_tab_result = create_new_tab(_new_tab_name.strip())
                                        if _create_tab_result.get("ok"):
                                            _created_tab = _create_tab_result["tab"]
                                            _live_tabs = st.session_state.get("live_sheet_tabs", list(SHEET_TABS))
                                            if _created_tab not in _live_tabs:
                                                _live_tabs.append(_created_tab)
                                                st.session_state["live_sheet_tabs"] = _live_tabs
                                            st.session_state[_tab_created_key] = _created_tab
                                            st.session_state[_sheet_tab_key] = _created_tab
                                            st.success(f"✅ Tab '{_created_tab}' ready")
                                            st.rerun()
                                        st.error(f"❌ Failed: {_create_tab_result.get('error', 'unknown error')}")
                                    else:
                                        st.warning("Enter a tab name first.")

                            _parsed_rows = parse_test_cases_to_rows(
                                card.name,
                                _tc_markdown,
                                epic=card.name,
                                positive_only=True,
                            )
                            st.caption(
                                "Approving saves a QA summary comment to Trello and writes positive test-case rows to Google Sheets."
                            )
                            _metric_col1, _metric_col2 = st.columns(2)
                            with _metric_col1:
                                st.metric("Google Sheets rows to write", len(_parsed_rows))
                            with _metric_col2:
                                st.metric("Suggested Google Sheets tab", _suggested_tab)

                            _dup_col1, _dup_col2 = st.columns([1, 3])
                            with _dup_col1:
                                _check_dups_clicked = st.button(
                                    "🔎 Check duplicates",
                                    key=f"check_dups_{card.id}",
                                    use_container_width=True,
                                )
                            with _dup_col2:
                                st.caption("Review Google Sheets duplicate risk before saving. Trello will still receive the QA summary comment.")

                            if _check_dups_clicked:
                                with st.spinner("Checking duplicates in Google Sheets…"):
                                    try:
                                        _dups = check_duplicates(_parsed_rows, _selected_tab)
                                        st.session_state[_dup_preview_key] = _dups
                                        st.session_state[_dup_tab_key] = _selected_tab
                                    except Exception as _dup_err:
                                        st.session_state[_dup_preview_key] = []
                                        st.session_state[_dup_tab_key] = _selected_tab
                                        st.warning(f"Duplicate check failed: {_dup_err}")

                            _dup_matches = st.session_state.get(_dup_preview_key, [])
                            if st.session_state.get(_dup_tab_key) != _selected_tab:
                                _dup_matches = []
                                st.session_state[_dup_preview_key] = []
                                st.session_state[_dup_tab_key] = _selected_tab

                            if _dup_matches:
                                st.warning(
                                    f"{len(_dup_matches)} potential duplicate(s) found in sheet tab '{_selected_tab}'."
                                )
                                with st.expander("Potential duplicates", expanded=False):
                                    for _dup in _dup_matches[:10]:
                                        st.markdown(
                                            f"- `{_dup.new_scenario}` matches `{_dup.existing_scenario}` "
                                            f"({int(_dup.similarity * 100)}%)"
                                        )
                                st.checkbox("Skip duplicate TCs (only add new ones)", key=_dup_override_key)
                            else:
                                st.caption("No duplicate warning recorded for the selected sheet tab yet.")

                            if st.button(
                                "✅ Final Approve" if _tc_saved else "✅ Approve & Save",
                                key=f"approve_{card.id}",
                                type="primary",
                                disabled=_has_unresolved_qa_needed,
                            ):
                                with st.spinner("Saving to Trello and Google Sheets…"):
                                    _approve_errors = []
                                    _tc_to_write = _tc_markdown
                                    _skipped_duplicates = 0

                                    _sheet_result = None
                                    if not _tc_saved:
                                        try:
                                            write_test_cases_to_card(
                                                card_id=card.id,
                                                test_cases=_tc_markdown,
                                                trello=trello,
                                                release=st.session_state.get("rqa_release", ""),
                                                card_name=card.name,
                                            )
                                        except Exception as _trello_err:
                                            _approve_errors.append(f"Trello: {_trello_err}")

                                        try:
                                            if _dup_matches and st.session_state.get(_dup_override_key, False):
                                                _tc_to_write, _skipped_duplicates = _filter_duplicate_test_cases(
                                                    _tc_markdown,
                                                    _dup_matches,
                                                )
                                            _sheet_result = append_to_sheet(
                                                card_name=card.name,
                                                test_cases_markdown=_tc_to_write,
                                                epic=card.name,
                                                tab_name=_selected_tab,
                                                release=st.session_state.get("rqa_release", ""),
                                                card_url=getattr(card, "url", ""),
                                            )
                                        except Exception as _sheet_err:
                                            _approve_errors.append(f"Sheets: {_sheet_err}")

                                    _rag_result = {"chunks_added": 0, "error": ""}
                                    try:
                                        from pipeline.rag_updater import update_rag_from_card
                                        _rag_result = update_rag_from_card(
                                            card_id=card.id,
                                            card_name=card.name,
                                            description=card.desc or "",
                                            acceptance_criteria=st.session_state.get(f"ac_suggestion_{card.id}") or (card.desc or ""),
                                            test_cases=_tc_markdown,
                                            release=st.session_state.get("rqa_release", ""),
                                        )
                                    except Exception as _rag_err:
                                        _rag_result = {"chunks_added": 0, "error": str(_rag_err)}

                                    approved_store[card.id] = True
                                    st.session_state["rqa_approved"] = approved_store
                                    _update_pipeline_run(
                                        card,
                                        approved_at=datetime.now().isoformat(timespec="seconds"),
                                        test_cases=_tc_markdown,
                                        sheet_tab=_selected_tab,
                                        sheet_rows=(_sheet_result or {}).get("rows_added", 0),
                                        qa_summary=_report_summary_dict(_approval_report),
                                        rag_chunks=_rag_result.get("chunks_added", 0),
                                    )

                                    if _approve_errors:
                                        for _err in _approve_errors:
                                            st.warning(f"⚠️ {_err}")
                                    else:
                                        st.success("✅ Final approval saved!" if _tc_saved else "✅ Saved to Trello!")

                                    if _sheet_result:
                                        if _sheet_result.get("rows_added"):
                                            _skip_suffix = f" ({_skipped_duplicates} duplicates skipped)" if _skipped_duplicates else ""
                                            st.success(
                                                f"📊 Saved {_sheet_result['rows_added']} test case(s) "
                                                f"to sheet tab **'{_sheet_result['tab']}'**{_skip_suffix}"
                                            )
                                        if _sheet_result.get("duplicates"):
                                            st.warning(
                                                f"⚠️ {len(_sheet_result['duplicates'])} potential duplicate(s) detected in sheet"
                                            )
                                    if _rag_result.get("error"):
                                        st.warning(f"⚠️ RAG update skipped: {_rag_result['error']}")
                                    elif _rag_result.get("chunks_added"):
                                        st.caption(f"📚 Knowledge base updated ({_rag_result['chunks_added']} chunks added)")

                                    st.rerun()
                        else:
                            st.info("Generate test cases in the Generate TC tab before approving.")

                    if show_automation_stage:
                        with _automation_container:
                            st.divider()
                            st.markdown(
                                '<div class="step-chip">① Write Automation Code</div>',
                                unsafe_allow_html=True,
                            )
                            st.caption(
                                "This step creates the release spec for this approved card. "
                                "Use the reviewed test cases below as the source, then the Run section will unlock."
                            )

                            _auto_tc_src = (
                                st.session_state.get(f"tc_text_{card.id}", "").strip()
                                or tc_store.get(card.id, "").strip()
                                or (_card_run.get("test_cases", "") or "").strip()
                                or (_existing_tc_markdown or "").strip()
                            )
                            _is_approved_for_auto = approved_store.get(card.id, False)

                            if not _is_approved_for_auto:
                                st.info("Approve the card in AI QA Verifier before writing automation.")
                            else:
                                _det_key = f"auto_detection_{card.id}"
                                _auto_feat_key = f"auto_feat_{card.id}"
                                _auto_res_key = f"auto_res_{card.id}"
                                _auto_branch_key = f"auto_branch_{card.id}"
                                _auto_written_key = f"rqa_auto_files_{card.id}"
                                _explore_key = f"auto_exploration_{card.id}"
                                _auto_nav_hint_key = f"auto_nav_hint_{card.id}"
                                if _det_key not in st.session_state:
                                    try:
                                        from pipeline.feature_detector import detect_feature

                                        st.session_state[_det_key] = detect_feature(card.name, card.desc or "")
                                    except Exception:
                                        st.session_state[_det_key] = None
                                _det = st.session_state.get(_det_key)
                                if _det:
                                    _det_kind = getattr(_det, "kind", "new")
                                    _kind_icon = "✏️" if _det_kind == "existing" else "🆕"
                                    st.caption(
                                        f"{_kind_icon} **{_det_kind.capitalize()} feature** "
                                        f"({getattr(_det, 'confidence', 0.0):.0%} confidence) — "
                                        f"{getattr(_det, 'reasoning', '')[:160]}"
                                    )
                                    _related = list(getattr(_det, "related_files", []) or [])[:3]
                                    if _related:
                                        st.caption("Related files: " + ", ".join(f"`{_file}`" for _file in _related))

                                _auto_feat_val = st.text_input(
                                    "Feature name",
                                    value=st.session_state.get(_auto_feat_key, card.name),
                                    key=f"auto_feat_input_{card.id}",
                                )
                                st.session_state[_auto_feat_key] = _auto_feat_val
                                _auto_tc_display = st.text_area(
                                    "Test cases (from Generate TC)",
                                    value=_auto_tc_src,
                                    height=150,
                                    key=f"auto_tc_display_{card.id}",
                                )

                                _repo_path = getattr(config, "MCSL_AUTOMATION_REPO_PATH", "")
                                _existing_branches = _get_repo_branches()
                                _default_branch = st.session_state.get(
                                    _auto_branch_key,
                                    f"automation/{re.sub(r'[^a-z0-9]+', '-', card.name.lower()).strip('-')[:40]}",
                                )
                                _branch_options = _existing_branches + (["➕ New branch…"] if _repo_path else [])
                                _branch_mode = "➕ New branch…" if _default_branch not in _existing_branches else _default_branch
                                _branch_pick = st.selectbox(
                                    "Branch",
                                    options=_branch_options or [_default_branch],
                                    index=(_branch_options.index(_branch_mode) if _branch_options and _branch_mode in _branch_options else 0),
                                    key=f"auto_branch_pick_{card.id}",
                                )
                                if _branch_pick == "➕ New branch…":
                                    _branch_value = st.text_input(
                                        "New branch name",
                                        value=_default_branch,
                                        key=f"auto_branch_input_{card.id}",
                                    ).strip()
                                else:
                                    _branch_value = _branch_pick
                                st.session_state[_auto_branch_key] = _branch_value

                                _dry_run = st.checkbox("Dry run (preview only)", key=f"auto_dry_{card.id}", value=False)
                                _push_after = st.checkbox(
                                    "Push to origin after generation",
                                    key=f"auto_push_{card.id}",
                                    value=False,
                                    disabled=_dry_run or not _repo_path,
                                )
                                _auto_fix_enabled = st.toggle(
                                    "🔄 Auto-run & fix until passing",
                                    key=f"auto_fix_{card.id}",
                                    value=False,
                                    disabled=_dry_run or not _repo_path,
                                    help="After generating code, run the generated spec and let Claude try to fix failures up to 3 times.",
                                )
                                _qa_context = st.text_area(
                                    "🧪 QA Test Context (optional)",
                                    key=f"auto_qa_ctx_{card.id}",
                                    placeholder=(
                                        "Give extra test data or setup notes, e.g.:\n"
                                        "• use product with COO IN and customs value 12.34\n"
                                        "• verify ZPL label\n"
                                        "• use UPS international shipment"
                                    ),
                                    height=90,
                                )

                                _qa_report = st.session_state.get(f"sav_report_{card.id}")
                                _has_ai_qa_context = _qa_report is not None
                                if _has_ai_qa_context:
                                    st.caption(
                                        "AI QA Agent already walked the app. Reviewed test cases will be grounded "
                                        "with the verified flow for code generation."
                                    )
                                    _use_live_explore = False
                                else:
                                    _use_live_explore = st.checkbox(
                                        "🌐 Walk app live with Chrome Agent (grounded locators)",
                                        key=f"auto_use_explore_{card.id}",
                                        value=bool(_det and getattr(_det, "kind", "") == "new"),
                                        help=(
                                            "Navigates the real MCSL app and captures UI elements. "
                                            "Run AI QA Verifier first for better grounded automation when possible."
                                        ),
                                    )

                                if _use_live_explore:
                                    if _auto_nav_hint_key not in st.session_state:
                                        try:
                                            from pipeline.automation_writer import find_pom

                                            _matched = find_pom(card.name, card.desc or "")
                                            st.session_state[_auto_nav_hint_key] = (_matched or {}).get("app_path", "")
                                        except Exception:
                                            st.session_state[_auto_nav_hint_key] = ""
                                    _nav_hint = st.text_input(
                                        "App path / nav hint (optional)",
                                        value=st.session_state.get(_auto_nav_hint_key, ""),
                                        key=f"auto_nav_hint_input_{card.id}",
                                        placeholder="e.g. orders, carriers, products, settings",
                                    ).strip()
                                    st.session_state[_auto_nav_hint_key] = _nav_hint

                                    with st.expander("🌐 Explore live app", expanded=False):
                                        _exp_result = st.session_state.get(_explore_key)
                                        if _exp_result:
                                            if getattr(_exp_result, "error", ""):
                                                st.error(f"❌ Chrome Agent: {_exp_result.error}")
                                            else:
                                                _ax_lines = len([line for line in getattr(_exp_result, "ax_tree_text", "").splitlines() if line.strip()])
                                                _elements_json = getattr(_exp_result, "elements_json", "") or ""
                                                _estimated_elements = _elements_json.count("selector_hint")
                                                with st.expander(
                                                    f"🌐 Agent explored {getattr(_exp_result, 'nav_destination', 'app')} — "
                                                    f"{_ax_lines} AX lines · {_estimated_elements} selector hints",
                                                    expanded=False,
                                                ):
                                                    if _elements_json:
                                                        st.code(_elements_json[:2500], language="json")
                                                    if getattr(_exp_result, "ax_tree_text", ""):
                                                        st.code(getattr(_exp_result, "ax_tree_text", "")[:2500], language="text")
                                        if st.button("🌐 Explore App", key=f"auto_explore_btn_{card.id}", use_container_width=True):
                                            with st.spinner("Exploring live MCSL app…"):
                                                try:
                                                    from pipeline.chrome_agent import explore_feature

                                                    st.session_state[_explore_key] = explore_feature(
                                                        _auto_feat_val.strip() or card.name,
                                                        nav_hint=_nav_hint,
                                                    )
                                                except Exception as _exp_err:
                                                    st.error(f"Chrome Agent failed: {_exp_err}")
                                            st.rerun()

                                if st.button("⚙️ Write Automation Code", key=f"auto_gen_{card.id}", type="primary"):
                                    _fix_progress_key = f"auto_fix_progress_{card.id}"
                                    _fix_progress_history_key = f"auto_fix_progress_history_{card.id}"
                                    st.session_state[_fix_progress_key] = ""
                                    st.session_state[_fix_progress_history_key] = []
                                    _progress_placeholder = st.empty()

                                    def _on_fix_progress(iteration: int, status: str, output: str) -> None:
                                        _history = list(st.session_state.get(_fix_progress_history_key, []))
                                        _history.append({
                                            "iteration": iteration,
                                            "status": status,
                                            "output": output[-1500:] if output else "",
                                        })
                                        st.session_state[_fix_progress_history_key] = _history
                                        _summary = f"🔄 Auto-fix iteration {iteration}/3 — {status}"
                                        st.session_state[_fix_progress_key] = _summary
                                        with _progress_placeholder.container():
                                            st.info(_summary)
                                            if output:
                                                with st.expander("Latest auto-fix output", expanded=False):
                                                    st.code(output[-1500:], language="text")

                                    _exp_result = st.session_state.get(_explore_key)
                                    _generation_label = (
                                        "Generating automation from reviewed test cases + verified AI QA flow..."
                                        if _has_ai_qa_context
                                        else "Generating automation from reviewed test cases + live app trace..."
                                        if _exp_result and not getattr(_exp_result, "error", "")
                                        else "Generating automation from reviewed test cases..."
                                    )

                                    with st.spinner(_generation_label):
                                        try:
                                            from dataclasses import replace
                                            from pipeline.automation_writer import push_to_branch, write_automation

                                            _merged_auto_ctx = "\n\n".join(
                                                part for part in [
                                                    _qa_context.strip(),
                                                    _qa_report.to_automation_context() if _qa_report else "",
                                                ] if part
                                            )
                                            _card_auto_result = write_automation(
                                                feature_name=_auto_feat_val.strip() or card.name,
                                                test_cases_markdown=_auto_tc_display.strip(),
                                                exploration_data=(
                                                    getattr(_exp_result, "elements_json", "")
                                                    if _exp_result and not getattr(_exp_result, "error", "")
                                                    else ""
                                                ),
                                                ai_qa_context=_merged_auto_ctx,
                                                branch_name=_branch_value,
                                                dry_run=_dry_run,
                                                push=_push_after,
                                                qa_context=_qa_context.strip(),
                                                auto_fix=_auto_fix_enabled,
                                                fix_iterations=3,
                                                on_fix_progress=_on_fix_progress,
                                                repo_path=_repo_path,
                                            )
                                            _written_files: list[str] = []
                                            if _repo_path and not _card_auto_result.error and not _dry_run:
                                                _written_files = _write_release_automation_files(_card_auto_result, _repo_path)
                                                st.session_state[_auto_written_key] = _written_files
                                            else:
                                                st.session_state[_auto_written_key] = []

                                            if not _card_auto_result.error and _push_after and not _dry_run and _repo_path and _written_files:
                                                _files_for_push = [
                                                    _card_auto_result.pom_path,
                                                    _card_auto_result.spec_path,
                                                ]
                                                _ok, _branch_or_err = push_to_branch(
                                                    _repo_path,
                                                    _branch_value or (_auto_feat_val.strip() or card.name),
                                                    [f for f in _files_for_push if f],
                                                    branch_name=_branch_value,
                                                )
                                                if _ok:
                                                    _card_auto_result = replace(
                                                        _card_auto_result,
                                                        git_branch=_branch_or_err,
                                                        git_pushed=True,
                                                    )
                                                    _update_pipeline_run(
                                                        card,
                                                        automation_pushed_at=datetime.now().isoformat(timespec="seconds"),
                                                        automation_branch=_branch_or_err,
                                                    )
                                                else:
                                                    _card_auto_result = replace(
                                                        _card_auto_result,
                                                        git_branch=_branch_value,
                                                        error=_branch_or_err,
                                                    )
                                            elif not _card_auto_result.error:
                                                _card_auto_result = replace(
                                                    _card_auto_result,
                                                    git_branch=_branch_value,
                                                )
                                            st.session_state[_auto_res_key] = _card_auto_result
                                            _update_pipeline_run(
                                                card,
                                                automation_generated_at=datetime.now().isoformat(timespec="seconds"),
                                                automation_branch=getattr(_card_auto_result, "git_branch", ""),
                                                automation_files=_written_files or getattr(_card_auto_result, "files_written", []),
                                                automation_error=getattr(_card_auto_result, "error", ""),
                                            )
                                        except Exception as _ae:
                                            st.error(f"Automation generation failed: {_ae}")
                                        finally:
                                            _progress_placeholder.empty()
                                    st.rerun()

                                _card_auto_result = st.session_state.get(_auto_res_key)
                                if _card_auto_result:
                                    if _card_auto_result.error:
                                        st.error(f"❌ {_card_auto_result.error}")
                                    else:
                                        _written_files = st.session_state.get(_auto_written_key, [])
                                        _kind = getattr(_card_auto_result, "kind", "")
                                        _kind_badge = "🆕 New feature" if _kind == "new_pom" else "✏️ Existing feature"
                                        st.success(f"{_kind_badge} · {len(_written_files)} file(s) written")
                                        _tc_summary = getattr(_card_auto_result, "tc_filter_summary", {}) or {}
                                        if _tc_summary:
                                            st.caption(
                                                f"📊 Test cases: {_tc_summary.get('kept', 0)}/{_tc_summary.get('total', 0)} automated "
                                                f"(✅ {_tc_summary.get('positive', 0)} positive · "
                                                f"⚡ {_tc_summary.get('edge', 0)} edge · "
                                                f"🚫 {_tc_summary.get('negative', 0)} negative skipped — manual only)"
                                            )
                                        if _written_files:
                                            for _path in _written_files:
                                                st.caption(f"📄 `{_path}`")
                                        elif _dry_run:
                                            st.caption("Preview only — no files were written to the automation repo.")
                                        if getattr(_card_auto_result, "detection_reason", ""):
                                            st.caption(getattr(_card_auto_result, "detection_reason"))
                                        if getattr(_card_auto_result, "git_branch", ""):
                                            st.info(f"📦 Branch: `{_card_auto_result.git_branch}`")
                                        if getattr(_card_auto_result, "git_pushed", False):
                                            st.success("✅ Pushed to origin")
                                        elif getattr(_card_auto_result, "push_error", ""):
                                            st.warning(f"⚠️ {getattr(_card_auto_result, 'push_error')}")
                                        _fix_history = getattr(_card_auto_result, "fix_history", []) or []
                                        if _fix_history:
                                            _fix_passed = getattr(_card_auto_result, "fix_passed", False)
                                            _fix_iters = getattr(_card_auto_result, "fix_iterations", 0)
                                            if _fix_passed:
                                                st.success(f"✅ Tests passing after {_fix_iters} run(s)")
                                            else:
                                                st.error(
                                                    f"❌ Tests still failing after {_fix_iters} auto-fix attempt(s) — "
                                                    "push blocked. Fix locally and push manually."
                                                )
                                            with st.expander("🔍 Auto-fix run history", expanded=not _fix_passed):
                                                for _run in _fix_history:
                                                    _icon = "✅" if _run.get("passed") else "❌"
                                                    st.markdown(f"**{_icon} Iteration {_run.get('iteration', '?')}**")
                                                    if _run.get("fixed_files"):
                                                        st.caption("Fixed: " + ", ".join(f"`{_f}`" for _f in _run.get("fixed_files", [])))
                                                    if _run.get("output"):
                                                        with st.expander(f"Output (iter {_run.get('iteration', '?')})", expanded=False):
                                                            st.code(_run.get("output", ""), language="text")

                                        _pt, _st = st.tabs(["POM", "Spec"])
                                        with _pt:
                                            st.code(_card_auto_result.pom_code, language="typescript")
                                        with _st:
                                            st.code(_card_auto_result.spec_code, language="typescript")

                                        _act_c1, _act_c2 = st.columns(2)
                                        with _act_c1:
                                            _can_push_now = bool(
                                                _repo_path
                                                and _written_files
                                                and getattr(_card_auto_result, "git_branch", "")
                                                and not getattr(_card_auto_result, "git_pushed", False)
                                            )
                                            if st.button("🚀 Push to origin", key=f"auto_push_now_{card.id}", use_container_width=True, disabled=not _can_push_now):
                                                from dataclasses import replace
                                                from pipeline.automation_writer import push_to_branch

                                                _ok, _branch_or_err = push_to_branch(
                                                    _repo_path,
                                                    _auto_feat_val.strip() or card.name,
                                                    [f for f in [_card_auto_result.pom_path, _card_auto_result.spec_path] if f],
                                                    branch_name=getattr(_card_auto_result, "git_branch", ""),
                                                )
                                                if _ok:
                                                    st.session_state[_auto_res_key] = replace(
                                                        _card_auto_result,
                                                        git_branch=_branch_or_err,
                                                        git_pushed=True,
                                                    )
                                                    _update_pipeline_run(
                                                        card,
                                                        automation_pushed_at=datetime.now().isoformat(timespec="seconds"),
                                                        automation_branch=_branch_or_err,
                                                    )
                                                    st.rerun()
                                                else:
                                                    st.error(f"Push failed: {_branch_or_err}")
                                        with _act_c2:
                                            if st.button("🔄 Re-run on different branch", key=f"auto_regen_branch_{card.id}", use_container_width=True):
                                                st.session_state.pop(_auto_res_key, None)
                                                st.session_state.pop(_auto_written_key, None)
                                                st.rerun()

                    # Phase 8: Auto-DM developers on failed verdict
                    _result_done = st.session_state.get(f"sav_result_{card.id}", {})
                    _rpt_done = st.session_state.get(f"sav_report_{card.id}")
                    if (
                        _result_done.get("done")
                        and _rpt_done is not None
                        and getattr(_rpt_done, "verdict", "").lower() == "fail"
                        and slack_configured()
                        and not st.session_state.get(f"bug_dm_sent_{card.id}", False)
                    ):
                        try:
                            _bug_desc = "; ".join(getattr(_rpt_done, "errors", []) or ["Verdict: fail"])
                            _dm_result = notify_devs_of_bug(
                                card_id=card.id,
                                card_name=card.name,
                                bug_description=_bug_desc,
                                trello_client=trello,
                                slack_client=__import__("pipeline.slack_client", fromlist=["SlackClient"]).SlackClient(),
                            )
                            if _dm_result.get("sent_count", 0) > 0:
                                st.caption(f"Bug DM sent to {_dm_result['sent_count']} developer(s)")
                            st.session_state[f"bug_dm_sent_{card.id}"] = True
                        except Exception as _dm_err:
                            logger.warning("Bug DM failed for card %s: %s", card.id, _dm_err)

                if show_automation_stage and card is cards[-1]:
                    st.divider()
                    _approved_count = sum(1 for _card in cards if approved_store.get(_card.id, False))
                    if _approved_count < len(cards):
                        if st.button("✅ Approve ALL remaining", type="primary", key="rqa_approve_all"):
                            _remaining_cards = [c for c in cards if not approved_store.get(c.id)]
                            _bulk_saved = 0
                            _bulk_rag_chunks = 0
                            for _card in _remaining_cards:
                                _bulk_tc = (st.session_state.get(f"tc_text_{_card.id}", "") or tc_store.get(_card.id, "")).strip()
                                if not _bulk_tc:
                                    continue
                                try:
                                    write_test_cases_to_card(
                                        card_id=_card.id,
                                        test_cases=_bulk_tc,
                                        trello=trello,
                                        release=st.session_state.get("rqa_release", ""),
                                        card_name=_card.name,
                                    )
                                    approved_store[_card.id] = True
                                    _bulk_saved += 1
                                except Exception as _bulk_err:
                                    logger.warning("Bulk approve failed for card %s: %s", _card.id, _bulk_err)
                                    continue

                                _bulk_rag = {"chunks_added": 0}
                                try:
                                    from pipeline.rag_updater import update_rag_from_card
                                    _bulk_rag = update_rag_from_card(
                                        card_id=_card.id,
                                        card_name=_card.name,
                                        description=_card.desc or "",
                                        acceptance_criteria=st.session_state.get(f"ac_suggestion_{_card.id}") or (_card.desc or ""),
                                        test_cases=_bulk_tc,
                                        release=st.session_state.get("rqa_release", ""),
                                    )
                                    _bulk_rag_chunks += int(_bulk_rag.get("chunks_added", 0) or 0)
                                except Exception as _bulk_rag_err:
                                    logger.warning("Bulk RAG update failed for card %s: %s", _card.id, _bulk_rag_err)
                                _update_pipeline_run(
                                    _card,
                                    approved_at=datetime.now().isoformat(timespec="seconds"),
                                    test_cases=_bulk_tc,
                                    sheet_tab="",
                                    sheet_rows=0,
                                    qa_summary=_report_summary_dict(st.session_state.get(f"sav_report_{_card.id}")),
                                    rag_chunks=int(_bulk_rag.get("chunks_added", 0) or 0),
                                )

                            st.session_state["rqa_approved"] = approved_store
                            st.success(f"✅ Approved {_bulk_saved} remaining card(s). 📚 {_bulk_rag_chunks} RAG chunks updated.")
                            st.rerun()

                    st.divider()
                    st.markdown(
                        '<div class="step-chip">② Run Automation &amp; Post to Slack</div>',
                        unsafe_allow_html=True,
                    )
                    st.caption("Run Playwright tests for this release's generated specs, then post the results to Slack.")

                    from pipeline.test_runner import run_release_tests, TestRunResult
                    from pipeline.slack_client import post_results

                    _release_label = st.session_state.get("rqa_release", "")
                    _repo_path = getattr(config, "MCSL_AUTOMATION_REPO_PATH", "")
                    _release_specs = _collect_release_spec_files(cards)
                    _card_spec_map = _collect_release_spec_map(cards)

                    _rl1, _rl2, _rl3 = st.columns(3)
                    _rl1.metric("Approved cards", _approved_count)
                    _rl2.metric("Spec files ready", len(_release_specs))
                    _rl3.metric("Slack", "Configured ✅" if slack_configured() else "Not set ❌")

                    _run_key = "rqa_release_run_result"
                    _posted_key = f"rqa_release_slack_posted_{_release_label}"
                    _project_key = "rqa_release_run_project"
                    _project = st.selectbox("Browser project", ["Google Chrome", "Safari", "Firefox"], key=_project_key)

                    if not _release_specs:
                        st.info(
                            "Generate automation for at least one approved card first. "
                            "Run Automation appears only after a release spec file exists."
                        )
                    elif not slack_configured():
                        st.warning(
                            "Slack not configured. Tests can still run, and a copyable result summary will appear after the run."
                        )

                    if _release_specs:
                        _run_scope = st.radio(
                            "Test scope",
                            ["This release only (generated specs)", "Full test suite"],
                            index=0,
                            horizontal=True,
                            key="rqa_release_run_scope",
                        )
                    else:
                        _run_scope = "This release only (generated specs)"

                    _run_col, _post_col = st.columns(2)
                    with _run_col:
                        _run_label = "▶️ Run Tests"
                        if _run_scope.startswith("This") and _release_specs:
                            _run_label += f" ({len(_release_specs)} specs)"
                        if st.button(
                            _run_label,
                            type="primary",
                            key="rqa_release_run_btn",
                            disabled=not _repo_path or not _release_specs or _approved_count == 0,
                            use_container_width=True,
                        ):
                            _specs_to_run = _release_specs if _run_scope.startswith("This") else []
                            _scope_label = f"{len(_specs_to_run)} specs" if _specs_to_run else "full suite"
                            with st.spinner(f"Running Playwright tests for {_release_label or 'current release'}… ({_scope_label})"):
                                st.session_state[_run_key] = run_release_tests(_repo_path, _specs_to_run, _project)
                            st.session_state[_posted_key] = False
                            st.rerun()
                    with _post_col:
                        _run_result = st.session_state.get(_run_key)
                        if st.session_state.get(_posted_key, False):
                            st.success("📣 Results already posted to Slack")
                        _post_label = "📣 Post again to Slack" if st.session_state.get(_posted_key, False) else "📣 Post Results to Slack"
                        if st.button(
                            _post_label,
                            key="rqa_release_post_slack_btn",
                            disabled=not (_run_result and slack_configured()),
                            use_container_width=True,
                        ):
                            _slack_resp = post_results(_run_result, _release_label)
                            if _slack_resp.get("ok"):
                                st.session_state[_posted_key] = True
                                st.success("✅ Results posted to Slack.")
                            else:
                                st.error(f"Slack error: {_slack_resp.get('error', 'unknown')}")

                    _run_result = st.session_state.get(_run_key)
                    if _run_result:
                        if getattr(_run_result, "error", ""):
                            st.error(f"❌ Run error: {_run_result.error}")
                        else:
                            _rr1, _rr2, _rr3, _rr4 = st.columns(4)
                            _rr1.metric("Total", _run_result.total)
                            _rr2.metric("Passed", _run_result.passed)
                            _rr3.metric("Failed", _run_result.failed)
                            _rr4.metric("Duration", f"{_run_result.duration_ms / 1000:.1f}s")
                            if _card_spec_map:
                                st.markdown("**Per-card breakdown:**")
                                for _card_name, _spec_path in _card_spec_map.items():
                                    _spec_results = [s for s in _run_result.specs if s.file == _spec_path]
                                    if not _spec_results:
                                        continue
                                    _passed = sum(1 for s in _spec_results if s.status == "passed")
                                    _failed = sum(1 for s in _spec_results if s.status in ("failed", "timedOut"))
                                    _icon = "✅" if _failed == 0 else "❌"
                                    st.caption(
                                        f"{_icon} **{_card_name}** — `{_spec_path}` · {_passed} passed · {_failed} failed"
                                    )
                            _failed_specs = [
                                f"{_spec.file} — {_spec.title}"
                                for _spec in _run_result.specs
                                if _spec.status in ("failed", "timedOut")
                            ]
                            if _failed_specs:
                                with st.expander(f"❌ {len(_failed_specs)} failed test(s)", expanded=True):
                                    for _failed in _failed_specs:
                                        st.code(_failed, language=None)
                            with st.expander("Release test results", expanded=False):
                                for _spec in _run_result.specs:
                                    _icon = "✅" if _spec.status == "passed" else ("❌" if _spec.status == "failed" else "⏭️")
                                    st.markdown(f"{_icon} `{_spec.file}` — **{_spec.title}** ({_spec.duration_ms}ms)")
                            if not slack_configured():
                                st.info("Configure Slack to enable posting. You can copy the summary below manually.")
                                st.code(_build_release_test_results_message(_release_label, _run_result), language=None)

                    st.divider()
                    st.markdown(
                        '<div class="step-chip">③ Generate Documentation</div>',
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        "Generate a feature doc (`docs/features/*.md`) and CHANGELOG entry for each card in this release."
                    )

                    from pipeline.doc_generator import generate_feature_doc

                    _cards_for_docs: list[dict[str, Any]] = []
                    for _card in cards:
                        _run = _get_card_run(getattr(_card, "id", ""))
                        _auto_files = list(dict.fromkeys([
                            *(st.session_state.get(f"rqa_auto_files_{_card.id}", []) or []),
                            *((_run.get("automation_files", []) or [])),
                        ]))
                        _spec = next((f for f in _auto_files if isinstance(f, str) and f.endswith(".spec.ts")), "")
                        _pom = next((f for f in _auto_files if isinstance(f, str) and f.endswith(".ts") and "pages" in f), "")
                        _cards_for_docs.append({
                            "card": _card,
                            "spec_file": _spec,
                            "pom_file": _pom,
                            "has_spec": bool(_spec),
                        })

                    _docs_ready = sum(1 for _item in _cards_for_docs if _item["has_spec"])
                    st.caption(
                        f"{_docs_ready}/{len(_cards_for_docs)} cards have spec files ready · "
                        "Docs will be saved to `docs/features/` in the automation repo"
                    )

                    if st.button(
                        "📄 Generate Docs for All Cards",
                        type="primary",
                        key="rqa_generate_all_docs",
                        disabled=_approved_count == 0,
                    ):
                        _doc_errors: list[str] = []
                        for _item in _cards_for_docs:
                            _card = _item["card"]
                            _doc_key = f"doc_result_{_card.id}"
                            if _doc_key not in st.session_state:
                                with st.spinner(f"Writing doc for '{_card.name}'…"):
                                    _doc_res = generate_feature_doc(
                                        card_name=_card.name,
                                        acceptance_criteria=st.session_state.get(f"ac_suggestion_{_card.id}") or (_card.desc or ""),
                                        test_cases=(st.session_state.get(f"tc_text_{_card.id}", "") or tc_store.get(_card.id, "")).strip(),
                                        spec_file=_item["spec_file"],
                                        pom_file=_item["pom_file"],
                                        release=_release_label,
                                    )
                                st.session_state[_doc_key] = _doc_res
                                if _doc_res.get("error"):
                                    _doc_errors.append(f"{_card.name}: {_doc_res['error']}")
                        if _doc_errors:
                            st.warning("Some docs failed:\n" + "\n".join(_doc_errors))
                        else:
                            st.success(f"✅ Docs generated for {len(_cards_for_docs)} card(s)")
                        st.rerun()

                    for _item in _cards_for_docs:
                        _card = _item["card"]
                        _doc_key = f"doc_result_{_card.id}"
                        _doc_res = st.session_state.get(_doc_key)

                        _doc_col1, _doc_col2 = st.columns([4, 1])
                        with _doc_col1:
                            if _doc_res:
                                if _doc_res.get("error"):
                                    st.caption(f"❌ **{_card.name}** — {_doc_res['error']}")
                                else:
                                    st.caption(f"✅ **{_card.name}** → `{_doc_res.get('doc_path', '')}`")
                            else:
                                _spec_label = f"`{_item['spec_file']}`" if _item["spec_file"] else "_(no spec yet)_"
                                st.caption(f"⚪ **{_card.name}** — {_spec_label}")
                        with _doc_col2:
                            if not _doc_res:
                                if st.button("📄", key=f"rqa_gen_doc_{_card.id}", help="Generate doc for this card"):
                                    with st.spinner(f"Writing doc for '{_card.name}'…"):
                                        st.session_state[_doc_key] = generate_feature_doc(
                                            card_name=_card.name,
                                            acceptance_criteria=st.session_state.get(f"ac_suggestion_{_card.id}") or (_card.desc or ""),
                                            test_cases=(st.session_state.get(f"tc_text_{_card.id}", "") or tc_store.get(_card.id, "")).strip(),
                                            spec_file=_item["spec_file"],
                                            pom_file=_item["pom_file"],
                                            release=_release_label,
                                        )
                                    st.rerun()
                        if _doc_res and not _doc_res.get("error") and _doc_res.get("doc_content"):
                            with st.expander(f"📄 Preview: {_card.name}", expanded=False):
                                st.markdown(_doc_res["doc_content"])
                                if _doc_res.get("changelog_entry"):
                                    st.caption("**CHANGELOG entry added:**")
                                    st.code(_doc_res["changelog_entry"], language="markdown")

                    st.divider()
                    st.markdown(
                        '<div class="step-chip">🐛 Bug Reporter</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown("#### Report a Bug Found During QA")
                    st.caption(
                        "Describe the issue in plain English → agent formats it in Jira style → "
                        "checks Trello backlog for duplicates → you review/edit → it is raised in Trello."
                    )

                    from pipeline.bug_tracker import check_and_draft_bug, raise_bug

                    _bug_desc = st.text_area(
                        "Describe the bug",
                        placeholder=(
                            "e.g. label automation rule saves correctly but order summary still shows "
                            "the previous carrier service when multiple packages are present."
                        ),
                        height=120,
                        key="bug_description",
                    )

                    _rqa_cards = cards
                    _card_options = ["— None (not linked to a card) —"] + [c.name for c in _rqa_cards]
                    _card_urls = {c.name: c.url for c in _rqa_cards}
                    _bug_linked_card_name = st.selectbox(
                        "Card being tested (optional)",
                        options=_card_options,
                        index=0,
                        key="bug_linked_card",
                        help="Select the release card you were testing when you found this bug.",
                    )

                    _bug_col1, _bug_col2 = st.columns([3, 2])
                    with _bug_col1:
                        _bug_feature = st.text_input(
                            "Feature / page context",
                            placeholder="e.g. Orders -> Order Summary, Automation Rules, Pickup Settings",
                            key="bug_feature_context",
                        )
                    with _bug_col2:
                        _bug_release = st.text_input(
                            "Release",
                            value=_release_label,
                            key="bug_release_input",
                        )

                    _linked_suffix = ""
                    if _bug_linked_card_name and _bug_linked_card_name != "— None (not linked to a card) —":
                        _linked_url = _card_urls.get(_bug_linked_card_name, "")
                        _linked_suffix = (
                            f"\n\n---\n**Found while testing card:** "
                            f"[{_bug_linked_card_name}]({_linked_url})" if _linked_url
                            else f"\n\n---\n**Found while testing card:** {_bug_linked_card_name}"
                        )

                    if st.button(
                        "🔍 Check Backlog & Draft Bug",
                        key="check_bug_btn",
                        type="primary",
                        disabled=not _bug_desc.strip(),
                    ):
                        with st.spinner("Formatting bug + checking Trello backlog for duplicates…"):
                            st.session_state["bug_check_result"] = check_and_draft_bug(
                                issue_description=_bug_desc.strip() + _linked_suffix,
                                feature_context=_bug_feature.strip(),
                                release=_bug_release.strip(),
                            )
                        st.rerun()

                    _bug_result = st.session_state.get("bug_check_result")
                    if _bug_result:
                        if _bug_result.error:
                            st.error(f"❌ {_bug_result.error}")
                        elif _bug_result.is_duplicate:
                            _dup = _bug_result.duplicate_card
                            st.warning(
                                "⚠️ This issue may already exist in the backlog.\n\n"
                                f"**{_bug_result.duplicate_reason}**"
                            )
                            if _dup:
                                st.markdown(f"**Existing card:** [{_dup.name}]({_dup.url})")
                                if _dup.desc:
                                    with st.expander("📋 View existing card description", expanded=False):
                                        st.markdown(_dup.desc[:800])
                            st.caption(
                                "If this is a different issue, make the description more specific and check again."
                            )
                            if st.button("➕ Raise Anyway (different issue)", key="raise_anyway_btn"):
                                _bug_result.is_duplicate = False
                                st.session_state["bug_check_result"] = _bug_result
                                st.rerun()

                        if not _bug_result.is_duplicate:
                            _draft = _bug_result.draft
                            if _draft:
                                st.success("✅ No duplicate found — new bug ready for review")
                                st.markdown("#### Bug Draft — Review before raising")
                                st.markdown(_draft.to_display_markdown())

                                st.divider()
                                st.caption(
                                    "Review the draft above. You can edit the title or severity before raising it in Trello."
                                )

                                _edit_title_col, _edit_sev_col = st.columns([4, 1])
                                with _edit_title_col:
                                    _edited_title = st.text_input(
                                        "Bug title (editable)",
                                        value=_draft.title,
                                        key="bug_edit_title",
                                    )
                                with _edit_sev_col:
                                    _edited_sev = st.selectbox(
                                        "Severity",
                                        ["P1", "P2", "P3", "P4"],
                                        index=["P1", "P2", "P3", "P4"].index(_draft.severity),
                                        key="bug_edit_sev",
                                    )

                                if st.button(
                                    "✅ Approve & Raise in Trello → Backlog",
                                    type="primary",
                                    key="raise_bug_btn",
                                    use_container_width=True,
                                ):
                                    _draft.title = _edited_title.strip() or _draft.title
                                    _draft.severity = _edited_sev
                                    _draft.labels = [
                                        _label for _label in _draft.labels if _label not in ["P1", "P2", "P3", "P4"]
                                    ] + [_edited_sev]

                                    with st.spinner("Creating card in Trello Backlog…"):
                                        try:
                                            _created_card = raise_bug(_draft)
                                            st.session_state["bug_raised_card"] = _created_card
                                            st.session_state.pop("bug_check_result", None)

                                            try:
                                                from pipeline.trello_client import TrelloClient as _TC

                                                _tc = _TC()
                                                _bug_comment = (
                                                    f"🐛 Bug raised to Backlog: [{_created_card.name}]({_created_card.url})\n"
                                                    f"Severity: {_draft.severity} · Release: {_draft.release}"
                                                )
                                                _linked_card_obj = next(
                                                    (c for c in _rqa_cards if c.name == _bug_linked_card_name),
                                                    None,
                                                )
                                                if _linked_card_obj:
                                                    _tc.add_comment(_linked_card_obj.id, _bug_comment)
                                                    _bugs_key = f"bugs_for_{_linked_card_obj.id}"
                                                    _existing = st.session_state.get(_bugs_key, [])
                                                    _existing.append({
                                                        "name": _created_card.name,
                                                        "url": _created_card.url or "",
                                                        "severity": _draft.severity,
                                                    })
                                                    st.session_state[_bugs_key] = _existing
                                            except Exception:
                                                pass
                                        except Exception as exc:
                                            st.error(f"❌ Failed to create card: {exc}")
                                    st.rerun()

                    _raised_card = st.session_state.get("bug_raised_card")
                    if _raised_card:
                        st.success(f"🐛 Bug raised in Trello! [{_raised_card.name}]({_raised_card.url})")
                        if st.button("🆕 Report another bug", key="clear_bug_btn"):
                            st.session_state.pop("bug_raised_card", None)
                            st.session_state.pop("bug_check_result", None)
                            st.rerun()

    with tab_history:
        st.markdown("## 📋 Pipeline Run History")
        st.caption("Per-card pipeline progress is saved to disk and persists across server restarts.")

        runs = st.session_state.get("pipeline_runs", {})
        _run_list = list(runs.values())
        _release_count = len({(run.get("release") or "").strip() for run in _run_list if (run.get("release") or "").strip()})
        _sheet_rows_total = sum(int(run.get("sheet_rows", 0) or 0) for run in _run_list)
        _fail_total = sum(int((run.get("qa_summary") or {}).get("fail", 0) or 0) for run in _run_list)

        col_count, col_clear = st.columns([4, 1])
        with col_count:
            _hc1, _hc2, _hc3, _hc4 = st.columns(4)
            _hc1.metric("Runs", len(runs))
            _hc2.metric("Releases", _release_count)
            _hc3.metric("Sheet rows", _sheet_rows_total)
            _hc4.metric("Failed findings", _fail_total)
        with col_clear:
            if st.button("🗑️ Clear history", key="hist_clear_btn"):
                st.session_state["pipeline_runs"] = {}
                _save_history({})
                st.rerun()

        if not runs:
            st.info("No pipeline activity saved yet. Publish TCs, approve a card, or generate automation to see history here.")
        else:
            _runs_by_release: dict[str, list[tuple[str, dict]]] = {}
            for _card_id, _run in runs.items():
                _release_key = (_run.get("release") or "Unlabeled release").strip() or "Unlabeled release"
                _runs_by_release.setdefault(_release_key, []).append((_card_id, _run))
            for _release_name, _release_runs in sorted(_runs_by_release.items(), key=lambda item: item[0], reverse=True):
                _release_fail = sum(int((run.get("qa_summary") or {}).get("fail", 0) or 0) for _, run in _release_runs)
                _release_partial = sum(int((run.get("qa_summary") or {}).get("partial", 0) or 0) for _, run in _release_runs)
                _release_qn = sum(int((run.get("qa_summary") or {}).get("qa_needed", 0) or 0) for _, run in _release_runs)
                _release_rows = sum(int(run.get("sheet_rows", 0) or 0) for _, run in _release_runs)
                with st.expander(
                    f"Release: {_release_name} · Cards {len(_release_runs)} · Rows {_release_rows} · "
                    f"Fail {_release_fail} · Partial {_release_partial} · QA Needed {_release_qn}",
                    expanded=False,
                ):
                    for card_id, run in _release_runs:
                        approved_at = run.get("approved_at", "")
                        card_name   = run.get("card_name", card_id)
                        label       = f"✅ {card_name}  ·  {approved_at}"
                        with st.expander(label, expanded=False):
                            col1, col2 = st.columns(2)
                            col1.markdown(f"**Release**  \n{run.get('release', '—')}")
                            col2.markdown(f"**Approved at**  \n{approved_at or '—'}")
                            _sum = run.get("qa_summary") or {}
                            _meta = []
                            if run.get("ac_generated_at"):
                                _meta.append(f"AC generated: `{run['ac_generated_at']}`")
                            if run.get("ac_saved_at"):
                                _meta.append(f"AC saved: `{run['ac_saved_at']}`")
                            if run.get("ac_updated_at"):
                                _meta.append(f"AC updated: `{run['ac_updated_at']}`")
                            if run.get("ac_validated_at"):
                                _meta.append(f"AC validated: `{run['ac_validated_at']}`")
                            if run.get("ac_validation_status"):
                                _meta.append(f"Validation: `{run['ac_validation_status']}`")
                            if run.get("tc_published_at"):
                                _meta.append(f"TC published: `{run['tc_published_at']}`")
                            if run.get("automation_generated_at"):
                                _meta.append(f"Automation generated: `{run['automation_generated_at']}`")
                            if run.get("automation_pushed_at"):
                                _meta.append(f"Automation pushed: `{run['automation_pushed_at']}`")
                            if run.get("sheet_tab"):
                                _meta.append(f"Sheet tab: `{run['sheet_tab']}`")
                            if run.get("sheet_rows"):
                                _meta.append(f"Rows: `{run['sheet_rows']}`")
                            if _sum:
                                _meta.append(
                                    "QA: "
                                    f"PASS {_sum.get('pass', 0)} · FAIL {_sum.get('fail', 0)} · "
                                    f"PARTIAL {_sum.get('partial', 0)} · QA NEEDED {_sum.get('qa_needed', 0)}"
                                )
                            if _meta:
                                st.caption(" | ".join(_meta))
                            if run.get("card_url"):
                                st.markdown(f"[Open in Trello]({run['card_url']})")
                            if run.get("ac_validation_summary"):
                                st.caption(f"Validation summary: {run['ac_validation_summary']}")
                            ac_preview = run.get("ac_preview", "")
                            if ac_preview:
                                with st.expander("AC preview", expanded=False):
                                    st.markdown(ac_preview[:800] + ("…" if len(ac_preview) > 800 else ""))
                            tc_text = run.get("test_cases", "")
                            if tc_text:
                                with st.expander("Test Cases preview", expanded=False):
                                    st.markdown(tc_text[:800] + ("…" if len(tc_text) > 800 else ""))
                            if run.get("signoff_message"):
                                with st.expander("Sign-off message", expanded=False):
                                    st.code(run.get("signoff_message", ""), language="")

    with tab_signoff:
        st.markdown(
            '<div class="step-chip">⑧ QA Sign Off</div>',
            unsafe_allow_html=True,
        )
        st.markdown("## ✅ QA Sign Off")
        st.caption(
            "Compose and send the team sign-off message to Slack — "
            "exactly like the format used by your QA team."
        )

        # Instantiate TrelloClient for list fetching and card moves
        try:
            _signoff_board_id = st.session_state.get("rqa_board_id") or None
            trello = TrelloClient(board_id=_signoff_board_id)
        except Exception:
            trello = None

        cards_so: list = st.session_state.get("rqa_cards", [])
        approved_so: dict = st.session_state.get("rqa_approved", {})
        tc_store_so: dict = st.session_state.get("rqa_test_cases", {})
        release_so: str = st.session_state.get("rqa_release", "")

        if not cards_so:
            st.info("Load cards in **🧾 Validate AC** first, then return here to sign off.")
        else:
            # ── Slack configuration gate ─────────────────────────────────
            if not slack_configured():
                st.warning(
                    "Slack not configured. Set `SLACK_WEBHOOK_URL` or "
                    "`SLACK_BOT_TOKEN` + `SLACK_CHANNEL` in `.env` to enable sign-off posting."
                )

            st.markdown(f"**Release:** `{release_so or '(no release label)'}`")
            _approved_count = sum(1 for card in cards_so if approved_so.get(card.id, False))
            _report_counts = {"pass": 0, "fail": 0, "partial": 0, "qa_needed": 0}
            for card in cards_so:
                _card_summary = _report_summary_dict(st.session_state.get(f"sav_report_{card.id}"))
                for _k, _v in _card_summary.items():
                    _report_counts[_k] += _v
            _so_m1, _so_m2, _so_m3, _so_m4 = st.columns(4)
            _so_m1.metric("Cards loaded", len(cards_so))
            _so_m2.metric("Approved", _approved_count)
            _so_m3.metric("Backlog draft", len([b for b in st.session_state.get("signoff_bugs", "").splitlines() if b.strip()]))
            _so_m4.metric("Failed findings", _report_counts["fail"])
            st.caption(
                "QA summary: "
                f"PASS {_report_counts['pass']} · FAIL {_report_counts['fail']} · "
                f"PARTIAL {_report_counts['partial']} · QA NEEDED {_report_counts['qa_needed']}"
            )
            st.divider()

            # ── Card approval summary ─────────────────────────────────────
            st.markdown("### Cards Verified")
            verified_cards = []
            backlog_cards  = []
            for card in cards_so:
                is_approved = approved_so.get(card.id, False)
                _rpt = st.session_state.get(f"sav_report_{card.id}")
                _summary = _report_summary_dict(_rpt)
                _status = "Approved" if is_approved else ("Has issues" if (_summary["fail"] or _summary["partial"]) else "Pending")
                with st.expander(f"{_status} — {card.name}", expanded=False):
                    _so_c1, _so_c2, _so_c3, _so_c4 = st.columns(4)
                    _so_c1.metric("Pass", _summary["pass"])
                    _so_c2.metric("Fail", _summary["fail"])
                    _so_c3.metric("Partial", _summary["partial"])
                    _so_c4.metric("QA Needed", _summary["qa_needed"])
                    if is_approved:
                        st.success("Approved for release.")
                    elif _summary["fail"] or _summary["partial"]:
                        st.warning("This card still has unresolved failed findings.")
                    else:
                        st.caption("Approval pending.")
                    if _rpt:
                        _render_report_review(_rpt, key_prefix=f"signoff_review_{card.id}")
                if is_approved:
                    verified_cards.append({"name": card.name, "url": card.url})

            st.divider()

            # ── Bug list ──────────────────────────────────────────────────
            st.markdown("### Bugs / Backlog Items")
            _auto_bugs = []
            for card in cards_so:
                _rpt = st.session_state.get(f"sav_report_{card.id}")
                _summary = _report_summary_dict(_rpt)
                if _rpt and (_summary["fail"] or _summary["partial"]):
                    for _sv in getattr(_rpt, "scenarios", []) or []:
                        if getattr(_sv, "status", "") in ("fail", "partial"):
                            _auto_bugs.append(
                                f"[{card.name}] {getattr(_sv, 'scenario', '')} — "
                                f"{getattr(_sv, 'finding', '') or getattr(_sv, 'status', '')}"
                            )

            _bugs_default = "\n".join(_auto_bugs) if _auto_bugs else ""
            bugs_text = st.text_area(
                "Bug / backlog items (one per line)",
                value=st.session_state.get("signoff_bugs", _bugs_default),
                height=120,
                key="signoff_bugs_input",
                placeholder="Bug title 1\nBug title 2",
            )
            st.session_state["signoff_bugs"] = bugs_text
            backlog_cards = [{"name": b.strip()} for b in bugs_text.splitlines() if b.strip()]
            _backlog_lines = [item["name"] for item in backlog_cards]
            _release_gate = _release_decision_snapshot(cards_so, approved_so, _backlog_lines)
            _decision_color = {"READY": "green", "NOT READY": "red", "PENDING": "orange"}.get(_release_gate["decision"], "gray")
            st.markdown(f"**Release Decision:** :{_decision_color}[{_release_gate['decision']}]")
            if _release_gate["reasons"]:
                for _reason in _release_gate["reasons"]:
                    st.caption(f"- {_reason}")

            st.divider()

            # ── Sign-off message composer ─────────────────────────────────
            st.markdown("### Sign-Off Message")
            _mentions_input = st.text_input(
                "Mention users (comma-separated Slack usernames, no @)",
                value=st.session_state.get("signoff_mentions", ""),
                key="signoff_mentions_input",
                placeholder="john, jane",
            )
            st.session_state["signoff_mentions"] = _mentions_input
            _mentions_list = [m.strip() for m in _mentions_input.split(",") if m.strip()]

            _cc_input = st.text_input(
                "CC (Slack username, no @)",
                value=st.session_state.get("signoff_cc", ""),
                key="signoff_cc_input",
            )
            st.session_state["signoff_cc"] = _cc_input

            _qa_lead = st.text_input(
                "QA Lead name",
                value=st.session_state.get("signoff_qa_lead", ""),
                key="signoff_qa_lead_input",
            )
            st.session_state["signoff_qa_lead"] = _qa_lead

            # Preview
            _preview_lines = []
            if _mentions_list:
                _preview_lines.append("  ".join(f"@{m}" for m in _mentions_list))
                _preview_lines.append("")
            _preview_lines.append(
                f"We've completed testing *{release_so}* and it's good for the release"
            )
            _preview_lines.append("")
            _preview_lines.append("*Cards Verified:*")
            for vc in verified_cards:
                _preview_lines.append(f"{vc['name']}\n{vc.get('url','')}")
            _preview_lines.append("")
            _preview_lines.append(f"*Cards added to backlog ({len(backlog_cards)}):*")
            for bc in backlog_cards:
                _preview_lines.append(bc["name"])
            _preview_lines.append("")
            _preview_lines.append("*QA Signed off*")
            if _cc_input:
                _preview_lines.append(f"CC: @{_cc_input.lstrip('@')}")
            if _qa_lead:
                _preview_lines.append(f"Signed by: {_qa_lead}")

            _preview_msg = "\n".join(_preview_lines)
            st.session_state["signoff_message"] = _preview_msg

            with st.expander("Preview Sign-Off Message", expanded=True):
                st.code(_preview_msg, language="")

            st.divider()

            # ── Send Sign-Off ─────────────────────────────────────────────
            _signoff_sent = st.session_state.get("signoff_sent", False)

            if _signoff_sent:
                st.success("Sign-Off sent! Release marked as QA-done.")
            else:
                _channel_override = st.text_input(
                    "Post to channel (leave blank for default)",
                    value="",
                    key="signoff_channel_override",
                    placeholder="C09F65XF4ER",
                )

                # QA-done Trello list selector
                _qa_done_list_id = ""
                if trello:
                    try:
                        _all_lists = trello.get_lists()
                        _list_opts = {lst.name: lst.id for lst in _all_lists}
                        _qa_done_name = st.selectbox(
                            "Move approved cards to list",
                            options=list(_list_opts.keys()),
                            key="signoff_qa_done_list",
                        )
                        _qa_done_list_id = _list_opts.get(_qa_done_name, "")
                    except Exception:
                        st.caption("Trello list selector unavailable.")
                else:
                    st.caption("Trello list selector unavailable.")

                _send_disabled = not slack_configured() or not verified_cards or _release_gate["decision"] != "READY"
                if st.button(
                    "Send Sign-Off",
                    type="primary",
                    disabled=_send_disabled,
                    key="send_signoff_btn",
                ):
                    with st.spinner("Sending Sign-Off to Slack..."):
                        _errors = []

                        # Post to Slack
                        try:
                            _slack_result = slack_post_signoff(
                                release=release_so,
                                verified_cards=verified_cards,
                                backlog_cards=backlog_cards,
                                mentions=_mentions_list or None,
                                cc=_cc_input,
                                qa_lead=_qa_lead,
                                channel=_channel_override.strip() or None,
                            )
                            if not _slack_result.get("ok"):
                                _errors.append(f"Slack: {_slack_result.get('error', 'unknown error')}")
                        except Exception as _se:
                            _errors.append(f"Slack: {_se}")

                        # Move approved cards to QA-done list
                        if _qa_done_list_id and trello:
                            for card in cards_so:
                                if approved_so.get(card.id):
                                    try:
                                        trello.move_card_to_list_by_id(card.id, _qa_done_list_id)
                                    except Exception as _te:
                                        _errors.append(f"Trello move {card.name}: {_te}")

                        if _errors:
                            for _err in _errors:
                                st.warning(f"{_err}")
                        else:
                            for card in cards_so:
                                if approved_so.get(card.id):
                                    try:
                                        if trello:
                                            trello.add_comment(
                                                card.id,
                                                f"✅ QA Signed off — {release_so or 'Release'}\n\n"
                                                f"Signed by: {_qa_lead or 'QA Team'}"
                                            )
                                    except Exception as _comment_err:
                                        st.warning(f"Trello comment {card.name}: {_comment_err}")
                                    _update_pipeline_run(
                                        card,
                                        signoff_sent_at=datetime.now().isoformat(timespec="seconds"),
                                        signoff_message=_preview_msg,
                                    )
                            st.session_state["signoff_sent"] = True
                            st.rerun()
                if _send_disabled and _release_gate["decision"] != "READY":
                    st.warning("Release is not ready for sign-off yet. Resolve the blocking QA/backlog items above first.")

            st.divider()
            st.markdown("#### 📊 Export Release to Google Sheet")
            st.caption(
                "Creates a new sheet tab named after the release and writes one row per card "
                "with URL, description, ticket, toggle info, and API type."
            )

            _sheet_col1, _sheet_col2 = st.columns([1, 2])
            with _sheet_col1:
                if st.button(
                    "📊 Export to Sheet",
                    use_container_width=True,
                    disabled=not cards_so,
                    key="signoff_sheet_btn",
                    type="primary",
                ):
                    from pipeline.sheets_writer import create_release_sheet

                    _bugs_by_card = {
                        c.id: st.session_state.get(f"bugs_for_{c.id}", [])
                        for c in cards_so
                    }
                    with st.spinner(f"Creating sheet tab '{release_so or 'Release'}'…"):
                        try:
                            result = create_release_sheet(
                                release_name=release_so or "Release",
                                cards=cards_so,
                                list_name=st.session_state.get("rqa_list_name", release_so),
                                bugs_by_card=_bugs_by_card,
                            )
                            st.session_state["signoff_sheet_result"] = result
                        except Exception as exc:
                            st.session_state["signoff_sheet_result"] = {"error": str(exc)}
                    st.rerun()

            with _sheet_col2:
                _sheet_res = st.session_state.get("signoff_sheet_result")
                if _sheet_res:
                    if "error" in _sheet_res:
                        st.error(f"❌ Sheet export failed: {_sheet_res['error']}")
                    else:
                        _action = "Created" if _sheet_res.get("created") else "Updated"
                        st.success(
                            f"✅ {_action} tab **{_sheet_res['tab']}** — "
                            f"{_sheet_res['rows_added']} cards written"
                        )
                        st.markdown(f"[🔗 Open Sheet]({_sheet_res['sheet_url']})")

    with tab_handoff:
        st.markdown(
            '<div class="step-chip">📘 Release Enablement</div>',
            unsafe_allow_html=True,
        )
        st.markdown("## 📘 Handoff Docs")
        st.caption(
            "Generate support/demo and business handoff documents for approved cards. "
            "You can edit, download, attach to Trello, or send the PDF to Slack."
        )

        handoff_tc_store = st.session_state.get("rqa_test_cases", {})
        handoff_runs = st.session_state.get("pipeline_runs", {})

        # ── Board / list selector ───────────────────────────────────────────
        hd_board_id, hd_board_name = _select_trello_board("Trello board", "hd")
        try:
            _hd_trello = TrelloClient(board_id=hd_board_id) if hd_board_id else None
            _hd_all_lists = _hd_trello.get_lists() if _hd_trello else []
        except Exception as _hd_e:
            st.error(f"Trello connection failed: {_hd_e}")
            _hd_all_lists = []

        _hd_list_options = {lst.name: lst.id for lst in _hd_all_lists} if _hd_all_lists else {}
        _hd_list_names = list(_hd_list_options.keys()) or [""]

        if st.button("🔄 Refresh Trello lists", key="hd_refresh_lists_btn"):
            st.cache_data.clear()
            st.rerun()

        _hd_show_all = st.toggle("Show all lists", value=False, key="hd_show_all_lists")
        _hd_filtered = _hd_list_names
        if not _hd_show_all:
            _hd_qa_names = [n for n in _hd_list_names if "qa" in n.lower() or "ready for qa" in n.lower()]
            if _hd_qa_names:
                _hd_filtered = _hd_qa_names

        _hd_col_list, _hd_col_load = st.columns([4, 1])
        with _hd_col_list:
            _hd_selected_list = st.selectbox(
                "Select Trello List",
                options=_hd_filtered,
                index=_hd_filtered.index(st.session_state["hd_list_name"])
                if st.session_state.get("hd_list_name") in _hd_filtered else 0,
                key="hd_list_selector",
            )
        with _hd_col_load:
            st.markdown("<br>", unsafe_allow_html=True)
            _hd_load_clicked = st.button("Load Cards", type="primary", key="hd_load_btn")

        if _hd_load_clicked and _hd_selected_list and _hd_list_options:
            _hd_list_id = _hd_list_options[_hd_selected_list]
            with st.spinner(f"Loading cards from '{_hd_selected_list}'…"):
                try:
                    _hd_loaded = _dedupe_cards(_hd_trello.get_cards_in_list(_hd_list_id))
                    st.session_state["hd_cards"] = _hd_loaded
                    st.session_state["hd_list_name"] = _hd_selected_list
                    st.session_state["hd_board_id"] = hd_board_id
                    st.session_state["hd_board_name"] = hd_board_name
                    st.rerun()
                except Exception as _hd_load_err:
                    st.error(f"Failed to load cards: {_hd_load_err}")

        handoff_cards = st.session_state.get("hd_cards", [])
        handoff_release = st.session_state.get("rqa_release", "")

        if not handoff_cards:
            st.info("Select a Trello board and list above, then click **Load Cards**.")
        else:
            from pipeline.handoff_docs import (
                build_handoff_context,
                generate_business_brief,
                generate_support_guide,
                render_pdf_bytes,
            )
            from pipeline.slack_client import (
                list_slack_channels,
                search_slack_users,
                upload_file_to_slack_channel,
                upload_file_to_slack_user,
            )

            def _safe_fname(text: str) -> str:
                return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "document"

            def _handoff_context_for(card: Any):
                _run = handoff_runs.get(card.id, {})
                _sav_report = st.session_state.get(f"sav_report_{card.id}")
                _summary = _report_summary_dict(_sav_report)
                _ai_qa_summary = (
                    f"PASS {_summary['pass']} · FAIL {_summary['fail']} · "
                    f"PARTIAL {_summary['partial']} · QA NEEDED {_summary['qa_needed']}"
                ) if _sav_report else ""
                _ai_qa_evidence = _sav_report.to_automation_context() if _sav_report else ""
                _members = []
                try:
                    _trello = TrelloClient(board_id=st.session_state.get("hd_board_id") or st.session_state.get("rqa_board_id") or None)
                    _members = _trello.get_card_members(card.id)
                except Exception:
                    _members = []
                return build_handoff_context(
                    card=card,
                    release_name=handoff_release or _run.get("release", ""),
                    approved_at=_run.get("approved_at", ""),
                    acceptance_criteria=st.session_state.get(f"ac_suggestion_{card.id}") or (card.desc or ""),
                    test_cases=handoff_tc_store.get(card.id, ""),
                    ai_qa_summary=_ai_qa_summary,
                    ai_qa_evidence=_ai_qa_evidence,
                    signoff_summary=_run.get("signoff_message", "") or st.session_state.get("signoff_message", ""),
                    members=_members,
                )

            _doc_options = {card.name: card for card in handoff_cards}
            _selected_name = st.selectbox(
                "Select approved card",
                options=list(_doc_options.keys()),
                key="handoff_selected_card",
            )
            _target_card = _doc_options[_selected_name]
            _ctx = _handoff_context_for(_target_card)

            st.caption(
                f"Developed by: {', '.join(_ctx.developer_names) or 'Unknown'}  |  "
                f"Tested by: {', '.join(_ctx.tester_names) or 'QA Team'}  |  "
                f"Toggles: {', '.join(_ctx.toggle_names) or 'None detected'}"
            )

            _gen_col1, _gen_col2, _gen_col3 = st.columns(3)
            with _gen_col1:
                if st.button("🤖 Generate Support Guide", key=f"gen_support_{_target_card.id}", type="primary", use_container_width=True):
                    with st.spinner("Generating support guide…"):
                        st.session_state[f"handoff_support_{_target_card.id}"] = generate_support_guide(_ctx)
                    st.rerun()
            with _gen_col2:
                if st.button("🤖 Generate Business Brief", key=f"gen_business_{_target_card.id}", type="primary", use_container_width=True):
                    with st.spinner("Generating business brief…"):
                        st.session_state[f"handoff_business_{_target_card.id}"] = generate_business_brief(_ctx)
                    st.rerun()
            with _gen_col3:
                if st.button("🤖 Generate Both", key=f"gen_both_{_target_card.id}", type="primary", use_container_width=True):
                    with st.spinner("Generating both handoff documents…"):
                        st.session_state[f"handoff_support_{_target_card.id}"] = generate_support_guide(_ctx)
                        st.session_state[f"handoff_business_{_target_card.id}"] = generate_business_brief(_ctx)
                    st.rerun()

            def _render_doc_editor(doc_type: str, label: str) -> None:
                _state_key = f"handoff_{doc_type}_{_target_card.id}"
                _text = st.session_state.get(_state_key, "")
                if not _text:
                    return

                st.divider()
                st.markdown(f"### {label}")
                _edited = st.text_area(
                    f"{label} content",
                    value=_text,
                    height=520 if doc_type == "support" else 420,
                    key=f"handoff_editor_{doc_type}_{_target_card.id}",
                    label_visibility="collapsed",
                )
                st.session_state[_state_key] = _edited

                _md_bytes = _edited.encode("utf-8")
                _pdf_title = f"{label} - {_target_card.name}"
                _base = _safe_fname(f"{_target_card.name}_{doc_type}")
                _md_name = f"{_base}.md"
                _pdf_name = f"{_base}.pdf"
                _pdf_bytes = b""
                _pdf_error = ""
                try:
                    _pdf_bytes = render_pdf_bytes(_pdf_title, _edited)
                except Exception as _exc:
                    _pdf_error = str(_exc)

                _dl1, _dl2 = st.columns(2)
                with _dl1:
                    st.download_button(
                        "⬇️ Download Markdown",
                        data=_md_bytes,
                        file_name=_md_name,
                        mime="text/markdown",
                        key=f"download_md_{doc_type}_{_target_card.id}",
                        use_container_width=True,
                    )
                with _dl2:
                    st.download_button(
                        "⬇️ Download PDF",
                        data=_pdf_bytes,
                        file_name=_pdf_name,
                        mime="application/pdf",
                        key=f"download_pdf_{doc_type}_{_target_card.id}",
                        disabled=bool(_pdf_error),
                        use_container_width=True,
                    )
                if _pdf_error:
                    st.info(f"PDF actions are unavailable: {_pdf_error}")

                _act1, _act2, _act3 = st.columns(3)
                with _act1:
                    if st.button("📎 Attach PDF to Trello", key=f"attach_trello_{doc_type}_{_target_card.id}", use_container_width=True, disabled=bool(_pdf_error)):
                        try:
                            _trello = TrelloClient(board_id=st.session_state.get("hd_board_id") or st.session_state.get("rqa_board_id") or None)
                            _att = _trello.attach_file(
                                _target_card.id,
                                filename=_pdf_name,
                                file_bytes=_pdf_bytes,
                                mime_type="application/pdf",
                                attachment_name=_pdf_name,
                            )
                            _trello.add_comment(
                                _target_card.id,
                                f"📘 {label} attached by MCSL QA Pipeline\n\n"
                                f"Attachment: {(_att or {}).get('url', _pdf_name)}"
                            )
                            st.success("✅ PDF attached to Trello and comment added")
                        except Exception as _exc:
                            st.error(f"❌ Trello upload failed: {_exc}")
                with _act2:
                    if dm_token_configured():
                        _ch_cache_key = "slack_channels_cache"
                        if _ch_cache_key not in st.session_state:
                            _chs, _err, _note = list_slack_channels()
                            st.session_state[_ch_cache_key] = (_chs, _err, _note)
                        _chs, _ch_err, _ch_note = st.session_state[_ch_cache_key]
                        if _chs:
                            _ch_map = {
                                f"{'🔒' if c.get('is_private') else '#'} {c['name']}": c["id"]
                                for c in _chs
                            }
                            _sel = st.selectbox(
                                "Slack channel",
                                options=list(_ch_map.keys()),
                                key=f"handoff_ch_sel_{doc_type}_{_target_card.id}",
                                label_visibility="collapsed",
                            )
                            if st.button("📢 Send PDF to Channel", key=f"send_ch_{doc_type}_{_target_card.id}", use_container_width=True, disabled=bool(_pdf_error)):
                                _res = upload_file_to_slack_channel(
                                    channel_id=_ch_map[_sel],
                                    filename=_pdf_name,
                                    file_bytes=_pdf_bytes,
                                    title=_pdf_title,
                                    initial_comment=f"📘 {label} - {_target_card.name}\n{_target_card.url}",
                                )
                                if _res.get("ok"):
                                    st.success("✅ PDF sent to Slack channel")
                                else:
                                    st.error(f"❌ Slack upload failed: {_res.get('error')}")
                        elif _ch_err:
                            st.error(f"❌ {_ch_err}")
                        elif _ch_note:
                            st.caption(_ch_note)
                    else:
                        st.caption("Slack bot not configured")
                with _act3:
                    _pool_key = f"handoff_user_pool_{doc_type}_{_target_card.id}"
                    if _pool_key not in st.session_state:
                        st.session_state[_pool_key] = {}
                    _query = st.text_input(
                        "Search person",
                        key=f"handoff_user_search_{doc_type}_{_target_card.id}",
                        label_visibility="collapsed",
                        placeholder="Search Slack user",
                    )
                    if st.button("🔎 Find", key=f"handoff_find_user_{doc_type}_{_target_card.id}", use_container_width=True):
                        if _query.strip():
                            _found, _err = search_slack_users(_query.strip())
                            if _err:
                                st.error(f"❌ {_err}")
                            elif not _found:
                                st.info("No users found")
                            else:
                                for _user in _found:
                                    _real_name = _user.get("real_name", "") or _user.get("name", "")
                                    _display_name = _user.get("display_name", "") or _real_name
                                    _label = f"{_real_name} (@{_display_name})"
                                    st.session_state[_pool_key][_label] = _user["id"]
                    _pool = st.session_state[_pool_key]
                    if _pool:
                        _picked = st.selectbox(
                            "Recipient",
                            options=list(_pool.keys()),
                            key=f"handoff_user_pick_{doc_type}_{_target_card.id}",
                            label_visibility="collapsed",
                        )
                        if st.button("📨 Send PDF to Person", key=f"handoff_send_user_{doc_type}_{_target_card.id}", use_container_width=True, disabled=bool(_pdf_error)):
                            _uid = _pool[_picked]
                            _res = upload_file_to_slack_user(
                                user_id=_uid,
                                filename=_pdf_name,
                                file_bytes=_pdf_bytes,
                                title=_pdf_title,
                                initial_comment=f"📘 {label} - {_target_card.name}\n{_target_card.url}",
                            )
                            if _res.get("ok"):
                                st.success("✅ PDF sent via Slack DM")
                            else:
                                st.error(f"❌ Slack DM upload failed: {_res.get('error')}")

            _render_doc_editor("support", "Support Guide")
            _render_doc_editor("business", "Business Brief")

_init_state()
if not getattr(st, "IS_SHIM", False):
    main()

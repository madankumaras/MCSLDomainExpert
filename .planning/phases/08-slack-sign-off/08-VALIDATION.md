---
phase: 8
slug: slack-sign-off
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-17
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | pytest.ini |
| **Quick run command** | `.venv/bin/pytest tests/test_pipeline.py tests/test_dashboard.py -x -q 2>&1 | tail -5` |
| **Full suite command** | `cd /Users/madan/Documents/MCSLDomainExpert && .venv/bin/pytest tests/ -x -q 2>&1 | tail -10` |
| **Estimated runtime** | ~6 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick command above
- **After every plan wave:** Run full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 08-01-RED | 01 | 1 | SLACK-01 | unit | `pytest tests/test_pipeline.py::test_slack01_send_dm -x` | ❌ W0 | ⬜ pending |
| 08-01-GREEN | 01 | 1 | SLACK-01 | unit | `pytest tests/test_pipeline.py::test_slack01_send_dm tests/test_pipeline.py::test_slack01_post_channel -x` | ❌ W0 | ⬜ pending |
| 08-02-RED | 02 | 1 | SLACK-02 | unit | `pytest tests/test_pipeline.py::test_slack02_notify_devs -x` | ❌ W0 | ⬜ pending |
| 08-02-GREEN | 02 | 1 | SLACK-02 | unit | `pytest tests/test_pipeline.py::test_slack02_notify_devs tests/test_pipeline.py::test_slack02_get_card_members -x` | ❌ W0 | ⬜ pending |
| 08-03-RED | 03 | 2 | SIGNOFF-01,SIGNOFF-02 | unit | `pytest tests/test_dashboard.py::test_signoff01_session_keys -x` | ❌ W0 | ⬜ pending |
| 08-03-GREEN | 03 | 2 | SIGNOFF-01,SIGNOFF-02 | unit | `pytest tests/test_dashboard.py -k "signoff" -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_pipeline.py` — stubs: test_slack01_send_dm, test_slack01_post_channel, test_slack01_post_signoff, test_slack02_notify_devs, test_slack02_get_card_members
- [ ] `tests/test_dashboard.py` — stubs: test_signoff01_session_keys, test_signoff01_compose_message, test_signoff02_send_signoff_posts_slack

*Existing test infrastructure (pytest, conftest) covers all phase requirements — only new stubs needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Slack DM arrives in Slack UI | SLACK-01 | Requires live Slack workspace | Send test DM, verify in Slack |
| Sign-Off message posted to channel | SIGNOFF-01 | Requires live Slack channel | Click Send Sign-Off, verify in #channel |
| Trello card moved to QA-done list | SIGNOFF-02 | Requires live Trello board | After sign-off, verify card position |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

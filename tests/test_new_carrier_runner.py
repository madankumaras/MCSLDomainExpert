from __future__ import annotations

from pipeline.new_carrier_runner import build_playwright_command


def test_build_playwright_command_for_smoke():
    command = build_playwright_command("smoke")
    assert command == [
        "npx",
        "playwright",
        "test",
        "--grep",
        "@smoke",
        "--project",
        "Google Chrome",
        "--headed",
    ]


def test_build_playwright_command_rejects_unknown_suite():
    try:
        build_playwright_command("full")
    except ValueError as exc:
        assert "Unsupported suite" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unsupported suite")

"""Tests for pm/agent/escalation.py — iMessage send and reply polling."""

import pytest
import subprocess
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call

from pm.agent.escalation import (
    _send_imessage,
    _poll_for_reply,
    send_escalation,
    wait_for_reply,
    escalate_and_wait,
    EscalationResult,
    DEFAULT_ESCALATION_PHONE,
)
from pm.agent.planner import AssessmentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_assessment(**kwargs):
    defaults = dict(
        project_name="test-proj",
        project_path="/tmp/test-proj",
        confidence=75,
        risk_level="safe",
        proposed_action="Run tests",
        proposed_prompt="run pytest",
        reasoning="Tests seem to be failing",
        error=None,
    )
    defaults.update(kwargs)
    return AssessmentResult(**defaults)


# ---------------------------------------------------------------------------
# _send_imessage — AppleScript generation and escaping
# ---------------------------------------------------------------------------

class TestSendImessage:
    @patch("pm.agent.escalation.subprocess.run")
    def test_send_returns_true_on_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert _send_imessage("+1234567890", "hello") is True

    @patch("pm.agent.escalation.subprocess.run")
    def test_send_returns_false_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert _send_imessage("+1234567890", "hello") is False

    @patch("pm.agent.escalation.subprocess.run")
    def test_send_returns_false_on_exception(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="osascript", timeout=10)
        assert _send_imessage("+1234567890", "hello") is False

    @patch("pm.agent.escalation.subprocess.run")
    def test_escapes_double_quotes(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        _send_imessage("+1", 'say "hello"')
        script = mock_run.call_args[0][0][2]
        assert '\\"hello\\"' in script

    @patch("pm.agent.escalation.subprocess.run")
    def test_escapes_backslash(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        _send_imessage("+1", "path\\to\\file")
        script = mock_run.call_args[0][0][2]
        assert "path\\\\to\\\\file" in script

    @patch("pm.agent.escalation.subprocess.run")
    def test_escapes_newlines(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        _send_imessage("+1", "line1\nline2")
        script = mock_run.call_args[0][0][2]
        assert "\\n" in script
        assert "\nline2" not in script

    @patch("pm.agent.escalation.subprocess.run")
    def test_strips_carriage_return(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        _send_imessage("+1", "text\rmore")
        script = mock_run.call_args[0][0][2]
        assert "\r" not in script

    @patch("pm.agent.escalation.subprocess.run")
    def test_calls_osascript(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        _send_imessage("+1234567890", "test message")
        args = mock_run.call_args[0][0]
        assert args[0] == "osascript"
        assert args[1] == "-e"


# ---------------------------------------------------------------------------
# send_escalation
# ---------------------------------------------------------------------------

class TestSendEscalation:
    @patch("pm.agent.escalation._send_imessage", return_value=True)
    def test_returns_escalation_result(self, mock_send):
        assessment = make_assessment()
        result = send_escalation(assessment)
        assert isinstance(result, EscalationResult)
        assert result.assessment is assessment

    @patch("pm.agent.escalation._send_imessage", return_value=True)
    def test_sets_sent_at_on_success(self, mock_send):
        result = send_escalation(make_assessment())
        assert result.sent_at is not None

    @patch("pm.agent.escalation._send_imessage", return_value=False)
    def test_sets_error_on_send_failure(self, mock_send):
        result = send_escalation(make_assessment())
        assert result.decision == "error"
        assert result.sent_at is None

    @patch("pm.agent.escalation._send_imessage", return_value=True)
    def test_message_contains_project_name(self, mock_send):
        send_escalation(make_assessment(project_name="my-proj"))
        msg = mock_send.call_args[0][1]
        assert "my-proj" in msg

    @patch("pm.agent.escalation._send_imessage", return_value=True)
    def test_message_contains_proposed_action(self, mock_send):
        send_escalation(make_assessment(proposed_action="fix auth bug"))
        msg = mock_send.call_args[0][1]
        assert "fix auth bug" in msg

    @patch("pm.agent.escalation._send_imessage", return_value=True)
    def test_message_contains_confidence_when_low(self, mock_send):
        send_escalation(make_assessment(confidence=55))
        msg = mock_send.call_args[0][1]
        assert "55" in msg

    @patch("pm.agent.escalation._send_imessage", return_value=True)
    def test_uses_default_phone(self, mock_send):
        send_escalation(make_assessment())
        phone = mock_send.call_args[0][0]
        assert phone == DEFAULT_ESCALATION_PHONE


# ---------------------------------------------------------------------------
# wait_for_reply
# ---------------------------------------------------------------------------

class TestWaitForReply:
    @patch("pm.agent.escalation._poll_for_reply", return_value="1")
    @patch("pm.agent.escalation.time.sleep")
    def test_approve_reply(self, mock_sleep, mock_poll):
        assessment = make_assessment()
        result = EscalationResult(assessment=assessment)
        result.sent_at = datetime(2026, 4, 13, 10, 0, 0)
        result = wait_for_reply(result)
        assert result.decision == "approved"
        assert result.replied_at is not None

    @patch("pm.agent.escalation._poll_for_reply", return_value="2")
    @patch("pm.agent.escalation.time.sleep")
    def test_skip_reply(self, mock_sleep, mock_poll):
        assessment = make_assessment()
        result = EscalationResult(assessment=assessment)
        result.sent_at = datetime(2026, 4, 13, 10, 0, 0)
        result = wait_for_reply(result)
        assert result.decision == "skipped"

    @patch("pm.agent.escalation._poll_for_reply", return_value="run pytest -x instead")
    @patch("pm.agent.escalation.time.sleep")
    def test_modified_reply(self, mock_sleep, mock_poll):
        assessment = make_assessment()
        result = EscalationResult(assessment=assessment)
        result.sent_at = datetime(2026, 4, 13, 10, 0, 0)
        result = wait_for_reply(result)
        assert result.decision == "modified"
        assert result.modified_prompt == "run pytest -x instead"

    @patch("pm.agent.escalation._poll_for_reply", return_value=None)
    @patch("pm.agent.escalation.time.sleep")
    def test_timeout(self, mock_sleep, mock_poll):
        assessment = make_assessment()
        result = EscalationResult(assessment=assessment)
        # sent far enough in the past that the deadline has already passed
        result.sent_at = datetime(2026, 4, 12, 0, 0, 0)
        result = wait_for_reply(result, timeout_mins=1)
        assert result.decision == "timeout"

    def test_error_result_skips_polling(self):
        assessment = make_assessment()
        result = EscalationResult(assessment=assessment, decision="error")
        with patch("pm.agent.escalation._poll_for_reply") as mock_poll:
            wait_for_reply(result)
            mock_poll.assert_not_called()

    def test_no_sent_at_skips_polling(self):
        assessment = make_assessment()
        result = EscalationResult(assessment=assessment)
        assert result.sent_at is None
        with patch("pm.agent.escalation._poll_for_reply") as mock_poll:
            wait_for_reply(result)
            mock_poll.assert_not_called()


# ---------------------------------------------------------------------------
# EscalationResult properties
# ---------------------------------------------------------------------------

class TestEscalationResult:
    def test_approved_true_for_approved(self):
        r = EscalationResult(assessment=make_assessment(), decision="approved")
        assert r.approved is True

    def test_approved_true_for_modified(self):
        r = EscalationResult(assessment=make_assessment(), decision="modified",
                             modified_prompt="do something else")
        assert r.approved is True

    def test_approved_false_for_skipped(self):
        r = EscalationResult(assessment=make_assessment(), decision="skipped")
        assert r.approved is False

    def test_effective_prompt_uses_modified(self):
        r = EscalationResult(assessment=make_assessment(proposed_prompt="original"),
                             decision="modified", modified_prompt="override")
        assert r.effective_prompt == "override"

    def test_effective_prompt_falls_back_to_proposed(self):
        r = EscalationResult(assessment=make_assessment(proposed_prompt="original"),
                             decision="approved")
        assert r.effective_prompt == "original"


# ---------------------------------------------------------------------------
# _poll_for_reply — chat.db not available
# ---------------------------------------------------------------------------

class TestPollForReply:
    def test_returns_none_when_chat_db_missing(self):
        with patch("os.path.exists", return_value=False):
            result = _poll_for_reply("+1234567890", datetime(2026, 4, 13, 10, 0, 0))
        assert result is None

    def test_returns_none_on_db_exception(self):
        import sqlite3
        with patch("sqlite3.connect", side_effect=sqlite3.Error("locked")):
            result = _poll_for_reply("+1234567890", datetime(2026, 4, 13, 10, 0, 0))
        assert result is None

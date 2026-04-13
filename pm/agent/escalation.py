"""iMessage escalation for blocked agents.

When an agent cannot auto-execute (confidence < 80 or risky), it sends an
iMessage asking the user to approve or reject the proposed action.

Message format:
    [PM] <project>: <why blocked>
    Action: <proposed action>
    Reply:
      1. Approve
      2. Skip
      3. Modify (reply with new prompt)

The handler then polls chat.db for a reply (timeout: 10 minutes).
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .planner import AssessmentResult


# Default phone number to escalate to
DEFAULT_ESCALATION_PHONE = "+12064962555"

# Poll interval when waiting for reply
POLL_INTERVAL_SECS = 15

# Maximum wait time for a reply
DEFAULT_TIMEOUT_MINS = 10


@dataclass
class EscalationResult:
    """Result of an escalation interaction."""
    assessment: AssessmentResult
    sent_at: Optional[datetime] = None
    replied_at: Optional[datetime] = None
    decision: str = "pending"       # "approved", "skipped", "modified", "timeout", "error"
    modified_prompt: Optional[str] = None
    error: Optional[str] = None

    @property
    def approved(self) -> bool:
        return self.decision in ("approved", "modified")

    @property
    def effective_prompt(self) -> str:
        """The prompt to actually run — modified if user changed it."""
        if self.decision == "modified" and self.modified_prompt:
            return self.modified_prompt
        return self.assessment.proposed_prompt


def send_escalation(
    assessment: AssessmentResult,
    phone: str = DEFAULT_ESCALATION_PHONE,
) -> EscalationResult:
    """Send an iMessage escalation for a blocked agent.

    Returns immediately after sending — call wait_for_reply() to block.
    """
    result = EscalationResult(assessment=assessment)

    reasons = []
    if assessment.confidence < 80:
        reasons.append(f"confidence {assessment.confidence}/100")
    if assessment.risk_level != "safe":
        reasons.append(f"risk={assessment.risk_level}")
    if assessment.error:
        reasons.append(f"error: {assessment.error}")

    reason_str = ", ".join(reasons) if reasons else "needs approval"

    message = (
        f"[PM] {assessment.project_name}: {reason_str}\n"
        f"Action: {assessment.proposed_action}\n"
        f"Reasoning: {assessment.reasoning[:150]}\n"
        f"\nReply:\n"
        f"  1 = Approve\n"
        f"  2 = Skip\n"
        f"  <anything else> = use as new prompt"
    )

    sent = _send_imessage(phone, message)
    if sent:
        result.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        result.decision = "error"
        result.error = "Failed to send iMessage"

    return result


def wait_for_reply(
    result: EscalationResult,
    phone: str = DEFAULT_ESCALATION_PHONE,
    timeout_mins: int = DEFAULT_TIMEOUT_MINS,
) -> EscalationResult:
    """Poll for a reply to an escalation message.

    Modifies result in place and returns it.
    Blocks until reply received or timeout.
    """
    if result.decision == "error" or result.sent_at is None:
        return result

    deadline = result.sent_at + timedelta(minutes=timeout_mins)

    while datetime.now(timezone.utc).replace(tzinfo=None) < deadline:
        reply = _poll_for_reply(phone, after=result.sent_at)
        if reply:
            result.replied_at = datetime.now(timezone.utc).replace(tzinfo=None)
            reply_clean = reply.strip().lower()

            if reply_clean == "1":
                result.decision = "approved"
            elif reply_clean == "2":
                result.decision = "skipped"
            else:
                # Treat as modified prompt
                result.decision = "modified"
                result.modified_prompt = reply.strip()
            return result

        time.sleep(POLL_INTERVAL_SECS)

    result.decision = "timeout"
    return result


def escalate_and_wait(
    assessment: AssessmentResult,
    phone: str = DEFAULT_ESCALATION_PHONE,
    timeout_mins: int = DEFAULT_TIMEOUT_MINS,
) -> EscalationResult:
    """Convenience: send escalation and wait for reply."""
    result = send_escalation(assessment, phone=phone)
    if result.decision == "error":
        return result
    return wait_for_reply(result, phone=phone, timeout_mins=timeout_mins)


def _send_imessage(phone: str, message: str) -> bool:
    """Send a message via iMessage using AppleScript. Returns True on success."""
    # Escape for AppleScript string
    escaped = (
        message
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
    )
    script = f'tell application "Messages" to send "{escaped}" to buddy "{phone}" of service "SMS"'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def _poll_for_reply(phone: str, after: datetime) -> Optional[str]:
    """Check chat.db for a reply from phone after the given timestamp.

    Returns the reply text or None if no reply yet.
    """
    import sqlite3
    import os

    chat_db_path = os.path.expanduser("~/Library/Messages/chat.db")
    if not os.path.exists(chat_db_path):
        return None

    after_ts = int(after.timestamp()) - 978307200  # Apple epoch offset

    try:
        conn = sqlite3.connect(f"file:{chat_db_path}?mode=ro", uri=True, timeout=5)
        try:
            cur = conn.cursor()
            # Find messages from this sender after the sent time
            cur.execute("""
                SELECT text FROM message
                JOIN handle ON message.handle_id = handle.ROWID
                WHERE handle.id LIKE ?
                  AND message.is_from_me = 0
                  AND message.date > ?
                ORDER BY message.date ASC
                LIMIT 1
            """, (f"%{phone.replace('+', '')}%", after_ts))
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    except Exception:
        return None

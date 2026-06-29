"""
Reads the VFS Global OTP email from Gmail via IMAP and extracts the code.

Uses the same Gmail account as the notification sender (GMAIL_SENDER + GMAIL_APP_PWD).
No new accounts or services needed.
"""

import imaplib
import email
import re
import time
import logging

log = logging.getLogger(__name__)

# Matches 4–8 digit codes (VFS typically sends 6 digits)
_OTP_RE = re.compile(r'\b(\d{4,8})\b')

# VFS sends OTP emails from one of these addresses
_VFS_SENDERS = [
    "noreply@vfsglobal.com",
    "donotreply@vfsglobal.com",
    "no-reply@vfsglobal.com",
    "notifications@vfsglobal.com",
    "vfsglobal",          # substring fallback
]

_MAX_WAIT_SECONDS = 60   # how long to wait for the OTP email to arrive
_POLL_INTERVAL    = 5    # check inbox every N seconds


def fetch_otp(gmail_user: str, gmail_app_pwd: str, max_wait: int = _MAX_WAIT_SECONDS) -> str | None:
    """
    Connect to Gmail via IMAP, wait up to `max_wait` seconds for a new OTP
    email from VFS, and return the numeric code as a string.

    Returns None if no OTP is found within the timeout.
    """
    log.info("Connecting to Gmail IMAP to fetch OTP …")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=20)
        mail.login(gmail_user, gmail_app_pwd)
    except Exception as exc:
        log.error("Gmail IMAP login failed: %s", exc)
        return None

    deadline = time.monotonic() + max_wait
    attempt = 0

    try:
        while time.monotonic() < deadline:
            attempt += 1
            log.info("OTP poll attempt %d (%.0fs remaining) …", attempt, deadline - time.monotonic())

            mail.select("INBOX")
            # Search for unseen emails from VFS — try each known sender
            msg_ids = _search_vfs_emails(mail)

            for msg_id in reversed(msg_ids):   # newest first
                code = _extract_otp_from_message(mail, msg_id)
                if code:
                    log.info("OTP extracted: %s", code)
                    # Mark as seen so we don't re-read it next cycle
                    mail.store(msg_id, '+FLAGS', '\\Seen')
                    return code

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sleep_for = min(_POLL_INTERVAL, remaining)
            log.info("OTP not found yet — waiting %ds …", sleep_for)
            time.sleep(sleep_for)

    finally:
        try:
            mail.logout()
        except Exception:
            pass

    log.warning("OTP not received within %ds.", max_wait)
    return None


def _search_vfs_emails(mail: imaplib.IMAP4_SSL) -> list[bytes]:
    """Return a list of message IDs that look like they're from VFS."""
    all_ids: list[bytes] = []

    for sender in _VFS_SENDERS:
        try:
            status, data = mail.search(None, f'(UNSEEN FROM "{sender}")')
            if status == "OK" and data and data[0]:
                ids = data[0].split()
                all_ids.extend(ids)
        except Exception as exc:
            log.debug("IMAP search for '%s' failed: %s", sender, exc)

    # Deduplicate while preserving order
    seen = set()
    unique: list[bytes] = []
    for i in all_ids:
        if i not in seen:
            seen.add(i)
            unique.append(i)

    return unique


def _extract_otp_from_message(mail: imaplib.IMAP4_SSL, msg_id: bytes) -> str | None:
    """Fetch a single message and extract the first OTP-like number from its body."""
    try:
        status, data = mail.fetch(msg_id, "(RFC822)")
        if status != "OK" or not data:
            return None

        raw = data[0][1]
        msg = email.message_from_bytes(raw)

        # Collect all text parts
        body_parts: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype in ("text/plain", "text/html"):
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        body_parts.append(part.get_payload(decode=True).decode(charset, errors="replace"))
                    except Exception:
                        pass
        else:
            charset = msg.get_content_charset() or "utf-8"
            try:
                body_parts.append(msg.get_payload(decode=True).decode(charset, errors="replace"))
            except Exception:
                pass

        full_text = "\n".join(body_parts)
        log.debug("OTP email body snippet: %s", full_text[:300].replace("\n", " "))

        # Look for the OTP — prioritise lines that mention "otp", "code", "verify"
        priority_lines: list[str] = []
        other_lines:    list[str] = []
        for line in full_text.splitlines():
            lower = line.lower()
            if any(k in lower for k in ("otp", "code", "verif", "pin", "one-time", "one time")):
                priority_lines.append(line)
            else:
                other_lines.append(line)

        for line in priority_lines + other_lines:
            m = _OTP_RE.search(line)
            if m:
                return m.group(1)

    except Exception as exc:
        log.error("Error reading OTP email: %s", exc)

    return None

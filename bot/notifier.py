"""
Email notification via Gmail SMTP (App Password — no cost).

Required environment variables:
  GMAIL_SENDER   – your Gmail address (e.g. yourname@gmail.com)
  GMAIL_APP_PWD  – 16-char App Password from Google Account > Security
  NOTIFY_EMAIL   – destination address (can be same as GMAIL_SENDER)
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger(__name__)

GMAIL_SENDER  = os.environ["GMAIL_SENDER"]
GMAIL_APP_PWD = os.environ["GMAIL_APP_PWD"]
NOTIFY_EMAIL  = os.environ["NOTIFY_EMAIL"]

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_email_notification(subject: str, body: str) -> None:
    """Send a plain-text email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_SENDER
    msg["To"]      = NOTIFY_EMAIL

    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(GMAIL_SENDER, GMAIL_APP_PWD)
            server.sendmail(GMAIL_SENDER, NOTIFY_EMAIL, msg.as_string())
        log.info("Notification email sent to %s", NOTIFY_EMAIL)
    except smtplib.SMTPAuthenticationError:
        log.error(
            "Gmail authentication failed. "
            "Make sure you are using an App Password, not your regular Gmail password. "
            "See README for instructions."
        )
    except Exception as exc:
        log.error("Failed to send notification email: %s", exc)

"""Outgoing e-mail (verification and password reset).

With SMTP_HOST empty (development) the message is written to the server log
instead of being sent, so the links can be copied from the console. Tokens are
never returned in API responses.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger("app.email")
sent_messages: list[dict] = []          # captured in the test environment only


def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if settings.APP_ENV == "test":
        sent_messages.append({"to": to, "subject": subject, "body": body})
        return
    if not settings.SMTP_HOST:
        logger.info("E-mail (not sent - SMTP_HOST is empty)\nTo: %s\nSubject: %s\n\n%s", to, subject, body)
        return
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = settings.SMTP_FROM, to, subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError):
        logger.exception("Could not send e-mail to %s", to)


def send_verification(to: str, token: str) -> None:
    link = f"{get_settings().FRONTEND_URL}/verify-email?token={token}"
    send_email(to, "Verify your e-mail address", f"Welcome to the Academic Research Data Analysis Platform.\n\nVerify your e-mail address:\n{link}\n")


def send_password_reset(to: str, token: str) -> None:
    settings = get_settings()
    link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    send_email(to, "Reset your password", f"A password reset was requested for this account.\n\nChoose a new password:\n{link}\n\n"
                                          f"The link is valid for {settings.PASSWORD_RESET_MINUTES} minutes. If you did not request it, ignore this message.")

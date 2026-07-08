from __future__ import annotations

import base64
import mimetypes
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from .template import html_to_text


def attachment_part(path: Path) -> MIMEBase:
    mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    maintype, subtype = mime_type.split("/", 1)
    part = MIMEBase(maintype, subtype)
    part.set_payload(path.read_bytes())
    encoders.encode_base64(part)
    filename = path.name.removeprefix("attachment-")
    part.add_header("Content-Disposition", "attachment", filename=filename)
    return part


def build_message(
    sender_email: str,
    sender_name: str,
    to_email: str,
    subject: str,
    html_body: str,
    attachment_paths: list[Path] | None = None,
) -> dict[str, str]:
    attachments = attachment_paths or []
    message = MIMEMultipart("mixed") if attachments else MIMEMultipart("alternative")
    message["To"] = to_email
    message["From"] = formataddr((sender_name, sender_email)) if sender_name else sender_email
    message["Subject"] = subject
    body = MIMEMultipart("alternative") if attachments else message
    text_body = html_to_text(html_body)
    body.attach(MIMEText(text_body, "plain", "utf-8"))
    body.attach(MIMEText(html_body, "html", "utf-8"))
    if attachments:
        message.attach(body)
        for path in attachments:
            message.attach(attachment_part(path))
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": encoded}


def sender_email(gmail_service) -> str:
    profile = gmail_service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def send_message(gmail_service, message: dict[str, str]) -> dict:
    return gmail_service.users().messages().send(userId="me", body=message).execute()

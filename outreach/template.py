from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import quote


PLACEHOLDER_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")
HREF_RE = re.compile(r'href=(["\'])(.*?)\1', re.IGNORECASE)
TEMPLATE_META_RE = re.compile(r"^\s*<!--\s*outreach-template-meta:\s*(\{.*?\})\s*-->\s*", re.DOTALL)


def render_string(template: str, values: dict[str, str], escape_values: bool = True) -> str:
    normalized = {str(key).strip().lower(): "" if value is None else str(value) for key, value in values.items()}

    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip().lower()
        value = normalized.get(key, "")
        return html.escape(value) if escape_values else value

    return PLACEHOLDER_RE.sub(replace, template)


def load_template(path: str) -> str:
    _, html_body = load_template_record(path)
    return html_body


def load_template_record(path: str | Path, default_subject: str = "") -> tuple[str, str]:
    raw = Path(path).read_text(encoding="utf-8")
    match = TEMPLATE_META_RE.match(raw)
    if not match:
        return default_subject, raw
    subject = default_subject
    try:
        metadata = json.loads(match.group(1))
        subject = str(metadata.get("subject") or default_subject)
    except json.JSONDecodeError:
        subject = default_subject
    return subject, raw[match.end() :]


def serialize_template(html_body: str, subject: str) -> str:
    metadata = json.dumps({"subject": subject}, ensure_ascii=False)
    return f"<!-- outreach-template-meta: {metadata} -->\n{html_body}"


def rewrite_links(html_body: str, tracking_id: str, tracking_base_url: str) -> str:
    if not tracking_base_url:
        return html_body
    base = tracking_base_url.rstrip("/")

    def replace(match: re.Match[str]) -> str:
        quote_char = match.group(1)
        destination = match.group(2)
        if destination.startswith(("mailto:", "tel:", "#")):
            return match.group(0)
        if destination.startswith(base):
            return match.group(0)
        tracked_url = f"{base}/click?id={quote(tracking_id)}&url={quote(destination, safe='')}"
        return f"href={quote_char}{tracked_url}{quote_char}"

    return HREF_RE.sub(replace, html_body)


def add_open_pixel(html_body: str, tracking_id: str, tracking_base_url: str) -> str:
    if not tracking_base_url:
        return html_body
    src = f"{tracking_base_url.rstrip('/')}/open?id={quote(tracking_id)}"
    pixel = f'<img src="{src}" width="1" height="1" alt="" style="display:none" />'
    if "</body>" in html_body.lower():
        return re.sub(r"</body>", pixel + "</body>", html_body, flags=re.IGNORECASE)
    return html_body + "\n" + pixel


def html_to_text(html_body: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", html_body)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def render_email_html(template_html: str, contact: dict[str, str], tracking_base_url: str) -> str:
    tracking_id = str(contact.get("tracking_id", ""))
    rendered = render_string(template_html, contact)
    rendered = rewrite_links(rendered, tracking_id, tracking_base_url)
    return add_open_pixel(rendered, tracking_id, tracking_base_url)

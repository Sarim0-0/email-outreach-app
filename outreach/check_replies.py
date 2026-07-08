from __future__ import annotations

import argparse

from .auth import gmail_service
from .config import load_config
from .sender import build_store


BOUNCE_MARKERS = (
    "mailer-daemon",
    "mail delivery subsystem",
    "delivery status notification",
    "undeliverable",
    "delivery incomplete",
)


def message_headers(message: dict) -> dict[str, str]:
    headers = message.get("payload", {}).get("headers", [])
    return {header.get("name", "").lower(): header.get("value", "") for header in headers}


def is_bounce_thread(messages: list[dict]) -> bool:
    for message in messages[1:]:
        headers = message_headers(message)
        haystack = " ".join([headers.get("from", ""), headers.get("subject", "")]).lower()
        if any(marker in haystack for marker in BOUNCE_MARKERS):
            return True
    return False


def check_replies(config_path: str, sheet: str | None = None) -> None:
    config = load_config(config_path, sheet_override=sheet)
    store = build_store(config)
    store.ensure_all()
    gmail = gmail_service()
    checked = 0
    updated = 0
    for contact in store.sent_contacts_for_reply_check():
        thread_id = contact.data.get("thread_id", "").strip()
        thread = gmail.users().threads().get(userId="me", id=thread_id, format="metadata").execute()
        messages = thread.get("messages", [])
        checked += 1
        if len(messages) <= 1:
            continue
        if is_bounce_thread(messages):
            store.update_contact(contact.row_number, {"status": "bounced"})
            updated += 1
            continue
        store.update_contact(contact.row_number, {"replied": "yes"})
        updated += 1
    print(f"Checked {checked} sent threads. Updated {updated} rows.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Best-effort Gmail reply and bounce detection.")
    parser.add_argument("--config", default="config.json", help="Path to safe config JSON.")
    parser.add_argument("--sheet", help="Full Google Sheet URL or raw spreadsheet id.")
    args = parser.parse_args()
    check_replies(args.config, sheet=args.sheet)


if __name__ == "__main__":
    main()

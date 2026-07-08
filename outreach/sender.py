from __future__ import annotations

import argparse
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .auth import gmail_service, sheets_service
from .config import Config, load_config
from .gmail_client import build_message, send_message, sender_email
from .sheets import SheetStore
from .template import load_template_record, render_email_html, render_string


ROOT = Path(__file__).resolve().parent.parent


def parse_time(value: str, timezone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def build_store(config: Config) -> SheetStore:
    return SheetStore(
        sheets_service(),
        config.spreadsheet_id,
        config.contacts_sheet_name,
        config.control_sheet_name,
        config.analytics_sheet_name,
        config.email_column,
    )


def resolve_attachment_paths(config: Config) -> list[Path]:
    if not config.attachment_path:
        return []
    attachment_path = Path(config.attachment_path)
    if not attachment_path.is_absolute():
        attachment_path = ROOT / attachment_path
    attachment_path = attachment_path.resolve()
    if not attachment_path.exists() or not attachment_path.is_file():
        raise FileNotFoundError(f"Configured attachment not found: {attachment_path}")
    return [attachment_path]


def choose_batch_template(config: Config, control: dict[str, str]) -> str:
    template_paths = list(dict.fromkeys(config.effective_template_paths))
    if not template_paths:
        return config.email_template_path
    last_template_path = control.get("last_template_path", "").strip()
    candidates = template_paths
    if len(template_paths) > 1 and last_template_path in template_paths:
        candidates = [path for path in template_paths if path != last_template_path]
    return random.choice(candidates)


def send_batch(config: Config, dry_run: bool = False) -> int:
    store = build_store(config)
    store.ensure_all()
    control = store.control_values()
    if control.get("paused", "no").strip().lower() == "yes":
        print("Campaign is paused in the Control sheet. No mail sent.")
        return 0

    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    next_eligible = parse_time(control.get("next_eligible_at", ""), tz)
    if next_eligible and now < next_eligible:
        print(f"Not eligible yet. Next send time is {next_eligible.isoformat()}.")
        return 0

    today = now.date().isoformat()
    daily_date = control.get("daily_date", "")
    daily_sent_count = int(control.get("daily_sent_count", "0") or "0")
    if daily_date != today:
        daily_sent_count = 0

    remaining_today = config.effective_daily_cap - daily_sent_count
    if remaining_today <= 0:
        print(f"Daily cap reached: {daily_sent_count}/{config.effective_daily_cap}.")
        return 0

    limit = min(config.effective_batch_size, remaining_today)
    contacts = store.pending_contacts(limit)
    if not contacts:
        print("No pending contacts found.")
        store.set_control_values({"daily_date": today, "daily_sent_count": daily_sent_count})
        return 0

    selected_template_path = choose_batch_template(config, control)
    template_subject, template_html = load_template_record(selected_template_path, config.email_subject)
    attachment_paths = resolve_attachment_paths(config)
    gmail = None if dry_run else gmail_service()
    from_email = "dry-run@example.com" if dry_run else sender_email(gmail)
    sent_count = 0

    for contact in contacts:
        tracking_id = contact.data.get("tracking_id") or str(uuid.uuid4())
        contact_data = {**contact.data, "tracking_id": tracking_id}
        subject = render_string(template_subject, contact_data, escape_values=False)
        html_body = render_email_html(template_html, contact_data, config.tracking_base_url)
        recipient_email = store.recipient_email(contact)

        if dry_run:
            attachment_note = f" attachment={attachment_paths[0].name!r}" if attachment_paths else ""
            print(
                f"[dry-run] Would send to {recipient_email} "
                f"template={Path(selected_template_path).name!r} subject={subject!r}{attachment_note}"
            )
            continue

        message = build_message(
            sender_email=from_email,
            sender_name=config.sender_name,
            to_email=recipient_email,
            subject=subject,
            html_body=html_body,
            attachment_paths=attachment_paths,
        )
        response = send_message(gmail, message)
        store.update_contact(
            contact.row_number,
            {
                "status": "sent",
                "sent_at": now.isoformat(timespec="seconds"),
                "thread_id": response.get("threadId", ""),
                "tracking_id": tracking_id,
                "opened": contact.data.get("opened") or "0",
                "clicked": contact.data.get("clicked") or "0",
                "replied": contact.data.get("replied") or "no",
            },
        )
        sent_count += 1
        print(f"Sent to {recipient_email}")

    if not dry_run and sent_count:
        min_delay, max_delay = config.effective_delay_range
        delay = random.randint(min_delay, max_delay)
        store.set_control_values(
            {
                "next_eligible_at": (now + timedelta(minutes=delay)).isoformat(timespec="seconds"),
                "daily_date": today,
                "daily_sent_count": daily_sent_count + sent_count,
                "last_template_path": selected_template_path,
            }
        )
        print(
            f"Sent {sent_count} with {Path(selected_template_path).name}. "
            f"Next eligible send in {delay} minutes."
        )
    elif dry_run:
        print("Dry run complete. The sheet was not marked as sent.")
    return sent_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Send one eligible outreach batch.")
    parser.add_argument("--config", default="config.json", help="Path to safe config JSON.")
    parser.add_argument("--sheet", help="Full Google Sheet URL or raw spreadsheet id.")
    parser.add_argument("--dry-run", action="store_true", help="Preview the next batch without sending.")
    args = parser.parse_args()
    config = load_config(args.config, sheet_override=args.sheet)
    send_batch(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

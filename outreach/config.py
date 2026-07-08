from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .env import load_env


load_env()


SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
RAW_SHEET_ID_RE = re.compile(r"^[a-zA-Z0-9-_]{20,}$")
SAFE_MAX_DAILY_CAP = 500
SAFE_MAX_BATCH_SIZE = 5


def extract_spreadsheet_id(value: str) -> str:
    """Accept either a full Google Sheets URL or a raw spreadsheet id."""
    value = value.strip()
    match = SHEET_ID_RE.search(value)
    if match:
        return match.group(1)
    if RAW_SHEET_ID_RE.match(value):
        return value
    raise ValueError(
        "Expected a Google Sheet URL like "
        "https://docs.google.com/spreadsheets/d/<id>/edit or a raw sheet id."
    )


@dataclass(frozen=True)
class Config:
    spreadsheet_id: str
    contacts_sheet_name: str = "auto"
    email_column: str = "email"
    control_sheet_name: str = "Control"
    analytics_sheet_name: str = "Analytics"
    sender_name: str = ""
    email_subject: str = "Quick note for {{company}}"
    email_template_path: str = "templates/email.html"
    campaign_template_paths: tuple[str, ...] = ()
    attachment_path: str = ""
    tracking_base_url: str = ""
    timezone: str = "Asia/Karachi"
    batch_size: int = 5
    daily_send_cap: int = 500
    min_delay_minutes: int = 10
    max_delay_minutes: int = 15

    @property
    def effective_daily_cap(self) -> int:
        return min(int(self.daily_send_cap), SAFE_MAX_DAILY_CAP)

    @property
    def effective_batch_size(self) -> int:
        return max(1, min(int(self.batch_size), SAFE_MAX_BATCH_SIZE))

    @property
    def effective_delay_range(self) -> tuple[int, int]:
        minimum = max(1, int(self.min_delay_minutes))
        maximum = max(minimum, int(self.max_delay_minutes))
        return minimum, maximum

    @property
    def effective_template_paths(self) -> tuple[str, ...]:
        paths = tuple(path for path in self.campaign_template_paths if path)
        return paths or (self.email_template_path,)


def _load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def _pick(data: dict[str, Any], key: str, env_key: str | None = None, default: Any = None) -> Any:
    env_name = env_key or key.upper()
    if key in data and data[key] != "":
        return data[key]
    if env_name in os.environ and os.environ[env_name] != "":
        return os.environ[env_name]
    return default


def _pick_list(data: dict[str, Any], key: str, env_key: str | None = None) -> list[str]:
    value = _pick(data, key, env_key, [])
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in re.split(r"[\n,]+", text) if part.strip()]


def load_config(path: str | None = None, sheet_override: str | None = None) -> Config:
    data = _load_json(path)
    sheet_value = (
        sheet_override
        or data.get("sheet_url")
        or data.get("sheet_id")
        or os.environ.get("SHEET_URL")
        or os.environ.get("SHEET_ID")
    )
    if not sheet_value:
        raise ValueError("Provide sheet_url/sheet_id in config or SHEET_URL/SHEET_ID in env.")

    return Config(
        spreadsheet_id=extract_spreadsheet_id(str(sheet_value)),
        contacts_sheet_name=str(_pick(data, "contacts_sheet_name", default="auto")),
        email_column=str(_pick(data, "email_column", "EMAIL_COLUMN", "email")),
        control_sheet_name=str(_pick(data, "control_sheet_name", default="Control")),
        analytics_sheet_name=str(_pick(data, "analytics_sheet_name", default="Analytics")),
        sender_name=str(_pick(data, "sender_name", default="")),
        email_subject=str(_pick(data, "email_subject", default="Quick note for {{company}}")),
        email_template_path=str(_pick(data, "email_template_path", default="templates/email.html")),
        campaign_template_paths=tuple(_pick_list(data, "campaign_template_paths", "CAMPAIGN_TEMPLATE_PATHS")),
        attachment_path=str(_pick(data, "attachment_path", "ATTACHMENT_PATH", "")),
        tracking_base_url=str(_pick(data, "tracking_base_url", "TRACKING_BASE_URL", "")),
        timezone=str(_pick(data, "timezone", default="Asia/Karachi")),
        batch_size=int(_pick(data, "batch_size", default=5)),
        daily_send_cap=int(_pick(data, "daily_send_cap", default=500)),
        min_delay_minutes=int(_pick(data, "min_delay_minutes", default=10)),
        max_delay_minutes=int(_pick(data, "max_delay_minutes", default=15)),
    )

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import load_config
from .env import load_env
from .sender import build_store
from .sheets import EMAIL_COLUMN_CANDIDATES, REQUIRED_CONTACT_HEADERS
from .template import load_template_record, render_email_html, render_string, serialize_template


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "frontend"
CONFIG_PATH = ROOT / "config.json"
CONFIG_EXAMPLE_PATH = ROOT / "config.example.json"
TEMPLATES_DIR = ROOT / "templates"
ATTACHMENTS_DIR = ROOT / "templates"
FALLBACK_ATTACHMENTS_DIR = Path.home() / "Documents" / "Codex" / "email-outreach-attachments"
LOCAL_STATE_DIR = Path.home() / "Documents" / "Codex" / "email-outreach-state"
LOCAL_CONFIG_PATH = LOCAL_STATE_DIR / "config.json"
ATTACHMENT_PREFIX = "attachment-"
TEMPLATE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_. -]{0,80}\.html$")
SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9_. -]+")
NUMERIC_CONFIG_FIELDS = {"batch_size", "daily_send_cap", "min_delay_minutes", "max_delay_minutes"}
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


load_env()


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_env_values(path: Path = ROOT / ".env") -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        values[key] = value
    return values


def default_config() -> dict:
    config = read_json(CONFIG_EXAMPLE_PATH)
    if CONFIG_PATH.exists():
        config.update(read_json(CONFIG_PATH))
    if LOCAL_CONFIG_PATH.exists():
        config.update(read_json(LOCAL_CONFIG_PATH))
    return config


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_config(payload: dict) -> Path:
    try:
        write_json(CONFIG_PATH, payload)
        return CONFIG_PATH
    except OSError:
        LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
        write_json(LOCAL_CONFIG_PATH, payload)
        return LOCAL_CONFIG_PATH


def safe_template_path(name: str) -> Path:
    name = unquote(name).strip()
    if not name.endswith(".html"):
        name += ".html"
    if not TEMPLATE_NAME_RE.match(name):
        raise ValueError("Template names may contain letters, numbers, spaces, dots, underscores, and dashes.")
    path = (TEMPLATES_DIR / name).resolve()
    if TEMPLATES_DIR.resolve() not in path.parents:
        raise ValueError("Invalid template path.")
    return path


def nonempty_rows(rows: list[list[str]]) -> list[list[str]]:
    return [row for row in rows if any(str(cell).strip() for cell in row)]


def cell_at(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index]).strip()


def find_header_index(headers: list[str], candidates: list[str]) -> int | None:
    normalized = [header.strip().lower() for header in headers]
    for candidate in candidates:
        if candidate and candidate.strip().lower() in normalized:
            return normalized.index(candidate.strip().lower())
    return None


def config_path_arg() -> str:
    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    write_json(LOCAL_CONFIG_PATH, default_config())
    return str(LOCAL_CONFIG_PATH)


def safe_attachment_name(name: str) -> str:
    cleaned = SAFE_FILENAME_RE.sub("_", Path(name).name).strip(" .")
    if not cleaned:
        raise ValueError("Attachment file must have a name.")
    if not cleaned.startswith(ATTACHMENT_PREFIX):
        cleaned = ATTACHMENT_PREFIX + cleaned
    return cleaned[:120]


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def write_attachment_file(filename: str, payload: bytes) -> Path:
    errors = []
    for directory in (ATTACHMENTS_DIR, FALLBACK_ATTACHMENTS_DIR):
        try:
            directory.mkdir(exist_ok=True)
            target = (directory / filename).resolve()
            if directory.resolve() not in target.parents:
                raise ValueError("Invalid attachment path.")
            target.write_bytes(payload)
            return target
        except OSError as error:
            errors.append(f"{directory}: {error}")
    raise OSError("; ".join(errors))


class FrontendHandler(BaseHTTPRequestHandler):
    server_version = "OutreachFrontend/1.0"

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self.send_json(default_config())
            return
        if parsed.path == "/api/credentials":
            self.send_json(self.credentials_status())
            return
        if parsed.path == "/api/attachment":
            self.get_attachment()
            return
        if parsed.path == "/api/sheet":
            self.get_sheet_state()
            return
        if parsed.path == "/api/templates":
            self.send_json(self.list_templates())
            return
        if parsed.path.startswith("/api/templates/"):
            self.get_template(parsed.path.removeprefix("/api/templates/"))
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self.save_config()
            return
        if parsed.path == "/api/attachment":
            self.save_attachment()
            return
        if parsed.path == "/api/attachment/remove":
            self.remove_attachment()
            return
        if parsed.path == "/api/setup-sheet":
            self.setup_sheet()
            return
        if parsed.path == "/api/send-batch":
            self.send_batch()
            return
        if parsed.path == "/api/check-replies":
            self.check_replies()
            return
        if parsed.path == "/api/preview":
            self.preview_template()
            return
        if parsed.path.startswith("/api/templates/"):
            self.save_template(parsed.path.removeprefix("/api/templates/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def request_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def request_bytes(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def send_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json_error(self, message: str, status: int = 400) -> None:
        self.send_json({"error": message}, status=status)

    def serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = target.read_bytes()
        mime_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def list_templates(self) -> list[str]:
        TEMPLATES_DIR.mkdir(exist_ok=True)
        templates = sorted(path.name for path in TEMPLATES_DIR.glob("*.html") if not path.name.startswith(ATTACHMENT_PREFIX))
        return templates

    def get_template(self, name: str) -> None:
        try:
            path = safe_template_path(name)
            if not path.exists():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            subject, html = load_template_record(path, str(default_config().get("email_subject") or ""))
            self.send_json({"name": path.name, "subject": subject, "html": html})
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)

    def save_template(self, name: str) -> None:
        try:
            path = safe_template_path(name)
            payload = self.request_json()
            html = str(payload.get("html", ""))
            subject = str(payload.get("subject", default_config().get("email_subject", "")))
            TEMPLATES_DIR.mkdir(exist_ok=True)
            path.write_text(serialize_template(html, subject), encoding="utf-8")
            self.send_json({"name": path.name, "subject": subject, "saved": True})
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)

    def save_config(self) -> None:
        payload = self.request_json()
        allowed = {
            "sheet_url",
            "sheet_id",
            "contacts_sheet_name",
            "email_column",
            "control_sheet_name",
            "analytics_sheet_name",
            "sender_name",
            "email_subject",
            "email_template_path",
            "campaign_template_paths",
            "attachment_path",
            "tracking_base_url",
            "timezone",
            "batch_size",
            "daily_send_cap",
            "min_delay_minutes",
            "max_delay_minutes",
        }
        existing = default_config()
        for key, value in payload.items():
            if key not in allowed:
                continue
            if key in NUMERIC_CONFIG_FIELDS:
                try:
                    existing[key] = int(value)
                except (TypeError, ValueError):
                    continue
            else:
                existing[key] = value
        write_config(existing)
        self.send_json({"saved": True, "config": existing})

    def attachment_payload(self) -> tuple[str, bytes]:
        content_type = self.headers.get("Content-Type", "")
        body = self.request_bytes()
        if len(body) > MAX_ATTACHMENT_BYTES + 1024 * 1024:
            raise ValueError("Attachment is too large. Keep it at 20 MB or smaller.")
        parser_body = (
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )
        message = BytesParser(policy=policy.default).parsebytes(parser_body)
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            if part.get_param("name", header="content-disposition") != "attachment":
                continue
            filename = safe_attachment_name(part.get_filename() or "")
            payload = part.get_payload(decode=True) or b""
            if not payload:
                raise ValueError("Attachment file is empty.")
            if len(payload) > MAX_ATTACHMENT_BYTES:
                raise ValueError("Attachment is too large. Keep it at 20 MB or smaller.")
            return filename, payload
        raise ValueError("Upload must include a file field named attachment.")

    def attachment_info(self, config: dict | None = None) -> dict:
        config = config or default_config()
        value = str(config.get("attachment_path") or "")
        if not value:
            return {"path": "", "name": "", "exists": False, "size": 0}
        path = Path(value)
        if not path.is_absolute():
            path = ROOT / path
        exists = path.exists() and path.is_file()
        return {
            "path": value,
            "name": path.name,
            "exists": exists,
            "size": path.stat().st_size if exists else 0,
        }

    def get_attachment(self) -> None:
        self.send_json(self.attachment_info())

    def save_attachment(self) -> None:
        try:
            filename, payload = self.attachment_payload()
            target = write_attachment_file(filename, payload)
            config = default_config()
            config["attachment_path"] = relative_to_root(target)
            write_config(config)
            self.send_json({"saved": True, "attachment": self.attachment_info(config), "config": config})
        except ValueError as error:
            self.send_json_error(str(error), status=400)
        except Exception as error:
            self.send_json_error(f"Attachment upload failed: {error}", status=500)

    def remove_attachment(self) -> None:
        config = default_config()
        config["attachment_path"] = ""
        write_config(config)
        self.send_json({"saved": True, "attachment": self.attachment_info(config), "config": config})

    def credentials_status(self) -> dict:
        load_env()
        env_values = read_env_values()

        def env_value(key: str) -> str:
            return os.environ.get(key, "") or env_values.get(key, "")

        def configured_path_exists(value: str) -> bool:
            if not value:
                return False
            path = Path(value)
            if not path.is_absolute():
                path = ROOT / path
            return path.exists()

        service_account_path = env_value("GOOGLE_APPLICATION_CREDENTIALS")
        gmail_client_id = env_value("GMAIL_CLIENT_ID")
        gmail_client_secret = env_value("GMAIL_CLIENT_SECRET")
        gmail_refresh_token = env_value("GMAIL_REFRESH_TOKEN")
        return {
            "service_account_json": bool(env_value("GOOGLE_SERVICE_ACCOUNT_JSON")),
            "service_account_path": service_account_path,
            "service_account_path_exists": configured_path_exists(service_account_path),
            "gmail_client_id": bool(gmail_client_id),
            "gmail_client_secret": bool(gmail_client_secret),
            "gmail_refresh_token": bool(gmail_refresh_token),
        }

    def get_sheet_state(self) -> None:
        try:
            config = load_config(config_path_arg())
            store = build_store(config)
            titles = store.sheet_titles()
            contacts_sheet = store.resolve_contacts_sheet_name()
            store.contacts_sheet = contacts_sheet
            rows = store.values_get(store.range_name(contacts_sheet, "A:ZZ"))
            headers = [cell.strip() for cell in rows[0]] if rows else []
            data_rows = nonempty_rows(rows[1:] if len(rows) > 1 else [])
            email_index = find_header_index(headers, [config.email_column, *EMAIL_COLUMN_CANDIDATES])
            status_index = find_header_index(headers, ["status"])
            replied_index = find_header_index(headers, ["replied"])
            setup_columns_present = all(
                required in [header.strip().lower() for header in headers] for required in REQUIRED_CONTACT_HEADERS
            )

            counts = {"total_rows": len(data_rows), "pending": 0, "sent": 0, "bounced": 0, "replied": 0}
            for row in data_rows:
                status = cell_at(row, status_index).lower()
                replied = cell_at(row, replied_index).lower()
                email_value = cell_at(row, email_index)
                if status == "sent":
                    counts["sent"] += 1
                if status == "bounced":
                    counts["bounced"] += 1
                if replied == "yes":
                    counts["replied"] += 1
                if email_value and status in ("", "pending") and replied != "yes":
                    counts["pending"] += 1

            control = store.control_values() if config.control_sheet_name in titles else {}
            self.send_json(
                {
                    "spreadsheet_id": config.spreadsheet_id,
                    "sheet_titles": titles,
                    "contacts_sheet_name": contacts_sheet,
                    "headers": headers,
                    "email_column": headers[email_index] if email_index is not None and email_index < len(headers) else "",
                    "configured_email_column": config.email_column,
                    "setup_columns_present": setup_columns_present,
                    "counts": counts,
                    "control": control,
                    "effective_batch_size": config.effective_batch_size,
                    "effective_daily_cap": config.effective_daily_cap,
                    "effective_delay_range": list(config.effective_delay_range),
                }
            )
        except Exception as error:
            self.send_json_error(str(error), status=400)

    def preview_template(self) -> None:
        try:
            payload = self.request_json()
            config = load_config(config_path_arg())
            store = build_store(config)
            store.contacts_sheet = store.resolve_contacts_sheet_name()
            rows = store.values_get(store.range_name(store.contacts_sheet, "A:ZZ"))
            headers = [cell.strip() for cell in rows[0]] if rows else []
            sample_row = next(iter(nonempty_rows(rows[1:] if len(rows) > 1 else [])), [])
            values = {}
            for index, header in enumerate(headers):
                if not header:
                    continue
                values[header] = cell_at(sample_row, index)
            values["tracking_id"] = "preview"
            subject_template = str(payload.get("subject") or config.email_subject)
            html_template = str(payload.get("html") or "")
            subject = render_string(subject_template, values, escape_values=False)
            html = render_email_html(html_template, values, "")
            self.send_json(
                {
                    "subject": subject,
                    "html": html,
                    "row_number": 2 if sample_row else None,
                    "contacts_sheet_name": store.contacts_sheet,
                }
            )
        except Exception as error:
            self.send_json_error(str(error), status=400)

    def run_module(self, module: str, extra_args: list[str] | None = None, timeout: int = 180) -> None:
        args = [sys.executable, "-m", module, "--config", config_path_arg()]
        if extra_args:
            args.extend(extra_args)
        try:
            process = subprocess.run(
                args,
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            status = 200 if process.returncode == 0 else 500
            self.send_json(
                {
                    "ok": process.returncode == 0,
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                    "returncode": process.returncode,
                },
                status=status,
            )
        except subprocess.TimeoutExpired as error:
            self.send_json_error(f"Command timed out after {error.timeout} seconds.", status=504)

    def setup_sheet(self) -> None:
        self.run_module("outreach.setup_sheet", timeout=90)

    def send_batch(self) -> None:
        payload = self.request_json()
        extra_args = ["--dry-run"] if payload.get("dry_run") else []
        self.run_module("outreach.sender", extra_args=extra_args, timeout=240)

    def check_replies(self) -> None:
        self.run_module("outreach.check_replies", timeout=240)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local outreach frontend.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), FrontendHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Frontend running at {url}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()

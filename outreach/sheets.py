from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


REQUIRED_CONTACT_HEADERS = [
    "status",
    "sent_at",
    "opened",
    "first_opened_at",
    "last_opened_at",
    "clicked",
    "replied",
    "thread_id",
    "tracking_id",
]

AUTO_CONTACTS_SHEET_NAMES = {"", "auto", "__first__"}
EMAIL_COLUMN_CANDIDATES = ("email", "email address", "e-mail", "mail", "work email")

CONTROL_DEFAULTS = {
    "paused": "no",
    "next_eligible_at": "",
    "daily_date": "",
    "daily_sent_count": "0",
    "last_template_path": "",
}


def col_letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def quote_sheet_name(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


@dataclass
class Contact:
    row_number: int
    data: dict[str, str]


class SheetStore:
    def __init__(
        self,
        service,
        spreadsheet_id: str,
        contacts_sheet: str,
        control_sheet: str,
        analytics_sheet: str,
        email_column: str = "email",
    ):
        self.service = service
        self.spreadsheet_id = spreadsheet_id
        self.contacts_sheet = contacts_sheet
        self.control_sheet = control_sheet
        self.analytics_sheet = analytics_sheet
        self.email_column = email_column.strip().lower()

    def ensure_all(self) -> None:
        self.contacts_sheet = self.resolve_contacts_sheet_name()
        self.ensure_sheet(self.contacts_sheet)
        self.ensure_sheet(self.control_sheet)
        self.ensure_sheet(self.analytics_sheet)
        self.ensure_contact_headers()
        self.ensure_control_defaults()
        self.ensure_analytics()

    def spreadsheet(self) -> dict[str, Any]:
        return self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()

    def sheet_titles(self) -> list[str]:
        return [sheet["properties"]["title"] for sheet in self.spreadsheet().get("sheets", [])]

    def resolve_contacts_sheet_name(self) -> str:
        configured = self.contacts_sheet.strip()
        if configured.lower() not in AUTO_CONTACTS_SHEET_NAMES:
            return configured
        reserved = {self.control_sheet.strip().lower(), self.analytics_sheet.strip().lower()}
        for title in self.sheet_titles():
            if title.strip().lower() not in reserved:
                return title
        return "Contacts"

    def ensure_sheet(self, title: str) -> None:
        if title in self.sheet_titles():
            return
        body = {"requests": [{"addSheet": {"properties": {"title": title}}}]}
        self.service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheet_id, body=body).execute()

    def values_get(self, range_name: str) -> list[list[str]]:
        response = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
        ).execute()
        return response.get("values", [])

    def range_name(self, sheet_title: str, a1_range: str) -> str:
        return f"{quote_sheet_name(sheet_title)}!{a1_range}"

    def values_update(self, range_name: str, values: list[list[Any]]) -> None:
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()

    def values_batch_update(self, updates: list[dict[str, Any]]) -> None:
        if not updates:
            return
        self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": updates},
        ).execute()

    def ensure_contact_headers(self) -> list[str]:
        rows = self.values_get(self.range_name(self.contacts_sheet, "1:1"))
        headers = [cell.strip() for cell in rows[0]] if rows else []
        lower_headers = [header.lower() for header in headers]
        if not headers:
            first_email_header = self.email_column if self.email_column else "email"
            headers = [first_email_header, "name", "company", *REQUIRED_CONTACT_HEADERS]
        else:
            for required in REQUIRED_CONTACT_HEADERS:
                if required not in lower_headers:
                    headers.append(required)
                    lower_headers.append(required)
        end = col_letter(len(headers))
        self.values_update(self.range_name(self.contacts_sheet, f"A1:{end}1"), [headers])
        return headers

    def headers(self) -> list[str]:
        return [cell.strip().lower() for cell in self.values_get(self.range_name(self.contacts_sheet, "1:1"))[0]]

    def original_headers(self) -> list[str]:
        return [cell.strip() for cell in self.values_get(self.range_name(self.contacts_sheet, "1:1"))[0]]

    def email_header(self) -> str:
        headers = self.headers()
        candidates = [self.email_column, *EMAIL_COLUMN_CANDIDATES]
        for candidate in candidates:
            if candidate and candidate.strip().lower() in headers:
                return candidate.strip().lower()
        raise ValueError(
            "Could not find the recipient email column. Set email_column in config.json "
            "or EMAIL_COLUMN in GitHub variables to match your sheet header exactly."
        )

    def email_header_label(self) -> str:
        target = self.email_header()
        for header in self.original_headers():
            if header.strip().lower() == target:
                return header.strip()
        return target

    def read_contacts(self) -> list[Contact]:
        values = self.values_get(self.range_name(self.contacts_sheet, "A:ZZ"))
        if not values:
            return []
        headers = [header.strip().lower() for header in values[0]]
        contacts: list[Contact] = []
        for offset, row in enumerate(values[1:], start=2):
            padded = row + [""] * (len(headers) - len(row))
            data = {headers[index]: padded[index] for index in range(len(headers))}
            contacts.append(Contact(row_number=offset, data=data))
        return contacts

    def pending_contacts(self, limit: int) -> list[Contact]:
        email_header = self.email_header()
        pending: list[Contact] = []
        for contact in self.read_contacts():
            status = contact.data.get("status", "").strip().lower()
            replied = contact.data.get("replied", "").strip().lower()
            email = contact.data.get(email_header, "").strip()
            if email and status in ("", "pending") and replied != "yes":
                pending.append(contact)
            if len(pending) >= limit:
                break
        return pending

    def sent_contacts_for_reply_check(self) -> list[Contact]:
        return [
            contact
            for contact in self.read_contacts()
            if contact.data.get("status", "").strip().lower() == "sent"
            and contact.data.get("thread_id", "").strip()
            and contact.data.get("replied", "").strip().lower() != "yes"
        ]

    def recipient_email(self, contact: Contact) -> str:
        return contact.data.get(self.email_header(), "").strip()

    def update_contact(self, row_number: int, fields: dict[str, Any]) -> None:
        headers = self.headers()
        updates = []
        for key, value in fields.items():
            normalized = key.strip().lower()
            if normalized not in headers:
                raise KeyError(f"Missing header: {key}")
            col = col_letter(headers.index(normalized) + 1)
            updates.append({"range": self.range_name(self.contacts_sheet, f"{col}{row_number}"), "values": [[value]]})
        self.values_batch_update(updates)

    def control_values(self) -> dict[str, str]:
        rows = self.values_get(self.range_name(self.control_sheet, "A:B"))
        result: dict[str, str] = {}
        for row in rows:
            if not row:
                continue
            key = str(row[0]).strip()
            value = str(row[1]).strip() if len(row) > 1 else ""
            if key:
                result[key] = value
        return result

    def ensure_control_defaults(self) -> None:
        current = self.control_values()
        rows = [["key", "value"]]
        merged = {**CONTROL_DEFAULTS, **{key: value for key, value in current.items() if key != "key"}}
        for key, value in merged.items():
            rows.append([key, value])
        self.values_update(self.range_name(self.control_sheet, f"A1:B{len(rows)}"), rows)

    def set_control_values(self, values: dict[str, Any]) -> None:
        current = self.control_values()
        merged = {**current, **{key: str(value) for key, value in values.items()}}
        rows = [["key", "value"]]
        for key, value in merged.items():
            if key == "key":
                continue
            rows.append([key, value])
        self.values_update(self.range_name(self.control_sheet, f"A1:B{len(rows)}"), rows)

    def ensure_analytics(self) -> None:
        c = quote_sheet_name(self.contacts_sheet)
        status_col = f'INDEX({c}!A:ZZ,0,MATCH("status",{c}!1:1,0))'
        email_header_label = self.email_header_label().replace('"', '""')
        email_col = f'INDEX({c}!A:ZZ,0,MATCH("{email_header_label}",{c}!1:1,0))'
        opened_col = f'INDEX({c}!A:ZZ,0,MATCH("opened",{c}!1:1,0))'
        clicked_col = f'INDEX({c}!A:ZZ,0,MATCH("clicked",{c}!1:1,0))'
        replied_col = f'INDEX({c}!A:ZZ,0,MATCH("replied",{c}!1:1,0))'
        formulas = [
            ["Metric", "Value"],
            ["Sent count", f'=COUNTIF({status_col},"sent")'],
            ["Open count", f'=SUM({opened_col})'],
            ["Open rate", '=IF(B2=0,0,B3/B2)'],
            ["Click count", f'=SUM({clicked_col})'],
            ["Click rate", '=IF(B2=0,0,B5/B2)'],
            ["Bounce count", f'=COUNTIF({status_col},"bounced")'],
            ["Reply count", f'=COUNTIF({replied_col},"yes")'],
            ["Pending count", f'=COUNTIFS({email_col},"<>",{status_col},"")+COUNTIF({status_col},"pending")'],
            ["Last refreshed", datetime.utcnow().isoformat(timespec="seconds") + "Z"],
        ]
        self.values_update(self.range_name(self.analytics_sheet, f"A1:B{len(formulas)}"), formulas)

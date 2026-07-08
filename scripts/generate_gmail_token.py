from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow

from outreach.auth import GMAIL_SCOPES


def update_env_file(env_path: Path, values: dict[str, str]) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    seen = set()
    updated = []
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            updated.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in values:
            updated.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            updated.append(line)
    for key, value in values.items():
        if key not in seen:
            updated.append(f"{key}={value}")
    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Gmail OAuth refresh token for GitHub Actions.")
    parser.add_argument("client_secret_file", help="Downloaded OAuth desktop client JSON from Google Cloud.")
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Update the local .env file with the Gmail OAuth values after consent.",
    )
    parser.add_argument("--env-file", default=".env", help="Path to the local .env file when using --write-env.")
    args = parser.parse_args()
    flow = InstalledAppFlow.from_client_secrets_file(args.client_secret_file, GMAIL_SCOPES)
    credentials = flow.run_local_server(port=0, prompt="consent")
    values = {
        "GMAIL_CLIENT_ID": credentials.client_id,
        "GMAIL_CLIENT_SECRET": credentials.client_secret,
        "GMAIL_REFRESH_TOKEN": credentials.refresh_token,
    }
    if args.write_env:
        update_env_file(Path(args.env_file), values)
        print(f"\nUpdated {args.env_file} with Gmail OAuth values.")
        print("Add the same three values to GitHub Actions secrets before scheduled sending.")
        return
    print("\nAdd these values to GitHub Actions secrets:\n")
    for key, value in values.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()

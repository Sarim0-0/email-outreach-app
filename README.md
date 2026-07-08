# Personal Email Outreach Tool

This is a personal-scale email outreach system that uses:

- Google Sheets as the contact list, state store, and analytics view.
- Gmail API to send from your existing personal Gmail account.
- GitHub Actions to run while your laptop is off.
- Optional Cloudflare Workers tracking can be added later.

It accepts either a raw Google Sheet ID or a full Google Sheet link.

It also includes a local frontend for editing safe settings and saved email templates.

## What Is Secret

Never commit these:

- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`
- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `GOOGLE_CLIENT_EMAIL`
- `GOOGLE_PRIVATE_KEY`
- OAuth client JSON files
- service account JSON files

Safe config values can be stored in `config.json` or GitHub Actions variables:

- `SHEET_URL` or `SHEET_ID`
- sheet tab names, or `auto` for the first real tab
- recipient email column name
- email subject
- sender display name
- template path
- timezone
- batch size
- daily cap
- delay range

The code hard-stops the effective daily cap at 500 even if config is set higher.

## 1. Google Cloud Setup

1. Go to Google Cloud Console.
2. Create a project, for example `personal-email-outreach`.
3. Enable **Gmail API**.
4. Enable **Google Sheets API**.

## 2. Gmail OAuth Setup

1. Go to **APIs & Services > OAuth consent screen**.
2. Choose **External** for a personal Gmail account.
3. Fill in the app name, support email, and developer contact email.
4. Add yourself as a test user.
5. Go to **APIs & Services > Credentials**.
6. Create an **OAuth client ID**.
7. Choose **Desktop app**.
8. Download the OAuth JSON.

Install dependencies locally:

```bash
python -m pip install -r requirements.txt
```

Generate the refresh token:

```bash
python scripts/generate_gmail_token.py path/to/oauth-client.json
```

Or write the local Gmail OAuth values directly into `.env` after browser consent:

```bash
python scripts/generate_gmail_token.py path/to/oauth-client.json --write-env
```

Put the printed values into GitHub Actions secrets.

Note: Google testing-mode refresh tokens can expire. For indefinite scheduled sending, you may need to move the OAuth app to production. Because this is personal-use, you can still approve your own unverified app.

## 3. Service Account For Sheets

1. Go to **IAM & Admin > Service Accounts**.
2. Create `email-outreach-sheet-writer`.
3. Create a JSON key.
4. Open the JSON and copy `client_email`.
5. Share your Google Sheet with that email as **Editor**.

For local use, either set:

```bash
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
```

or set `GOOGLE_SERVICE_ACCOUNT_JSON` to the full JSON text.

You can also create a local `.env` file from `.env.example` and put the credential path there. The real `.env` file is ignored by git. Keep `.env` for local secrets only; use the frontend or `config.json` for Sheet links and campaign settings.

## 4. Configure The Sheet Link

The easiest way is to use the local frontend:

```bash
python scripts/frontend.py
```

Open:

```text
http://127.0.0.1:8765
```

Paste your full Google Sheet link, set the contacts tab to `auto`, set the email column name, write your email, and click **Save**.

Then click **Load Sheet** to read the real sheet tabs and columns. The email-column dropdown and placeholder buttons are generated from the sheet headers, so column order and header names can be anything. Click **Set Up Sheet** in the frontend to add the control/status/analytics columns.

You can also edit config by hand. Copy the example config:

```bash
cp config.example.json config.json
```

On Windows PowerShell:

```powershell
Copy-Item config.example.json config.json
```

Edit `config.json` and paste your full Google Sheet link:

```json
{
  "sheet_url": "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID_HERE/edit"
}
```

You can also skip `config.json` and use environment variables:

```bash
SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID_HERE/edit
```

The app can use any normal Google Sheet tab. By default:

- `contacts_sheet_name: "auto"` means "use the first sheet tab that is not `Control` or `Analytics`."
- `email_column: "email"` means "look for a column named `email`."

If your recipient column is called something else, set it in `config.json`:

```json
{
  "sheet_url": "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID_HERE/edit",
  "contacts_sheet_name": "auto",
  "email_column": "Email Address"
}
```

Column order does not matter.

For command-line local setup, copy `.env.example` to `.env` and set only your local credential path:

```text
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\your-real-service-account.json
```

The Sheet link belongs in the frontend/config, not in `.env`, unless you are intentionally overriding it for a one-off terminal run.

Run setup:

```bash
python scripts/setup_sheet.py --sheet "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID_HERE/edit"
```

This creates or updates:

- your contact tab, auto-detected unless configured
- `Control`
- `Analytics`
- required status columns

## 5. Add Contacts

In your contact tab, the only required contact data is a recipient email column.

Examples that work:

- `email`
- `Email Address`
- `Work Email`
- any other header, if you set `email_column` to that exact header

Your other columns can be anything, in any order:

- `First Name`
- `Company`
- `Website`
- `Role`
- `Custom Note`

The setup script adds these tracking columns if missing:

- `status`
- `sent_at`
- `opened`
- `first_opened_at`
- `last_opened_at`
- `clicked`
- `replied`
- `thread_id`
- `tracking_id`

Rows with blank `status` or `pending` are eligible to send.

## 6. Write The Template

Use the local frontend:

```bash
python scripts/frontend.py
```

Then open `http://127.0.0.1:8765`, write the email in the editor, set the template's email subject, name the template, and click **Save Template** or **Save**. Saved templates appear in the left sidebar and can be loaded again.

You can also edit `templates/email.html` directly.

Any contact column can be used as a placeholder:

```html
<p>Hi {{First Name}},</p>
<p>I noticed {{Company}} and wanted to reach out.</p>
```

Use the exact column header between `{{` and `}}`. So if your sheet has a column named `Custom Note`, you can use `{{Custom Note}}`.

The frontend also suggests sheet columns when you type `{{` or click inside an existing placeholder. Typed and pasted placeholders are still plain template text, so copy-pasted templates with `{{Column Name}}` work the same way as placeholders inserted from the UI.

## 6a. Optional Attachment

Use the local frontend attachment control to upload one file. The app first tries to save it under `templates/` with an `attachment-` storage prefix. If Windows blocks new files in the project folder, it falls back to `Documents/Codex/email-outreach-attachments`. The prefix is removed from the filename when the email is sent.

That file is attached to every email in a sent batch. For GitHub Actions scheduled sending, the attachment file must also exist in the GitHub workflow checkout, usually by committing the uploaded file in a private repo, and setting a repo-relative path:

```text
ATTACHMENT_PATH=templates/attachment-your-file.pdf
```

## 6b. Batch Template Rotation

Use **Batch Template Rotation** in the frontend to select one or more saved templates for the campaign.

Each sender run chooses one selected template for the whole batch, so the same 5-email batch uses the same subject and body. If more than one template is selected, the next batch excludes the template used by the previous batch. The last-used template is stored in the `Control` tab as `last_template_path`.

For GitHub Actions, set selected templates with a comma-separated variable:

```text
CAMPAIGN_TEMPLATE_PATHS=templates/email-a.html,templates/email-b.html,templates/email-c.html
```

Tracking is intentionally skipped for the current sending setup. Leave `tracking_base_url` blank.

## 7. Tracking Later

This is parked for now. When you want open/click tracking later, the Worker will handle:

- `/open?id=<tracking_id>`
- `/click?id=<tracking_id>&url=<destination>`

Deploy the Worker from this repo:

```bash
cd worker
npx wrangler login
```

```bash
npx wrangler deploy
```

Set Worker secrets:

```bash
npx wrangler secret put GOOGLE_CLIENT_EMAIL
npx wrangler secret put GOOGLE_PRIVATE_KEY
```

Use values from the service account JSON:

- `GOOGLE_CLIENT_EMAIL` = `client_email`
- `GOOGLE_PRIVATE_KEY` = `private_key`

Set Worker variables in `worker/wrangler.toml` or the Cloudflare dashboard:

- `SHEET_URL` or `SHEET_ID`
- `CONTACTS_SHEET_NAME`

Then put the deployed Worker URL into `tracking_base_url` in `config.json`. Do not set this while tracking is paused.

## 8. GitHub Actions

Add repository secrets:

- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`
- `GOOGLE_SERVICE_ACCOUNT_JSON`

Add repository variables:

- `SHEET_URL`
- `CONTACTS_SHEET_NAME`
- `EMAIL_COLUMN`
- `CONTROL_SHEET_NAME`
- `ANALYTICS_SHEET_NAME`
- `SENDER_NAME`
- `EMAIL_SUBJECT`
- `EMAIL_TEMPLATE_PATH`
- `CAMPAIGN_TEMPLATE_PATHS`
- `ATTACHMENT_PATH`
- `TIMEZONE`
- `BATCH_SIZE`
- `DAILY_SEND_CAP`
- `MIN_DELAY_MINUTES`
- `MAX_DELAY_MINUTES`

The sender workflow runs every 10 minutes, but the Sheet control tab stores the real next eligible time. Each successful batch sends the configured batch size and then schedules the next batch for a random delay.

The reply checker workflow is manual-only while tracking/reply automation is paused.

## 9. Pause Or Resume

Open the `Control` tab.

Set:

```text
paused = yes
```

to pause.

Set:

```text
paused = no
```

to resume.

## 10. Change Batch Size Or Daily Cap

Edit `config.json` or GitHub variables:

```json
{
  "batch_size": 5,
  "daily_send_cap": 500,
  "min_delay_minutes": 10,
  "max_delay_minutes": 15
}
```

Do not set the daily cap above 500 for a personal Gmail account. The code clamps it to 500 anyway.

## 11. Test Before Sending

Preview without sending:

```bash
python scripts/send_batch.py --dry-run
```

Send one real eligible batch:

```bash
python scripts/send_batch.py
```

Check replies manually:

```bash
python scripts/check_replies.py
```

## Limitations

- GitHub Actions scheduled runs are not exact. They can be delayed, so the Sheet's `next_eligible_at` is the source of truth.
- Gmail personal accounts have their own daily send limits. Manual emails you send can count against the same limit.
- Tracking is currently off. Open/click tracking can be added later.
- Reply detection is currently manual-only. It can be enabled later if needed.

const SHEET_ID_RE = /\/spreadsheets\/d\/([a-zA-Z0-9-_]+)/;
const RAW_SHEET_ID_RE = /^[a-zA-Z0-9-_]{20,}$/;
const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets";
const TRANSPARENT_GIF = Uint8Array.from([
  71, 73, 70, 56, 57, 97, 1, 0, 1, 0, 128, 0, 0, 0, 0, 0, 255, 255, 255,
  33, 249, 4, 1, 0, 0, 0, 0, 44, 0, 0, 0, 0, 1, 0, 1, 0, 0, 2, 2, 68,
  1, 0, 59,
]);

let cachedToken = null;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/open") {
      await logEvent(env, url.searchParams.get("id"), "open");
      return new Response(TRANSPARENT_GIF, {
        headers: {
          "Content-Type": "image/gif",
          "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        },
      });
    }

    if (url.pathname === "/click") {
      const destination = url.searchParams.get("url");
      if (!isSafeRedirect(destination)) {
        return new Response("Invalid redirect URL", { status: 400 });
      }
      await logEvent(env, url.searchParams.get("id"), "click");
      return Response.redirect(destination, 302);
    }

    return new Response("OK");
  },
};

function spreadsheetId(env) {
  const value = env.SHEET_URL || env.SHEET_ID || "";
  const match = value.match(SHEET_ID_RE);
  if (match) return match[1];
  if (RAW_SHEET_ID_RE.test(value)) return value;
  throw new Error("Set SHEET_URL or SHEET_ID in Worker variables.");
}

function isSafeRedirect(value) {
  if (!value) return false;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

async function logEvent(env, trackingId, eventType) {
  if (!trackingId) return;
  const sheetId = spreadsheetId(env);
  const sheetName = await contactsSheetName(env, sheetId);
  const token = await accessToken(env);
  const readUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${encodeURIComponent(a1Range(sheetName, "A:ZZ"))}`;
  const response = await fetch(readUrl, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`Sheet read failed: ${response.status}`);
  const payload = await response.json();
  const rows = payload.values || [];
  if (rows.length === 0) return;

  const headers = rows[0].map((header) => String(header).trim().toLowerCase());
  const trackingIndex = headers.indexOf("tracking_id");
  const countHeader = eventType === "open" ? "opened" : "clicked";
  const countIndex = headers.indexOf(countHeader);
  const firstOpenedIndex = headers.indexOf("first_opened_at");
  const lastOpenedIndex = headers.indexOf("last_opened_at");
  if (trackingIndex === -1 || countIndex === -1) return;

  const rowOffset = rows.findIndex((row, index) => index > 0 && row[trackingIndex] === trackingId);
  if (rowOffset === -1) return;

  const rowNumber = rowOffset + 1;
  const now = new Date().toISOString();
  const row = rows[rowOffset];
  const currentCount = Number.parseInt(row[countIndex] || "0", 10) || 0;
  const updates = [
    {
      range: a1Range(sheetName, `${colLetter(countIndex + 1)}${rowNumber}`),
      values: [[String(currentCount + 1)]],
    },
  ];

  if (eventType === "open") {
    if (firstOpenedIndex !== -1 && !row[firstOpenedIndex]) {
      updates.push({
        range: a1Range(sheetName, `${colLetter(firstOpenedIndex + 1)}${rowNumber}`),
        values: [[now]],
      });
    }
    if (lastOpenedIndex !== -1) {
      updates.push({
        range: a1Range(sheetName, `${colLetter(lastOpenedIndex + 1)}${rowNumber}`),
        values: [[now]],
      });
    }
  }

  const writeUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values:batchUpdate`;
  const writeResponse = await fetch(writeUrl, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ valueInputOption: "USER_ENTERED", data: updates }),
  });
  if (!writeResponse.ok) throw new Error(`Sheet write failed: ${writeResponse.status}`);
}

async function contactsSheetName(env, sheetId) {
  const configured = env.CONTACTS_SHEET_NAME || "auto";
  if (!["", "auto", "__first__"].includes(configured.trim().toLowerCase())) {
    return configured;
  }
  const token = await accessToken(env);
  const metadataUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}?fields=sheets.properties.title`;
  const response = await fetch(metadataUrl, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`Sheet metadata read failed: ${response.status}`);
  const payload = await response.json();
  const reserved = new Set([
    (env.CONTROL_SHEET_NAME || "Control").toLowerCase(),
    (env.ANALYTICS_SHEET_NAME || "Analytics").toLowerCase(),
  ]);
  for (const sheet of payload.sheets || []) {
    const title = sheet.properties?.title;
    if (title && !reserved.has(title.toLowerCase())) return title;
  }
  return "Contacts";
}

function a1Range(sheetName, range) {
  return `${quoteSheetName(sheetName)}!${range}`;
}

function quoteSheetName(sheetName) {
  return `'${sheetName.replace(/'/g, "''")}'`;
}

function colLetter(index) {
  let result = "";
  while (index > 0) {
    const remainder = (index - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    index = Math.floor((index - 1) / 26);
  }
  return result;
}

async function accessToken(env) {
  const now = Math.floor(Date.now() / 1000);
  if (cachedToken && cachedToken.expiresAt > now + 60) {
    return cachedToken.token;
  }

  const assertion = await signedJwt(env, now);
  const response = await fetch(GOOGLE_TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion,
    }),
  });
  if (!response.ok) throw new Error(`Google token request failed: ${response.status}`);
  const payload = await response.json();
  cachedToken = {
    token: payload.access_token,
    expiresAt: now + Number(payload.expires_in || 3600),
  };
  return cachedToken.token;
}

async function signedJwt(env, now) {
  const header = { alg: "RS256", typ: "JWT" };
  const claim = {
    iss: env.GOOGLE_CLIENT_EMAIL,
    scope: SHEETS_SCOPE,
    aud: GOOGLE_TOKEN_URL,
    exp: now + 3600,
    iat: now,
  };
  const unsigned = `${base64UrlJson(header)}.${base64UrlJson(claim)}`;
  const key = await importPrivateKey(env.GOOGLE_PRIVATE_KEY);
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    key,
    new TextEncoder().encode(unsigned),
  );
  return `${unsigned}.${base64Url(new Uint8Array(signature))}`;
}

async function importPrivateKey(pem) {
  const normalized = pem.replace(/\\n/g, "\n");
  const body = normalized
    .replace("-----BEGIN PRIVATE KEY-----", "")
    .replace("-----END PRIVATE KEY-----", "")
    .replace(/\s/g, "");
  const binary = Uint8Array.from(atob(body), (char) => char.charCodeAt(0));
  return crypto.subtle.importKey(
    "pkcs8",
    binary,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
}

function base64UrlJson(value) {
  return base64Url(new TextEncoder().encode(JSON.stringify(value)));
}

function base64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

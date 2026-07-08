const fields = [
  "sheet_url",
  "contacts_sheet_name",
  "email_column",
  "control_sheet_name",
  "analytics_sheet_name",
  "sender_name",
  "email_subject",
  "timezone",
  "batch_size",
  "daily_send_cap",
  "min_delay_minutes",
  "max_delay_minutes",
];

const numericFields = new Set(["batch_size", "daily_send_cap", "min_delay_minutes", "max_delay_minutes"]);
const templateList = document.querySelector("#templateList");
const campaignTemplates = document.querySelector("#campaignTemplates");
const templateName = document.querySelector("#templateName");
const editor = document.querySelector("#editor");
const statusBox = document.querySelector("#status");
const activityLog = document.querySelector("#activityLog");
const placeholderChips = document.querySelector("#placeholderChips");
const previewFrame = document.querySelector("#previewFrame");
const subjectInput = document.querySelector("#email_subject");
const attachmentFile = document.querySelector("#attachmentFile");
const autocomplete = document.querySelector("#autocomplete");

let currentConfig = {};
let currentTemplates = [];
let activeTemplate = "";
let activeEditable = editor;
let sheetState = null;
let autocompleteContext = null;
let autocompleteIndex = 0;

function byId(id) {
  return document.querySelector(`#${id}`);
}

function setStatus(message) {
  statusBox.textContent = message;
}

function setLog(text) {
  activityLog.textContent = text || "";
}

function normalizeTemplateName(name) {
  const withoutExtension = String(name || "email").trim().replace(/\.html$/i, "").trim();
  const cleaned = withoutExtension
    .replace(/[\\/]+/g, " ")
    .replace(/[^a-zA-Z0-9_. -]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return `${cleaned || "email"}.html`;
}

function templatePath(name) {
  return `templates/${normalizeTemplateName(templateNameFromPath(name))}`;
}

function templateNameFromPath(path) {
  return String(path || "").split(/[\\/]/).pop();
}

function displayTemplateName(name) {
  return templateNameFromPath(name).replace(/\.html$/i, "");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { error: text };
    }
  }
  if (!response.ok) {
    throw new Error(payload.error || payload.stderr || payload.stdout || `Request failed: ${response.status}`);
  }
  return payload;
}

async function formApi(path, formData) {
  const response = await fetch(path, { method: "POST", body: formData });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { error: text };
    }
  }
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function plainTextToHtml(text) {
  return text
    .replace(/\r\n/g, "\n")
    .split(/\n{2,}/)
    .map((paragraph) => `<p>${escapeHtml(paragraph).replace(/\n/g, "<br>")}</p>`)
    .join("");
}

function formatBytes(size) {
  if (!size) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function ensureOption(select, value, label = value) {
  if (!value) return;
  const exists = [...select.options].some((option) => option.value === value);
  if (exists) return;
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  select.append(option);
}

function fillSelect(select, values, selectedValue) {
  const previous = selectedValue || select.value;
  select.innerHTML = "";
  const seen = new Set();
  for (const value of values.filter(Boolean)) {
    if (seen.has(value)) continue;
    seen.add(value);
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
  ensureOption(select, previous);
  select.value = previous || select.options[0]?.value || "";
}

function setFieldValue(field, value) {
  const input = byId(field);
  if (!input) return;
  if (input.tagName === "SELECT") {
    ensureOption(input, String(value || ""));
  }
  input.value = value ?? "";
}

function collectConfig() {
  const payload = {};
  for (const field of fields) {
    const input = byId(field);
    if (!input) continue;
    payload[field] = numericFields.has(field) ? Number(input.value || currentConfig[field] || 0) : input.value.trim();
  }
  const activePath = templatePath(templateName.value);
  const selectedPaths = selectedCampaignTemplatePaths();
  payload.email_template_path = activePath;
  payload.campaign_template_paths = selectedPaths.length ? selectedPaths : [activePath];
  payload.tracking_base_url = "";
  return payload;
}

async function loadConfig() {
  currentConfig = await api("/api/config");
  fillSelect(byId("contacts_sheet_name"), ["auto", currentConfig.contacts_sheet_name || "auto"], currentConfig.contacts_sheet_name || "auto");
  fillSelect(byId("email_column"), [currentConfig.email_column || "email"], currentConfig.email_column || "email");
  for (const field of fields) {
    setFieldValue(field, currentConfig[field] ?? "");
  }
}

async function saveConfig() {
  const result = await api("/api/config", { method: "POST", body: JSON.stringify(collectConfig()) });
  currentConfig = result.config || currentConfig;
  return currentConfig;
}

async function loadCredentials() {
  const credentials = await api("/api/credentials");
  const sheetsReady = credentials.service_account_json || credentials.service_account_path_exists;
  const gmailReady = credentials.gmail_client_id && credentials.gmail_client_secret && credentials.gmail_refresh_token;
  setCredentialState("sheetsCredential", sheetsReady);
  setCredentialState("gmailCredential", gmailReady);
  byId("credentialSummary").textContent = sheetsReady && gmailReady ? "Credentials ready" : "Credentials needed";
}

function setCredentialState(id, ready) {
  const element = byId(id);
  element.textContent = ready ? "Ready" : "Missing";
  element.dataset.state = ready ? "ready" : "missing";
}

function selectedCampaignTemplatePaths() {
  return [...campaignTemplates.querySelectorAll("input[type='checkbox']:checked")].map((input) => input.value);
}

function configuredCampaignTemplateNames() {
  const selected = Array.isArray(currentConfig.campaign_template_paths) ? currentConfig.campaign_template_paths : [];
  const names = selected.map(templateNameFromPath).filter(Boolean);
  const fallback = templateNameFromPath(currentConfig.email_template_path);
  return names.length ? names : fallback ? [fallback] : [];
}

function renderCampaignTemplates() {
  campaignTemplates.innerHTML = "";
  const selectedNames = new Set(configuredCampaignTemplateNames());
  if (!currentTemplates.length) {
    const empty = document.createElement("span");
    empty.className = "soft-label";
    empty.textContent = "No templates";
    campaignTemplates.append(empty);
    byId("selectedTemplateCount").textContent = "0 selected";
    return;
  }
  for (const name of currentTemplates) {
    const label = document.createElement("label");
    label.className = "campaign-template-option";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = templatePath(name);
    checkbox.checked = selectedNames.has(name) || (!selectedNames.size && name === activeTemplate);
    checkbox.addEventListener("change", updateSelectedTemplateCount);
    const text = document.createElement("span");
    text.textContent = displayTemplateName(name);
    label.append(checkbox, text);
    campaignTemplates.append(label);
  }
  updateSelectedTemplateCount();
}

function updateSelectedTemplateCount() {
  const count = selectedCampaignTemplatePaths().length;
  byId("selectedTemplateCount").textContent = `${count} selected`;
}

function renderAttachment(attachment) {
  const hasAttachment = attachment?.path && attachment.exists;
  byId("attachmentName").textContent = hasAttachment ? attachment.name : "No attachment";
  byId("attachmentMeta").textContent = hasAttachment ? `${formatBytes(attachment.size)} attached to every email` : "";
  byId("attachmentRemove").disabled = !attachment?.path;
  currentConfig.attachment_path = attachment?.path || "";
}

async function loadAttachment() {
  renderAttachment(await api("/api/attachment"));
}

async function uploadAttachment(file) {
  if (!file) return;
  const formData = new FormData();
  formData.append("attachment", file);
  setStatus(`Uploading ${file.name}...`);
  const result = await formApi("/api/attachment", formData);
  currentConfig = result.config || currentConfig;
  renderAttachment(result.attachment);
  setStatus(`Attached ${result.attachment.name}.`);
}

async function removeAttachment() {
  const result = await api("/api/attachment/remove", { method: "POST", body: "{}" });
  currentConfig = result.config || currentConfig;
  renderAttachment(result.attachment);
  attachmentFile.value = "";
  setStatus("Attachment removed.");
}

function renderTemplateList() {
  templateList.innerHTML = "";
  if (!currentTemplates.length) {
    const empty = document.createElement("div");
    empty.className = "soft-label";
    empty.textContent = "No templates";
    templateList.append(empty);
    return;
  }
  for (const name of currentTemplates) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `template-item${name === activeTemplate ? " active" : ""}`;
    button.innerHTML = `<span>${displayTemplateName(name)}</span><small>Edit</small>`;
    button.addEventListener("click", () => runAction(button, () => loadTemplate(name)));
    templateList.append(button);
  }
}

function updateActiveTitle() {
  byId("activeTemplateTitle").textContent = displayTemplateName(templateName.value || activeTemplate || "email");
}

async function refreshTemplates() {
  currentTemplates = await api("/api/templates");
  renderTemplateList();
  renderCampaignTemplates();
}

async function loadTemplates() {
  await refreshTemplates();
  const preferred = currentConfig.email_template_path?.split(/[\\/]/).pop();
  const first = currentTemplates.includes(preferred) ? preferred : currentTemplates[0];
  if (first) {
    await loadTemplate(first);
  } else {
    startNewTemplate();
  }
}

async function loadTemplate(name) {
  const payload = await api(`/api/templates/${encodeURIComponent(name)}`);
  activeTemplate = payload.name;
  templateName.value = displayTemplateName(payload.name);
  subjectInput.value = payload.subject || currentConfig.email_subject || "";
  editor.innerHTML = payload.html || "";
  updateActiveTitle();
  renderTemplateList();
  if (sheetState) await renderPreview();
  setStatus(`Loaded ${displayTemplateName(payload.name)}.`);
}

function startNewTemplate() {
  activeTemplate = "";
  templateName.value = "untitled template";
  editor.innerHTML = "";
  updateActiveTitle();
  renderTemplateList();
  if (sheetState) renderPreview();
  setStatus("New template ready.");
}

async function saveTemplateOnly() {
  const name = normalizeTemplateName(templateName.value);
  const result = await api(`/api/templates/${encodeURIComponent(name)}`, {
    method: "POST",
    body: JSON.stringify({ html: editor.innerHTML, subject: subjectInput.value }),
  });
  activeTemplate = result.name;
  templateName.value = displayTemplateName(result.name);
  currentConfig.email_subject = result.subject || subjectInput.value;
  const selected = new Set(Array.isArray(currentConfig.campaign_template_paths) ? currentConfig.campaign_template_paths : []);
  selected.add(templatePath(result.name));
  currentConfig.campaign_template_paths = [...selected];
  await refreshTemplates();
  updateActiveTitle();
  setStatus(`Saved ${displayTemplateName(result.name)}.`);
}

function renderPlaceholderChips(headers) {
  placeholderChips.innerHTML = "";
  const cleanHeaders = headers.filter((header) => header && header.trim());
  byId("columnCount").textContent = String(cleanHeaders.length);
  if (!cleanHeaders.length) {
    const empty = document.createElement("span");
    empty.className = "soft-label";
    empty.textContent = "Load a sheet";
    placeholderChips.append(empty);
    return;
  }
  for (const header of cleanHeaders) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = `{{${header}}}`;
    chip.addEventListener("mousedown", (event) => event.preventDefault());
    chip.addEventListener("click", () => insertPlaceholder(header));
    placeholderChips.append(chip);
  }
}

function sheetHeaders() {
  return (sheetState?.headers || []).filter((header) => header && header.trim());
}

function hideAutocomplete() {
  autocomplete.hidden = true;
  autocomplete.innerHTML = "";
  autocompleteContext = null;
  autocompleteIndex = 0;
}

function positionAutocomplete(rect) {
  const margin = 8;
  const top = Math.min(window.innerHeight - 240, Math.max(margin, rect.bottom + margin));
  const left = Math.min(window.innerWidth - 272, Math.max(margin, rect.left));
  autocomplete.style.top = `${top}px`;
  autocomplete.style.left = `${left}px`;
}

function inputPlaceholderContext(input) {
  const caret = input.selectionStart ?? 0;
  const before = input.value.slice(0, caret);
  const open = before.lastIndexOf("{{");
  const closeBefore = before.lastIndexOf("}}");
  if (open === -1 || open < closeBefore) return null;
  const nextClose = input.value.indexOf("}}", caret);
  const query = before.slice(open + 2);
  if (query.includes("{") || query.includes("}")) return null;
  return {
    type: "input",
    input,
    start: open,
    end: nextClose === -1 ? caret : nextClose + 2,
    query,
    rect: input.getBoundingClientRect(),
  };
}

function editorTextNodeContext() {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount || !editor.contains(selection.anchorNode)) return null;
  let node = selection.anchorNode;
  let offset = selection.anchorOffset;
  if (node.nodeType !== Node.TEXT_NODE) {
    const child = node.childNodes[Math.max(0, offset - 1)];
    if (!child || child.nodeType !== Node.TEXT_NODE) return null;
    node = child;
    offset = child.textContent.length;
  }
  const text = node.textContent || "";
  const before = text.slice(0, offset);
  const open = before.lastIndexOf("{{");
  const closeBefore = before.lastIndexOf("}}");
  if (open === -1 || open < closeBefore) return null;
  const nextClose = text.indexOf("}}", offset);
  const query = before.slice(open + 2);
  if (query.includes("{") || query.includes("}")) return null;

  const range = selection.getRangeAt(0).cloneRange();
  range.collapse(true);
  const rect = range.getBoundingClientRect();
  return {
    type: "editor",
    node,
    start: open,
    end: nextClose === -1 ? offset : nextClose + 2,
    query,
    rect,
  };
}

function currentPlaceholderContext() {
  if (document.activeElement === subjectInput) return inputPlaceholderContext(subjectInput);
  if (document.activeElement === editor || editor.contains(document.activeElement)) return editorTextNodeContext();
  return null;
}

function renderAutocomplete(context) {
  const headers = sheetHeaders();
  if (!context || !headers.length) {
    hideAutocomplete();
    return;
  }
  const query = context.query.trim().toLowerCase();
  const matches = headers
    .filter((header) => !query || header.toLowerCase().includes(query))
    .slice(0, 8);
  if (!matches.length) {
    hideAutocomplete();
    return;
  }

  autocompleteContext = context;
  autocomplete.innerHTML = "";
  autocompleteIndex = Math.min(autocompleteIndex, matches.length - 1);
  matches.forEach((header, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = header;
    button.className = index === autocompleteIndex ? "active" : "";
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("click", () => applyAutocomplete(header));
    autocomplete.append(button);
  });
  positionAutocomplete(context.rect);
  autocomplete.hidden = false;
}

function updateAutocomplete() {
  autocompleteIndex = 0;
  renderAutocomplete(currentPlaceholderContext());
}

function setEditorCaret(node, offset) {
  const range = document.createRange();
  const selection = window.getSelection();
  range.setStart(node, offset);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

function applyAutocomplete(header) {
  const context = autocompleteContext || currentPlaceholderContext();
  if (!context) return;
  const placeholder = `{{${header}}}`;
  if (context.type === "input") {
    context.input.setRangeText(placeholder, context.start, context.end, "end");
    context.input.focus();
  } else {
    const text = context.node.textContent || "";
    context.node.textContent = text.slice(0, context.start) + placeholder + text.slice(context.end);
    setEditorCaret(context.node, context.start + placeholder.length);
    editor.focus();
  }
  hideAutocomplete();
  renderPreview();
}

function moveAutocomplete(delta) {
  if (autocomplete.hidden) return false;
  const buttons = [...autocomplete.querySelectorAll("button")];
  if (!buttons.length) return false;
  autocompleteIndex = (autocompleteIndex + delta + buttons.length) % buttons.length;
  buttons.forEach((button, index) => button.classList.toggle("active", index === autocompleteIndex));
  buttons[autocompleteIndex].scrollIntoView({ block: "nearest" });
  return true;
}

function acceptAutocomplete() {
  if (autocomplete.hidden) return false;
  const buttons = [...autocomplete.querySelectorAll("button")];
  const button = buttons[autocompleteIndex];
  if (!button) return false;
  applyAutocomplete(button.textContent);
  return true;
}

function renderSheetState(state) {
  sheetState = state;
  fillSelect(byId("contacts_sheet_name"), ["auto", ...(state.sheet_titles || [])], currentConfig.contacts_sheet_name || state.contacts_sheet_name || "auto");
  fillSelect(byId("email_column"), state.headers || [], state.email_column || currentConfig.email_column || "email");
  renderPlaceholderChips(state.headers || []);

  byId("metricTotal").textContent = state.counts?.total_rows ?? 0;
  byId("metricPending").textContent = state.counts?.pending ?? 0;
  byId("metricSent").textContent = state.counts?.sent ?? 0;
  byId("metricReplies").textContent = state.counts?.replied ?? 0;
  byId("setupState").textContent = state.setup_columns_present ? "Ready" : "Needs setup";
  byId("controlPaused").textContent = state.control?.paused || "-";
  byId("controlNext").textContent = state.control?.next_eligible_at || "-";
  byId("controlDaily").textContent = `${state.control?.daily_sent_count || "0"}/${state.effective_daily_cap || 500}`;
  byId("batchBadge").textContent = `Batch ${state.effective_batch_size || 5}`;
  byId("capBadge").textContent = `${state.effective_daily_cap || 500}/day`;
  const delayRange = state.effective_delay_range || [10, 15];
  byId("delayBadge").textContent = `${delayRange[0]}-${delayRange[1]} min`;
}

async function loadSheet(saveFirst = false) {
  if (saveFirst) await saveConfig();
  const state = await api("/api/sheet");
  renderSheetState(state);
  setStatus(`Loaded ${state.contacts_sheet_name}.`);
  renderPreview();
}

function renderPreviewHtml(html) {
  const doc = previewFrame.contentDocument || previewFrame.contentWindow.document;
  doc.open();
  doc.write(`<!doctype html>
    <html>
      <head>
        <base target="_blank" />
        <style>
          body { margin: 0; padding: 18px; color: #151922; font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 1.55; }
          a { color: #285f9f; }
          p { margin: 0 0 14px; }
        </style>
      </head>
      <body>${html || ""}</body>
    </html>`);
  doc.close();
}

async function renderPreview() {
  if (!editor) return;
  try {
    const preview = await api("/api/preview", {
      method: "POST",
      body: JSON.stringify({ subject: subjectInput.value, html: editor.innerHTML }),
    });
    byId("previewSubject").textContent = preview.subject || "(No subject)";
    byId("previewRow").textContent = preview.row_number ? `${preview.contacts_sheet_name} row ${preview.row_number}` : "No row";
    renderPreviewHtml(preview.html || "");
  } catch (error) {
    byId("previewSubject").textContent = "";
    byId("previewRow").textContent = "No preview";
    renderPreviewHtml("");
  }
}

function insertPlaceholder(header) {
  const text = `{{${header}}}`;
  const target = activeEditable || editor;
  if (target === subjectInput) {
    const start = subjectInput.selectionStart ?? subjectInput.value.length;
    const end = subjectInput.selectionEnd ?? subjectInput.value.length;
    subjectInput.setRangeText(text, start, end, "end");
    subjectInput.focus();
    renderPreview();
    return;
  }
  editor.focus();
  document.execCommand("insertText", false, text);
  renderPreview();
}

async function setupSheet() {
  await saveConfig();
  setStatus("Setting up sheet...");
  const result = await api("/api/setup-sheet", { method: "POST", body: "{}" });
  setLog([result.stdout, result.stderr].filter(Boolean).join("\n").trim());
  await loadSheet(false);
  setStatus(result.stdout?.trim() || "Sheet setup complete.");
}

async function runBatch(dryRun) {
  await saveConfig();
  if (!dryRun && !confirm("Send the next eligible batch now?")) return;
  setStatus(dryRun ? "Running dry run..." : "Sending batch...");
  const result = await api("/api/send-batch", {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun }),
  });
  setLog([result.stdout, result.stderr].filter(Boolean).join("\n").trim());
  await loadSheet(false);
  setStatus(dryRun ? "Dry run complete." : "Batch run complete.");
}

async function saveEverything() {
  await saveTemplateOnly();
  await saveConfig();
  await loadSheet(false).catch(() => {});
  setStatus("Saved config and template.");
}

async function runAction(button, task) {
  const buttons = button ? [button] : [];
  try {
    for (const item of buttons) item.disabled = true;
    await task();
  } catch (error) {
    setStatus(error.message);
    setLog(error.message);
  } finally {
    for (const item of buttons) item.disabled = false;
  }
}

document.querySelector("#saveAll").addEventListener("click", (event) => runAction(event.currentTarget, saveEverything));
document.querySelector("#saveTemplate").addEventListener("click", (event) => runAction(event.currentTarget, saveTemplateOnly));
document.querySelector("#setupSheet").addEventListener("click", (event) => runAction(event.currentTarget, setupSheet));
document.querySelector("#loadSheet").addEventListener("click", (event) => runAction(event.currentTarget, () => loadSheet(true)));
document.querySelector("#dryRun").addEventListener("click", (event) => runAction(event.currentTarget, () => runBatch(true)));
document.querySelector("#sendNow").addEventListener("click", (event) => runAction(event.currentTarget, () => runBatch(false)));
document.querySelector("#newTemplate").addEventListener("click", startNewTemplate);
document.querySelector("#attachmentPick").addEventListener("click", () => attachmentFile.click());
document.querySelector("#attachmentRemove").addEventListener("click", (event) => runAction(event.currentTarget, removeAttachment));
attachmentFile.addEventListener("change", (event) => {
  const file = event.currentTarget.files?.[0];
  runAction(byId("attachmentPick"), () => uploadAttachment(file));
});

byId("contacts_sheet_name").addEventListener("change", () => runAction(null, () => loadSheet(true)));
templateName.addEventListener("input", updateActiveTitle);
editor.addEventListener("focus", () => {
  activeEditable = editor;
});
subjectInput.addEventListener("focus", () => {
  activeEditable = subjectInput;
});
editor.addEventListener("input", () => {
  renderPreview();
  updateAutocomplete();
});
editor.addEventListener("click", updateAutocomplete);
editor.addEventListener("keyup", (event) => {
  if (["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(event.key)) return;
  updateAutocomplete();
});
editor.addEventListener("paste", (event) => {
  const text = event.clipboardData?.getData("text/plain");
  if (!text) return;
  event.preventDefault();
  document.execCommand("insertHTML", false, plainTextToHtml(text));
  renderPreview();
  updateAutocomplete();
});
subjectInput.addEventListener("input", () => {
  renderPreview();
  updateAutocomplete();
});
subjectInput.addEventListener("click", updateAutocomplete);
subjectInput.addEventListener("keyup", (event) => {
  if (["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(event.key)) return;
  updateAutocomplete();
});

document.addEventListener("selectionchange", () => {
  if (document.activeElement === subjectInput || document.activeElement === editor || editor.contains(document.activeElement)) {
    updateAutocomplete();
  }
});

document.addEventListener("mousedown", (event) => {
  if (!autocomplete.contains(event.target) && event.target !== subjectInput && !editor.contains(event.target)) {
    hideAutocomplete();
  }
});

document.addEventListener("keydown", (event) => {
  if (autocomplete.hidden) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    moveAutocomplete(1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    moveAutocomplete(-1);
  } else if (event.key === "Enter" || event.key === "Tab") {
    event.preventDefault();
    acceptAutocomplete();
  } else if (event.key === "Escape") {
    hideAutocomplete();
  }
});

document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("click", () => {
    document.execCommand(button.dataset.command, false, null);
    editor.focus();
    renderPreview();
  });
});

document.querySelector("#linkButton").addEventListener("click", () => {
  const url = prompt("Link URL");
  if (!url) return;
  editor.focus();
  document.execCommand("createLink", false, url);
  renderPreview();
});

async function init() {
  try {
    await loadConfig();
    await Promise.all([loadTemplates(), loadCredentials(), loadAttachment()]);
    await loadSheet(false).catch((error) => {
      setStatus(error.message);
      renderPlaceholderChips([]);
    });
    setStatus("Ready.");
  } catch (error) {
    setStatus(`Startup issue: ${error.message}`);
  }
}

init();

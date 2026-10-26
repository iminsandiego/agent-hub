"use strict";
// Agent Hub memory browser.
// No third-party scripts and no HTML interpolation of captured data (every value is
// set with textContent). Two ways in: the password exchanges for a server session
// held in an HttpOnly cookie this script never sees; a pasted token lives only in
// `state` and is dropped on reload, tab close or sign-out. Nothing goes in storage.

const $ = (id) => document.getElementById(id);
const state = {
  token: "", connected: false, me: null, health: null, projects: [], project: "",
  route: { view: "home", id: "", params: new URLSearchParams() },
  revision: 0, sessions: new Map(), conversationOnly: false,
};
const VIEW_NAMES = { home: "Home", search: "Search", sessions: "Sessions", notes: "Notes", context: "Agent context", timeline: "Timeline", integrations: "Connect agents" };
const CLIENTS = { codex: ["Codex", "Cx"], claude: ["Claude Code", "Cl"], cursor: ["Cursor", "Cu"], t3: ["T3", "T3"], chatgpt: ["ChatGPT", "GP"], generic: ["Generic", "Gn"] };
const ROLES = { user: "user", assistant: "assistant", tool: "tool", system: "system" };
const KINDS = ["decision", "instruction", "observation", "procedure", "failure", "question", "preference"];
const INJECTED = /^\s*(<[a-z_-]+>|# AGENTS\.md|Caveat:)/i;
// Cursor wraps the user's own prompt in <user_query>, so it is not client context.
const USER_QUERY = /<user_query>/i;
const injectedText = (text) => INJECTED.test(text) && !USER_QUERY.test(text);
const STATUS_LABEL = { candidate: "Awaiting review", active: "Active", rejected: "Rejected", superseded: "Superseded" };

// ---------------------------------------------------------------- DOM helpers

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (typeof attrs === "string") node.className = attrs;
  else if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), guard(value));
      else node.setAttribute(key, value === true ? "" : value);
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}
function add(parent, ...children) {
  parent.append(...children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false));
  return parent;
}
function guard(handler) {
  return (event) => { try { Promise.resolve(handler(event)).catch(fail); } catch (e) { fail(e); } };
}
function fail(e) {
  if (e && e.status === 401 && state.connected) return disconnect(e.message);
  toast(e && e.message ? e.message : String(e), "error");
}

const SVG = "http://www.w3.org/2000/svg";
const ICONS = {
  home: "M4 10.5 12 4l8 6.5V20h-5v-5.5H9V20H4z",
  search: "M10.5 4a6.5 6.5 0 1 0 0 13a6.5 6.5 0 1 0 0-13|M20 20l-4.8-4.8",
  sessions: "M4 5.5h16v10H9l-5 4z",
  notes: "M7 3.5h10a1 1 0 0 1 1 1V20l-6-3.5L6 20V4.5a1 1 0 0 1 1-1z",
  context: "M12 3.5 3.5 8 12 12.5 20.5 8z|M3.5 12 12 16.5 20.5 12|M3.5 16 12 20.5 20.5 16",
  timeline: "M4 6h16|M4 12h11|M4 18h6",
  integrations: "M9 3.5v5|M15 3.5v5|M6.5 8.5h11v3a5.5 5.5 0 0 1-11 0z|M12 17v3.5",
  close: "M6 6l12 12|M18 6 6 18",
  back: "M15 5l-7 7 7 7",
  arrow: "M5 12h14|M13 6l6 6-6 6",
  copy: "M9 9h11v11H9z|M5 15H4V4h11v1",
  download: "M12 4v11|M7 10l5 5 5-5|M4 20h16",
  check: "M5 12.5l4.5 4.5L19 7.5",
  plus: "M12 5v14|M5 12h14",
  user: "M12 12a4 4 0 1 0 0-8a4 4 0 1 0 0 8|M4.5 20.5c.8-3.6 3.8-5.5 7.5-5.5s6.7 1.9 7.5 5.5",
  assistant: "M12 3.5l1.9 4.6 4.6 1.9-4.6 1.9L12 16.5l-1.9-4.6L5.5 10l4.6-1.9z|M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z",
  tool: "M4 5h16v14H4z|M8 10l2.5 2L8 14|M13 15h3",
  system: "M12 3.5a8.5 8.5 0 1 0 0 17a8.5 8.5 0 1 0 0-17|M12 11v5|M12 8h.01",
  external: "M14 4h6v6|M20 4l-9 9|M18 14v6H4V6h6",
  shield: "M12 3.5l7.5 3v5.5c0 4.5-3.2 7.6-7.5 8.5-4.3-.9-7.5-4-7.5-8.5V6.5z",
  layers: "M4 7h16|M4 12h16|M4 17h16",
};
function icon(name, cls = "icon") {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  for (const d of (ICONS[name] || ICONS.system).split("|")) {
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

// ------------------------------------------------------------------ formatting

const numberFormat = new Intl.NumberFormat();
const num = (value) => numberFormat.format(Number(value) || 0);
const plural = (count, one, many = one + "s") => num(count) + " " + (Number(count) === 1 ? one : many);
const enc = encodeURIComponent;
function date(value) { const d = value ? new Date(value) : null; return d && !isNaN(d) ? d : null; }
function relative(value) {
  const d = date(value);
  if (!d) return "";
  const seconds = (Date.now() - d.getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
  if (seconds < 86400) return Math.floor(seconds / 3600) + "h ago";
  if (seconds < 86400 * 7) return Math.floor(seconds / 86400) + "d ago";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
}
function stamp(value) {
  const d = date(value);
  return d ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "Unknown time";
}
function timeEl(value) {
  const d = date(value);
  return d ? el("time", { datetime: d.toISOString(), title: stamp(value) }, relative(value)) : el("span", "faint", "no timestamp");
}
function span(first, last) {
  const a = date(first), b = date(last);
  if (!a && !b) return "";
  if (!a || !b || Math.abs(b - a) < 60000) return stamp(a || b);
  const sameDay = a.toDateString() === b.toDateString();
  return stamp(a) + " – " + (sameDay ? b.toLocaleTimeString(undefined, { timeStyle: "short" }) : stamp(b));
}
function clientLabel(client) { return (CLIENTS[client] || [client || "Agent"])[0]; }
function roleClass(role) { return ROLES[role] || "system"; }
function roleLabel(role) { return role ? role.charAt(0).toUpperCase() + role.slice(1) : "Record"; }
function shortId(id) { return id && id.length > 14 ? id.slice(0, 10) + "…" + id.slice(-4) : id || ""; }

// ------------------------------------------------------------------- network

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
async function api(path, { method = "GET", body, raw = false } = {}) {
  const headers = state.token ? { Authorization: "Bearer " + state.token } : {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, { method, headers, cache: "no-store", body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (_) {
    throw new ApiError(0, "Can’t reach the Agent Hub service at " + location.host + ". If you reach it through an SSH tunnel, check that the tunnel is still running.");
  }
  if (!response.ok) {
    let detail = "";
    try {
      const value = await response.json();
      if (typeof value.detail === "string") detail = value.detail;
      else if (Array.isArray(value.detail)) detail = value.detail.map((item) => item.msg).join("; ");
    } catch (_) { /* Non-JSON error body. */ }
    throw new ApiError(response.status, explain(response.status, detail));
  }
  return raw ? response : response.json();
}
function explain(status, detail) {
  if (status === 401 && !state.token) return "You’ve been signed out. Sign in again to continue.";
  if (status === 401) return "This server didn’t accept that token. Tokens belong to one server: use one issued by the service behind " + location.host + ".";
  if (status === 403 && /origin/i.test(detail)) return "The server refused this page’s address (" + location.origin + "). Upgrade the server, or add the address to allowed_origins in its server.json.";
  if (status === 403 && /^host/i.test(detail)) return "The server refused the host name “" + location.hostname + "”. Add it to allowed_hosts in the server’s server.json.";
  if (status === 403) return detail || "This token doesn’t have permission for that.";
  if (status === 404) return "That record isn’t available. It may have been forgotten.";
  return detail || "Request failed (" + status + ").";
}
const base = (project = state.project) => "/v1/projects/" + enc(project);
const canWrite = () => !!state.me && (state.me.admin || state.me.permissions.includes("write"));
const isAdmin = () => !!state.me && state.me.admin;
const currentProject = () => state.projects.find((item) => item.id === state.project) || { id: state.project, name: state.project };

// --------------------------------------------------------------------- routing

function href(view, id = "", params = {}, project = state.project) {
  let hash = "#/" + enc(project) + "/" + view;
  if (id) hash += "/" + enc(id);
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null && value !== "") query.set(key, value);
  const text = query.toString();
  return hash + (text ? "?" + text : "");
}
function go(view, id, params) { location.hash = href(view, id, params); }
function parseHash() {
  const [path, query = ""] = location.hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean).map((part) => { try { return decodeURIComponent(part); } catch (_) { return ""; } });
  return { project: parts[0] || "", view: parts[1] || "home", id: parts[2] || "", params: new URLSearchParams(query) };
}

const VIEWS = { home: homeView, search: searchView, sessions: sessionsView, notes: notesView, context: contextView, timeline: timelineView, integrations: integrationsView };

async function route() {
  if (!state.connected) return;
  const next = parseHash();
  if (!(next.view in VIEWS)) next.view = "home";
  if (!state.projects.some((item) => item.id === next.project)) {
    const fallback = state.projects.reduce((best, item) => (!best || item.size > best.size ? item : best), null);
    if (fallback) { history.replaceState(null, "", href(next.view, "", {}, fallback.id)); return route(); }
    return renderNoProjects();
  }
  const projectChanged = next.project !== state.project;
  const moved = projectChanged || next.view !== state.route.view || next.id !== state.route.id;
  state.project = next.project;
  state.route = next;
  $("project").value = next.project;
  if (projectChanged) { state.sessions.clear(); closeInspector(); refreshCounts(); }
  for (const link of document.querySelectorAll(".rail-link")) {
    link.href = href(link.dataset.view);
    if (link.dataset.view === next.view) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  $("global-query").value = next.view === "search" ? next.params.get("q") || "" : "";
  document.title = VIEW_NAMES[next.view] + " · " + (currentProject().name || state.project) + " · Agent Hub";
  const revision = ++state.revision;
  const target = el("div", "view view-" + next.view);
  const main = $("main");
  const settled = setTimeout(() => { if (revision === state.revision) main.replaceChildren(skeleton()); }, 120);
  try {
    await VIEWS[next.view](target, next);
    if (revision !== state.revision) return;
    main.replaceChildren(target);
    if (moved) window.scrollTo(0, 0);
  } catch (e) {
    if (revision !== state.revision) return;
    if (e.status === 401) return disconnect(e.message);
    main.replaceChildren(errorState(e));
  } finally {
    clearTimeout(settled);
  }
}
function rerender() { return route(); }
function renderNoProjects() {
  $("main").replaceChildren(el("div", "view", stateBlock("No projects for this token",
    "This token isn’t assigned to any memory project on this server. Ask the server administrator for a project token, or connect with a different one.",
    button("Sign out", signOut, { cls: "button" }))));
}

// ------------------------------------------------------------ shared components

function pageHead({ eyebrow, title, sub, actions }) {
  return el("header", "page-head",
    el("div", "page-head-text", eyebrow ? el("div", "eyebrow", eyebrow) : null, el("h1", null, title), sub ? el("p", "page-sub", sub) : null),
    actions ? el("div", "page-actions", actions) : null);
}
function panel(title, { sub, link, linkText, body, cls } = {}) {
  return el("section", "panel" + (cls ? " " + cls : ""),
    el("header", "panel-head", el("div", null, el("h2", null, title), sub ? el("p", "panel-sub", sub) : null),
      link ? el("a", { class: "panel-link", href: link }, linkText || "View all", icon("arrow", "icon icon-sm")) : null),
    body);
}
function stateBlock(title, text, action) {
  return el("div", "state", el("strong", null, title), text ? el("p", null, text) : null, action || null);
}
function errorState(e) {
  return el("div", "view", el("div", "state state-error", el("strong", null, "This view couldn’t load"), el("p", null, e.message || String(e)),
    el("button", { class: "button", type: "button", onclick: rerender }, "Try again")));
}
function skeleton() {
  return el("div", "view", el("div", "skeleton", el("span", "sk sk-title"), el("span", "sk sk-line"), el("span", "sk sk-block"), el("span", "sk sk-block")));
}
function roleChip(role) {
  const cls = roleClass(role);
  return el("span", "role role-" + cls, icon(cls, "icon icon-sm"), roleLabel(role));
}
function clientBadge(client) {
  const [label, short] = CLIENTS[client] || [client || "Agent", (client || "?").slice(0, 2)];
  return el("span", { class: "client client-" + (CLIENTS[client] ? client : "other"), title: label, "aria-label": label }, short);
}
function chip(text, cls = "") { return el("span", "chip " + cls, text); }
function kindChip(kind) { return chip(kind || "note", "kind kind-" + (kind || "note")); }
function statusChip(status) { return chip(STATUS_LABEL[status] || status, "status status-" + status); }
function button(label, handler, { cls = "button", iconName, title, disabled } = {}) {
  return el("button", { class: cls, type: "button", title, "aria-label": title && !label ? title : undefined, disabled, onclick: handler },
    iconName ? icon(iconName, "icon icon-sm") : null, label || null);
}
function copyButton(value, label = "Copy") {
  return button(label, async () => { await copyText(value); toast("Copied to the clipboard"); }, { cls: "button ghost small", iconName: "copy" });
}
async function copyText(value) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(value);
  const area = el("textarea", { readonly: true, class: "offscreen" });
  area.value = value; document.body.append(area); area.select();
  document.execCommand("copy"); area.remove();
}
function highlight(text, query) {
  const fragment = document.createDocumentFragment();
  const terms = [...new Set((query || "").toLowerCase().match(/[\p{L}\p{N}_][\p{L}\p{N}_.-]+/gu) || [])].sort((a, b) => b.length - a.length);
  if (!terms.length) { fragment.append(text); return fragment; }
  const pattern = new RegExp("(" + terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "giu");
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    fragment.append(text.slice(last, match.index), el("mark", null, match[0]));
    last = match.index + match[0].length;
  }
  fragment.append(text.slice(last));
  return fragment;
}
function toast(message, kind = "info") {
  const node = el("div", "toast toast-" + kind, message);
  $("toasts").append(node);
  setTimeout(() => node.classList.add("leaving"), kind === "error" ? 8000 : 4000);
  setTimeout(() => node.remove(), kind === "error" ? 8400 : 4400);
}
function updateReviewBadge(stats) {
  const count = stats && stats.memories ? stats.memories.candidate || 0 : 0;
  $("review-count").textContent = count > 99 ? "99+" : String(count);
  $("review-count").hidden = !count;
}
async function refreshCounts() {
  if (!state.project) return;
  const project = state.project;
  try { const stats = await api(base(project) + "/stats"); if (project === state.project) updateReviewBadge(stats); } catch (_) { /* Counts are decorative. */ }
}

// Summary text is a sequence of role-attributed JSON paragraphs, extractive
// fragments (possibly cut mid-record) or model prose. Parse what is structured.
function parseSummary(summary) {
  const parts = [];
  const normalized = String(summary || "").replace(/\n?\[(…|\.\.\.)\]\n?/g, "\n\n[…]\n\n");
  for (const chunk of normalized.split(/\n\n+/)) {
    const text = chunk.trim();
    if (!text) continue;
    if (text === "[…]" || text === "[...]") { parts.push({ gap: true }); continue; }
    try {
      const value = JSON.parse(text);
      if (value && typeof value.text === "string") { parts.push({ role: value.role, text: value.text }); continue; }
    } catch (_) { /* Fall through to partial parsing. */ }
    const partial = /^\{"role":"([^"]+)","text":"([\s\S]*)$/.exec(text);
    if (partial) {
      let body = partial[2].replace(/"\}$/, "");
      try { body = JSON.parse('"' + body.replace(/\\?…$/, "") + '"') + (body.endsWith("…") ? "…" : ""); } catch (_) { /* Keep escaped text. */ }
      parts.push({ role: partial[1], text: body });
      continue;
    }
    for (const line of text.split("\n")) if (line.trim() === "[…]") parts.push({ gap: true }); else if (line.trim()) parts.push({ text: line });
  }
  return parts;
}
function summaryBlock(summary, limit = 6) {
  const parts = parseSummary(summary);
  const list = el("div", "summary");
  for (const part of parts.slice(0, limit)) {
    if (part.gap) list.append(el("div", "summary-gap", "⋯"));
    else list.append(el("div", "summary-line", part.role ? roleChip(part.role) : null, el("span", null, part.text)));
  }
  if (parts.length > limit) list.append(el("div", "summary-more", "+ " + plural(parts.length - limit, "more excerpt")));
  return list;
}

// -------------------------------------------------------------------- dialogs

function openModal(content, { wide = false } = {}) {
  const dialog = $("modal");
  dialog.classList.toggle("wide", wide);
  $("modal-body").replaceChildren(content);
  if (!dialog.open) dialog.showModal();
  return dialog;
}
function closeModal() { const dialog = $("modal"); if (dialog.open) dialog.close(); $("modal-body").replaceChildren(); }
function confirmAction({ title, body, confirm, danger = false }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (value) => { if (done) return; done = true; $("modal").removeEventListener("close", onClose); closeModal(); resolve(value); };
    const onClose = () => finish(false);
    const content = el("div", "modal-content",
      el("h2", null, title), ...[].concat(body),
      el("div", "modal-actions",
        el("button", { class: "button ghost", type: "button", onclick: () => finish(false) }, "Cancel"),
        el("button", { class: "button " + (danger ? "danger" : "primary"), type: "button", onclick: () => finish(true) }, confirm)));
    openModal(content);
    $("modal").addEventListener("close", onClose);
  });
}

function composeNote({ sources = [], statement = "" } = {}) {
  const selected = [...new Set(sources)];
  const text = el("textarea", { id: "note-statement", rows: 5, maxlength: 8000, required: true, placeholder: "One clear statement, for example: Decision: release builds are signed on the build server, not on laptops." });
  text.value = statement;
  const kind = el("select", { id: "note-kind" }, KINDS.map((value) => el("option", { value }, value.charAt(0).toUpperCase() + value.slice(1))));
  kind.value = /^decision\b/i.test(statement) ? "decision" : "observation";
  const sourceList = el("div", "source-chips");
  const drawSources = () => sourceList.replaceChildren(...(selected.length
    ? selected.map((id) => el("span", "chip source-chip", "Record " + shortId(id), button("", () => { selected.splice(selected.indexOf(id), 1); drawSources(); }, { cls: "chip-remove", iconName: "close", title: "Remove source" })))
    : [el("span", "faint", "No sources. The note will be marked as unsourced.")]));
  drawSources();
  const error = el("p", { class: "form-error", role: "alert", hidden: true });
  const form = el("form", "modal-content",
    el("h2", null, "New note"),
    el("p", "muted", "Notes start as candidates. An administrator decides whether a note becomes active context for every new session."),
    el("label", { for: "note-statement" }, "Statement"), text,
    el("div", "form-row", el("div", null, el("label", { for: "note-kind" }, "Kind"), kind)),
    el("div", null, el("span", "label", "Sources"), sourceList),
    error,
    el("div", "modal-actions",
      el("button", { class: "button ghost", type: "button", onclick: closeModal }, "Cancel"),
      el("button", { class: "button primary", type: "submit" }, "Save candidate")));
  form.addEventListener("submit", guard(async (event) => {
    event.preventDefault();
    error.hidden = true;
    try {
      await api(base() + "/memories", { method: "POST", body: { statement: text.value.trim(), kind: kind.value, source_event_ids: selected, idempotency_key: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random() } });
    } catch (e) { error.textContent = e.message; error.hidden = false; return; }
    closeModal();
    toast("Saved as a candidate note.");
    refreshCounts();
    if (state.route.view === "notes" || state.route.view === "home") rerender();
  }));
  openModal(form, { wide: true });
  text.focus();
}

async function reviewNote(note, status, supersedes = null) {
  await api(base() + "/memories/" + enc(note.id) + "/review", { method: "POST", body: { status, supersedes } });
  const message = status === "rejected" ? (note.status === "active" ? "Note retired. Its history is kept." : "Candidate rejected. Its history is kept.")
    : supersedes ? "Note activated and the earlier note superseded." : "Note activated. New sessions will start with it.";
  toast(message);
  refreshCounts();
  rerender();
  if (!$("inspector").hidden) showInspector();
}
async function chooseReplacement(note) {
  const active = await api(base() + "/memories?status=active&limit=200");
  if (!active.length) { toast("There are no active notes to replace."); return; }
  let chosen = "";
  const options = el("div", "choice-list", active.map((item) => {
    const input = el("input", { type: "radio", name: "replace", value: item.id });
    input.addEventListener("change", () => { chosen = item.id; });
    return el("label", "choice", input, el("span", null, kindChip(item.kind), el("span", "choice-text", item.statement)));
  }));
  const ok = await confirmAction({
    title: "Activate and replace an active note",
    body: [el("p", "muted", "The new note becomes active and the one you choose is marked superseded. The superseded note stays readable with its sources."),
      el("blockquote", "quote", note.statement), options],
    confirm: "Activate and replace",
  });
  if (ok && !chosen) { toast("Choose the note to replace.", "error"); return; }
  if (ok) await reviewNote(note, "active", chosen);
}
async function retireNote(note) {
  const ok = await confirmAction({
    title: "Retire this note?",
    body: [el("blockquote", "quote", note.statement), el("p", "muted", "It stops appearing in agent context. The note, its sources and its review history are kept.")],
    confirm: "Retire note", danger: true,
  });
  if (ok) await reviewNote(note, "rejected");
}
function noteActions(note) {
  if (!isAdmin()) return null;
  if (note.status === "candidate") {
    return el("div", "note-actions",
      button("Activate", () => reviewNote(note, "active"), { cls: "button primary small", iconName: "check" }),
      button("Replace…", () => chooseReplacement(note), { cls: "button small" }),
      button("Reject", () => reviewNote(note, "rejected"), { cls: "button ghost small" }));
  }
  if (note.status === "active") return el("div", "note-actions", button("Retire", () => retireNote(note), { cls: "button ghost small" }));
  return null;
}
function noteCard(note, { compact = false } = {}) {
  const sources = (note.source_event_ids || []).length;
  return el("article", "note-card" + (compact ? " compact" : ""),
    el("div", "note-head", kindChip(note.kind), compact ? null : statusChip(note.status), el("span", "note-time", timeEl(note.updated_at || note.created_at))),
    el("button", { class: "note-statement", type: "button", onclick: () => inspect({ type: "memory", id: note.id }) }, note.statement),
    el("div", "note-foot",
      el("span", "faint", sources ? plural(sources, "source") : "Unsourced", " · ", createdBy(note.created_by)),
      note.superseded_by ? el("button", { class: "link", type: "button", onclick: () => inspect({ type: "memory", id: note.superseded_by }) }, "Replaced by a newer note") : null,
      noteActions(note)));
}
function createdBy(value) {
  if (!value || value === "manual") return "added manually";
  return "proposed by " + value;
}
function sessionRow(session) {
  state.sessions.set(session.id, session);
  return el("a", { class: "session-row", href: href("sessions", session.id) },
    clientBadge(session.client),
    el("div", "session-main",
      el("div", "session-title", session.preview || session.external_id || session.id),
      el("div", "session-meta", clientLabel(session.client), " · ", session.machine, " · ", plural(session.total_events, "record"))),
    el("div", "session-time", timeEl(session.last_timestamp || session.updated_at)));
}

// ------------------------------------------------------------------- inspector

const inspector = { stack: [], revision: 0 };
function inspect(item, { push = false } = {}) {
  if (!push) inspector.stack = [];
  inspector.stack.push(item);
  return showInspector();
}
function closeInspector() {
  inspector.stack = [];
  inspector.revision++;
  $("inspector").hidden = true;
  $("app").classList.remove("inspecting");
  $("inspector-body").replaceChildren();
}
async function showInspector() {
  const item = inspector.stack[inspector.stack.length - 1];
  if (!item) return closeInspector();
  const panelNode = $("inspector");
  panelNode.hidden = false;
  $("app").classList.add("inspecting");
  $("inspector-back").hidden = inspector.stack.length < 2;
  const revision = ++inspector.revision;
  const body = el("div", "inspector-content");
  $("inspector-body").replaceChildren(el("div", "skeleton", el("span", "sk sk-line"), el("span", "sk sk-block")));
  try {
    const title = await INSPECTORS[item.type](body, item);
    if (revision !== inspector.revision) return;
    $("inspector-title").textContent = title;
    $("inspector-body").replaceChildren(body);
    $("inspector-body").scrollTop = 0;
  } catch (e) {
    if (revision !== inspector.revision) return;
    if (e.status === 401) return disconnect(e.message);
    $("inspector-title").textContent = "Unavailable";
    $("inspector-body").replaceChildren(el("div", "state state-error", el("strong", null, "This record couldn’t load"), el("p", null, e.message)));
  }
}
function facts(rows) {
  return el("dl", "facts", rows.filter(Boolean).map(([term, value]) => [el("dt", null, term), el("dd", null, value)]));
}
const INSPECTORS = {
  async event(body, item) {
    const representation = item.representation || "text";
    const offset = item.offset || 0;
    const record = await api(base() + "/events/" + enc(item.id) + "?offset=" + offset + "&max_chars=16000&representation=" + representation);
    const content = record[representation];
    const toggle = el("div", { class: "segmented", role: "group", "aria-label": "Representation" },
      ["text", "raw"].map((value) => el("button", { type: "button", "aria-pressed": String(value === representation), onclick: () => { item.representation = value; item.offset = 0; showInspector(); } },
        value === "text" ? "Text" : "Captured original")));
    const pager = record.truncated ? el("div", "pager",
      el("span", "faint", "Characters " + num(offset + 1) + "–" + num(offset + content.length) + " of " + num(record.total_chars)),
      offset > 0 ? button("Previous", () => { item.offset = Math.max(0, offset - 16000); showInspector(); }, { cls: "button ghost small" }) : null,
      record.next_offset !== null ? button("Next", () => { item.offset = record.next_offset; showInspector(); }, { cls: "button ghost small" }) : null) : null;
    add(body,
      el("div", "inspector-row", roleChip(record.role), el("span", "faint", "Record #" + num(record.sequence))),
      toggle,
      el("pre", "source" + (representation === "raw" ? " raw" : ""), content || "(empty)"),
      pager,
      el("div", "inspector-actions",
        copyButton(content, "Copy"),
        button("Download original", () => downloadRecord(record.id), { cls: "button ghost small", iconName: "download" }),
        canWrite() ? button("Save as note", () => composeNote({ sources: [record.id], statement: record.text ? record.text.slice(0, 600) : "" }), { cls: "button ghost small", iconName: "plus" }) : null),
      facts([
        ["Session", el("a", { href: href("sessions", record.session_id), class: "link" }, shortId(record.session_id))],
        ["Source time", stamp(record.source_timestamp)],
        ["Archived", stamp(record.ingested_at)],
        ["Record ID", el("code", null, record.id)],
        ["Source ID", el("code", null, record.external_event_id)],
      ]),
      el("p", "caveat", icon("shield", "icon icon-sm"), "Historical data. Check the current source, build or test evidence before relying on it."));
    return "Record #" + num(record.sequence);
  },

  async memory(body, item) {
    const note = await api(base() + "/memories/" + enc(item.id));
    const sources = note.sources || [];
    const sourceList = el("div", "source-list");
    add(body,
      el("div", "inspector-row", kindChip(note.kind), statusChip(note.status)),
      el("p", "statement", note.statement),
      el("p", "caveat", icon("shield", "icon icon-sm"), sources.length
        ? "Source-backed historical claim. Review makes a note useful context; it does not verify it."
        : "Unsourced note. Treat it as an unverified claim."),
      noteActions(note) || "",
      sources.length ? el("h3", null, plural(sources.length, "source")) : null,
      sourceList,
      note.supersedes ? el("p", null, button("Show the note it replaced", () => inspect({ type: "memory", id: note.supersedes }, { push: true }), { cls: "link" })) : null,
      note.superseded_by ? el("p", null, button("Show the note that replaced it", () => inspect({ type: "memory", id: note.superseded_by }, { push: true }), { cls: "link" })) : null,
      (note.reviews || []).length ? el("h3", null, "Review history") : null,
      el("ol", "history", (note.reviews || []).map((review) => el("li", null,
        el("span", null, STATUS_LABEL[review.previous_status] || review.previous_status, " → ", el("b", null, STATUS_LABEL[review.status] || review.status)),
        el("span", "faint", review.actor + " · " + stamp(review.created_at))))),
      facts([["Created", stamp(note.created_at)], ["Created by", note.created_by], ["Note ID", el("code", null, note.id)]]));
    const previews = await Promise.all(sources.slice(0, 8).map((source) =>
      api(base() + "/events/" + enc(source.event_id) + "?max_chars=320").catch(() => null)));
    sources.slice(0, 8).forEach((source, index) => {
      const preview = previews[index];
      sourceList.append(el("button", { class: "source-item", type: "button", onclick: () => inspect({ type: "event", id: source.event_id }, { push: true }) },
        el("span", "source-head", roleChip(source.role), el("span", "faint", "#" + num(source.sequence) + " · " + relative(source.timestamp))),
        el("span", "source-text", preview ? preview.text + (preview.truncated ? "…" : "") : "Source unavailable")));
    });
    if (sources.length > 8) sourceList.append(el("p", "faint", "+ " + plural(sources.length - 8, "more source")));
    return "Note";
  },

  async node(body, item) {
    const value = await api(base() + "/nodes/" + enc(item.id));
    const node = value.node;
    add(body,
      el("div", "inspector-row", chip(modeLabel(node.mode), "mode mode-" + node.mode), el("span", "faint", rangeLabel(node))),
      summaryBlock(node.summary, 40),
      el("div", "inspector-actions",
        value.event ? button("Open record", () => inspect({ type: "event", id: value.event.id }, { push: true }), { cls: "button small", iconName: "arrow" }) : null,
        ...value.children.map((child) => button(rangeLabel(child), () => inspect({ type: "node", id: child.id }, { push: true }), { cls: "button ghost small" }))),
      el("p", "caveat", icon("shield", "icon icon-sm"), "Summaries can be lossy. Open the records for the exact wording."));
    return "History " + rangeLabel(node).toLowerCase();
  },
};
async function downloadRecord(id) {
  const response = await api(base() + "/events/" + enc(id) + "/download", { raw: true });
  const url = URL.createObjectURL(await response.blob());
  const anchor = el("a", { href: url, download: "agent-hub-record-" + id + ".txt", class: "offscreen" });
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function modeLabel(mode) { return { semantic: "Summary", extractive: "Excerpt", verbatim: "Verbatim" }[mode] || mode; }
function rangeLabel(node) { return node.lo === node.hi ? "Record " + num(node.lo) : "Records " + num(node.lo) + "–" + num(node.hi); }

// ----------------------------------------------------------------------- views

async function homeView(root) {
  const [stats, sessions, candidates, active] = await Promise.all([
    api(base() + "/stats"), api(base() + "/sessions?limit=6"),
    api(base() + "/memories?status=candidate&limit=4"), api(base() + "/memories?status=active&limit=6")]);
  updateReviewBadge(stats);
  const project = currentProject();
  const latest = sessions[0];
  root.append(pageHead({
    eyebrow: state.health && state.health.domain ? state.health.domain + " memory" : "Project memory",
    title: project.name || project.id,
    sub: stats.events ? plural(stats.events, "record") + " across " + plural(stats.sessions, "session") + (latest ? " · last capture " + relative(latest.last_timestamp || latest.updated_at) : "") : "Nothing has been captured in this project yet.",
  }));
  const tiles = [
    ["Records", stats.events, href("timeline"), "Captured messages, tool calls and outputs"],
    ["Sessions", stats.sessions, href("sessions"), "Conversations from your computers"],
    ["Active notes", stats.memories.active || 0, href("notes", "", { status: "active" }), "Given to every new session"],
    ["Awaiting review", stats.memories.candidate || 0, href("notes", "", { status: "candidate" }), "Proposed by agents and the worker"],
  ];
  root.append(el("div", "tiles", tiles.map(([label, value, link, hint], index) =>
    el("a", { class: "tile" + (index === 3 && value ? " attention" : ""), href: link }, el("span", "tile-label", label), el("strong", null, num(value)), el("span", "tile-hint", hint)))));
  if (!stats.events) {
    root.append(panel("Start capturing", { body: el("div", "panel-body", el("p", null, "Agent Hub stores what your Codex, Claude Code and T3 sessions capture on connected computers. Configure a computer with this project to begin."), el("a", { class: "button primary", href: href("integrations") }, "Connect an agent")) }));
    return;
  }
  const review = panel("Awaiting review", {
    sub: isAdmin() ? "Activate useful notes so new sessions start with them." : "Reviewing needs an administrator token.",
    link: href("notes", "", { status: "candidate" }), linkText: "All candidates",
    body: el("div", "panel-body stack", candidates.length ? candidates.map((note) => noteCard(note, { compact: true })) : stateBlock("Nothing to review", "New candidates appear when agents propose notes.")),
  });
  const recent = panel("Recent sessions", {
    link: href("sessions"), linkText: "All sessions",
    body: el("div", "panel-body list", sessions.length ? sessions.map(sessionRow) : stateBlock("No sessions yet")),
  });
  root.append(el("div", "columns", recent, review));
  root.append(panel("Always in context", {
    sub: "Active notes are placed at the start of the context every agent in this project receives.",
    link: href("context"), linkText: "Preview agent context",
    body: el("div", "panel-body stack", active.length ? active.map((note) => noteCard(note, { compact: true })) : stateBlock("No active notes", "Activate a candidate to make it part of every new session’s context.")),
  }));
}

async function searchView(root, routeInfo) {
  const query = (routeInfo.params.get("q") || "").trim();
  const limit = routeInfo.params.get("more") ? 50 : 25;
  let filter = routeInfo.params.get("type") || "all";
  const input = el("input", { type: "search", id: "search-input", "aria-label": "Search this project", placeholder: "A decision, error message, file name or phrase", value: query, autocomplete: "off" });
  const form = el("form", { class: "search-hero", role: "search" }, icon("search"), input, el("button", { class: "button primary", type: "submit" }, "Search"));
  form.addEventListener("submit", (event) => { event.preventDefault(); go("search", "", { q: input.value.trim() }); });
  root.append(pageHead({ title: "Search", sub: "Matches words in captured records and notes in " + (currentProject().name || state.project) + "." }), form);
  if (!query) {
    root.append(el("div", "tips",
      el("h2", null, "Search tips"),
      el("ul", null,
        el("li", null, "Use the exact words that would have appeared: an error message, a function, a file name or a person."),
        el("li", null, "Search is lexical, not semantic. A miss doesn’t prove a topic never came up — try another phrasing, or browse the timeline."),
        el("li", null, "Open any result to read the captured original and the session around it."))));
    requestAnimationFrame(() => input.focus());
    return;
  }
  const results = await api(base() + "/search?limit=" + limit + "&query=" + enc(query));
  const notes = results.filter((item) => item.type === "memory");
  const records = results.filter((item) => item.type === "event");
  const list = el("div", "results");
  const filters = el("div", { class: "filters", role: "group", "aria-label": "Result type" });
  const draw = () => {
    filters.replaceChildren(...[["all", "All", results.length], ["notes", "Notes", notes.length], ["records", "Records", records.length]].map(([value, label, count]) =>
      el("button", { type: "button", class: "filter", "aria-pressed": String(filter === value), onclick: () => { filter = value; draw(); } }, label, el("span", "count", num(count)))));
    const shown = filter === "notes" ? notes : filter === "records" ? records : [...notes, ...records];
    list.replaceChildren(...(shown.length ? shown.map((hit) => searchHit(hit, query)) : [stateBlock("No " + (filter === "notes" ? "notes" : "records") + " matched")]));
  };
  draw();
  const backend = results[0] && results[0].retrieval && results[0].retrieval !== "fts5" ? "Simple substring search (full-text index unavailable)" : "Full-text search";
  root.append(el("div", "results-bar", filters, el("span", "faint", backend)));
  if (!results.length) {
    root.append(stateBlock("Nothing matched “" + query + "”", "Try fewer or different words. Search matches exact terms, so a miss doesn’t prove the topic never came up."));
    return;
  }
  root.append(list);
  if (results.length === limit && limit < 50) root.append(el("div", "more", el("a", { class: "button", href: href("search", "", { q: query, more: 1 }) }, "Show more results")));
}
function searchHit(hit, query) {
  if (hit.type === "memory") {
    return el("button", { class: "hit hit-note", type: "button", onclick: () => inspect({ type: "memory", id: hit.id }) },
      el("span", "hit-head", el("span", "hit-type", icon("notes", "icon icon-sm"), "Note"), kindChip(hit.kind), statusChip(hit.status)),
      el("span", "hit-text", highlight(hit.excerpt || "", query)),
      el("span", "hit-meta", plural((hit.source_event_ids || []).length, "source")));
  }
  return el("div", "hit",
    el("button", { class: "hit-body", type: "button", onclick: () => inspect({ type: "event", id: hit.id }) },
      el("span", "hit-head", roleChip(hit.role), el("span", "faint", "Record #" + num(hit.sequence)), el("span", "hit-when", timeEl(hit.timestamp))),
      el("span", "hit-text", highlight(hit.excerpt || "", query))),
    el("a", { class: "hit-session", href: href("sessions", hit.session_id) }, "Open session", icon("arrow", "icon icon-sm")));
}

async function sessionsView(root, routeInfo) {
  if (routeInfo.id) return sessionDetail(root, routeInfo.id);
  const sessions = await api(base() + "/sessions?limit=100");
  root.append(pageHead({ title: "Sessions", sub: "Conversations captured from your computers, most recent first." }));
  if (!sessions.length) {
    root.append(stateBlock("No sessions yet", "Captured sessions appear here once a connected computer’s watcher uploads them.", el("a", { class: "button", href: href("integrations") }, "Connect an agent")));
    return;
  }
  const clients = [...new Set(sessions.map((item) => item.client))];
  const machines = [...new Set(sessions.map((item) => item.machine))];
  const text = el("input", { type: "search", placeholder: "Filter these sessions", "aria-label": "Filter sessions" });
  const client = el("select", { "aria-label": "Client" }, el("option", { value: "" }, "All clients"), clients.map((value) => el("option", { value }, clientLabel(value))));
  const machine = el("select", { "aria-label": "Computer" }, el("option", { value: "" }, "All computers"), machines.map((value) => el("option", { value }, value)));
  const list = el("div", "list card");
  const count = el("span", "faint");
  const draw = () => {
    const needle = text.value.trim().toLowerCase();
    const shown = sessions.filter((item) => (!client.value || item.client === client.value) && (!machine.value || item.machine === machine.value)
      && (!needle || [item.preview, item.external_id, item.machine, item.client].some((field) => field && field.toLowerCase().includes(needle))));
    count.textContent = shown.length === sessions.length ? plural(sessions.length, "session") : num(shown.length) + " of " + plural(sessions.length, "session");
    list.replaceChildren(...(shown.length ? shown.map(sessionRow) : [stateBlock("No sessions match these filters")]));
  };
  for (const control of [text, client, machine]) control.addEventListener("input", draw);
  draw();
  root.append(el("div", "toolbar", text, client, machine, count), list);
  root.append(el("p", "footnote", "To keep a new chat out of memory, start its first message with ", el("code", null, "[temp]"), ". " +
    (sessions.length === 100 ? "Showing the latest 100 sessions; use search to find older work." : "")));
}

async function sessionDetail(root, id) {
  const page = await api(base() + "/sessions/" + enc(id) + "?limit=50");
  const known = state.sessions.get(id);
  const events = page.events || [];
  const title = (known && known.preview) || firstUserText(events) || page.external_id;
  const actions = el("div", "page-actions",
    canWrite() ? button("New note", () => composeNote(), { cls: "button small", iconName: "plus" }) : null,
    isAdmin() ? button("Forget…", () => privacyMenu(page), { cls: "button ghost small danger-text" }) : null);
  root.append(
    el("a", { class: "back-link", href: href("sessions") }, icon("back", "icon icon-sm"), "Sessions"),
    el("header", "page-head session-head",
      el("div", "page-head-text",
        el("div", "eyebrow", clientBadge(page.client), clientLabel(page.client), " · ", page.machine),
        el("h1", "session-heading", title),
        el("p", "page-sub", plural(page.total, "record"), known ? " · " + span(known.first_timestamp, known.last_timestamp) : "")),
      actions),
    el("details", "identifiers",
      el("summary", null, "Identifiers and source"),
      facts([
        ["Native session", el("span", null, el("code", null, page.external_id), " ", copyButton(page.external_id))],
        ["Agent Hub session", el("code", null, page.id)],
        known && known.metadata && known.metadata.source_path ? ["Source file", el("code", null, known.metadata.source_path)] : null,
        known && known.metadata && known.metadata.format ? ["Capture format", known.metadata.format] : null,
        ["First archived", stamp(page.created_at)],
        ["Last archived", stamp(page.updated_at)],
      ])));
  const transcript = el("div", "transcript" + (state.conversationOnly ? " conversation-only" : ""));
  const only = el("input", { type: "checkbox", id: "conversation-only" });
  only.checked = state.conversationOnly;
  only.addEventListener("change", () => { state.conversationOnly = only.checked; transcript.classList.toggle("conversation-only", only.checked); });
  root.append(el("div", "transcript-bar", el("label", "switch", only, el("span", null, "Hide tool and system records"))), transcript);
  const more = el("div", "more");
  const append = (result) => {
    transcript.append(...result.events.map(message));
    more.replaceChildren();
    if (result.next_offset !== null && result.next_offset !== undefined) {
      const remaining = result.total - result.next_offset;
      more.append(button("Load " + num(Math.min(remaining, 50)) + " more · " + num(remaining) + " remaining", async () => {
        more.replaceChildren(el("span", "faint", "Loading…"));
        append(await api(base() + "/sessions/" + enc(id) + "?limit=50&offset=" + result.next_offset));
      }));
    } else if (result.total) more.append(el("span", "faint", "End of session"));
  };
  append(page);
  root.append(more);
}
function firstUserText(events) {
  const first = events.find((item) => item.role === "user" && item.text.trim() && !injectedText(item.text));
  if (!first) return "";
  const query = first.text.match(/<user_query>([\s\S]*?)(<\/user_query>|$)/i);
  return (query ? query[1] : first.text).replace(/\s+/g, " ").trim().slice(0, 160);
}
function message(record) {
  const cls = roleClass(record.role);
  const injected = cls === "user" && injectedText(record.text || "");
  const auxiliary = cls === "tool" || cls === "system" || injected;
  const body = el("div", "msg-body", record.text || "(empty)");
  const long = auxiliary && (record.text.length > 360 || record.text.split("\n").length > 6);
  const node = el("article", { class: "msg msg-" + (injected ? "system" : cls) + (auxiliary ? " aux" : "") + (long ? " collapsed" : ""), id: "record-" + record.id },
    el("div", "msg-head",
      roleChip(record.role), injected ? el("span", "faint", "client context") : null,
      el("span", "faint", "#" + num(record.sequence)),
      el("span", "msg-time", timeEl(record.timestamp || record.ingested_at)),
      el("span", "msg-tools",
        button("", () => inspect({ type: "event", id: record.id }), { cls: "icon-button", iconName: "layers", title: "Inspect record" }),
        button("", async () => { await copyText(record.text); toast("Copied to the clipboard"); }, { cls: "icon-button", iconName: "copy", title: "Copy text" }),
        canWrite() ? button("", () => composeNote({ sources: [record.id], statement: record.text.slice(0, 600) }), { cls: "icon-button", iconName: "plus", title: "Save as note" }) : null)),
    body);
  if (long) node.append(button("Show all", (event) => { node.classList.remove("collapsed"); event.currentTarget.remove(); }, { cls: "link expand" }));
  if (record.next_offset !== null && record.next_offset !== undefined) {
    node.append(button("Continue reading · " + plural(record.total_chars, "character"), () => inspect({ type: "event", id: record.id }), { cls: "link" }));
  }
  return node;
}
async function privacyMenu(session) {
  let mode = "forgotten";
  const choice = (value, label, text) => {
    const input = el("input", { type: "radio", name: "privacy", value, checked: value === mode });
    input.addEventListener("change", () => { mode = value; });
    return el("label", "choice", input, el("span", null, el("b", null, label), el("span", "choice-text", text)));
  };
  const ok = await confirmAction({
    title: "Remove this chat from memory?",
    body: [
      facts([["Client", clientLabel(session.client)], ["Computer", session.machine], ["Native session", el("code", null, session.external_id)]]),
      el("div", "choice-list",
        choice("forgotten", "Forget this chat", "Remove it and keep it out of memory from now on."),
        choice("temporary", "Make temporary", "Treat it as a temporary chat, as if it had started with [temp].")),
      el("p", "warning", "Either way, the chat, its linked copies and every note citing it are removed from Agent Hub, and future capture of these sessions stays excluded. The native chat files and earlier backups remain. This can’t be undone here."),
    ],
    confirm: "Remove from memory", danger: true,
  });
  if (!ok) return;
  const result = await api(base() + "/sessions/" + enc(session.id) + "/privacy", { method: "POST", body: { mode } });
  state.sessions.delete(session.id);
  toast("Chat " + (result.mode === "temporary" ? "made temporary" : "forgotten") + ". Watchers won’t save it again." +
    (result.summaries_reset ? " " + plural(result.summaries_reset, "later summary", "later summaries") + " will be rewritten without it." : ""));
  refreshCounts();
  go("sessions");
}

async function notesView(root, routeInfo) {
  const stats = await api(base() + "/stats");
  updateReviewBadge(stats);
  const counts = stats.memories || {};
  const requested = routeInfo.params.get("status");
  const status = STATUS_LABEL[requested] ? requested : counts.candidate ? "candidate" : "active";
  if (requested !== status) {
    // Pin the chosen tab so acting on the last candidate doesn't switch tabs underneath you.
    history.replaceState(null, "", href("notes", "", { status }));
    routeInfo.params.set("status", status);
  }
  const notes = await api(base() + "/memories?status=" + status + "&limit=200");
  root.append(pageHead({
    title: "Notes",
    sub: "Short statements tied to their sources. Active notes start every new agent session in this project; candidates wait for review.",
    actions: canWrite() ? button("New note", () => composeNote(), { cls: "button primary", iconName: "plus" }) : null,
  }));
  root.append(el("nav", { class: "tabs", "aria-label": "Note status" }, Object.entries(STATUS_LABEL).map(([value, label]) =>
    el("a", { class: "tab", href: href("notes", "", { status: value }), "aria-current": value === status ? "page" : undefined },
      label, counts[value] ? el("span", "count", num(counts[value])) : null))));
  if (!isAdmin() && status === "candidate") root.append(el("p", "callout", "You can browse notes with this token. Activating or rejecting a note needs the server’s administrator token."));
  const empty = {
    candidate: ["Nothing awaiting review", "Agents propose candidates with the memory_note tool, and you can write one here."],
    active: ["No active notes", "Activate a candidate to give every new session in this project that context."],
    rejected: ["No rejected notes", ""],
    superseded: ["No superseded notes", "When an active note is replaced, the earlier version is kept here."],
  }[status];
  root.append(el("div", "stack", notes.length ? notes.map((note) => noteCard(note)) : stateBlock(empty[0], empty[1])));
}

async function contextView(root, routeInfo) {
  const budgets = [2000, 4000, 8000, 12000, 24000];
  const budget = budgets.includes(Number(routeInfo.params.get("budget"))) ? Number(routeInfo.params.get("budget")) : 8000;
  const query = (routeInfo.params.get("q") || "").trim();
  const pack = await api(base() + "/context?budget_chars=" + budget + (query ? "&query=" + enc(query) : ""));
  root.append(pageHead({
    title: "Agent context",
    sub: "What an agent in this project receives when it asks memory for context. The startup hook requests 8,000 characters. Everything is labelled as historical data, not instructions.",
  }));
  const size = el("select", { id: "context-budget", "aria-label": "Context size" }, budgets.map((value) => el("option", { value }, num(value) + " characters" + (value === 8000 ? " (startup)" : ""))));
  size.value = String(budget);
  const focus = el("input", { type: "search", id: "context-query", placeholder: "Focus on a task (optional)", "aria-label": "Focus on a task", value: query });
  const form = el("form", "toolbar", size, focus, el("button", { class: "button", type: "submit" }, "Preview"));
  form.addEventListener("submit", (event) => { event.preventDefault(); go("context", "", { budget: size.value, q: focus.value.trim() }); });
  size.addEventListener("change", () => go("context", "", { budget: size.value, q: focus.value.trim() }));
  const meter = el("div", "meter-fill");
  meter.style.width = Math.min(100, (pack.char_count / budget) * 100).toFixed(1) + "%";
  root.append(form, el("div", "meter-row", el("div", { class: "meter", role: "img", "aria-label": num(pack.char_count) + " of " + num(budget) + " characters" }, meter),
    el("span", null, num(pack.char_count) + " of " + num(budget) + " characters"), pack.truncated ? chip("Trimmed to fit", "status status-candidate") : null));
  // The pack is one record per line: "note id | kind | sources | statement" or
  // "lo+n | dates | text", grouped under "## " headings (store.py context()).
  const groups = { notes: [], matches: [], history: [] };
  const notices = [];
  let current = null;
  for (const line of pack.text.split("\n")) {
    if (line.startsWith("## ")) { current = /^## Active notes/.test(line) ? "notes" : /^## Records matching/.test(line) ? "matches" : /^## History/.test(line) ? "history" : null; continue; }
    const note = /^note (\S+) \| ([^|]*) \| ([^|]*) \| (.*)$/.exec(line);
    if (note && current === "notes") { groups.notes.push({ id: note[1], kind: note[2], sources: note[3], statement: note[4] }); continue; }
    const span = /^(\d+)\+(\d+) \| ([^|]*) \| (.*)$/.exec(line);
    if (span && current && current !== "notes") {
      const [, lo, n, when, body] = span;
      const mode = /^summary: /.test(body) ? "semantic" : /^excerpt: /.test(body) ? "extractive" : "verbatim";
      groups[current].push({ ref: lo + "+" + n, lo: Number(lo), hi: Number(lo) + Number(n) - 1, when, mode, text: body.replace(/^(summary|excerpt): /, "") });
      continue;
    }
    if (/truncated/i.test(line)) notices.push(line);
  }
  const lines = (text, query, limit = 3) => {
    const parts = text.split(" ¶ ");
    const list = el("div", "summary");
    for (const part of parts.slice(0, limit)) {
      const tagged = /^(user|assistant|tool|system|developer|human): ([\s\S]*)$/.exec(part);
      list.append(el("div", "summary-line", tagged ? roleChip(tagged[1]) : null, el("span", null, query ? highlight(tagged ? tagged[2] : part, query) : (tagged ? tagged[2] : part))));
    }
    if (parts.length > limit) list.append(el("div", "summary-more", "+ " + plural(parts.length - limit, "more record")));
    return list;
  };
  const section = (title, sub, items, render, emptyText) => panel(title + " · " + num(items.length), { sub, body: el("div", "panel-body stack", items.length ? items.map(render) : el("p", "faint", emptyText)) });
  root.append(section("Active notes", "Reviewed notes, newest first" + (query ? ", with ones matching the task first" : "") + ".", groups.notes,
    (record) => el("button", { class: "context-item", type: "button", onclick: () => inspect({ type: "memory", id: record.id }) }, kindChip(record.kind), el("span", null, record.statement)),
    "No active notes in this project."));
  if (query) {
    root.append(section("Records matching the task", "Search hits for “" + query + "”.", groups.matches,
      (record) => el("button", { class: "context-item column", type: "button", onclick: () => inspect({ type: "node", id: record.ref }) },
        el("span", "context-range", el("span", "faint", rangeLabel(record) + " · " + record.when)), lines(record.text, query, 1)),
      "No matching records were included."));
  }
  root.append(section("History", "All history, newest first here (agents read it oldest first). Recent spans in more detail; dates are UTC.", [...groups.history].reverse(),
    (record) => el("button", { class: "context-item column", type: "button", onclick: () => inspect({ type: "node", id: record.ref }) },
      el("span", "context-range", chip(modeLabel(record.mode), "mode mode-" + record.mode), el("span", "faint", rangeLabel(record) + " · " + record.when)), lines(record.text)),
    "No history yet."));
  if (notices.length) root.append(el("p", "callout", notices.join(" ")));
  root.append(el("details", "exact", el("summary", null, "Exact text sent to the agent"), el("div", "exact-actions", copyButton(pack.text, "Copy text")), el("pre", "source", pack.text)));
}

async function timelineView(root, routeInfo) {
  const nodeId = routeInfo.params.get("node");
  const stats = await api(base() + "/stats");
  root.append(pageHead({
    title: "Timeline",
    sub: "Every record in this project in capture order, folded into a tree of summaries. Unfold a span to go deeper; the bottom of the tree is the original records.",
  }));
  if (!stats.events) { root.append(stateBlock("No history yet", "The timeline fills in as sessions are captured.")); return; }
  let nodes, current = null, leafEvent = null;
  if (nodeId) {
    const zoom = await api(base() + "/nodes/" + enc(nodeId));
    current = zoom.node;
    nodes = zoom.children.length ? zoom.children : [zoom.node];
    leafEvent = zoom.event || null;
  } else {
    nodes = await api(base() + "/tree?max_nodes=12");
  }
  const lo = current ? current.lo : 0;
  const total = current ? current.hi - current.lo + 1 : Math.max(0, ...nodes.map((node) => node.hi + 1));
  root.append(el("nav", { class: "crumbs", "aria-label": "Timeline position" },
    el("a", { href: href("timeline") }, "All history · " + plural(stats.events, "record")),
    current ? [el("span", "faint", "›"), el("span", null, rangeLabel(current))] : null,
    current ? el("button", { class: "link", type: "button", onclick: () => history.back() }, "Back") : null));
  const bar = el("div", { class: "timeline-bar", role: "list" });
  for (const node of nodes) {
    const label = rangeLabel(node) + " · " + modeLabel(node.mode);
    const segment = node.lo !== node.hi
      ? el("a", { class: "segment mode-" + node.mode, href: href("timeline", "", { node: node.id }), title: label, "aria-label": label, role: "listitem" })
      : el("button", { class: "segment mode-" + node.mode, type: "button", title: label, "aria-label": label, role: "listitem", disabled: !node.event_id, onclick: () => inspect({ type: "event", id: node.event_id }) });
    segment.style.flexGrow = String(node.hi - node.lo + 1);
    bar.append(segment);
  }
  root.append(el("div", "timeline", bar, el("div", "timeline-scale", el("span", null, num(lo)), el("span", null, num(lo + total - 1)))),
    el("div", "legend", ["semantic", "extractive", "verbatim"].map((mode) => el("span", null, el("i", "swatch mode-" + mode), modeLabel(mode)))));
  const list = el("div", "stack");
  for (const node of [...nodes].reverse()) {
    const leaf = node.lo === node.hi;
    list.append(el("article", "span-card",
      el("header", "span-head", el("strong", null, rangeLabel(node)), chip(modeLabel(node.mode), "mode mode-" + node.mode),
        leaf ? button("Open record", () => inspect({ type: "event", id: node.event_id }), { cls: "button small", disabled: !node.event_id })
          : el("a", { class: "button small", href: href("timeline", "", { node: node.id }) }, "Unfold", icon("arrow", "icon icon-sm"))),
      summaryBlock(node.summary, 5)));
  }
  if (leafEvent) list.append(button("Open the original record", () => inspect({ type: "event", id: leafEvent.id }), { cls: "button primary" }));
  root.append(el("p", "footnote", "Newest spans first. Excerpts and summaries are lossy; open records for the exact wording."), list);
}

async function integrationsView(root) {
  const catalog = await api("/v1/catalog");
  const url = location.origin;
  const loopback = /^(127\.|localhost$|\[::1\]$)/.test(location.hostname);
  const project = state.project || "PROJECT";
  const code = (text) => el("div", "code-block", el("pre", null, text), copyButton(text));
  root.append(pageHead({ title: "Connect agents", sub: "Each computer gets its own token. Codex, Claude Code and T3’s providers keep their own tools and share memory through this service." }));
  root.append(el("div", "columns",
    panel("This service", { body: el("div", "panel-body", facts([
      ["Address", el("code", null, url)],
      ["MCP endpoint", el("span", null, el("code", null, url + "/mcp"), " ", copyButton(url + "/mcp"))],
      ["Domain", state.health && state.health.domain ? state.health.domain : "not restricted"],
      ["Version", state.health ? state.health.version : "unknown"],
      ["Signed in as", state.me ? state.me.name + " (" + roleName() + ")" : ""],
    ]), loopback ? el("p", "callout", "This is a loopback address, typically an SSH tunnel. Other computers need their own tunnel or the server’s private HTTPS name.") : null) }),
    panel("Add a computer", { body: el("ol", "panel-body steps",
      el("li", null, el("p", null, "On the server, issue a token for the computer:"), code("agent-hub token create --name laptop --project " + project + " --output laptop.token")),
      el("li", null, el("p", null, "On the computer, point Agent Hub at this service and map your repositories:"), code("agent-hub configure --url " + url + " --machine-id laptop --map /path/to/repo=" + project + " --save-token")),
      el("li", null, el("p", null, "Register memory and capture hooks with the native clients:"), code("agent-hub setup --clients codex claude")),
      el("li", null, el("p", null, "Check the connection and the capture queue:"), code("agent-hub doctor"))) })));
  root.append(panel("Integration catalog", {
    sub: "Reviewed MCP servers, plugins and skills from the repository. Listing something here installs nothing and grants no credentials.",
    body: el("div", "panel-body stack", catalog.entries.map((entry) => el("article", "catalog-entry",
      el("div", "note-head", chip(entry.kind.toUpperCase()), chip(entry.status, "status status-active")),
      el("h3", null, entry.id), el("p", null, entry.description),
      el("p", "faint", "Clients: " + entry.clients.join(", ") + " · Credentials: " + (entry.credentials || []).join(", "))))),
  }));
}
function roleName() {
  if (!state.me) return "";
  if (state.me.admin) return "administrator";
  return state.me.permissions.includes("write") ? "read and write" : "read only";
}

// ------------------------------------------------------------- connect / shell

async function checkServer() {
  const box = $("server-check");
  try {
    const response = await fetch("/health", { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    state.health = await response.json();
    box.dataset.state = "ok";
    $("server-title").textContent = "Agent Hub " + state.health.version + " is reachable";
    $("server-detail").textContent = location.host + (state.health.domain ? " · " + state.health.domain + " domain" : "");
  } catch (e) {
    box.dataset.state = "error";
    $("server-title").textContent = "Can’t reach the service at " + location.host;
    $("server-detail").textContent = e.message === "403" ? "The server rejected this host name; add it to allowed_hosts in server.json." : "If you use an SSH tunnel, start it, then reload this page.";
  }
}
function showSignIn(mode, message) {
  const passwords = !!(state.health && state.health.password_login);
  const usePassword = passwords && mode !== "token";
  $("password-form").hidden = !usePassword;
  $("connect-form").hidden = usePassword;
  $("use-password").hidden = !passwords;
  $("help-no-password").hidden = passwords;
  $("signin-help").open = !passwords && !!state.health;
  const error = usePassword ? $("password-error") : $("connect-error");
  $("password-error").hidden = $("connect-error").hidden = true;
  if (message) { error.textContent = message; error.hidden = false; }
  (usePassword ? $("password") : $("token")).focus();
}
async function loadIdentity() {
  const [me, projects] = await Promise.all([api("/v1/me"), api("/v1/projects")]);
  state.me = me;
  state.projects = projects.map((item) => ({ id: item.id || item.project, name: item.name || item.id || item.project, size: item.next_sequence || 0 }));
}
async function busy(button, label, work) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try { return await work(); } finally { button.disabled = false; button.textContent = original; }
}
async function signIn(event) {
  event.preventDefault();
  $("password-error").hidden = true;
  await busy($("password-submit"), "Signing in…", async () => {
    let response;
    try {
      response = await fetch("/auth/login", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: $("password").value }) });
    } catch (_) {
      return showSignIn("password", "Can’t reach the Agent Hub service at " + location.host + ". If you use an SSH tunnel, check that it is running.");
    }
    if (!response.ok) {
      let detail = "Sign-in failed (" + response.status + ").";
      try { const value = await response.json(); if (typeof value.detail === "string") detail = value.detail; } catch (_) { /* Keep default. */ }
      $("password").select();
      return showSignIn("password", detail);
    }
    $("password").value = "";
    state.token = "";
    try { await loadIdentity(); } catch (e) { return showSignIn("password", e.message); }
    enterApp();
  });
}
async function connect(event) {
  event.preventDefault();
  $("connect-error").hidden = true;
  await busy($("connect-submit"), "Connecting…", async () => {
    state.token = $("token").value.trim();
    try {
      await loadIdentity();
    } catch (e) {
      state.token = "";
      return showSignIn("token", e.message);
    }
    $("token").value = "";
    enterApp();
  });
}
function enterApp() {
  state.connected = true;
  $("project").replaceChildren(...state.projects.map((item) => el("option", { value: item.id }, item.name === item.id ? item.id : item.name + " · " + item.id)));
  $("project").disabled = state.projects.length < 2;
  $("identity-name").textContent = state.me.name;
  $("identity-role").textContent = roleName();
  $("identity-role").className = "badge" + (state.me.admin ? " badge-admin" : "");
  $("disconnect").textContent = state.token ? "Disconnect" : "Sign out";
  $("server-foot").replaceChildren(el("span", "dot ok"), el("span", null, location.host), el("span", "faint", (state.health && state.health.domain ? state.health.domain + " · " : "") + "v" + (state.health ? state.health.version : "?")));
  $("connect").hidden = true;
  $("app").hidden = false;
  state.project = "";
  route();
}
async function signOut() {
  if (!state.token) {
    try { await fetch("/auth/logout", { method: "POST", cache: "no-store" }); } catch (_) { /* The local state is cleared regardless. */ }
  }
  disconnect();
}
function disconnect(message) {
  const mode = state.token ? "token" : "password";
  state.token = ""; state.connected = false; state.me = null; state.projects = []; state.project = ""; state.revision++;
  state.sessions.clear();
  closeInspector();
  closeModal();
  $("main").replaceChildren();
  $("app").hidden = true;
  $("connect").hidden = false;
  $("review-count").hidden = true;
  showSignIn(mode, typeof message === "string" ? message : "");
}
async function resume() {
  // A password session survives reloads in its HttpOnly cookie. Try it before showing the form.
  await checkServer();
  if (state.health && state.health.password_login) {
    try {
      await loadIdentity();
      return enterApp();
    } catch (_) { /* No valid session; show the form. */ }
  }
  showSignIn("password");
}

function init() {
  for (const link of document.querySelectorAll(".rail-link")) link.prepend(icon(link.dataset.view));
  $("inspector-close").append(icon("close"));
  $("inspector-back").append(icon("back"));
  $("connect-form").addEventListener("submit", guard(connect));
  $("password-form").addEventListener("submit", guard(signIn));
  $("use-token").addEventListener("click", () => showSignIn("token"));
  $("use-password").addEventListener("click", () => showSignIn("password"));
  $("token-reveal").addEventListener("click", () => {
    const hidden = $("token").type === "password";
    $("token").type = hidden ? "text" : "password";
    $("token-reveal").textContent = hidden ? "Hide" : "Show";
    $("token-reveal").setAttribute("aria-pressed", String(hidden));
  });
  $("disconnect").addEventListener("click", guard(signOut));
  $("brand-link").addEventListener("click", (event) => { event.preventDefault(); go("home"); });
  $("project").addEventListener("change", () => {
    const view = state.route.view;
    location.hash = href(view, "", {}, $("project").value);
  });
  $("global-search").addEventListener("submit", (event) => {
    event.preventDefault();
    const query = $("global-query").value.trim();
    if (query) go("search", "", { q: query });
  });
  $("inspector-close").addEventListener("click", closeInspector);
  $("inspector-back").addEventListener("click", () => { inspector.stack.pop(); showInspector(); });
  $("modal").addEventListener("click", (event) => { if (event.target === $("modal")) closeModal(); });
  document.addEventListener("keydown", (event) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement && document.activeElement.tagName);
    if (event.key === "/" && !typing && state.connected && !$("modal").open) { event.preventDefault(); $("global-query").focus(); }
    else if (event.key === "Escape" && !$("modal").open && !$("inspector").hidden) closeInspector();
  });
  window.addEventListener("hashchange", () => route());
  resume();
}
init();

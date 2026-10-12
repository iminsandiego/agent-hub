"use strict";
// No external scripts, HTML interpolation of source data, or persistent token storage.
const $ = (id) => document.getElementById(id);
const state = { token: "", project: "", view: "overview", admin: false, query: "", reviewStatus: "candidate", revision: 0 };
const titles = {
  overview: ["An overview of what stays.", "Useful context from your work, with a path back to the original records. Historical memories remain separate from current evidence."],
  search: ["Find the reason behind a decision.", "Search captured event text and memory notes. Open a source to see the original wording and its provenance."],
  sessions: ["A record of the work.", "Captured sessions from your connected computers. Each record retains its source identity and timestamps."],
  review: ["Make useful context durable.", "Candidates are suggestions. Reviewing a note keeps it available as context; it does not verify a claim or a test result."],
  catalog: ["One home for your integrations.", "Memory is the first service. Add your other MCP servers, plugins, and skills through the repository's versioned catalog."]
};
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
function button(text, handler, cls = "secondary") { const node = el("button", cls, text); node.type = "button"; node.addEventListener("click", () => Promise.resolve(handler()).catch(error)); return node; }
function error(e) { notice(e.message || String(e)); }
function notice(text) { $("notice").textContent = text; $("notice").hidden = false; clearTimeout(notice.timer); notice.timer = setTimeout(() => { $("notice").hidden = true; }, 7000); }
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { Authorization: "Bearer " + state.token, ...(options.body ? { "Content-Type": "application/json" } : {}) }, cache: "no-store" });
  if (!response.ok) { let detail = "Request failed (" + response.status + ")"; try { const value = await response.json(); if (typeof value.detail === "string") detail = value.detail; } catch (_) {} throw new Error(detail); }
  return response.json();
}
function base() { return "/v1/projects/" + encodeURIComponent(state.project); }
function empty(parent, heading, description) { const node = el("div", "empty"); node.append(el("strong", "", heading), el("span", "", description)); parent.append(node); }
function tag(value) { return el("span", "tag " + value, value); }
function meta(record) { const div = el("div", "meta"); div.append(tag(record.status || record.type || record.role || "history")); if (record.kind) div.append(el("span", "", record.kind)); const timestamp = record.source_timestamp || record.timestamp || record.created_at || record.ingested_at; if (timestamp) div.append(el("span", "", new Date(timestamp).toLocaleString())); return div; }
function json(value) { return JSON.stringify(value, null, 2); }
function detail(title, nodes) { $("detail-title").textContent = title; $("detail-content").replaceChildren(...nodes); if (!$("detail").open) $("detail").showModal(); }
async function showEvent(id, offset = 0, representation = "text") {
  const item = await api(base() + "/events/" + encodeURIComponent(id) + "?offset=" + offset + "&max_chars=16000&representation=" + representation);
  const source = el("pre", "context", item[representation]); source.style.maxHeight = "50vh";
  const actions = el("div", "detail-actions");
  if (item.next_offset !== null) actions.append(button("Next page →", () => showEvent(id, item.next_offset, representation)));
  if (offset) actions.append(button("Start", () => showEvent(id, 0, representation)));
  actions.append(button(representation === "text" ? "View captured raw record" : "View normalized text", () => showEvent(id, 0, representation === "text" ? "raw" : "text")));
  detail("Captured source", [meta(item), el("p", "detail-note", "Event " + id + " · " + representation + " characters " + offset + "–" + (offset + item[representation].length) + " of " + item.total_chars), source, actions, el("p", "subtle", "Historical data. Check the original build, requirement, or execution evidence before relying on this claim.")]);
}
async function showNode(id) {
  const value = await api(base() + "/nodes/" + encodeURIComponent(id));
  const children = [el("p", "detail-note", value.node.mode + " · events " + value.node.lo + "–" + value.node.hi), el("pre", "context", value.node.summary)];
  for (const child of value.children) children.push(button("Open events " + child.lo + "–" + child.hi + " →", () => showNode(child.id)));
  if (value.event) children.push(button("Open original captured event →", () => showEvent(value.event.id)));
  detail("History tree", children);
}
async function showMemory(id) {
  const value = await api(base() + "/memories/" + encodeURIComponent(id));
  const nodes = [meta(value), el("p", "record", value.statement)];
  for (const source of value.source_event_ids || []) nodes.push(button("Open source " + source.slice(0, 12) + "…", () => showEvent(source)));
  nodes.push(el("pre", "context", json(value)));
  detail("Memory and provenance", nodes);
}
async function showSession(id, offset = 0) {
  const value = await api(base() + "/sessions/" + encodeURIComponent(id) + "?offset=" + offset + "&limit=20");
  const nodes = [el("p", "detail-note", "Session " + id + ". Event previews are bounded; open an event for complete pages.")];
  for (const event of value.events) { const card = el("div", "record"); card.append(meta(event), el("p", "", event.text), button("Open source →", () => showEvent(event.id))); nodes.push(card); }
  if (value.next_offset !== null) nodes.push(button("Next 20 records →", () => showSession(id, value.next_offset)));
  detail("Captured session", nodes);
}
async function overview(parent) {
  const [stats, context, tree] = await Promise.all([api(base() + "/stats"), api(base() + "/context?budget_chars=8000"), api(base() + "/tree?max_nodes=8")]);
  const row = el("div", "stats");
  const counts = [["Captured events", stats.events ?? stats.event_count ?? 0], ["Sessions", stats.sessions ?? stats.session_count ?? 0], ["Active notes", stats.memories?.active ?? stats.active_memories ?? 0], ["Candidate notes", stats.memories?.candidate ?? stats.candidate_memories ?? 0]];
  for (const [label, count] of counts) { const stat = el("div", "stat"); stat.append(el("span", "", label), el("strong", "", Number(count).toLocaleString())); row.append(stat); }
  parent.append(row);
  const columns = el("div", "grid-two");
  const pack = el("div", "panel"); const heading = el("div", "section-title"); heading.append(el("h2", "", "Current context pack"), el("small", "", context.char_count + " characters"));
  pack.append(heading, el("pre", "context", context.text), el("footer", "", context.truncated ? "This pack is bounded. Search or open a source for more detail." : "Historical context · sources remain available for inspection."));
  const navigation = el("div", "panel"); const treeheading = el("div", "section-title"); treeheading.append(el("h2", "", "Explore the history tree")); navigation.append(treeheading);
  if (!tree.length) navigation.append(el("p", "subtle", "The tree will appear as sessions are captured."));
  for (const node of tree) { const item = button("", () => showNode(node.id), "tree-node"); item.append(el("span", "", "EVENTS " + node.lo + "–" + node.hi + " · " + node.mode.toUpperCase()), el("p", "", node.summary)); navigation.append(item); }
  columns.append(pack, navigation); parent.append(columns);
}
async function searchView(parent) {
  const form = el("form", "toolbar"); const query = el("input"); query.type = "search"; query.placeholder = "A decision, failure, requirement, or phrase…"; query.value = state.query; query.setAttribute("aria-label", "Search memory"); const submit = el("button", "primary", "Search →"); submit.type = "submit"; form.append(query, submit); parent.append(form);
  form.addEventListener("submit", (event) => { event.preventDefault(); state.query = query.value.trim(); render().catch(error); });
  if (!state.query) { empty(parent, "Find the context you need.", "Search terms match original event text and candidate or active memory notes within this project."); return; }
  const results = await api(base() + "/search?limit=20&query=" + encodeURIComponent(state.query));
  if (!results.length) empty(parent, "No matching records.", "Try a distinctive name or exact term. A missed search does not prove the topic was never discussed.");
  for (const result of results) { const card = el("div", "record"); card.append(meta(result), el("p", "", result.excerpt || result.statement || result.text || ""), button("Open source →", () => result.type === "memory" ? showMemory(result.id) : showEvent(result.id))); parent.append(card); }
}
async function sessionsView(parent) {
  const records = await api(base() + "/sessions?limit=100");
  if (!records.length) empty(parent, "No captured sessions yet.", "Connect a computer and run its capture watcher, or backfill a selected transcript.");
  for (const record of records) { const card = el("div", "record"); card.append(meta(record), el("h3", "", (record.client || "Agent") + " · " + (record.machine || "Execution host")), el("p", "", record.external_id || record.external_session_id || record.id), button("Inspect session →", () => showSession(record.id))); parent.append(card); }
  if (records.length === 100) parent.append(el("p", "subtle", "Showing the latest 100 sessions. Use scoped search to find older records."));
}
async function reviewView(parent) {
  const toolbar = el("div", "toolbar"); const select = el("select"); select.setAttribute("aria-label", "Memory status");
  for (const status of ["candidate", "active", "rejected", "superseded"]) { const option = el("option", "", status.charAt(0).toUpperCase() + status.slice(1)); option.value = status; option.selected = status === state.reviewStatus; select.append(option); }
  select.addEventListener("change", () => { state.reviewStatus = select.value; render().catch(error); }); toolbar.append(select); parent.append(toolbar);
  if (!state.admin) parent.append(el("p", "subtle", "This credential can inspect notes. Activating, rejecting, or superseding a note requires an administrative credential."));
  const [records, active] = await Promise.all([api(base() + "/memories?status=" + state.reviewStatus), state.admin ? api(base() + "/memories?status=active") : Promise.resolve([])]);
  if (!records.length) empty(parent, "No " + state.reviewStatus + " notes.", "Candidate notes can be proposed by an agent or the enrichment worker, with their source references attached.");
  for (const record of records) {
    const card = el("div", "record"); card.append(meta(record), el("h3", "", record.statement));
    const actions = el("div", "actions"); actions.append(button("Inspect sources", () => showMemory(record.id)));
    if (state.admin && record.status === "candidate") {
      const replace = el("select"); replace.setAttribute("aria-label", "Note to supersede"); const none = el("option", "", "Add as a new active note"); none.value = ""; replace.append(none);
      for (const prior of active) { const option = el("option", "", "Replace: " + prior.statement.slice(0, 65)); option.value = prior.id; replace.append(option); }
      const review = async (status) => { await api(base() + "/memories/" + encodeURIComponent(record.id) + "/review", { method: "POST", body: JSON.stringify({ status, supersedes: status === "active" ? replace.value || null : null }) }); notice(status === "active" ? "Note added to active context." : "Candidate rejected. Its history is retained."); await render(); };
      actions.append(replace, button("Activate note", () => review("active"), "primary"), button("Reject", () => review("rejected")));
    }
    card.append(actions); parent.append(card);
  }
}
async function catalogView(parent) {
  const catalog = await api("/v1/catalog");
  for (const entry of catalog.entries) { const card = el("div", "record"); const metadata = el("div", "meta"); metadata.append(tag(entry.kind), el("span", "", entry.status)); card.append(metadata, el("h3", "", entry.id), el("p", "", entry.description), el("p", "subtle", "Clients: " + entry.clients.join(" · "))); parent.append(card); }
  empty(parent, "Ready for your next integration.", "Add reviewed definitions to the repository catalog. Nothing is installed or granted credentials merely by appearing here.");
}
async function render() {
  if (!state.token) return;
  const revision = ++state.revision;
  const target = el("div");
  $("page-title").textContent = titles[state.view][0]; $("page-description").textContent = titles[state.view][1]; $("scope-label").textContent = (state.project || "WORKSPACE").toUpperCase() + " / " + state.view.toUpperCase();
  for (const nav of document.querySelectorAll(".nav")) nav.classList.toggle("active", nav.dataset.view === state.view);
  $("content").replaceChildren(el("div", "loading", "Loading project memory…"));
  try { if (!state.project && state.view !== "catalog") empty(target, "No projects assigned.", "Ask the service administrator to assign this credential to a project."); else await ({ overview, search: searchView, sessions: sessionsView, review: reviewView, catalog: catalogView }[state.view])(target); if (revision === state.revision) $("content").replaceChildren(...target.childNodes); }
  catch (e) { if (revision === state.revision) { $("content").replaceChildren(); empty($("content"), "This view could not be loaded.", e.message); } throw e; }
}
$("connect-form").addEventListener("submit", async (event) => {
  event.preventDefault(); state.token = $("token").value.trim();
  try { const [projects, me] = await Promise.all([api("/v1/projects"), api("/v1/me")]); state.admin = me.admin; $("project").replaceChildren(); for (const project of projects) { const option = el("option", "", project.name || project.id); option.value = project.id; $("project").append(option); } state.project = projects[0]?.id || ""; $("project").disabled = !projects.length; $("login").hidden = true; $("workspace").hidden = false; $("disconnect").hidden = false; $("token").value = ""; $("connection-status").textContent = me.name; document.body.classList.add("connected"); await render(); } catch (e) { if ($("workspace").hidden) state.token = ""; error(e); }
});
$("disconnect").addEventListener("click", () => { state.token = ""; state.revision++; $("workspace").hidden = true; $("login").hidden = false; $("disconnect").hidden = true; $("project").disabled = true; $("project").replaceChildren(el("option", "", "Connect to choose")); $("connection-status").textContent = "Not connected"; $("content").replaceChildren(); $("detail-content").replaceChildren(); $("detail").close(); document.body.classList.remove("connected"); });
$("project").addEventListener("change", () => { state.project = $("project").value; $("detail").close(); render().catch(error); });
$("refresh").addEventListener("click", () => render().catch(error));
$("close-detail").addEventListener("click", () => $("detail").close());
for (const nav of document.querySelectorAll(".nav")) nav.addEventListener("click", () => { state.view = nav.dataset.view; render().catch(error); });

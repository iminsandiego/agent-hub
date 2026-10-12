// Run against scripts/smoke_fixture.py. Uses Playwright installed in your dev environment.
// Synthetic data only; no credentials or captured content are printed.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

async function main() {
  const info = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const output = process.argv[3] || "/tmp/agent-hub-browser";
  fs.mkdirSync(output, { recursive: true });
  const token = fs.readFileSync(info.token_file, "utf8").trim();
  const password = fs.readFileSync(info.password_file, "utf8");
  const browser = await chromium.launch({ headless: true, executablePath: process.env.AGENT_HUB_CHROMIUM_EXECUTABLE || undefined, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
    const tile = (label) => page.locator(".tile", { hasText: label }).locator("strong");

    // Sign-in screen reports the server, rejects a wrong password inline, then signs in.
    await page.goto(info.url);
    await page.locator('#server-check[data-state="ok"]').waitFor();
    await page.getByLabel("Password").waitFor();
    await page.screenshot({ path: path.join(output, "sign-in.png"), fullPage: true });
    await page.getByLabel("Password").fill("not the password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByText("That password isn’t right.", { exact: true }).waitFor();
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.locator(".tiles").waitFor();
    // The HttpOnly session survives a reload; page script cannot read it.
    await page.reload();
    await page.locator(".tiles").waitFor();
    assert.equal(await page.evaluate(() => document.cookie), "");
    assert.equal(await tile("Records").textContent(), "12");
    assert.equal(await tile("Active notes").textContent(), "1");
    assert.equal(await tile("Awaiting review").textContent(), "1");
    await page.screenshot({ path: path.join(output, "home.png"), fullPage: true });

    // Search from the top bar, inspect a source and switch to the captured original.
    await page.getByRole("searchbox", { name: "Search memory" }).fill("source");
    await page.keyboard.press("Enter");
    await page.locator(".results .hit").first().waitFor();
    assert(await page.locator(".results mark").count() > 0);
    await page.screenshot({ path: path.join(output, "search.png"), fullPage: true });
    await page.locator(".hit-body").first().click();
    await page.locator("#inspector .source").waitFor();
    await page.getByRole("button", { name: "Captured original" }).click();
    await page.locator("#inspector .source.raw").waitFor();
    await page.getByRole("button", { name: "Close inspector" }).click();
    assert.equal(await page.locator("#inspector").isHidden(), true);

    // Session transcript renders hostile captured text literally.
    await page.getByRole("link", { name: "Sessions" }).click();
    await page.locator(".session-row").first().click();
    await page.getByText("Fixture complete. These records are synthetic browser-test data.", { exact: true }).waitFor();
    assert.equal(await page.locator("main img").count(), 0);
    assert.equal(await page.evaluate(() => window.fixture_xss), undefined);
    await page.screenshot({ path: path.join(output, "session.png"), fullPage: true });

    // Context and timeline views load from the same project.
    await page.getByRole("link", { name: "Agent context" }).click();
    await page.getByText("Exact text sent to the agent").waitFor();
    await page.getByRole("link", { name: "Timeline" }).click();
    await page.locator(".timeline-bar .segment").first().waitFor();

    // Review: activate the candidate.
    await page.getByRole("link", { name: "Notes" }).click();
    await page.getByRole("button", { name: "Activate", exact: true }).click();
    await page.getByText("Nothing awaiting review", { exact: true }).waitFor();
    await page.getByRole("link", { name: /^Active/ }).click();
    await page.getByText("Decision: route native clients to the same scoped service on the execution host.", { exact: true }).waitFor();

    // Forget: cancelling keeps the chat; confirming removes it and its source-linked notes.
    await page.getByRole("link", { name: "Sessions" }).click();
    await page.locator(".session-row").first().click();
    await page.getByRole("button", { name: "Forget…" }).click();
    await page.locator("dialog[open]").getByText("fixture-session").waitFor();
    await page.screenshot({ path: path.join(output, "forget-chat.png") });
    await page.getByRole("button", { name: "Cancel" }).click();
    assert.equal(await page.locator("dialog[open]").count(), 0);
    assert.equal(await page.locator(".transcript .msg").count(), 12);
    await page.getByRole("button", { name: "Forget…" }).click();
    await page.getByRole("button", { name: "Remove from memory" }).click();
    await page.getByText("No sessions yet", { exact: true }).waitFor();
    await page.getByRole("link", { name: "Notes" }).click();
    await page.getByRole("link", { name: /^Active/ }).click();
    await page.getByText("No active notes", { exact: true }).waitFor();

    await page.getByRole("link", { name: "Connect agents" }).click();
    await page.getByRole("heading", { name: "memory", exact: true }).waitFor();

    // Mobile layout and project switching.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("link", { name: "Home", exact: true }).click();
    await page.locator(".tiles").waitFor();
    await page.screenshot({ path: path.join(output, "mobile.png"), fullPage: true });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await page.getByLabel("Memory project").selectOption("empty");
    await page.getByText("Nothing has been captured in this project yet.", { exact: true }).waitFor();
    assert.equal(await tile("Records").textContent(), "0");

    await page.setViewportSize({ width: 1440, height: 1000 });
    // Sign out ends the server session; a reload stays signed out.
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await page.getByLabel("Password").waitFor();
    await page.reload();
    await page.getByLabel("Password").waitFor();
    assert.equal(await page.locator("#app").isHidden(), true);

    // Token fallback: rejected token message, then a page-memory connection that a reload drops.
    await page.getByRole("button", { name: "Use an access token instead" }).click();
    await page.getByLabel("Access token").fill("not-a-real-token");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.getByText("This server didn’t accept that token", { exact: false }).waitFor();
    await page.getByLabel("Access token").fill(token);
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.locator(".tiles").waitFor();
    await page.reload();
    await page.getByLabel("Password").waitFor();
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
    assert.deepEqual(errors.filter(text => !text.includes("401")), []);
    console.log(JSON.stringify({ browser_smoke: "passed", desktop: "1440x1000", mobile: "390x844", checks: ["server check", "wrong password message", "password sign-in", "session survives reload", "cookie unreadable by script", "home counts", "top-bar search", "highlighted results", "source inspection", "captured original", "session transcript", "XSS literal rendering", "context view", "timeline view", "candidate activation", "cancel forget preserves chat", "confirmed forget removes chat and notes", "catalog", "mobile overflow", "project switch", "sign out", "signed out after reload", "rejected token message", "token connect", "token dropped on reload", "no persistent browser credentials", "no browser exceptions"], screenshots: output }));
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });

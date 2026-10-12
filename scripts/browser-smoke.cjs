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
  const browser = await chromium.launch({ headless: true, executablePath: process.env.AGENT_HUB_CHROMIUM_EXECUTABLE || undefined, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(info.url);
    await page.screenshot({ path: path.join(output, "welcome.png"), fullPage: true });
    await page.getByLabel("Connect with your access token").fill(fs.readFileSync(info.token_file, "utf8").trim());
    await page.getByRole("button", { name: "Connect →" }).click();
    await page.getByText("Current context pack", { exact: true }).waitFor();
    assert.equal(await page.locator(".stat strong").nth(0).textContent(), "12");
    assert.equal(await page.locator(".stat strong").nth(2).textContent(), "1");
    await page.screenshot({ path: path.join(output, "overview.png"), fullPage: true });
    await page.getByRole("button", { name: "Search memory" }).click();
    await page.getByLabel("Search memory", { exact: true }).fill("source");
    await page.getByRole("button", { name: "Search →", exact: true }).click();
    await page.getByRole("button", { name: "Open source →" }).first().waitFor();
    await page.screenshot({ path: path.join(output, "search.png"), fullPage: true });
    await page.getByRole("button", { name: "Open source →" }).first().click();
    await page.locator("dialog[open]").waitFor();
    await page.getByRole("button", { name: "Close details" }).click();
    await page.getByRole("button", { name: "Captured sessions" }).click();
    await page.getByRole("button", { name: "Inspect session →" }).click();
    await page.getByText("Fixture complete. These records are synthetic browser-test data.", { exact: true }).waitFor();
    assert.equal(await page.locator("img").count(), 0);
    assert.equal(await page.evaluate(() => window.fixture_xss), undefined);
    await page.getByRole("button", { name: "Close details" }).click();
    await page.getByRole("button", { name: "Review notes" }).click();
    await page.getByRole("button", { name: "Activate note" }).click();
    await page.getByText("No candidate notes.", { exact: true }).waitFor();
    await page.getByLabel("Memory status").selectOption("active");
    await page.getByRole("heading", { name: "Decision: route native clients to the same scoped service on the execution host.", exact: true }).waitFor();
    await page.getByRole("button", { name: "Captured sessions" }).click();
    await page.getByRole("button", { name: "Inspect session →" }).click();
    await page.getByRole("button", { name: "Forget this chat", exact: true }).waitFor();
    await page.screenshot({ path: path.join(output, "forget-chat.png"), fullPage: true });
    page.once("dialog", dialog => dialog.dismiss());
    await page.getByRole("button", { name: "Forget this chat", exact: true }).click();
    assert.equal(await page.locator("dialog[open]").count(), 1);
    page.once("dialog", async dialog => {
      assert(dialog.message().includes("fixture-session"));
      await dialog.accept();
    });
    await page.getByRole("button", { name: "Forget this chat", exact: true }).click();
    await page.getByText("No captured sessions yet.", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Review notes" }).click();
    await page.getByText("No active notes.", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Integrations" }).click();
    await page.getByText("memory", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Overview", exact: false }).click();
    await page.getByText("Current context pack", { exact: true }).waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(output, "mobile.png"), fullPage: true });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await page.getByLabel("MEMORY PROJECT").selectOption("empty");
    await page.getByText("The tree will appear as sessions are captured.", { exact: true }).waitFor();
    assert.equal(await page.locator(".stat strong").nth(0).textContent(), "0");
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole("button", { name: "Disconnect", exact: true }).click();
    await page.getByLabel("Connect with your access token").waitFor();
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ browser_smoke: "passed", desktop: "1440x1000", mobile: "390x844", checks: ["login", "overview counts", "search", "source inspection", "session inspection", "XSS literal rendering", "candidate activation", "cancel forget preserves chat", "confirmed forget removes chat and notes", "catalog", "project switch", "mobile overflow", "disconnect", "no persistent browser credentials", "no browser exceptions"], screenshots: output }));
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });

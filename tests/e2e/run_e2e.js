// End-to-end browser test of the whole Q-MigrateAI journey, with screenshots.
//
// The expected numbers (399 assets, 347 quantum-exposed...) come from the synthetic simulator, because live
// website measurements change every day. Start the platform on a FRESH database in simulator mode:
//   ENABLE_SIMULATOR=1 DATA_SOURCE=simulator python -m uvicorn qmigrate.server.app:app --port 8002
// then:
//   node tests/e2e/run_e2e.js
// Settings (environment variables): QM_URL (default http://127.0.0.1:8002), QM_SHOTS (screenshot folder),
// QM_DEMO_PASSWORD (default QuantumDemo!2026). Needs Node.js and Playwright with Chromium.
const { chromium } = require("playwright");
const assert = require("assert/strict");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const BASE = process.env.QM_URL || "http://127.0.0.1:8002";
const SHOTS = process.env.QM_SHOTS || path.join(__dirname, "screenshots");
const PW = process.env.QM_DEMO_PASSWORD || "QuantumDemo!2026";
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
let page, browser, context;
const problems = [];

async function step(name, fn) {
  const t0 = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - t0 });
    console.log(`  PASS  ${name} (${Date.now() - t0} ms)`);
  } catch (e) {
    results.push({ name, ok: false, error: e.message });
    console.log(`  FAIL  ${name}\n        ${e.message.split("\n")[0]}`);
    await page.screenshot({ path: path.join(SHOTS, `FAIL-${name.replace(/\W+/g, "_")}.png`), fullPage: true }).catch(() => {});
  }
}

const shot = (name, full = false) => page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: full });
const text = (sel) => page.locator(sel).first().innerText();
const go = async (hash) => {
  await page.goto(`${BASE}/#/${hash}`);
  await page.waitForFunction(() => !document.querySelector("#page .skeleton") || document.querySelector("#app form"), null, { timeout: 30000 });
};

function base32(s) {
  const alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of s.replace(/=+$/, "").toUpperCase()) bits += alpha.indexOf(c).toString(2).padStart(5, "0");
  const out = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(out);
}
function totp(secret, step) {
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(step));
  const h = crypto.createHmac("sha1", base32(secret)).update(msg).digest();
  const o = h[h.length - 1] & 0xf;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1e6).padStart(6, "0");
}
const nowStep = () => Math.floor(Date.now() / 1000 / 30);

async function login(email, password = PW) {
  await page.goto(`${BASE}/#/login`);
  await page.waitForSelector("#email");
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click("form button[type=submit]");
  await page.waitForFunction(() => /^#\/(dashboard|login-2fa|connect)/.test(location.hash), null, { timeout: 15000 });
}
async function logout() {
  await page.click("[data-logout]");
  await page.waitForFunction(() => location.hash.startsWith("#/login"));
}
async function waitHealthySeed() {
  // Demo seeding runs in the background after start-up (about half a minute).
  for (let i = 0; i < 180; i++) {
    const h = await (await page.request.get(`${BASE}/api/health`)).json();
    if (h.data_source && h.data_source !== "simulator") {
      throw new Error(`The server uses ${h.data_source} data. This test checks fixed simulator numbers: restart it with ENABLE_SIMULATOR=1 DATA_SOURCE=simulator on a fresh database.`);
    }
    if (h.demo_data === "ready") return;
    if (h.demo_data === "failed" || h.demo_data === "off") throw new Error(`Demo data is ${h.demo_data}; start the server with SEED_DEMO=1 on a fresh database.`);
    await page.waitForTimeout(1000);
  }
  throw new Error("Demo data was not ready after 3 minutes.");
}

(async () => {
  browser = await chromium.launch();
  context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  page = await context.newPage();
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/status of (400|401|501)/.test(m.text())) problems.push(`console: ${m.text()}`);
  });
  console.log(`Q-MigrateAI end-to-end test against ${BASE}`);
  await page.goto(BASE);
  await waitHealthySeed();

  await step("Login page shows the GDPR panel with the exact wording", async () => {
    await page.goto(`${BASE}/#/login`);
    await page.waitForSelector("#email");
    await shot("01-login");
    await page.click("[data-gdpr]");
    const body = await text("[role=dialog]");
    for (const s of ["We only read cryptographic metadata (key types, algorithms, certificates), never your files or customer data.",
      "Access is read-only and can be removed at any time.", "Data is stored in the EU and encrypted.",
      "Never shared with other customers or third parties.", "You can export or delete all your data at any time.",
      "Contact: privacy@awhlle.com"]) assert.ok(body.includes(s), `missing: ${s}`);
    assert.ok((await text("#modal-title")).includes("Your data and GDPR"));
    await shot("02-gdpr-panel");
    await page.keyboard.press("Escape");
  });

  await step("Login with Microsoft is an honest placeholder", async () => {
    await page.click("[data-ms]");
    await page.waitForSelector("[role=dialog]");
    assert.match(await text("[role=dialog]"), /not configured|not set up|placeholder/i);
    await page.keyboard.press("Escape");
  });

  await step("Wrong password is refused", async () => {
    await page.fill("#email", "ciso@demofinance.example");
    await page.fill("#password", "wrong-password-1A");
    await page.click("form button[type=submit]");
    await page.waitForSelector("[data-error]:not(.hidden)");
  });

  await step("Demo chip logs in the CISO and the dashboard shows the estate", async () => {
    await page.click('[data-demo="ciso@demofinance.example"]');
    await page.click("form button[type=submit]");
    await page.waitForFunction(() => location.hash.startsWith("#/dashboard"));
    await page.waitForSelector(".kpi-value");
    const t = await text("#page");
    assert.ok(t.includes("399"), "expected 399 assets");
    assert.ok(t.includes("347"), "expected 347 quantum-exposed");
    assert.ok(t.includes("PQC readiness"));
    await page.waitForTimeout(300);
    await shot("03-dashboard", true);
  });

  await step("Clicking a key on the map lights up its dependants", async () => {
    await go("graph");
    await page.waitForFunction(() => document.querySelector("#cy")?._cy);
    await page.waitForTimeout(600);
    const pos = await page.evaluate(() => {
      const cy = document.querySelector("#cy")._cy;
      const n = cy.getElementById("AWS-KMS-004");
      const r = document.querySelector("#cy").getBoundingClientRect();
      const p = n.renderedPosition();
      return { x: r.left + p.x, y: r.top + p.y };
    });
    await page.mouse.click(pos.x, pos.y);
    await page.waitForFunction(() => document.querySelector("#g-side")?.innerText.includes("Depend on it"));
    const dep = await page.evaluate(() => document.querySelector("#cy")._cy.nodes(".dep").length);
    assert.ok(dep >= 100, `expected 100+ dependants highlighted, got ${dep}`);
    assert.ok((await text("#g-side")).includes("AWS-KMS-004"));
    await page.waitForTimeout(500);
    await shot("04-graph-click");
  });

  let exposedBefore, exposedAfter;
  await step("Migrate Wave 1 live: nodes turn green and counters fall", async () => {
    exposedBefore = Number((await text("[data-k=exposed]")).replace(/\D/g, ""));
    await page.click("[data-wave]");
    await page.click("[data-ok]");
    await page.waitForTimeout(3200);
    await shot("05-wave-in-progress");
    await page.waitForFunction(() => document.querySelectorAll("#g-side [data-log] li").length >= 20, null, { timeout: 30000 });
    await page.waitForTimeout(800);
    exposedAfter = Number((await text("[data-k=exposed]")).replace(/\D/g, ""));
    assert.ok(exposedAfter < exposedBefore, `exposed should fall: ${exposedBefore} -> ${exposedAfter}`);
    await shot("06-wave-done");
    console.log(`        quantum-exposed ${exposedBefore} -> ${exposedAfter}`);
  });

  await step("What-if slider projects the effect of the top N", async () => {
    await go("plan");
    await page.waitForSelector("#w-n");
    await page.evaluate(() => { const s = document.querySelector("#w-n"); s.value = "30"; s.dispatchEvent(new Event("input")); });
    assert.equal((await text("[data-n]")).trim(), "30");
    assert.ok((await text("[data-proj]")).includes("today"));
    await shot("07-plan-whatif", true);
  });

  await step("Asset drawer explains the AI risk", async () => {
    await go("assets?focus=AWS-KMS-001");
    await page.waitForSelector("aside[role=dialog] h3");
    const t = await text("aside[role=dialog]");
    assert.ok(t.includes("In plain words") && t.includes("Formula breakdown") && t.includes("neural network"));
    await shot("08-asset-explain");
    await page.keyboard.press("Escape");
  });

  await step("PQC lab: validate, migrate, then roll back", async () => {
    const plan = await (await page.request.get(`${BASE}/api/plan`)).json();
    const target = plan.queue[0];
    await go(`lab?asset=${encodeURIComponent(target.asset_id)}`);
    await page.waitForSelector("[data-validate]");
    await page.click("[data-validate]");
    await page.waitForFunction(() => document.querySelector("[data-result]")?.innerText.includes("Projected effect"));
    assert.ok(await page.locator("[data-migrate]").isEnabled(), "Migrate should be enabled after a valid check");
    await shot("09-lab-validated", true);
    await page.click("[data-migrate]");
    await page.waitForSelector("[data-rollback]");
    assert.ok((await text("#page")).includes(target.target));
    await shot("10-lab-migrated");
    await page.click("[data-rollback]");
    await page.waitForFunction(() => !document.querySelector("[data-rollback]") && document.querySelector("[data-validate]"));
    const back = await (await page.request.get(`${BASE}/api/lab/${encodeURIComponent(target.asset_id)}`)).json();
    assert.equal(back.asset.algorithm, target.algorithm, "rollback should restore the original algorithm");
  });

  await step("Assistant answers from the inventory", async () => {
    await page.click("#assistant [data-open]");
    await page.fill("#assistant-input", "What should we migrate first?");
    await page.press("#assistant-input", "Enter");
    await page.waitForFunction(() => {
      const log = document.querySelector("#assistant [data-log]");
      return log && !log.innerText.includes("Looking at your inventory") && log.children.length >= 4;
    }, null, { timeout: 15000 });
    const t = await text("#assistant [data-log]");
    assert.match(t, /[A-Z]+-[A-Z]+-\d{3}/, "answer should name assets");
    await shot("11-assistant");
    await page.click("#assistant [data-close]");
  });

  await step("Model comparison shows five models", async () => {
    await go("models");
    await page.waitForSelector("[data-cm-body] table");
    assert.equal(await page.locator("table.tbl tbody tr").count(), 5);
    await shot("12-models", true);
  });

  await step("Report page and one-click PDF", async () => {
    await go("report");
    await page.waitForSelector("[data-pdf]");
    const t = await text("#page");
    assert.ok(t.includes("Before and after") && t.includes("Migration history"));
    await shot("13-report", true);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("[data-pdf]")]);
    const file = await dl.path();
    const head = fs.readFileSync(file).subarray(0, 5).toString();
    assert.equal(head, "%PDF-");
    assert.ok(fs.statSync(file).size > 5000);
    fs.copyFileSync(file, path.join(SHOTS, "sample-report.pdf"));
  });

  await step("Alerts and audit log record the work", async () => {
    await go("alerts");
    await page.waitForSelector("#page h2");
    await shot("14-alerts");
    await go("audit");
    await page.waitForSelector("[data-body] tr");
    const t = await text("[data-body]");
    assert.ok(t.includes("Migrated a wave") && t.includes("Rolled back an asset"), "audit should list the wave and the rollback");
    await shot("15-audit");
  });

  await step("Connect page explains read-only access, with the GDPR button", async () => {
    await go("connect");
    await page.waitForSelector("[data-setup]");
    assert.equal(await page.locator("#page [data-gdpr]").count(), 1);
    await page.click('[data-setup="aws"]');
    await page.waitForSelector("[role=dialog]");
    const t = await text("[role=dialog]");
    assert.ok(/SecurityAudit|read-only/i.test(t));
    await shot("16-connect-aws");
    await page.keyboard.press("Escape");
  });

  await step("Tenant isolation: the hospital never sees the bank's migrations", async () => {
    await logout();
    await login("admin@demohealth.example");
    await page.waitForSelector(".kpi-value");
    const mig = await (await page.request.get(`${BASE}/api/migrations`)).json();
    assert.equal(mig.length, 0, "Demo Health should have no migrations");
    const me = await (await page.request.get(`${BASE}/api/auth/me`)).json();
    assert.equal(me.tenant.name, "Demo Health Group");
    const t = await text("#page");
    assert.ok(!t.includes("347"), "should not show Demo Finance numbers");
    await shot("17-tenant-health", true);
    await logout();
  });

  await step("Viewer role is read-only", async () => {
    await login("viewer@demofinance.example");
    assert.equal(await page.locator('[data-nav="audit"]').count(), 0, "viewer must not see the audit log");
    await go("lab");
    await page.waitForSelector("#lab-asset");
    assert.equal(await page.locator("[data-migrate]").count(), 0);
    assert.equal(await page.locator("[data-validate]").count(), 0);
    const r = await page.request.post(`${BASE}/api/migrations/wave`, { data: { wave: "Wave 1" }, headers: { "X-QM-Request": "1" } });
    assert.equal(r.status(), 403);
    await logout();
  });

  const company = `E2E Test Company ${Date.now() % 100000}`;
  const email = `owner${Date.now() % 100000}@e2e-test.example`;
  const password = "E2eTestPass2026";
  await step("Sign-up needs GDPR consent, then creates a separate company", async () => {
    await page.goto(`${BASE}/#/signup`);
    await page.waitForSelector("#company");
    await page.fill("#company", company);
    await page.fill("#name", "Test Owner");
    await page.fill("#email", email);
    await page.fill("#password", password);
    await page.click("form button[type=submit]");
    assert.match(await text("[data-error]"), /privacy notice/i);
    await shot("18-signup-consent");
    await page.check("#consent");
    await page.click("form button[type=submit]");
    await page.waitForFunction(() => location.hash.startsWith("#/connect"));
    await page.waitForSelector("[data-run]");
    assert.ok((await text("#page")).includes("Your account is ready"));
  });

  await step("New company runs its first discovery", async () => {
    await page.click("[data-run]");
    await page.waitForFunction(() => document.querySelector("#page")?.innerText.includes("Running"), null, { timeout: 10000 });
    await shot("19-discovery-running");
    await page.waitForFunction(() => !document.querySelector("#page")?.innerText.includes("Running") &&
      document.querySelector("#page")?.innerText.includes("Completed"), null, { timeout: 120000 });
    await go("dashboard");
    await page.waitForSelector(".kpi-value");
  });

  let secret;
  await step("Two-factor: turn on with a QR code, then log in with a code", async () => {
    await go("settings?tab=account");
    await page.click("[data-2fa-setup]");
    await page.waitForSelector("[data-qr] svg");
    secret = (await text("[data-secret]")).trim();
    await shot("20-2fa-setup");
    const s = nowStep();
    await page.fill("#tf-on", totp(secret, s));
    await page.click("[data-2fa-on]");
    await page.waitForFunction(() => document.querySelector("[data-2fa-body]")?.innerText.includes("asks for a code"));
    await logout();
    await page.fill("#email", email);
    await page.fill("#password", password);
    await page.click("form button[type=submit]");
    await page.waitForFunction(() => location.hash.startsWith("#/login-2fa"));
    await page.fill("#code", totp(secret, s));   // same code again must be refused (replay)
    await page.click("form button[type=submit]");
    await page.waitForSelector("[data-error]:not(.hidden)");
    await page.fill("#code", totp(secret, s + 1));
    await page.click("form button[type=submit]");
    await page.waitForFunction(() => location.hash.startsWith("#/dashboard"));
  });

  await step("Settings: team, alerts and the Slack address check", async () => {
    await go("settings?tab=team");
    await page.click("[data-add]");
    await page.fill("#nu-name", "Second Analyst");
    await page.fill("#nu-email", `analyst${Date.now() % 100000}@e2e-test.example`);
    await page.click("[data-save]");
    await page.waitForSelector("[data-temp]");
    assert.ok((await text("[data-temp]")).length >= 10);
    await page.keyboard.press("Escape");
    await go("settings?tab=alerts");
    await page.fill("#s-slack", "https://evil.example/hook");
    await page.click("[data-form] button.btn-primary");
    await page.waitForFunction(() => document.querySelector("#toasts")?.innerText.includes("hooks.slack.com"));
    await shot("21-settings-alerts");
  });

  await step("GDPR: export all data, then delete the company", async () => {
    await go("settings?tab=privacy");
    assert.equal(await page.locator("#page [data-gdpr]").count(), 1);
    await shot("22-settings-privacy");
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("[data-export]")]);
    const data = JSON.parse(fs.readFileSync(await dl.path(), "utf8"));
    const blob = JSON.stringify(data);
    assert.ok(blob.includes(company), "export should contain the company");
    assert.ok(!/password_hash|totp_secret/.test(blob), "export must not contain secrets");
    await page.click("[data-delete]");
    await page.fill("#del-confirm", company);
    await page.click("[data-go]");
    await page.waitForFunction(() => location.hash.startsWith("#/login"));
    const r = await page.request.post(`${BASE}/api/auth/login`, { data: { email, password }, headers: { "X-QM-Request": "1" } });
    assert.equal(r.status(), 401, "deleted user must not log in");
  });

  await step("Privacy policy page is marked as a template for a lawyer", async () => {
    await page.goto(`${BASE}/#/privacy`);
    await page.waitForSelector("article h1");
    assert.ok((await text("article")).includes("to be reviewed by a lawyer"));
    await shot("23-privacy", true);
  });

  await step("Phone-sized screen", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login("ciso@demofinance.example");
    await page.waitForSelector(".kpi-value");
    await shot("24-mobile-dashboard", true);
    await page.click("[data-menu]");
    await page.waitForTimeout(300);
    await shot("25-mobile-menu");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    assert.ok(!overflow, "page should not scroll sideways on a phone");
  });

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} steps passed. Screenshots in ${SHOTS}`);
  if (problems.length) console.log("Browser problems:\n  " + [...new Set(problems)].join("\n  "));
  process.exit(failed.length || problems.length ? 1 : 0);
})().catch(async (e) => {
  console.error(e);
  await browser?.close();
  process.exit(1);
});

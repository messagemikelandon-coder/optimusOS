const { chromium } = require("playwright");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const invalidUsername = "owner-invalid-fixture";
const invalidPassword = "invalid-password-fixture";
const outDir = path.resolve("docs/screenshots/auth-integration");
const sessionCookieName = "optimus_session";
const skipDockerVerification = process.env.OPTIMUS_AUDIT_SKIP_DOCKER === "1";
const skipBillableFlows = process.env.OPTIMUS_AUDIT_SKIP_BILLABLE === "1";

function readDotEnvValue(key) {
  const envPath = path.resolve(".env");
  if (!fs.existsSync(envPath)) return "";
  const prefix = `${key}=`;
  const line = fs
    .readFileSync(envPath, "utf8")
    .split(/\n/)
    .map((entry) => entry.replace(/\r$/, ""))
    .find((entry) => entry.startsWith(prefix));
  if (!line) return "";
  return line.slice(prefix.length).trim();
}

const baseUrl = process.env.OPTIMUS_UI_URL || "http://127.0.0.1:5173";
const username = process.env.OPTIMUS_OWNER_USERNAME || readDotEnvValue("OPTIMUS_OWNER_USERNAME");
const password = process.env.OPTIMUS_OWNER_PASSWORD || readDotEnvValue("OPTIMUS_OWNER_PASSWORD");

function ensureDir() {
  fs.mkdirSync(outDir, { recursive: true });
}

async function screenshot(page, name) {
  ensureDir();
  await page.screenshot({ path: path.join(outDir, name), fullPage: true });
}

function fail(message) {
  throw new Error(message);
}

function sha256(value) {
  return crypto.createHash("sha256").update(value, "utf8").digest("hex");
}

function runDocker(args) {
  const result = spawnSync("docker", args, { encoding: "utf8" });
  if (result.status !== 0) {
    const message = result.stderr.trim() || result.stdout.trim() || "docker command failed";
    fail(message);
  }
  return result.stdout.trim();
}

function psqlValue(sql) {
  return runDocker([
    "compose",
    "exec",
    "-T",
    "postgres",
    "psql",
    "-U",
    "optimus",
    "-d",
    "optimus_os",
    "-At",
    "-c",
    sql,
  ]);
}

function dockerVerificationEnabled() {
  return !skipDockerVerification;
}

function billableFlowsEnabled() {
  return !skipBillableFlows;
}

async function getToastText(page) {
  await page.waitForSelector("#toast-region .toast", { timeout: 15000 });
  return page.locator("#toast-region .toast").last().innerText();
}

async function login(page) {
  await page.goto(`${baseUrl}/login`, { waitUntil: "networkidle" });
  await page.waitForSelector("#login-form");
  await page.fill("#login-username", username);
  await page.fill("#login-password", password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForSelector("#view-dashboard:not([hidden])", { timeout: 20000 });
  await page.waitForFunction(() => document.querySelector("#operator-name")?.textContent !== "Signed out");
}

async function logout(page) {
  await page.getByRole("button", { name: "Sign out" }).first().click();
  await page.waitForSelector("#view-login:not([hidden])", { timeout: 15000 });
}

async function expectToast(page, expectedText) {
  await page.waitForFunction(
    (needle) => {
      const toasts = Array.from(document.querySelectorAll("#toast-region .toast"));
      const last = toasts.at(-1);
      return Boolean(last && last.textContent && last.textContent.includes(needle));
    },
    expectedText,
    { timeout: 15000 },
  );
  const text = await getToastText(page);
  if (!text.includes(expectedText)) {
    fail(`Expected toast containing "${expectedText}" but received "${text}".`);
  }
}

async function clearToasts(page) {
  await page.evaluate(() => {
    const region = document.querySelector("#toast-region");
    if (region) {
      region.innerHTML = "";
    }
  });
}

function seedEstimateFixture({ zeroTotal = false } = {}) {
  const args = ["run", "python", "scripts/seed_estimate_approval_fixture.py"];
  if (zeroTotal) args.push("--zero-total");
  const result = spawnSync("uv", args, {
    encoding: "utf8",
    env: {
      ...process.env,
      UV_CACHE_DIR: "/tmp/uv-cache",
    },
  });
  if (result.status !== 0) {
    const message = result.stderr.trim() || result.stdout.trim() || "fixture seeding failed";
    fail(message);
  }
  const line = result.stdout
    .split(/\n/)
    .map((entry) => entry.trim())
    .filter(Boolean)
    .at(-1);
  if (!line) fail("Fixture seeding did not return JSON output.");
  try {
    return JSON.parse(line);
  } catch {
    fail("Fixture seeding returned malformed JSON.");
  }
}

async function main() {
  if (!username || !password) {
    fail("OPTIMUS_OWNER_USERNAME and OPTIMUS_OWNER_PASSWORD are required.");
  }

  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(() => {
    const clipboardStore = { value: "" };
    Object.defineProperty(window, "__auditClipboard", {
      value: clipboardStore,
      configurable: true,
    });
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async (text) => {
          clipboardStore.value = String(text);
        },
      },
      configurable: true,
    });
  });
  const page = await context.newPage();
  const consoleMessages = [];
  const failedRequests = [];
  const apiResponses = [];
  const summary = {
    baseUrl,
    loginUrl: `${baseUrl}/login`,
    protectedResponses: {},
    screenshots: [],
    localStorageKeys: [],
    sessionStorageKeys: [],
    cookie: null,
    authMe: null,
    database: {},
    verificationMode: {
      docker: dockerVerificationEnabled() ? "full" : "skipped",
      billableFlows: billableFlowsEnabled() ? "full" : "skipped",
    },
  };

  page.on("console", (msg) => {
    if (msg.type() === "error") {
      const text = msg.text();
      if (text.includes("status of 401 (Unauthorized)")) {
        return;
      }
      consoleMessages.push(`${msg.type()}: ${text}`);
    }
  });
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`);
  });
  page.on("dialog", async (dialog) => {
    await dialog.accept();
  });
  page.on("response", async (response) => {
    const url = response.url();
    if (url.includes("/api/")) {
      apiResponses.push({
        status: response.status(),
        method: response.request().method(),
        url,
      });
    }
  });

  await page.goto(`${baseUrl}/login`, { waitUntil: "networkidle" });
  await page.waitForSelector("#view-login:not([hidden])");
  await screenshot(page, "01-login-screen.png");
  summary.screenshots.push("docs/screenshots/auth-integration/01-login-screen.png");

  const loginTitle = await page.locator("#view-login h2").innerText();
  if (!/Sign in to Optimus/.test(loginTitle)) {
    fail("Unauthenticated login screen did not render.");
  }

  await page.fill("#login-username", invalidUsername);
  await page.fill("#login-password", invalidPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  const invalidToast = await getToastText(page);
  if (!invalidToast.includes("Invalid username or password")) {
    fail(`Invalid login feedback was not shown. Received: ${invalidToast}`);
  }
  await page.fill("#login-username", "");
  await page.fill("#login-password", "");

  await login(page);
  await screenshot(page, "02-dashboard-authenticated.png");
  summary.screenshots.push("docs/screenshots/auth-integration/02-dashboard-authenticated.png");

  const me = await page.evaluate(async () => {
    const response = await fetch("/api/auth/me", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    });
    const data = await response.json().catch(() => null);
    return { status: response.status, data };
  });
  if (me.status !== 200 || !me.data?.user || me.data.user.role !== "owner") {
    fail(`GET /api/auth/me did not return the authenticated owner session (status ${me.status}).`);
  }
  summary.authMe = { status: me.status, role: me.data.user.role };

  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector("#view-dashboard:not([hidden])", { timeout: 20000 });
  const restoredName = await page.locator("#operator-name").innerText();
  if (!restoredName || restoredName === "Signed out") {
    fail("Reload did not restore the authenticated session.");
  }

  const cookies = await context.cookies(baseUrl);
  const sessionCookie = cookies.find((cookie) => cookie.name === sessionCookieName);
  if (!sessionCookie) {
    fail("The browser did not receive the session cookie.");
  }
  if (!sessionCookie.httpOnly) {
    fail("The browser session cookie is not HttpOnly.");
  }
  summary.cookie = {
    name: sessionCookie.name,
    httpOnly: sessionCookie.httpOnly,
    sameSite: sessionCookie.sameSite,
    secure: sessionCookie.secure,
  };

  const rawToken = sessionCookie.value;
  const tokenHash = sha256(rawToken);
  if (dockerVerificationEnabled()) {
    const matchingHashCount = Number(psqlValue(`select count(*) from auth_sessions where token_hash = '${tokenHash}';`));
    const rawTokenCount = Number(psqlValue(`select count(*) from auth_sessions where token_hash = '${rawToken}';`));
    if (matchingHashCount !== 1) {
      fail(`Expected one stored hashed session record, found ${matchingHashCount}.`);
    }
    if (rawTokenCount !== 0) {
      fail("The raw session token appears to be stored in the database.");
    }
    summary.database.sessionHashStored = matchingHashCount === 1;
    summary.database.rawTokenStored = rawTokenCount > 0;
  } else {
    summary.database.sessionHashStored = "skipped";
    summary.database.rawTokenStored = "skipped";
  }

  const storage = await page.evaluate((cookieValue) => {
    const snapshot = (storageArea) => {
      const entries = [];
      for (let index = 0; index < storageArea.length; index += 1) {
        const key = storageArea.key(index);
        entries.push([key, storageArea.getItem(key)]);
      }
      return entries;
    };
    const localEntries = snapshot(window.localStorage);
    const sessionEntries = snapshot(window.sessionStorage);
    const containsToken = (entries) => entries.some(([key, value]) => {
      const joined = `${key || ""} ${value || ""}`.toLowerCase();
      return joined.includes("bearer")
        || joined.includes("token")
        || joined.includes(cookieValue.toLowerCase());
    });
    return {
      localEntries,
      sessionEntries,
      localContainsToken: containsToken(localEntries),
      sessionContainsToken: containsToken(sessionEntries),
    };
  }, rawToken);
  if (storage.localContainsToken || storage.sessionContainsToken) {
    fail("Browser storage contains a bearer token or raw session token.");
  }
  summary.localStorageKeys = storage.localEntries.map(([key]) => key);
  summary.sessionStorageKeys = storage.sessionEntries.map(([key]) => key);

  await page.locator('.nav-item[data-view="system"]').click();
  await page.waitForSelector("#view-system:not([hidden])");
  await page.locator("#view-system:not([hidden]) #postal-code").fill("95677");

  const location = await page.evaluate(async () => {
    const response = await fetch("/api/location/resolve", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ postal_code: "95677", country: "US" }),
    });
    const data = await response.json().catch(() => null);
    return { status: response.status, data };
  });
  if (location.status !== 200 || location.data?.postal_code !== "95677") {
    fail(`Location resolve failed with status ${location.status}.`);
  }
  summary.protectedResponses.location = location.status;

  const uniqueSuffix = Date.now().toString().slice(-6);
  const customerName = `Vehicle Audit ${uniqueSuffix}`;
  const firstVehicleVin = `1HGCM82633A${uniqueSuffix}`;
  const secondVehiclePlate = `CA${uniqueSuffix}`;
  await page.locator('.nav-item[data-view="customers"]').click();
  await page.waitForSelector("#view-customers:not([hidden])");
  await page.fill("#customer-company-name", customerName);
  await page.fill("#customer-email", `vehicle-audit-${uniqueSuffix}@example.com`);
  await page.fill("#customer-phone", "9165550101");
  await page.getByRole("button", { name: "Save customer" }).click();
  await expectToast(page, "Customer created.");
  await clearToasts(page);
  const selectedCustomerName = await page.locator("#customer-detail .customer-detail-header strong").innerText();
  if (!selectedCustomerName.includes(customerName)) {
    fail("Customer detail did not update after customer creation.");
  }

  await page.getByRole("button", { name: "Open Vehicles" }).click();
  await page.waitForSelector("#view-vehicles:not([hidden])");
  await page.waitForFunction(() => document.querySelectorAll("#vehicle-customer-id option").length > 1);
  await page.selectOption("#vehicle-customer-id", { label: customerName });
  const firstVehicleCustomerId = await page.locator("#vehicle-customer-id").inputValue();
  if (!firstVehicleCustomerId) {
    fail("Vehicle create form did not retain the selected customer.");
  }

  await page.fill("#vehicle-vin", firstVehicleVin);
  await page.fill("#vehicle-year", "2018");
  await page.fill("#vehicle-make", "Honda");
  await page.fill("#vehicle-model", "Civic");
  await page.fill("#vehicle-trim", "EX");
  await page.fill("#vehicle-engine", "2.0L I4");
  await page.fill("#vehicle-drivetrain", "FWD");
  await page.fill("#vehicle-transmission", "CVT");
  await page.fill("#vehicle-license-plate", "8abc123");
  await page.fill("#vehicle-license-plate-state", "ca");
  await page.fill("#vehicle-color", "Blue");
  await page.fill("#vehicle-current-mileage", "125000");
  const vehicleCreateRequestStart = apiResponses.length;
  await page.getByRole("button", { name: "Save vehicle" }).click();
  try {
    await expectToast(page, "Vehicle created.");
  } catch (error) {
    const recentVehicleResponses = apiResponses
      .slice(vehicleCreateRequestStart)
      .filter((entry) => entry.url.includes("/api/vehicles") || entry.url.includes("/api/customers/"));
    const lastToast = await page.locator("#toast-region .toast").last().innerText().catch(() => "");
    fail(`${error.message} Recent vehicle responses: ${JSON.stringify(recentVehicleResponses)} Last toast: ${lastToast}`);
  }
  await clearToasts(page);

  await page.getByRole("button", { name: "New vehicle" }).click();
  await page.selectOption("#vehicle-customer-id", { label: customerName });
  await page.fill("#vehicle-year", "2020");
  await page.fill("#vehicle-make", "Ford");
  await page.fill("#vehicle-model", "Transit");
  await page.fill("#vehicle-license-plate", secondVehiclePlate);
  await page.fill("#vehicle-license-plate-state", "CA");
  await page.fill("#vehicle-current-mileage", "88000");
  await page.fill("#vehicle-fleet-unit-number", "Unit 9");
  await page.getByRole("button", { name: "Save vehicle" }).click();
  await expectToast(page, "Vehicle created.");
  await clearToasts(page);

  await page.fill("#vehicles-search", firstVehicleVin);
  await page.waitForFunction(
    (vin) => {
      const items = Array.from(document.querySelectorAll("#vehicles-list .customer-list-item"));
      return items.length === 1 && items[0].innerText.includes(vin);
    },
    firstVehicleVin,
  );

  await page.fill("#vehicles-search", secondVehiclePlate);
  await page.waitForFunction(
    (plate) => {
      const items = Array.from(document.querySelectorAll("#vehicles-list .customer-list-item"));
      return items.length === 1 && items[0].innerText.toUpperCase().includes(plate.toUpperCase());
    },
    secondVehiclePlate,
  );

  await page.fill("#vehicles-search", "");
  await page.waitForFunction(() => document.querySelectorAll("#vehicles-list .customer-list-item").length >= 2);

  await page.fill("#vehicles-search", firstVehicleVin);
  await page.waitForFunction(
    (vin) => {
      const item = document.querySelector("#vehicles-list .customer-list-item");
      return Boolean(item) && item.innerText.includes(vin);
    },
    firstVehicleVin,
  );
  await page.locator("#vehicles-list .customer-list-item").first().click();
  await page.waitForFunction(
    (vin) => {
      const vehicleId = document.querySelector("#vehicle-id")?.value;
      const vinValue = document.querySelector("#vehicle-vin")?.value;
      return Boolean(vehicleId) && vinValue === vin;
    },
    firstVehicleVin,
  );
  await page.fill("#vehicle-current-mileage", "126500");
  const vehicleUpdateRequestStart = apiResponses.length;
  await page.getByRole("button", { name: "Save vehicle" }).click();
  await expectToast(page, "Vehicle updated.");
  await clearToasts(page);
  const updatedVehicleLookup = await page.evaluate(async (vin) => {
    const response = await fetch(`/api/vehicles?search=${encodeURIComponent(vin)}&archived=false`, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    });
    const data = await response.json().catch(() => null);
    return { status: response.status, data };
  }, firstVehicleVin);
  if (updatedVehicleLookup.status !== 200 || updatedVehicleLookup.data?.items?.[0]?.current_mileage !== 126500) {
    const recentVehicleResponses = apiResponses
      .slice(vehicleUpdateRequestStart)
      .filter((entry) => entry.url.includes("/api/vehicles"));
    fail(`Vehicle mileage update was not persisted. Recent update responses: ${JSON.stringify(recentVehicleResponses)} Lookup: ${JSON.stringify(updatedVehicleLookup)}`);
  }
  await page.fill("#vehicles-search", "");

  const selectedVehicleContext = await page.evaluate(async () => {
    const response = await fetch("/api/context/vehicles?scope=session", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    });
    const data = await response.json().catch(() => null);
    return { status: response.status, data };
  });
  const selectedVehicleEntry = selectedVehicleContext.data?.entries?.find(
    (entry) => entry.context_key === "selected-vehicle",
  );
  if (selectedVehicleContext.status !== 200 || !selectedVehicleEntry?.value) {
    fail("Selected vehicle context entry was not stored.");
  }
  let selectedVehicleValue = null;
  try {
    selectedVehicleValue = JSON.parse(selectedVehicleEntry.value);
  } catch {
    fail("Selected vehicle context entry was not valid JSON.");
  }
  if (!selectedVehicleValue?.id || selectedVehicleValue?.vin) {
    fail("Selected vehicle context stored more than the lightweight vehicle reference.");
  }

  await page.fill("#vehicles-search", secondVehiclePlate);
  await page.waitForFunction(
    (plate) => {
      const item = document.querySelector("#vehicles-list .customer-list-item");
      return Boolean(item) && item.innerText.toUpperCase().includes(plate.toUpperCase());
    },
    secondVehiclePlate,
  );
  await page.locator("#vehicles-list .customer-list-item").first().click();
  await page.getByRole("button", { name: "Archive" }).click();
  await expectToast(page, "Vehicle archived.");
  await clearToasts(page);
  await page.fill("#vehicles-search", "");
  await page.locator("#vehicles-archived-only").check();
  await page.waitForFunction(
    (plate) => Array.from(document.querySelectorAll("#vehicles-list .customer-list-item")).some(
      (item) => item.innerText.toUpperCase().includes(plate.toUpperCase()),
    ),
    secondVehiclePlate,
  );
  await screenshot(page, "03-vehicles-authenticated.png");
  summary.screenshots.push("docs/screenshots/auth-integration/03-vehicles-authenticated.png");
  summary.protectedResponses.vehicles = apiResponses
    .filter((entry) => entry.url.includes("/api/vehicles") || entry.url.includes("/api/customers/") && entry.url.includes("/vehicles"))
    .map((entry) => entry.status)
    .at(-1);
  if (summary.protectedResponses.vehicles !== 200) {
    fail(`Authenticated vehicle workflow ended with HTTP ${summary.protectedResponses.vehicles}.`);
  }

  if (billableFlowsEnabled()) {
    await page.getByRole("button", { name: "Talk to Optimus" }).first().click();
    await page.waitForSelector("#view-chat:not([hidden])");
    await page.fill("#chat-message", "Summarize what information you need before pricing a brake job.");
    await page.getByRole("button", { name: "Send" }).click();
    await page.waitForFunction(() => !document.querySelector("#chat-loading"), { timeout: 120000 });
    const assistantMessages = page.locator(".assistant-message");
    const chatText = await assistantMessages.last().innerText();
    if (!chatText || chatText.includes("Command failed")) {
      fail("Chat did not render a successful assistant response.");
    }
    await screenshot(page, "03-chat-authenticated.png");
    summary.screenshots.push("docs/screenshots/auth-integration/03-chat-authenticated.png");

    await page.locator('.nav-item[data-view="vehicles"]').click();
    await page.waitForSelector("#view-vehicles:not([hidden])");
    await page.locator("#vehicles-archived-only").uncheck();
    await page.fill("#vehicles-search", firstVehicleVin);
    await page.waitForFunction(
      (vin) => {
        const item = document.querySelector("#vehicles-list .customer-list-item");
        return Boolean(item) && item.innerText.includes(vin);
      },
      firstVehicleVin,
    );
    await page.locator("#vehicles-list .customer-list-item").first().click();
    await page.waitForFunction(
      (vin) => {
        const detail = document.querySelector("#vehicle-detail");
        return Boolean(detail && detail.textContent && detail.textContent.includes(vin));
      },
      firstVehicleVin,
    );

    await page.locator('.nav-item[data-view="estimate"]').click();
    await page.waitForSelector("#view-estimate:not([hidden])");
    const estimatePanel = page.locator("#view-estimate:not([hidden])");
    const selectedEstimateVehicle = await estimatePanel.locator("#estimate-selected-vehicle").innerText();
    if (!selectedEstimateVehicle.includes("Honda") && !selectedEstimateVehicle.includes("Civic")) {
      fail("Estimate view did not preserve the selected vehicle context.");
    }
    await estimatePanel.locator("#job").fill("Front brake pad replacement");
    const estimateRequestStart = apiResponses.length;
    await page.getByRole("button", { name: "Create saved estimate" }).click();
    await page.waitForFunction(
      () => Boolean(document.querySelector("#result .result-hero, #result .error-card")),
      { timeout: 180000 },
    );
    const estimateError = await page.locator("#result .error-card").count();
    if (estimateError > 0) {
      const errorText = await page.locator("#result .error-card").innerText();
      fail(`Estimate did not render successfully: ${errorText}`);
    }
    const estimateTitle = await page.locator("#result .result-hero h2").innerText();
    if (!estimateTitle.includes("Honda") && !estimateTitle.includes("Civic")) {
      fail("Estimate did not render the researched vehicle.");
    }
    const estimateContext = await page.evaluate(async () => {
      const response = await fetch("/api/context/estimates?scope=session", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      return { status: response.status, data };
    });
    const selectedEstimateEntry = estimateContext.data?.entries?.find(
      (entry) => entry.context_key === "selected-estimate",
    );
    if (estimateContext.status !== 200 || !selectedEstimateEntry?.value) {
      fail("Selected estimate context entry was not stored.");
    }
    let selectedEstimateValue = null;
    try {
      selectedEstimateValue = JSON.parse(selectedEstimateEntry.value);
    } catch {
      fail("Selected estimate context entry was not valid JSON.");
    }
    if (!selectedEstimateValue?.id || selectedEstimateValue?.token || selectedEstimateValue?.signature) {
      fail("Selected estimate context stored more than the lightweight estimate reference.");
    }
    const approvalRequestStart = apiResponses.length;
    await page.getByRole("button", { name: "Send for approval" }).click();
    await expectToast(page, "Approval link copied to the clipboard.");
    await clearToasts(page);
    const copiedApprovalLink = await page.evaluate(() => window.__auditClipboard?.value || "");
    if (!copiedApprovalLink.includes("/approval#token=")) {
      fail("Approval link was not copied in the expected hash-based format.");
    }
    const approvalStatus = apiResponses
      .slice(approvalRequestStart)
      .filter((entry) => entry.url.includes("/send-for-approval"))
      .map((entry) => entry.status)
      .at(-1);
    if (approvalStatus !== 200) {
      fail(`Send-for-approval ended with HTTP ${approvalStatus}.`);
    }
    await screenshot(page, "04-estimate-authenticated.png");
    summary.screenshots.push("docs/screenshots/auth-integration/04-estimate-authenticated.png");

    summary.protectedResponses.chat = apiResponses
      .filter((entry) => entry.url.includes("/api/chat"))
      .map((entry) => entry.status)
      .at(-1);
    summary.protectedResponses.estimate = apiResponses
      .slice(estimateRequestStart)
      .filter((entry) => entry.url.includes("/api/estimates"))
      .map((entry) => entry.status)
      .at(-1);
    summary.protectedResponses.approval = approvalStatus;
    if (summary.protectedResponses.chat !== 200) {
      fail(`Authenticated chat ended with HTTP ${summary.protectedResponses.chat}.`);
    }
    if (summary.protectedResponses.estimate !== 200) {
      fail(`Authenticated estimate ended with HTTP ${summary.protectedResponses.estimate}.`);
    }
    if (summary.protectedResponses.approval !== 200) {
      fail(`Authenticated approval-link flow ended with HTTP ${summary.protectedResponses.approval}.`);
    }
  } else {
    summary.protectedResponses.chat = "skipped";

    const seededEstimate = seedEstimateFixture();
    const seededZeroEstimate = seedEstimateFixture({ zeroTotal: true });
    summary.nonBillableApprovalProof = {
      seededEstimateId: seededEstimate.estimate_id,
      zeroTotalEstimateId: seededZeroEstimate.estimate_id,
    };

    await page.locator('.nav-item[data-view="customers"]').click();
    await page.waitForSelector("#view-customers:not([hidden])");
    await page.fill("#customers-search", seededEstimate.customer_display_name);
    await page.waitForFunction(
      (displayName) => Array.from(document.querySelectorAll("#customers-list .customer-list-item")).some(
        (item) => item.textContent?.includes(displayName),
      ),
      seededEstimate.customer_display_name,
    );
    await page.locator("#customers-list .customer-list-item").filter({ hasText: seededEstimate.customer_display_name }).first().click();
    await page.waitForFunction(
      (displayName) => document.querySelector("#customer-detail")?.textContent?.includes(displayName),
      seededEstimate.customer_display_name,
    );

    await page.getByRole("button", { name: "Open Vehicles" }).click();
    await page.waitForSelector("#view-vehicles:not([hidden])");
    await page.fill("#vehicles-search", seededEstimate.vehicle_display_name);
    await page.waitForFunction(
      (displayName) => Array.from(document.querySelectorAll("#vehicles-list .customer-list-item")).some(
        (item) => item.textContent?.includes(displayName),
      ),
      seededEstimate.vehicle_display_name,
    );
    await page.locator("#vehicles-list .customer-list-item").filter({ hasText: seededEstimate.vehicle_display_name }).first().click();
    await page.waitForFunction(
      (displayName) => document.querySelector("#vehicle-detail")?.textContent?.includes(displayName),
      seededEstimate.vehicle_display_name,
    );

    const selectedEstimateContext = await page.evaluate(async (fixture) => {
      const response = await fetch("/api/context/estimates/selected-estimate?scope=session", {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          value: JSON.stringify({
            id: fixture.estimate_id,
            estimate_number: fixture.estimate_number,
            revision_number: fixture.revision_number,
          }),
        }),
      });
      const data = await response.json().catch(() => null);
      return { status: response.status, data };
    }, seededEstimate);
    if (selectedEstimateContext.status !== 200) {
      fail(`Selected estimate context could not be stored (HTTP ${selectedEstimateContext.status}).`);
    }

    const estimateReloadStart = apiResponses.length;
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForFunction(() => document.querySelector("#operator-name")?.textContent !== "Signed out");
    await page.locator('.nav-item[data-view="estimate"]').click();
    await page.waitForSelector("#view-estimate:not([hidden])");
    await page.waitForFunction(
      (estimateNumber) => document.querySelector("#result .result-hero")?.textContent?.includes(estimateNumber),
      seededEstimate.estimate_number,
      { timeout: 20000 },
    );
    const estimateReloadStatus = apiResponses
      .slice(estimateReloadStart)
      .filter((entry) => entry.url.includes(`/api/estimates/${seededEstimate.estimate_id}`))
      .map((entry) => entry.status)
      .at(-1);
    if (estimateReloadStatus !== 200) {
      fail(`Reloaded estimate did not come back from PostgreSQL (HTTP ${estimateReloadStatus}).`);
    }
    const persistedEstimate = await page.evaluate(async (estimateId) => {
      const response = await fetch(`/api/estimates/${estimateId}`, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      return { status: response.status, data };
    }, seededEstimate.estimate_id);
    if (persistedEstimate.status !== 200 || Number(persistedEstimate.data?.current_revision?.estimate?.totals?.estimated_total || 0) <= 0) {
      fail("Persisted seeded estimate did not reload with a positive total.");
    }

    const approvalRequestStart = apiResponses.length;
    await page.getByRole("button", { name: "Send for approval" }).click();
    await expectToast(page, "Approval link copied to the clipboard.");
    await clearToasts(page);
    const copiedApprovalLink = await page.evaluate(() => window.__auditClipboard?.value || "");
    if (!copiedApprovalLink.includes("/approval#token=")) {
      fail("Approval link was not copied in the expected hash-based format.");
    }
    const approvalUrl = new URL(copiedApprovalLink, baseUrl);
    if (approvalUrl.pathname !== "/approval" || !approvalUrl.hash.startsWith("#token=")) {
      fail("Approval link did not retain the expected approval route.");
    }
    const approvalStatus = apiResponses
      .slice(approvalRequestStart)
      .filter((entry) => entry.url.includes("/send-for-approval"))
      .map((entry) => entry.status)
      .at(-1);
    if (approvalStatus !== 200) {
      fail(`Send-for-approval ended with HTTP ${approvalStatus}.`);
    }

    summary.protectedResponses.estimate = estimateReloadStatus;
    summary.protectedResponses.approval = approvalStatus;
    summary.nonBillableApprovalProof.approvalRoute = approvalUrl.pathname;

    await page.goto(approvalUrl.toString(), { waitUntil: "networkidle" });
    await page.waitForSelector("#view-approval:not([hidden])");
    await page.waitForSelector("#approval-action-form", { timeout: 20000 });
    if (new URL(page.url()).pathname !== "/approval") {
      fail(`Customer approval route navigated to ${new URL(page.url()).pathname} instead of /approval.`);
    }

    await page.reload({ waitUntil: "networkidle" });
    await page.waitForSelector("#view-approval:not([hidden])");
    await page.waitForSelector("#approval-action-form", { timeout: 20000 });
    if (new URL(page.url()).pathname !== "/approval") {
      fail("Refreshing the customer approval page did not preserve /approval.");
    }

    const approvalText = await page.locator("#approval-public-root").innerText();
    const expectedApprovalSnippets = [
      seededEstimate.customer_display_name,
      seededEstimate.vehicle_display_name,
      "Front brake pad set",
      "Front brake rotor",
      "Labor subtotal",
      "Parts subtotal",
      "Shop supplies",
      "Mobile service charge",
      "Parts tax",
      "Pay in full",
      "Two-month plan",
    ];
    for (const snippet of expectedApprovalSnippets) {
      if (!approvalText.includes(snippet)) {
        fail(`Approval page did not render expected customer-facing content: ${snippet}`);
      }
    }
    const forbiddenApprovalSnippets = [
      "supplier cost",
      "markup",
      "margin",
      "PAD-2018-CIVIC",
      "ROTOR-2018-CIVIC",
    ];
    for (const snippet of forbiddenApprovalSnippets) {
      if (approvalText.toLowerCase().includes(snippet.toLowerCase())) {
        fail(`Approval page exposed non-customer data: ${snippet}`);
      }
    }

    await screenshot(page, "04-approval-customer-view.png");
    summary.screenshots.push("docs/screenshots/auth-integration/04-approval-customer-view.png");

    await page.fill("#approval-name", "Fixture Customer");
    await page.fill("#approval-typed-authorization", "Fixture Customer approves this synthetic estimate revision.");
    await page.locator('input[name="approval-payment-option"][value="two_month_plan"]').check();
    await page.locator("#approval-accept-terms").check();
    await page.locator("#approval-ack-payment-plan").check();
    const approvalDecisionStart = apiResponses.length;
    await page.getByRole("button", { name: "Approve estimate" }).click();
    await page.waitForFunction(
      () => document.querySelector("#approval-public-root")?.textContent?.includes("Estimate approved"),
      { timeout: 20000 },
    );
    const approvalDecisionStatus = apiResponses
      .slice(approvalDecisionStart)
      .filter((entry) => entry.url.includes("/api/estimate-approval/approve"))
      .map((entry) => entry.status)
      .at(-1);
    if (approvalDecisionStatus !== 200) {
      fail(`Customer approval ended with HTTP ${approvalDecisionStatus}.`);
    }

    const approvalHistory = await page.evaluate(async (estimateId) => {
      const response = await fetch(`/api/estimates/${estimateId}/approval-history`, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      return { status: response.status, data };
    }, seededEstimate.estimate_id);
    const latestApprovalEvent = approvalHistory.data?.events?.at(-1);
    if (
      approvalHistory.status !== 200
      || latestApprovalEvent?.event_type !== "approved"
      || latestApprovalEvent?.payment_option !== "two_month_plan"
      || latestApprovalEvent?.revision_number !== seededEstimate.revision_number
    ) {
      fail("Approval history did not persist the approved revision and payment option.");
    }

    const approvedEstimate = await page.evaluate(async (estimateId) => {
      const response = await fetch(`/api/estimates/${estimateId}`, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      return { status: response.status, data };
    }, seededEstimate.estimate_id);
    if (
      approvedEstimate.status !== 200
      || approvedEstimate.data?.status !== "approved"
      || approvedEstimate.data?.payment_option_selected !== "two_month_plan"
    ) {
      fail("Approved estimate did not persist the approved status and payment option.");
    }

    const lockAttempt = await page.evaluate(async (estimateId) => {
      const response = await fetch(`/api/estimates/${estimateId}`, {
        method: "PATCH",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ terms_text: "Attempted post-approval edit." }),
      });
      const data = await response.json().catch(() => null);
      return { status: response.status, data };
    }, seededEstimate.estimate_id);
    if (lockAttempt.status !== 409) {
      fail(`Approved estimate was not locked. PATCH returned HTTP ${lockAttempt.status}.`);
    }

    await page.reload({ waitUntil: "networkidle" });
    await page.waitForSelector("#approval-public-root .error-card", { timeout: 20000 });
    if (new URL(page.url()).pathname !== "/approval") {
      fail("Approval token reuse refresh did not remain on /approval.");
    }
    const reusedTokenText = await page.locator("#approval-public-root .error-card").innerText();
    if (!reusedTokenText.includes("Approval token is invalid or unavailable.")) {
      fail("Approval token reuse did not fail with the expected sanitized message.");
    }

    const zeroSend = await page.evaluate(async (estimateId) => {
      const response = await fetch(`/api/estimates/${estimateId}/send-for-approval`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approval_method: "link", expires_in_hours: 72 }),
      });
      const data = await response.json().catch(() => null);
      return { status: response.status, data };
    }, seededZeroEstimate.estimate_id);
    if (zeroSend.status !== 422) {
      fail(`Zero-total estimate should be rejected before approval. HTTP ${zeroSend.status} received.`);
    }
    if (!JSON.stringify(zeroSend.data?.detail || "").toLowerCase().includes("zero-value")) {
      fail("Zero-total approval rejection did not return the expected sanitized validation error.");
    }

    summary.nonBillableApprovalProof = {
      ...summary.nonBillableApprovalProof,
      persistedEstimateTotal: approvedEstimate.data.current_revision.estimate.totals.estimated_total,
      approvalHistoryEvents: approvalHistory.data.events.map((event) => event.event_type),
      tokenReuseMessage: "Approval token is invalid or unavailable.",
      zeroTotalSendStatus: zeroSend.status,
      approvedEstimateLockedStatus: lockAttempt.status,
    };
  }

  await logout(page);
  await clearToasts(page);
  await page.waitForTimeout(400);
  await screenshot(page, "05-logged-out.png");
  summary.screenshots.push("docs/screenshots/auth-integration/05-logged-out.png");

  if (dockerVerificationEnabled()) {
    const revokedAt = psqlValue(`select coalesce(to_char(revoked_at, 'YYYY-MM-DD\"T\"HH24:MI:SSOF'), '') from auth_sessions where token_hash = '${tokenHash}' order by id desc limit 1;`);
    if (!revokedAt) {
      fail("Logout did not revoke the server-side session.");
    }
    summary.logoutRevokedSession = true;
  } else {
    summary.logoutRevokedSession = "verified via /api/auth/me 401 only";
  }
  const meAfterLogout = await page.evaluate(async () => {
    const response = await fetch("/api/auth/me", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    });
    const data = await response.json().catch(() => null);
    return { status: response.status, data };
  });
  if (meAfterLogout.status !== 401) {
    fail(`GET /api/auth/me after logout returned ${meAfterLogout.status} instead of 401.`);
  }

  await login(page);
  const cookiesAfterRelogin = await context.cookies(baseUrl);
  const activeCookie = cookiesAfterRelogin.find((cookie) => cookie.name === sessionCookieName);
  if (!activeCookie?.value) {
    fail("Expected a new session cookie after re-login.");
  }
  if (dockerVerificationEnabled()) {
    const expiringTokenHash = sha256(activeCookie.value);
    psqlValue(
      `update auth_sessions set expires_at = now() - interval '1 minute' where token_hash = '${expiringTokenHash}'; select 1;`,
    );
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForSelector("#view-login:not([hidden])", { timeout: 20000 });
    const expiredPath = await page.evaluate(() => window.location.pathname);
    if (expiredPath !== "/login") {
      fail(`Expired session did not return the browser to /login. Path was ${expiredPath}.`);
    }
    summary.expiredSessionReturnedToLogin = true;
  } else {
    await logout(page);
    await page.waitForSelector("#view-login:not([hidden])", { timeout: 15000 });
    summary.expiredSessionReturnedToLogin = "skipped";
  }
  await screenshot(page, "06-expired-session-login.png");
  summary.screenshots.push("docs/screenshots/auth-integration/06-expired-session-login.png");

  const authFailures = apiResponses.filter((entry) => entry.url.includes("/api/") && entry.status === 401);
  const allowed401s = authFailures.filter((entry) => (
    entry.url.includes("/api/auth/login")
    || entry.url.includes("/api/auth/me")
  ));
  if (authFailures.length !== allowed401s.length) {
    const unexpected = authFailures
      .filter((entry) => !allowed401s.includes(entry))
      .map((entry) => `${entry.method} ${entry.url}`)
      .join(" | ");
    fail(`Unexpected HTTP 401 observed during the audit: ${unexpected}`);
  }

  if (consoleMessages.length > 0) {
    fail(`Browser console reported errors: ${consoleMessages.join(" | ")}`);
  }
  if (failedRequests.length > 0) {
    fail(`Browser requests failed: ${failedRequests.join(" | ")}`);
  }

  summary.apiResponses = apiResponses;
  summary.invalidLoginHandled = true;
  summary.reloadRestoredSession = true;
  await browser.close();
  console.log(JSON.stringify(summary, null, 2));
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});

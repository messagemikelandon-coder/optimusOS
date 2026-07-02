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

async function main() {
  if (!username || !password) {
    fail("OPTIMUS_OWNER_USERNAME and OPTIMUS_OWNER_PASSWORD are required.");
  }

  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
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

    await page.locator('.nav-item[data-view="estimate"]').click();
    await page.waitForSelector("#view-estimate:not([hidden])");
    const estimatePanel = page.locator("#view-estimate:not([hidden])");
    await estimatePanel.locator("#year").fill("2020");
    await estimatePanel.locator("#make").fill("Toyota");
    await estimatePanel.locator("#model").fill("Camry");
    await estimatePanel.locator("#job").fill("Front brake pad replacement");
    await page.getByRole("button", { name: "Research and estimate" }).click();
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
    if (!estimateTitle.includes("Toyota") && !estimateTitle.includes("Camry")) {
      fail("Estimate did not render the researched vehicle.");
    }
    await screenshot(page, "04-estimate-authenticated.png");
    summary.screenshots.push("docs/screenshots/auth-integration/04-estimate-authenticated.png");

    summary.protectedResponses.chat = apiResponses
      .filter((entry) => entry.url.includes("/api/chat"))
      .map((entry) => entry.status)
      .at(-1);
    summary.protectedResponses.estimate = apiResponses
      .filter((entry) => entry.url.includes("/api/estimate"))
      .map((entry) => entry.status)
      .at(-1);
    if (summary.protectedResponses.chat !== 200) {
      fail(`Authenticated chat ended with HTTP ${summary.protectedResponses.chat}.`);
    }
    if (summary.protectedResponses.estimate !== 200) {
      fail(`Authenticated estimate ended with HTTP ${summary.protectedResponses.estimate}.`);
    }
  } else {
    summary.protectedResponses.chat = "skipped";
    summary.protectedResponses.estimate = "skipped";
  }

  await logout(page);
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

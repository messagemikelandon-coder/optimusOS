const { chromium } = require("playwright");
const path = require("path");

const baseUrl = process.env.OPTIMUS_UI_URL || "http://127.0.0.1:5173";
const outDir = path.resolve("docs/screenshots");

async function screenshot(page, name) {
  await page.screenshot({ path: path.join(outDir, name), fullPage: true });
}

async function main() {
  const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const consoleMessages = [];
  const failedRequests = [];
  const network = [];

  page.on("console", (msg) => {
    if (["error", "warning"].includes(msg.type())) {
      consoleMessages.push(`${msg.type()}: ${msg.text()}`);
    }
  });
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`);
  });
  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/api/") || url.endsWith("/health") || url.endsWith("/ready")) {
      network.push(`${response.status()} ${response.request().method()} ${url}`);
    }
  });

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForSelector("#dashboard-send");
  await screenshot(page, "repaired-dashboard.png");

  await page.getByRole("button", { name: "Talk to Optimus" }).first().click();
  await page.waitForSelector("#view-chat:not([hidden])");
  await screenshot(page, "optimus-chat.png");

  await page.fill("#chat-message", "Test local backend connection with synthetic data.");
  await page.getByRole("button", { name: "Send" }).click();
  await page.waitForSelector(".assistant-message:has-text('Command failed')", { timeout: 15000 });

  await page.getByRole("button", { name: "Job estimator" }).click();
  await page.waitForSelector("#view-estimate:not([hidden])");
  await screenshot(page, "estimates.png");

  await page.getByRole("button", { name: "System bay" }).click();
  await page.waitForSelector("#view-system:not([hidden])");
  await page.fill("#postal-code", "95677");
  await page.getByRole("button", { name: "Job estimator" }).click();
  await page.waitForSelector("#view-estimate:not([hidden])");

  await page.fill("#year", "2020");
  await page.fill("#make", "Toyota");
  await page.fill("#model", "Camry");
  await page.fill("#job", "Synthetic front brake pad replacement test");
  await page.getByRole("button", { name: "Research and estimate" }).click();
  await page.waitForSelector("#result .error-card, #result .loading-panel", { timeout: 15000 });
  await page.waitForSelector("#result .error-card", { timeout: 15000 });

  await page.getByRole("button", { name: "System bay" }).click();
  await page.waitForSelector("#view-system:not([hidden])");
  await page.getByRole("button", { name: "Run check" }).click();
  await page.waitForSelector("#system-server-status:text('Online')", { timeout: 10000 });
  await screenshot(page, "system-status.png");

  await browser.close();

  console.log(JSON.stringify({
    baseUrl,
    consoleMessages,
    failedRequests,
    network,
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

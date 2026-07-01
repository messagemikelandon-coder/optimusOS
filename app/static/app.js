"use strict";

const $ = (id) => document.getElementById(id);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const money = (value) => new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
}).format(Number(value || 0));
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const state = {
  auth: { authenticated: false, user: null, expiresAt: null },
  coordinates: null,
  chatHistory: [],
  currentView: "dashboard",
  health: null,
  lastEstimate: null,
};

const viewMeta = {
  login: { eyebrow: "Authentication", title: "Sign in" },
  dashboard: { eyebrow: "Operations", title: "Command deck" },
  chat: { eyebrow: "Owner channel", title: "Talk to Optimus" },
  estimate: { eyebrow: "Pricing workflow", title: "Job estimator" },
  system: { eyebrow: "Configuration", title: "System bay" },
};

function showToast(message, type = "info") {
  const region = $("toast-region");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  region.append(toast);
  window.setTimeout(() => toast.remove(), 4800);
}

function apiFetch(path, options = {}) {
  const { headers = {}, ...fetchOptions } = options;
  return fetch(path, {
    ...fetchOptions,
    credentials: "same-origin",
    headers,
  });
}

async function readApiPayload(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }
  try {
    return { detail: await response.text() };
  } catch {
    return null;
  }
}

function apiError(response, data, fallback) {
  const detail = data?.detail;
  if (typeof detail === "string" && detail.trim()) return new Error(detail);
  if (detail && typeof detail === "object") {
    const message = detail.message || fallback;
    const context = [detail.code, detail.stage, detail.request_id]
      .filter(Boolean)
      .join(" · ");
    return new Error(context ? `${message} (${context})` : message);
  }
  return new Error(`${fallback} (HTTP ${response.status})`);
}

function setAuthState(authenticated, user = null, expiresAt = null) {
  state.auth = { authenticated, user, expiresAt };
  $("topbar-login-link").hidden = authenticated;
  $("topbar-logout").hidden = !authenticated;
  $("system-login-link").hidden = authenticated;
  $("system-logout").hidden = !authenticated;

  if (authenticated && user) {
    $("operator-name").textContent = user.display_name || user.username;
    $("operator-role").textContent = user.role;
    $("system-auth-state").textContent = "Authenticated";
    $("system-auth-detail").textContent = expiresAt
      ? `Session active until ${new Date(expiresAt).toLocaleString()}.`
      : "Session active.";
    $("auth-status-title").textContent = "Signed in";
    $("auth-status-detail").textContent = "Authenticated workflows are available.";
    return;
  }

  $("operator-name").textContent = "Signed out";
  $("operator-role").textContent = "Authentication required";
  $("system-auth-state").textContent = "Authentication required";
  $("system-auth-detail").textContent = "Sign in before using chat, estimates, or location research.";
  $("auth-status-title").textContent = "Authentication required";
  $("auth-status-detail").textContent = "Sign in before using chat, estimates, or location research.";
}

async function loadSession() {
  try {
    const response = await apiFetch("/api/auth/me", { cache: "no-store" });
    const data = await readApiPayload(response);
    if (response.status === 401) {
      setAuthState(false);
      return false;
    }
    if (!response.ok || !data) throw apiError(response, data, "Session check failed");
    setAuthState(true, data.user, data.expires_at);
    return true;
  } catch (error) {
    setAuthState(false);
    showToast(`Session check failed: ${error.message}`, "error");
    return false;
  }
}

async function requireAuthenticated(view = "login") {
  if (state.auth.authenticated) return true;
  await loadSession();
  if (state.auth.authenticated) return true;
  showToast("Sign in is required for this workflow.", "error");
  navigate(view);
  return false;
}

async function handleLoginSubmit(event) {
  event.preventDefault();
  const submit = $("login-submit");
  submit.disabled = true;
  submit.textContent = "Signing in…";
  try {
    const response = await apiFetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: $("login-username").value.trim(),
        password: $("login-password").value,
      }),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Sign-in failed");
    setAuthState(true, data.user, data.expires_at);
    $("login-password").value = "";
    showToast("Signed in.", "success");
    navigate("dashboard");
  } catch (error) {
    setAuthState(false);
    showToast(`Sign-in failed: ${error.message}`, "error");
  } finally {
    submit.disabled = false;
    submit.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m10 17 5-5-5-5v10Zm-6 4V3h2v18H4Zm14 0h2V3h-2v18Z"/></svg> Sign in';
  }
}

async function performLogout() {
  try {
    const response = await apiFetch("/api/auth/logout", { method: "POST" });
    const data = await readApiPayload(response);
    if (!response.ok) throw apiError(response, data, "Sign-out failed");
  } catch (error) {
    showToast(`Sign-out failed: ${error.message}`, "error");
  } finally {
    setAuthState(false);
    state.chatHistory = [];
    navigate("login");
  }
}

function navigate(view) {
  if (!viewMeta[view]) return;
  if (view !== "login" && !state.auth.authenticated) {
    history.replaceState(null, "", "/login");
    return navigate("login");
  }
  state.currentView = view;
  $$('[data-view-panel]').forEach((panel) => {
    const active = panel.dataset.viewPanel === view;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
  $$('[data-view]').forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("is-active", active);
    if (button.classList.contains("nav-item")) {
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
  });
  $("view-eyebrow").textContent = viewMeta[view].eyebrow;
  $("view-title").textContent = viewMeta[view].title;
  $("sidebar").classList.remove("is-open");
  $("mobile-menu").setAttribute("aria-expanded", "false");
  if (view === "login") history.replaceState(null, "", "/login");
  else if (window.location.pathname === "/login") history.replaceState(null, "", "/");
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (view === "chat") window.setTimeout(() => $("chat-message").focus(), 180);
  if (view === "login") window.setTimeout(() => $("login-username").focus(), 180);
}

function initializeNavigation() {
  $$('[data-view]').forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.view));
  });
  $("topbar-login-link").addEventListener("click", (event) => {
    event.preventDefault();
    navigate("login");
  });
  $("system-login-link").addEventListener("click", (event) => {
    event.preventDefault();
    navigate("login");
  });
  ["topbar-logout", "system-logout"].forEach((id) => {
    $(id).addEventListener("click", () => {
      void performLogout();
    });
  });
  $("mobile-menu").addEventListener("click", () => {
    const sidebar = $("sidebar");
    const open = sidebar.classList.toggle("is-open");
    $("mobile-menu").setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      $("sidebar").classList.remove("is-open");
      $("mobile-menu").setAttribute("aria-expanded", "false");
    }
  });
}

function initializeTilt() {
  if (window.matchMedia("(pointer: coarse)").matches || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const tiltClasses = ["tilt-nw", "tilt-n", "tilt-ne", "tilt-w", "tilt-e", "tilt-sw", "tilt-s", "tilt-se"];
  $$("[data-tilt-strength]").forEach((card) => {
    card.addEventListener("pointermove", (event) => {
      const rect = card.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width;
      const y = (event.clientY - rect.top) / rect.height;
      const horizontal = x < .34 ? "w" : x > .66 ? "e" : "";
      const vertical = y < .34 ? "n" : y > .66 ? "s" : "";
      card.classList.remove(...tiltClasses);
      const key = `tilt-${vertical}${horizontal}`;
      if (tiltClasses.includes(key)) card.classList.add(key);
    });
    card.addEventListener("pointerleave", () => card.classList.remove(...tiltClasses));
  });
}

function loadSavedPreferences() {
  try {
    const savedLocation = JSON.parse(localStorage.getItem("optimus_location_preferences") || "null");
    if (savedLocation) {
      $("postal-code").value = savedLocation.postal_code || "";
      $("city").value = savedLocation.city || "";
      $("region").value = savedLocation.region || "";
    }
    const savedPricing = JSON.parse(localStorage.getItem("optimus_pricing_preferences") || "null");
    if (savedPricing) {
      $("labor-rate").value = savedPricing.labor_rate ?? 100;
      $("mobile-fee").value = savedPricing.mobile_fee ?? 0;
      $("supplies").value = savedPricing.supplies ?? 0;
      $("tax-rate").value = savedPricing.tax_rate ?? 0;
    }
  } catch {
    localStorage.removeItem("optimus_location_preferences");
    localStorage.removeItem("optimus_pricing_preferences");
  }
  try {
    state.coordinates = JSON.parse(sessionStorage.getItem("optimus_coordinates") || "null");
  } catch {
    sessionStorage.removeItem("optimus_coordinates");
  }
  updateLocationLabels();
}

function saveLocationPreferences() {
  localStorage.setItem("optimus_location_preferences", JSON.stringify({
    postal_code: $("postal-code").value.trim(),
    city: $("city").value.trim(),
    region: $("region").value.trim(),
  }));
  updateLocationLabels();
}

function savePricingPreferences() {
  localStorage.setItem("optimus_pricing_preferences", JSON.stringify({
    labor_rate: numericValue("labor-rate") ?? 100,
    mobile_fee: numericValue("mobile-fee") ?? 0,
    supplies: numericValue("supplies") ?? 0,
    tax_rate: numericValue("tax-rate") ?? 0,
  }));
}

function currentLocationLabel() {
  if (state.coordinates) return "Current coordinates";
  const postalCode = $("postal-code").value.trim();
  const city = $("city").value.trim();
  const region = $("region").value.trim();
  if (postalCode) return `ZIP ${postalCode}`;
  if (city && region) return `${city}, ${region}`;
  return "Location not set";
}

function updateLocationLabels() {
  const label = currentLocationLabel();
  $("top-location-label").textContent = label;
  $("chat-location-label").textContent = label;
  if (state.coordinates) {
    $("location-status").textContent = `Browser location ready (±${Math.round(state.coordinates.accuracy_m || 0)} m)`;
  } else if (label !== "Location not set") {
    $("location-status").textContent = `${label} will be used for store research`;
  } else {
    $("location-status").textContent = "Location not supplied";
  }
}

function initializeLocation() {
  ["postal-code", "city", "region"].forEach((id) => {
    $(id).addEventListener("input", saveLocationPreferences);
  });
  $("use-location").addEventListener("click", () => {
    if (!navigator.geolocation) {
      $("location-status").textContent = "This browser does not support geolocation.";
      showToast("Browser location is unavailable. Enter ZIP or city and state.", "error");
      return;
    }
    $("location-status").textContent = "Requesting browser permission…";
    navigator.geolocation.getCurrentPosition(
      (position) => {
        state.coordinates = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy_m: position.coords.accuracy,
        };
        sessionStorage.setItem("optimus_coordinates", JSON.stringify(state.coordinates));
        updateLocationLabels();
        showToast("Current location is ready for nearby-store research.", "success");
      },
      (error) => {
        state.coordinates = null;
        sessionStorage.removeItem("optimus_coordinates");
        $("location-status").textContent = `Location unavailable: ${error.message}`;
        showToast("Location permission was not granted. Enter ZIP or city and state.", "error");
      },
      { enableHighAccuracy: false, timeout: 12000, maximumAge: 300000 },
    );
  });
}

function numericValue(id) {
  const raw = $(id).value.trim();
  return raw === "" ? null : Number(raw);
}

function vehiclePayload() {
  const vin = $("vin").value.trim();
  const year = numericValue("year");
  const make = $("make").value.trim();
  const model = $("model").value.trim();
  const engine = $("engine").value.trim();
  const drivetrain = $("drivetrain").value.trim();
  return {
    vin: vin || null,
    year,
    make: make || null,
    model: model || null,
    engine: engine || null,
    drivetrain: drivetrain || null,
  };
}

function locationPayload() {
  const payload = {
    coordinates: state.coordinates,
    postal_code: $("postal-code").value.trim() || null,
    city: $("city").value.trim() || null,
    region: $("region").value.trim() || null,
    country: "US",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || null,
  };
  return payload.coordinates || payload.postal_code || (payload.city && payload.region) ? payload : null;
}

function inlineMarkup(value) {
  let text = escapeHtml(value);
  text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return text;
}

function renderRichText(value) {
  const lines = String(value ?? "").replaceAll("\r\n", "\n").split("\n");
  const output = [];
  let listType = null;
  let inCode = false;
  let codeLines = [];
  const closeList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = null;
  };
  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      closeList();
      if (inCode) {
        output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(rawLine);
      continue;
    }
    if (!line.trim()) {
      closeList();
      continue;
    }
    const heading = line.match(/^(#{2,4})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = Math.min(4, heading[1].length + 1);
      output.push(`<h${level}>${inlineMarkup(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    const numbered = line.match(/^\d+[.)]\s+(.+)$/);
    if (bullet || numbered) {
      const wanted = bullet ? "ul" : "ol";
      if (listType !== wanted) {
        closeList();
        output.push(`<${wanted}>`);
        listType = wanted;
      }
      output.push(`<li>${inlineMarkup((bullet || numbered)[1])}</li>`);
      continue;
    }
    closeList();
    output.push(`<p>${inlineMarkup(line)}</p>`);
  }
  closeList();
  if (inCode) output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  return output.join("");
}

function citationMarkup(citations) {
  if (!citations?.length) return "";
  const links = citations.map((citation) => (
    `<a href="${escapeHtml(citation.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(citation.title)}</a>`
  )).join("");
  return `<div class="message-citations"><strong>Research sources</strong>${links}</div>`;
}

function appendMessage(role, content, options = {}) {
  const feed = $("chat-feed");
  const article = document.createElement("article");
  article.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;
  if (options.id) article.id = options.id;
  const speaker = role === "user" ? "Dejake" : "Optimus";
  const status = options.status || new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const contentHtml = options.loading
    ? '<div class="typing-dots" aria-label="Optimus is working"><i></i><i></i><i></i></div>'
    : `${renderRichText(content)}${citationMarkup(options.citations)}`;
  article.innerHTML = `
    <div class="message-avatar"><span class="avatar-core"></span></div>
    <div class="message-content">
      <header><strong>${speaker}</strong><span>${escapeHtml(status)}</span></header>
      ${contentHtml}
    </div>`;
  feed.append(article);
  feed.scrollTop = feed.scrollHeight;
  return article;
}

async function runChat(message) {
  const text = String(message || "").trim();
  if (!text) return;
  navigate("chat");
  const button = $("chat-submit");
  button.disabled = true;
  button.textContent = "Working…";
  appendMessage("user", text);
  const loading = appendMessage("assistant", "", { id: "chat-loading", loading: true, status: "Researching" });

  try {
    const response = await apiFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        mode: $("chat-mode").value,
        location: locationPayload(),
        history: state.chatHistory.slice(-20),
        requested_agents: [],
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
    loading.remove();
    appendMessage("assistant", data.answer, {
      citations: data.citations,
      status: data.consultations?.length ? "Silent review complete" : "Direct response",
    });
    state.chatHistory.push({ role: "user", content: text });
    state.chatHistory.push({ role: "assistant", content: data.answer });
  } catch (error) {
    loading.remove();
    appendMessage("assistant", `Command failed: ${error.message}`, { status: "Error" });
    showToast(`Optimus request failed: ${error.message}`, "error");
  } finally {
    button.disabled = false;
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m3 20 18-8L3 4v6l12 2-12 2v6Z"/></svg> Send';
    $("chat-message").focus();
  }
}

function initializeChat() {
  $("chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!await requireAuthenticated("login")) return;
    const input = $("chat-message");
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    await runChat(message);
  });
  $("chat-message").addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key === "Enter") {
      event.preventDefault();
      $("chat-form").requestSubmit();
    }
  });
  $("dashboard-send").addEventListener("click", async () => {
    if (!await requireAuthenticated("login")) return;
    const input = $("dashboard-command");
    const message = input.value.trim();
    if (!message) {
      showToast("Enter a command for Optimus.", "error");
      input.focus();
      return;
    }
    input.value = "";
    await runChat(message);
  });
  $("dashboard-command").addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key === "Enter") $("dashboard-send").click();
  });
  $$(".quick-prompt").forEach((button) => {
    button.addEventListener("click", () => {
      navigate("chat");
      $("chat-message").value = button.dataset.prompt || "";
      $("chat-message").focus();
      $("chat-message").setSelectionRange($("chat-message").value.length, $("chat-message").value.length);
    });
  });
}

function estimateText(data) {
  const vehicle = [data.vehicle.year, data.vehicle.make, data.vehicle.model, data.vehicle.engine].filter(Boolean).join(" ");
  const parts = data.selected_parts.map((part) => (
    `${part.part_name} x${part.quantity}: ${money(part.extended_price)} — ${part.retailer}`
  )).join("\n");
  return [
    "LANDON MOTOR WORKS — JOB ESTIMATE",
    vehicle,
    data.job,
    "",
    `Labor: ${data.totals.labor_hours} hr × ${money(data.totals.labor_rate)} = ${money(data.totals.labor_total)}`,
    `Parts: ${money(data.totals.parts_subtotal)}`,
    `Shop supplies: ${money(data.totals.shop_supplies)}`,
    `Mobile fee: ${money(data.totals.mobile_service_fee)}`,
    `Parts tax: ${money(data.totals.parts_tax)}`,
    `Estimated total: ${money(data.totals.estimated_total)}`,
    "",
    parts,
    "",
    `Practical working time: ${data.totals.practical_time_low}–${data.totals.practical_time_high} hr`,
  ].filter((line, index, all) => line !== "" || all[index - 1] !== "").join("\n");
}

function renderEstimate(data) {
  state.lastEstimate = data;
  const result = $("result");
  const vehicle = [data.vehicle.year, data.vehicle.make, data.vehicle.model, data.vehicle.trim, data.vehicle.engine].filter(Boolean).join(" ") || data.vehicle.vin || "Vehicle";
  const parts = data.selected_parts.map((part) => `
    <article class="part-card">
      <div>
        <strong>${escapeHtml(part.part_name)} × ${part.quantity}</strong>
        <span>${escapeHtml([part.brand, part.part_number].filter(Boolean).join(" ") || "Part number not exposed")}</span>
        <span>${escapeHtml(part.retailer)} · ${escapeHtml(part.availability)}${part.store_name ? ` · ${escapeHtml(part.store_name)}` : ""}</span>
      </div>
      <div class="part-price"><strong>${money(part.extended_price)}</strong><a href="${escapeHtml(part.url)}" target="_blank" rel="noopener noreferrer">Open source</a></div>
    </article>`).join("");
  const tools = data.research.labor.special_tools.map((tool) => `<li>${escapeHtml(tool)}</li>`).join("") || "<li>None identified.</li>";
  const risks = data.research.labor.risk_flags.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("") || "<li>None identified.</li>";
  const warnings = data.research.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("") || "<li>None.</li>";
  const sources = data.research.citations.map((citation) => `<a href="${escapeHtml(citation.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(citation.title)}</a>`).join("") || "<p>No source links were returned.</p>";

  result.innerHTML = `
    <div class="result-hero">
      <div><span class="section-kicker"><i></i> Research complete</span><h2>${escapeHtml(vehicle)}</h2><p>${escapeHtml(data.job)}</p></div>
      <div class="result-total"><span>Estimated total</span><strong>${money(data.totals.estimated_total)}</strong></div>
    </div>
    <div class="result-actions">
      <button class="secondary-button compact" type="button" id="copy-estimate">Copy estimate</button>
      <button class="secondary-button compact" type="button" id="print-estimate">Print estimate</button>
      <button class="text-button" type="button" id="new-estimate">Start another</button>
    </div>
    <div class="money-grid">
      <div class="money-card"><span>Labor (${data.totals.labor_hours} hr)</span><strong>${money(data.totals.labor_total)}</strong></div>
      <div class="money-card"><span>Selected parts</span><strong>${money(data.totals.parts_subtotal)}</strong></div>
      <div class="money-card"><span>Shop supplies</span><strong>${money(data.totals.shop_supplies)}</strong></div>
      <div class="money-card"><span>Mobile fee</span><strong>${money(data.totals.mobile_service_fee)}</strong></div>
      <div class="money-card"><span>Parts tax</span><strong>${money(data.totals.parts_tax)}</strong></div>
    </div>
    <div class="result-grid">
      <section class="result-section">
        <h3>Selected priced parts</h3>
        <div class="parts-list">${parts || "<p>No currently priced part option could be selected. Review the source links for products with hidden pricing.</p>"}</div>
      </section>
      <section class="result-section">
        <h3>Labor and practical time</h3>
        <p><strong>Published/book:</strong> ${data.research.labor.book_hours} hr</p>
        <p><strong>Practical mobile range:</strong> ${data.totals.practical_time_low}–${data.totals.practical_time_high} hr</p>
        <p><strong>Confidence:</strong> ${escapeHtml(data.research.labor.confidence)}</p>
        <p>${escapeHtml(data.research.labor.basis)}</p>
      </section>
      <section class="result-section"><h3>Special tools</h3><ul>${tools}</ul></section>
      <section class="result-section"><h3>Risk flags</h3><ul>${risks}</ul></section>
      <section class="result-section"><h3>Warnings</h3><ul>${warnings}</ul></section>
      <section class="result-section"><h3>Research sources</h3><div class="source-list">${sources}</div></section>
      ${data.research.request_id ? `<section class="result-section"><h3>Research trace</h3><p>${escapeHtml(data.research.request_id)} · ${escapeHtml(data.research.research_mode || "standard")}</p></section>` : ""}
    </div>`;
  result.hidden = false;
  result.scrollIntoView({ behavior: "smooth", block: "start" });
  $("copy-estimate").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(estimateText(data));
      showToast("Estimate copied to the clipboard.", "success");
    } catch {
      showToast("Clipboard access failed. Use Print estimate instead.", "error");
    }
  });
  $("print-estimate").addEventListener("click", () => window.print());
  $("new-estimate").addEventListener("click", () => {
    result.hidden = true;
    $("vin").focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

function initializeEstimate() {
  ["labor-rate", "mobile-fee", "supplies", "tax-rate"].forEach((id) => $(id).addEventListener("input", savePricingPreferences));
  $("estimate-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!await requireAuthenticated("login")) return;
    const submit = $("submit");
    const result = $("result");
    const location = locationPayload();
    if (!location) {
      showToast("Set a ZIP, city/state, or current location before researching local parts.", "error");
      navigate("system");
      $("postal-code").focus();
      return;
    }
    submit.disabled = true;
    submit.textContent = "Researching current sources…";
    result.hidden = false;
    result.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Optimus is researching the job</strong><br><small>Checking labor guidance, parts, availability, fitment, tools, and risks.</small></div></div>';

    const payload = {
      vehicle: vehiclePayload(),
      job: $("job").value.trim(),
      location,
      labor_rate: numericValue("labor-rate"),
      mobile_service_fee: numericValue("mobile-fee"),
      shop_supplies_percent: numericValue("supplies"),
      parts_tax_rate: numericValue("tax-rate"),
    };

    try {
      const response = await apiFetch("/api/estimate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await readApiPayload(response);
      if (!response.ok) throw apiError(response, data, "Estimate research failed");
      if (!data) throw new Error("The estimator returned an empty response.");
      renderEstimate(data);
      showToast("Estimate research completed.", "success");
    } catch (error) {
      result.innerHTML = `<div class="error-card"><strong>Estimate failed</strong><p>${escapeHtml(error.message)}</p></div>`;
      showToast(`Estimate failed: ${error.message}`, "error");
    } finally {
      submit.disabled = false;
      submit.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 13h8V3h2v8h8v2h-8v8h-2v-8H3v-2Z"/></svg> Research and estimate';
    }
  });
}

function setStatus(id, text, online = null) {
  $(id).textContent = text;
  const dot = $(`${id}-dot`);
  if (dot) {
    dot.classList.remove("online", "offline");
    if (online === true) dot.classList.add("online");
    if (online === false) dot.classList.add("offline");
  }
}

async function loadHealth(showNotification = false) {
  try {
    const response = await apiFetch("/health", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.health = data;
    $("sidebar-status-orb").className = "status-orb online";
    $("sidebar-status-title").textContent = "Optimus online";
    $("sidebar-status-detail").textContent = data.web_search_configured ? "Research systems configured" : "API key needs attention";
    setStatus("health-server", "Online", true);
    setStatus("health-web", data.web_search_configured ? "Configured" : "Not configured", data.web_search_configured);
    setStatus("health-owner", data.owner_full_control ? "Full control" : "Guarded", data.owner_full_control);
    setStatus("health-agent", data.agent_delegation_enabled ? "Selective" : "Disabled", true);
    $("system-server-status").textContent = "Online";
    $("system-version").textContent = `Version ${data.version}`;
    $("system-web-status").textContent = data.web_search_configured ? "Configured" : "API key missing";
    $("system-autonomy-status").textContent = data.owner_full_control ? "Owner full control" : "Guarded";
    $("system-agent-status").textContent = data.agent_delegation_enabled ? "Selective and silent" : "Disabled";
    if (showNotification) showToast("System check completed.", "success");
  } catch (error) {
    $("sidebar-status-orb").className = "status-orb offline";
    $("sidebar-status-title").textContent = "Server offline";
    $("sidebar-status-detail").textContent = "Local health check failed";
    setStatus("health-server", "Offline", false);
    setStatus("health-web", "Unknown", false);
    setStatus("health-owner", "Unknown", false);
    setStatus("health-agent", "Unknown", false);
    $("system-server-status").textContent = "Offline";
    $("system-web-status").textContent = "Unknown";
    $("system-autonomy-status").textContent = "Unknown";
    $("system-agent-status").textContent = "Unknown";
    if (showNotification) showToast(`Health check failed: ${error.message}`, "error");
  }
}

function initializeSystem() {
  $("refresh-health").addEventListener("click", () => loadHealth(true));
  $("system-refresh-health").addEventListener("click", () => loadHealth(true));
}

function initializeAuth() {
  $("login-form").addEventListener("submit", (event) => {
    void handleLoginSubmit(event);
  });
}

function initializeApp() {
  setAuthState(false);
  initializeNavigation();
  initializeTilt();
  loadSavedPreferences();
  initializeLocation();
  initializeChat();
  initializeEstimate();
  initializeSystem();
  initializeAuth();
  if (window.location.pathname === "/login") navigate("login");
  void loadSession().then((authenticated) => {
    if (!authenticated) {
      navigate("login");
      return;
    }
    if (window.location.pathname === "/login") navigate("dashboard");
  });
  void loadHealth(false);
  window.setInterval(() => loadHealth(false), 60000);
}

document.addEventListener("DOMContentLoaded", initializeApp);

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
  customers: {
    items: [],
    selectedCustomerId: null,
    selectedCustomer: null,
    vehiclePreviewItems: [],
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
    search: "",
    archivedOnly: false,
  },
  vehicles: {
    items: [],
    selectedVehicleId: null,
    selectedVehicle: null,
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
    search: "",
    archivedOnly: false,
    customerFilterId: null,
  },
  estimates: {
    selectedEstimateId: null,
    selectedEstimate: null,
  },
  currentView: "dashboard",
  health: null,
  lastEstimate: null,
};

const viewMeta = {
  login: { eyebrow: "Authentication", title: "Sign in" },
  dashboard: { eyebrow: "Operations", title: "Command deck" },
  customers: { eyebrow: "Records", title: "Customers" },
  vehicles: { eyebrow: "Fleet", title: "Vehicles" },
  chat: { eyebrow: "Owner channel", title: "Talk to Optimus" },
  estimate: { eyebrow: "Pricing workflow", title: "Job estimator" },
  approval: { eyebrow: "Customer authorization", title: "Estimate approval" },
  system: { eyebrow: "Configuration", title: "System bay" },
};

function allowsAnonymousView(view) {
  return view === "login" || view === "approval";
}

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
    void loadCustomerOptions();
    void restoreSelectionsFromContext();
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
    state.customers.selectedCustomerId = null;
    state.customers.selectedCustomer = null;
    state.customers.vehiclePreviewItems = [];
    state.vehicles.selectedVehicleId = null;
    state.vehicles.selectedVehicle = null;
    state.vehicles.customerFilterId = null;
    navigate("login");
  }
}

function navigate(view) {
  if (!viewMeta[view]) return;
  if (!allowsAnonymousView(view) && !state.auth.authenticated) {
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
  else if (view === "approval") history.replaceState(null, "", "/approval" + window.location.hash);
  else if (window.location.pathname === "/login") history.replaceState(null, "", "/");
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (view === "customers" && state.auth.authenticated) void loadCustomers();
  if (view === "vehicles" && state.auth.authenticated) void loadVehicles();
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
  const estimate = data.current_revision ? data.current_revision.estimate : data;
  const vehicle = [estimate.vehicle.year, estimate.vehicle.make, estimate.vehicle.model, estimate.vehicle.engine].filter(Boolean).join(" ");
  const parts = estimate.selected_parts.map((part) => (
    `${part.part_name} x${part.quantity}: ${money(part.extended_price)} — ${part.retailer}`
  )).join("\n");
  return [
    "LANDON MOTOR WORKS — JOB ESTIMATE",
    vehicle,
    estimate.job,
    "",
    `Labor: ${estimate.totals.labor_hours} hr × ${money(estimate.totals.labor_rate)} = ${money(estimate.totals.labor_total)}`,
    `Parts: ${money(estimate.totals.parts_subtotal)}`,
    `Shop supplies: ${money(estimate.totals.shop_supplies)}`,
    `Mobile fee: ${money(estimate.totals.mobile_service_fee)}`,
    `Parts tax: ${money(estimate.totals.parts_tax)}`,
    `Estimated total: ${money(estimate.totals.estimated_total)}`,
    "",
    parts,
    "",
    `Practical working time: ${estimate.totals.practical_time_low}–${estimate.totals.practical_time_high} hr`,
  ].filter((line, index, all) => line !== "" || all[index - 1] !== "").join("\n");
}

function renderEstimate(data) {
  state.lastEstimate = data;
  state.estimates.selectedEstimateId = data.id;
  state.estimates.selectedEstimate = data;
  const current = data.current_revision;
  const estimate = current.estimate;
  const result = $("result");
  const vehicle = [estimate.vehicle.year, estimate.vehicle.make, estimate.vehicle.model, estimate.vehicle.trim, estimate.vehicle.engine].filter(Boolean).join(" ") || estimate.vehicle.vin || "Vehicle";
  const parts = estimate.selected_parts.map((part) => `
    <article class="part-card">
      <div>
        <strong>${escapeHtml(part.part_name)} × ${part.quantity}</strong>
        <span>${escapeHtml([part.brand, part.part_number].filter(Boolean).join(" ") || "Part number not exposed")}</span>
        <span>${escapeHtml(part.retailer)} · ${escapeHtml(part.availability)}${part.store_name ? ` · ${escapeHtml(part.store_name)}` : ""}</span>
      </div>
      <div class="part-price"><strong>${money(part.extended_price)}</strong><a href="${escapeHtml(part.url)}" target="_blank" rel="noopener noreferrer">Open source</a></div>
    </article>`).join("");
  const tools = estimate.research.labor.special_tools.map((tool) => `<li>${escapeHtml(tool)}</li>`).join("") || "<li>None identified.</li>";
  const risks = estimate.research.labor.risk_flags.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("") || "<li>None identified.</li>";
  const warnings = estimate.research.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("") || "<li>None.</li>";
  const sources = estimate.research.citations.map((citation) => `<a href="${escapeHtml(citation.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(citation.title)}</a>`).join("") || "<p>No source links were returned.</p>";
  const paymentOptions = current.payment_options.map((option) => `<li>${escapeHtml(option.label)}${option.requires_payment_plan_acknowledgement ? " · payment-plan acknowledgement required" : ""}</li>`).join("");
  const audit = data.approval_audit?.events?.map((event) => `<li><strong>${escapeHtml(event.event_type)}</strong> · revision ${event.revision_number} · ${escapeHtml(event.actor_name || event.actor_type)} · ${new Date(event.created_at).toLocaleString()}</li>`).join("") || "<li>No approval events recorded yet.</li>";

  result.innerHTML = `
    <div class="result-hero">
      <div><span class="section-kicker"><i></i> Saved estimate ${escapeHtml(data.estimate_number)}</span><h2>${escapeHtml(vehicle)}</h2><p>${escapeHtml(estimate.job)}</p></div>
      <div class="result-total"><span>${escapeHtml(data.status.replaceAll("_", " "))}</span><strong>${money(estimate.totals.estimated_total)}</strong></div>
    </div>
    <div class="result-actions">
      <button class="secondary-button compact" type="button" id="copy-estimate">Copy estimate</button>
      <button class="secondary-button compact" type="button" id="print-estimate">Print estimate</button>
      <button class="secondary-button compact" type="button" id="send-estimate-approval"${data.status === "approved" ? " disabled" : ""}>Send for approval</button>
      <button class="text-button" type="button" id="new-estimate">Start another</button>
    </div>
    <div class="money-grid">
      <div class="money-card"><span>Labor (${estimate.totals.labor_hours} hr)</span><strong>${money(estimate.totals.labor_total)}</strong></div>
      <div class="money-card"><span>Selected parts</span><strong>${money(estimate.totals.parts_subtotal)}</strong></div>
      <div class="money-card"><span>Shop supplies</span><strong>${money(estimate.totals.shop_supplies)}</strong></div>
      <div class="money-card"><span>Mobile fee</span><strong>${money(estimate.totals.mobile_service_fee)}</strong></div>
      <div class="money-card"><span>Parts tax</span><strong>${money(estimate.totals.parts_tax)}</strong></div>
    </div>
    <div class="result-grid">
      <section class="result-section">
        <h3>Selected priced parts</h3>
        <div class="parts-list">${parts || "<p>No currently priced part option could be selected. Review the source links for products with hidden pricing.</p>"}</div>
      </section>
      <section class="result-section">
        <h3>Labor and practical time</h3>
        <p><strong>Published/book:</strong> ${estimate.research.labor.book_hours} hr</p>
        <p><strong>Practical mobile range:</strong> ${estimate.totals.practical_time_low}–${estimate.totals.practical_time_high} hr</p>
        <p><strong>Confidence:</strong> ${escapeHtml(estimate.research.labor.confidence)}</p>
        <p>${escapeHtml(estimate.research.labor.basis)}</p>
      </section>
      <section class="result-section"><h3>Special tools</h3><ul>${tools}</ul></section>
      <section class="result-section"><h3>Risk flags</h3><ul>${risks}</ul></section>
      <section class="result-section"><h3>Warnings</h3><ul>${warnings}</ul></section>
      <section class="result-section"><h3>Terms</h3><p>${escapeHtml(current.terms_text)}</p></section>
      <section class="result-section"><h3>Payment options</h3><ul>${paymentOptions}</ul></section>
      <section class="result-section"><h3>Approval audit</h3><ul>${audit}</ul></section>
      <section class="result-section"><h3>Research sources</h3><div class="source-list">${sources}</div></section>
      ${estimate.research.request_id ? `<section class="result-section"><h3>Research trace</h3><p>${escapeHtml(estimate.research.request_id)} · ${escapeHtml(estimate.research.research_mode || "standard")}</p></section>` : ""}
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
  $("send-estimate-approval").addEventListener("click", () => {
    void sendSelectedEstimateForApproval();
  });
  $("new-estimate").addEventListener("click", () => {
    result.hidden = true;
    $("vin").focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

function selectedPaymentOptions() {
  return [
    $("payment-option-pay-in-full").checked ? {
      code: "pay_in_full",
      label: "Pay in full",
      description: "Pay the full approved amount when service is complete.",
      requires_payment_plan_acknowledgement: false,
    } : null,
    $("payment-option-split-payment").checked ? {
      code: "split_payment",
      label: "Split payment",
      description: "Pay a deposit now and the balance when service is complete.",
      requires_payment_plan_acknowledgement: false,
    } : null,
    $("payment-option-two-month-plan").checked ? {
      code: "two_month_plan",
      label: "Two-month plan",
      description: "Parts-price deposit is due before parts are ordered. No repair begins until deposit and authorization are complete. Remaining payments are due 30 and 60 days after service.",
      requires_payment_plan_acknowledgement: true,
    } : null,
  ].filter(Boolean);
}

function syncEstimateRecordSummary() {
  $("estimate-selected-customer").textContent = state.customers.selectedCustomer?.display_name || "Select a customer record first.";
  $("estimate-selected-vehicle").textContent = state.vehicles.selectedVehicle?.display_name || "Select a vehicle record first.";
}

async function rememberSelectedEstimate(estimate) {
  try {
    await apiFetch("/api/context/estimates/selected-estimate?scope=session", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        value: JSON.stringify({
          id: estimate.id,
          estimate_number: estimate.estimate_number,
          revision_number: estimate.current_revision_number,
        }),
      }),
    });
  } catch {
    // Estimate persistence remains authoritative even if assistive context storage fails.
  }
}

async function loadEstimateApprovalAudit(estimateId) {
  const response = await apiFetch(`/api/estimates/${estimateId}/approval-history`);
  const data = await readApiPayload(response);
  if (!response.ok || !data) throw apiError(response, data, "Estimate approval history failed");
  return data;
}

async function sendSelectedEstimateForApproval() {
  const estimate = state.estimates.selectedEstimate;
  if (!estimate) return;
  try {
    const response = await apiFetch(`/api/estimates/${estimate.id}/send-for-approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approval_method: "link",
        expires_in_hours: Number($("estimate-link-hours").value || 72),
      }),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Estimate approval link failed");
    await navigator.clipboard.writeText(new URL(data.approval_link, window.location.origin).toString());
    const refreshed = await apiFetch(`/api/estimates/${estimate.id}`);
    const refreshedPayload = await readApiPayload(refreshed);
    if (!refreshed.ok || !refreshedPayload) throw apiError(refreshed, refreshedPayload, "Estimate refresh failed");
    refreshedPayload.approval_audit = await loadEstimateApprovalAudit(estimate.id);
    renderEstimate(refreshedPayload);
    void rememberSelectedEstimate(refreshedPayload);
    showToast("Approval link copied to the clipboard.", "success");
  } catch (error) {
    showToast(`Estimate approval link failed: ${error.message}`, "error");
  }
}

function initializeEstimate() {
  ["labor-rate", "mobile-fee", "supplies", "tax-rate"].forEach((id) => $(id).addEventListener("input", savePricingPreferences));
  syncEstimateRecordSummary();
  $("estimate-open-customer").addEventListener("click", () => navigate("customers"));
  $("estimate-open-vehicle").addEventListener("click", () => navigate("vehicles"));
  $("estimate-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!await requireAuthenticated("login")) return;
    if (!state.customers.selectedCustomerId || !state.vehicles.selectedVehicleId) {
      showToast("Select the customer and vehicle records before saving an estimate.", "error");
      navigate(!state.customers.selectedCustomerId ? "customers" : "vehicles");
      return;
    }
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
      customer_id: state.customers.selectedCustomerId,
      vehicle_id: state.vehicles.selectedVehicleId,
      job: $("job").value.trim(),
      location,
      labor_rate: numericValue("labor-rate"),
      mobile_service_fee: numericValue("mobile-fee"),
      shop_supplies_percent: numericValue("supplies"),
      parts_tax_rate: numericValue("tax-rate"),
      terms_text: $("estimate-terms").value.trim(),
      payment_options: selectedPaymentOptions(),
      expires_in_days: Number($("estimate-expires-days").value || 7),
    };

    try {
      const response = await apiFetch("/api/estimates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await readApiPayload(response);
      if (!response.ok) throw apiError(response, data, "Estimate research failed");
      if (!data) throw new Error("The estimator returned an empty response.");
      data.approval_audit = await loadEstimateApprovalAudit(data.id);
      renderEstimate(data);
      void rememberSelectedEstimate(data);
      showToast("Saved estimate created.", "success");
    } catch (error) {
      result.innerHTML = `<div class="error-card"><strong>Estimate failed</strong><p>${escapeHtml(error.message)}</p></div>`;
      showToast(`Estimate failed: ${error.message}`, "error");
    } finally {
      submit.disabled = false;
      submit.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 13h8V3h2v8h8v2h-8v8h-2v-8H3v-2Z"/></svg> Create saved estimate';
    }
  });
}

function customerPayloadFromForm() {
  return {
    first_name: $("customer-first-name").value.trim() || null,
    last_name: $("customer-last-name").value.trim() || null,
    company_name: $("customer-company-name").value.trim() || null,
    email: $("customer-email").value.trim() || null,
    phone: $("customer-phone").value.trim() || null,
    secondary_phone: $("customer-secondary-phone").value.trim() || null,
    address_line_1: $("customer-address-line-1").value.trim() || null,
    address_line_2: $("customer-address-line-2").value.trim() || null,
    city: $("customer-city").value.trim() || null,
    state: $("customer-state").value.trim() || null,
    postal_code: $("customer-postal-code").value.trim() || null,
    preferred_contact_method: $("customer-preferred-contact-method").value.trim() || null,
    internal_notes: $("customer-internal-notes").value.trim() || null,
  };
}

function populateCustomerForm(customer = null) {
  $("customer-id").value = customer?.id ?? "";
  $("customer-first-name").value = customer?.first_name ?? "";
  $("customer-last-name").value = customer?.last_name ?? "";
  $("customer-company-name").value = customer?.company_name ?? "";
  $("customer-email").value = customer?.email ?? "";
  $("customer-phone").value = customer?.phone ?? "";
  $("customer-secondary-phone").value = customer?.secondary_phone ?? "";
  $("customer-address-line-1").value = customer?.address_line_1 ?? "";
  $("customer-address-line-2").value = customer?.address_line_2 ?? "";
  $("customer-city").value = customer?.city ?? "";
  $("customer-state").value = customer?.state ?? "";
  $("customer-postal-code").value = customer?.postal_code ?? "";
  $("customer-preferred-contact-method").value = customer?.preferred_contact_method ?? "";
  $("customer-internal-notes").value = customer?.internal_notes ?? "";
  $("customer-form-title").textContent = customer ? "Edit customer" : "Create customer";
  $("customer-form-mode").textContent = customer ? "EDIT" : "CREATE";
  $("customer-archive").hidden = !customer;
}

function customerSummaryLine(customer) {
  return [customer.email, customer.phone, customer.city && customer.state ? `${customer.city}, ${customer.state}` : customer.city || customer.state]
    .filter(Boolean)
    .join(" · ");
}

function renderCustomerDetail(customer = null) {
  const detail = $("customer-detail");
  if (!customer) {
    detail.innerHTML = "<p>Select a customer from the list or create a new record.</p>";
    $("customer-archive").hidden = true;
    renderCustomerVehiclePreview();
    return;
  }
  const addressLines = [
    customer.address_line_1,
    customer.address_line_2,
    [customer.city, customer.state, customer.postal_code].filter(Boolean).join(", "),
  ].filter(Boolean);
  const address = addressLines.map((line) => escapeHtml(line)).join("<br>");
  detail.innerHTML = `
    <div class="customer-detail-header">
      <strong>${escapeHtml(customer.display_name)}</strong>
      <span>${customer.is_archived ? "Archived" : "Active"}</span>
    </div>
    <p>${escapeHtml(customerSummaryLine(customer) || "No contact details provided.")}</p>
    <div class="customer-detail-grid">
      <div><span>Email</span><strong>${escapeHtml(customer.email || "Not set")}</strong></div>
      <div><span>Primary phone</span><strong>${escapeHtml(customer.phone || "Not set")}</strong></div>
      <div><span>Secondary phone</span><strong>${escapeHtml(customer.secondary_phone || "Not set")}</strong></div>
      <div><span>Preferred contact</span><strong>${escapeHtml(customer.preferred_contact_method || "Not set")}</strong></div>
    </div>
    <div class="customer-detail-notes">
      <span>Address</span>
      <p>${address || "No address recorded."}</p>
    </div>
    <div class="customer-detail-notes">
      <span>Internal notes</span>
      <p>${escapeHtml(customer.internal_notes || "No internal notes recorded.")}</p>
    </div>`;
  $("customer-archive").hidden = false;
}

function renderCustomersList() {
  const container = $("customers-list");
  if (!state.customers.items.length) {
    const emptyMessage = state.customers.search || state.customers.archivedOnly
      ? "No customers matched this filter."
      : "No customers yet. Create the first customer record.";
    container.innerHTML = `<div class="empty-card"><strong>No results</strong><p>${escapeHtml(emptyMessage)}</p></div>`;
  } else {
    container.innerHTML = state.customers.items.map((customer) => `
      <button type="button" class="customer-list-item${state.customers.selectedCustomerId === customer.id ? " is-active" : ""}" data-customer-id="${customer.id}">
        <strong>${escapeHtml(customer.display_name)}</strong>
        <span>${escapeHtml(customerSummaryLine(customer) || "No contact details")}</span>
      </button>`).join("");
    $$("[data-customer-id]", container).forEach((button) => {
      button.addEventListener("click", () => {
        void selectCustomer(Number(button.dataset.customerId));
      });
    });
  }
  $("customers-page-status").textContent = `Page ${state.customers.page} · ${state.customers.total} total`;
  $("customers-prev").disabled = state.customers.page <= 1;
  $("customers-next").disabled = !state.customers.hasMore;
}

async function rememberSelectedCustomer(customer) {
  try {
    await apiFetch("/api/context/customers/selected-customer?scope=session", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        value: JSON.stringify({ id: customer.id, display_name: customer.display_name }),
      }),
    });
  } catch {
    // Customer persistence remains authoritative even if assistive context storage fails.
  }
}

async function clearSelectedVehicleReference() {
  try {
    await apiFetch("/api/context/vehicles/selected-vehicle?scope=session", {
      method: "DELETE",
    });
  } catch {
    // Ignore missing or unavailable assistive context entries.
  }
}

function vehicleSummaryLine(vehicle) {
  return [
    vehicle.vin,
    vehicle.license_plate,
    vehicle.current_mileage != null ? `${vehicle.current_mileage.toLocaleString()} mi` : null,
    vehicle.customer_display_name,
  ].filter(Boolean).join(" · ");
}

function renderCustomerVehiclePreview() {
  const container = $("customer-vehicles-list");
  const customer = state.customers.selectedCustomer;
  const items = state.customers.vehiclePreviewItems;
  if (!customer) {
    container.innerHTML = "<p>Select a customer to load active vehicles.</p>";
    return;
  }
  if (!items.length) {
    container.innerHTML = `<div class="empty-card"><strong>No active vehicles</strong><p>${escapeHtml(customer.display_name)} does not have any active vehicles yet.</p></div>`;
    return;
  }
  container.innerHTML = items.map((vehicle) => `
    <button type="button" class="vehicle-preview-item${state.vehicles.selectedVehicleId === vehicle.id ? " is-active" : ""}" data-customer-vehicle-id="${vehicle.id}">
      <strong>${escapeHtml(vehicle.display_name)}</strong>
      <span>${escapeHtml(vehicleSummaryLine(vehicle) || "Vehicle record")}</span>
    </button>`).join("");
  $$("[data-customer-vehicle-id]", container).forEach((button) => {
    button.addEventListener("click", () => {
      void openVehicleFromCustomerDetail(Number(button.dataset.customerVehicleId));
    });
  });
}

async function loadCustomerVehiclePreview(customerId) {
  const container = $("customer-vehicles-list");
  container.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading vehicles</strong><br><small>Reading active customer vehicles.</small></div></div>';
  try {
    const response = await apiFetch(`/api/customers/${customerId}/vehicles?page=1&page_size=20&archived=false`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Customer vehicles failed");
    state.customers.vehiclePreviewItems = data.items;
    renderCustomerVehiclePreview();
  } catch (error) {
    container.innerHTML = `<div class="error-card"><strong>Vehicle list failed</strong><p>${escapeHtml(error.message)}</p></div>`;
  }
}

async function selectCustomer(customerId, options = {}) {
  const { remember = true, refreshVehicles = true, suppressErrors = false } = options;
  try {
    const response = await apiFetch(`/api/customers/${customerId}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Customer lookup failed");
    state.customers.selectedCustomerId = data.id;
    state.customers.selectedCustomer = data;
    renderCustomerDetail(data);
    populateCustomerForm(data);
    renderCustomersList();
    syncEstimateRecordSummary();
    if (refreshVehicles) void loadCustomerVehiclePreview(data.id);
    if (remember) void rememberSelectedCustomer(data);
    return data;
  } catch (error) {
    if (!suppressErrors) showToast(`Customer lookup failed: ${error.message}`, "error");
    return null;
  }
}

async function loadCustomers() {
  if (!await requireAuthenticated("login")) return;
  const list = $("customers-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading customers</strong><br><small>Reading PostgreSQL customer records.</small></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.customers.page),
    page_size: String(state.customers.pageSize),
    archived: String(state.customers.archivedOnly),
  });
  if (state.customers.search.trim()) searchParams.set("search", state.customers.search.trim());
  try {
    const response = await apiFetch(`/api/customers?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Customer list failed");
    state.customers.items = data.items;
    state.customers.total = data.total;
    state.customers.hasMore = data.has_more;
    renderCustomersList();
    if (state.customers.selectedCustomerId) {
      const selected = data.items.find((item) => item.id === state.customers.selectedCustomerId);
      if (selected) {
        state.customers.selectedCustomer = selected;
        renderCustomerDetail(selected);
        populateCustomerForm(selected);
        syncEstimateRecordSummary();
        void loadCustomerVehiclePreview(selected.id);
      } else {
        state.customers.selectedCustomerId = null;
        state.customers.selectedCustomer = null;
        state.customers.vehiclePreviewItems = [];
        renderCustomerDetail(null);
        populateCustomerForm(null);
        syncEstimateRecordSummary();
      }
    }
  } catch (error) {
    list.innerHTML = `<div class="error-card"><strong>Customer list failed</strong><p>${escapeHtml(error.message)}</p></div>`;
    showToast(`Customer list failed: ${error.message}`, "error");
  }
}

async function submitCustomerForm(event) {
  event.preventDefault();
  if (!await requireAuthenticated("login")) return;
  const customerId = $("customer-id").value.trim();
  const submit = $("customer-save");
  submit.disabled = true;
  submit.textContent = customerId ? "Saving…" : "Creating…";
  try {
    const response = await apiFetch(customerId ? `/api/customers/${customerId}` : "/api/customers", {
      method: customerId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(customerPayloadFromForm()),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Customer save failed");
    state.customers.selectedCustomerId = data.id;
    state.customers.selectedCustomer = data;
    populateCustomerForm(data);
    renderCustomerDetail(data);
    state.customers.page = 1;
    await loadCustomers();
    await loadCustomerOptions();
    showToast(customerId ? "Customer updated." : "Customer created.", "success");
    void rememberSelectedCustomer(data);
  } catch (error) {
    showToast(`Customer save failed: ${error.message}`, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Save customer";
  }
}

async function archiveSelectedCustomer() {
  const customer = state.customers.selectedCustomer;
  if (!customer) return;
  if (!window.confirm(`Archive ${customer.display_name}?`)) return;
  try {
    const response = await apiFetch(`/api/customers/${customer.id}`, { method: "DELETE" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Customer archive failed");
    state.customers.selectedCustomerId = null;
    state.customers.selectedCustomer = null;
    state.customers.vehiclePreviewItems = [];
    populateCustomerForm(null);
    renderCustomerDetail(null);
    await loadCustomers();
    await loadCustomerOptions();
    showToast("Customer archived.", "success");
  } catch (error) {
    showToast(`Customer archive failed: ${error.message}`, "error");
  }
}

function setVehicleCustomerFilter(customerId) {
  state.vehicles.customerFilterId = customerId ? Number(customerId) : null;
  $("vehicles-customer-filter").value = state.vehicles.customerFilterId ? String(state.vehicles.customerFilterId) : "";
  if (!$("vehicle-id").value) {
    $("vehicle-customer-id").value = state.vehicles.customerFilterId ? String(state.vehicles.customerFilterId) : "";
  }
}

function openVehiclesForCustomer(customer) {
  if (!customer) {
    navigate("vehicles");
    return;
  }
  setVehicleCustomerFilter(customer.id);
  populateVehicleForm(null, { preferredCustomerId: customer.id });
  renderVehicleDetail(null);
  state.vehicles.page = 1;
  navigate("vehicles");
  void loadVehicles();
}

async function openVehicleFromCustomerDetail(vehicleId) {
  const customer = state.customers.selectedCustomer;
  if (customer) setVehicleCustomerFilter(customer.id);
  navigate("vehicles");
  await loadVehicles();
  await selectVehicle(vehicleId, { remember: true, suppressErrors: false });
}

function initializeCustomers() {
  $("customer-form").addEventListener("submit", (event) => {
    void submitCustomerForm(event);
  });
  $("customer-cancel").addEventListener("click", () => {
    state.customers.selectedCustomerId = null;
    state.customers.selectedCustomer = null;
    state.customers.vehiclePreviewItems = [];
    populateCustomerForm(null);
    renderCustomerDetail(null);
  });
  $("customers-new").addEventListener("click", () => {
    navigate("customers");
    state.customers.selectedCustomerId = null;
    state.customers.selectedCustomer = null;
    state.customers.vehiclePreviewItems = [];
    populateCustomerForm(null);
    renderCustomerDetail(null);
    $("customer-first-name").focus();
  });
  $("customers-refresh").addEventListener("click", () => {
    void loadCustomers();
  });
  $("customers-search").addEventListener("input", () => {
    state.customers.search = $("customers-search").value;
    state.customers.page = 1;
    void loadCustomers();
  });
  $("customers-archived-only").addEventListener("change", () => {
    state.customers.archivedOnly = $("customers-archived-only").checked;
    state.customers.page = 1;
    state.customers.selectedCustomerId = null;
    state.customers.selectedCustomer = null;
    state.customers.vehiclePreviewItems = [];
    populateCustomerForm(null);
    renderCustomerDetail(null);
    void loadCustomers();
  });
  $("customers-prev").addEventListener("click", () => {
    state.customers.page = Math.max(1, state.customers.page - 1);
    void loadCustomers();
  });
  $("customers-next").addEventListener("click", () => {
    if (!state.customers.hasMore) return;
    state.customers.page += 1;
    void loadCustomers();
  });
  $("customer-archive").addEventListener("click", () => {
    void archiveSelectedCustomer();
  });
  $("customer-vehicles-manage").addEventListener("click", () => {
    openVehiclesForCustomer(state.customers.selectedCustomer);
  });
  $("customer-vehicle-new").addEventListener("click", async () => {
    const customer = state.customers.selectedCustomer;
    if (!customer) {
      showToast("Select a customer before creating a vehicle.", "error");
      return;
    }
    await loadCustomerOptions();
    populateVehicleForm(null, { preferredCustomerId: customer.id });
    openVehiclesForCustomer(customer);
    $("vehicle-vin").focus();
  });
  populateCustomerForm(null);
  renderCustomerDetail(null);
  renderCustomerVehiclePreview();
}

function vehiclePayloadFromForm() {
  return {
    vin: $("vehicle-vin").value.trim() || null,
    year: $("vehicle-year").value ? Number($("vehicle-year").value) : null,
    make: $("vehicle-make").value.trim() || null,
    model: $("vehicle-model").value.trim() || null,
    trim: $("vehicle-trim").value.trim() || null,
    engine: $("vehicle-engine").value.trim() || null,
    drivetrain: $("vehicle-drivetrain").value.trim() || null,
    transmission: $("vehicle-transmission").value.trim() || null,
    license_plate: $("vehicle-license-plate").value.trim() || null,
    license_plate_state: $("vehicle-license-plate-state").value.trim() || null,
    color: $("vehicle-color").value.trim() || null,
    current_mileage: $("vehicle-current-mileage").value ? Number($("vehicle-current-mileage").value) : null,
    fleet_unit_number: $("vehicle-fleet-unit-number").value.trim() || null,
    internal_notes: $("vehicle-internal-notes").value.trim() || null,
  };
}

async function loadCustomerOptions() {
  const currentVehicleCustomerId = $("vehicle-customer-id").value || (state.vehicles.customerFilterId ? String(state.vehicles.customerFilterId) : "");
  const response = await apiFetch("/api/customers?page=1&page_size=100&archived=false");
  const data = await readApiPayload(response);
  if (!response.ok || !data) throw apiError(response, data, "Customer options failed");
  const options = ['<option value="">Select a customer</option>'];
  for (const customer of data.items) {
    options.push(`<option value="${customer.id}">${escapeHtml(customer.display_name)}</option>`);
  }
  $("vehicle-customer-id").innerHTML = options.join("");
  $("vehicles-customer-filter").innerHTML = ['<option value="">All active customers</option>', ...data.items.map((customer) => (
    `<option value="${customer.id}">${escapeHtml(customer.display_name)}</option>`
  ))].join("");
  if (currentVehicleCustomerId) {
    $("vehicle-customer-id").value = currentVehicleCustomerId;
  }
  if (state.vehicles.customerFilterId) {
    $("vehicles-customer-filter").value = String(state.vehicles.customerFilterId);
  }
}

function populateVehicleForm(vehicle = null, options = {}) {
  const { preferredCustomerId = null } = options;
  const customerId = vehicle?.customer_id ?? preferredCustomerId;
  $("vehicle-id").value = vehicle?.id ?? "";
  $("vehicle-customer-id").value = customerId ? String(customerId) : "";
  $("vehicle-vin").value = vehicle?.vin ?? "";
  $("vehicle-year").value = vehicle?.year ?? "";
  $("vehicle-make").value = vehicle?.make ?? "";
  $("vehicle-model").value = vehicle?.model ?? "";
  $("vehicle-trim").value = vehicle?.trim ?? "";
  $("vehicle-engine").value = vehicle?.engine ?? "";
  $("vehicle-drivetrain").value = vehicle?.drivetrain ?? "";
  $("vehicle-transmission").value = vehicle?.transmission ?? "";
  $("vehicle-license-plate").value = vehicle?.license_plate ?? "";
  $("vehicle-license-plate-state").value = vehicle?.license_plate_state ?? "";
  $("vehicle-color").value = vehicle?.color ?? "";
  $("vehicle-current-mileage").value = vehicle?.current_mileage ?? "";
  $("vehicle-fleet-unit-number").value = vehicle?.fleet_unit_number ?? "";
  $("vehicle-internal-notes").value = vehicle?.internal_notes ?? "";
  $("vehicle-form-title").textContent = vehicle ? "Edit vehicle" : "Create vehicle";
  $("vehicle-form-mode").textContent = vehicle ? "EDIT" : "CREATE";
  $("vehicle-open-customer").hidden = !vehicle;
  $("vehicle-archive").hidden = !vehicle;
  $("vehicle-customer-id").disabled = Boolean(vehicle);
}

function renderVehicleDetail(vehicle = null) {
  const detail = $("vehicle-detail");
  if (!vehicle) {
    detail.innerHTML = "<p>Select a vehicle from the list or create a new record.</p>";
    $("vehicle-open-customer").hidden = true;
    $("vehicle-archive").hidden = true;
    return;
  }
  detail.innerHTML = `
    <div class="customer-detail-header">
      <strong>${escapeHtml(vehicle.display_name)}</strong>
      <span>${vehicle.is_archived ? "Archived" : "Active"}</span>
    </div>
    <p>${escapeHtml(vehicleSummaryLine(vehicle) || "No VIN or plate recorded.")}</p>
    <div class="customer-detail-grid">
      <div><span>Customer</span><strong>${escapeHtml(vehicle.customer_display_name || "Unknown customer")}</strong></div>
      <div><span>VIN</span><strong>${escapeHtml(vehicle.vin || "Not set")}</strong></div>
      <div><span>Plate</span><strong>${escapeHtml(vehicle.license_plate || "Not set")}</strong></div>
      <div><span>Mileage</span><strong>${escapeHtml(vehicle.current_mileage != null ? `${vehicle.current_mileage.toLocaleString()} mi` : "Not set")}</strong></div>
      <div><span>Powertrain</span><strong>${escapeHtml([vehicle.engine, vehicle.drivetrain, vehicle.transmission].filter(Boolean).join(" · ") || "Not set")}</strong></div>
      <div><span>Fleet unit</span><strong>${escapeHtml(vehicle.fleet_unit_number || "Not set")}</strong></div>
    </div>
    <div class="customer-detail-notes">
      <span>Internal notes</span>
      <p>${escapeHtml(vehicle.internal_notes || "No internal notes recorded.")}</p>
    </div>`;
  $("vehicle-open-customer").hidden = false;
  $("vehicle-archive").hidden = false;
}

function renderVehiclesList() {
  const container = $("vehicles-list");
  if (!state.vehicles.items.length) {
    const emptyMessage = state.vehicles.search || state.vehicles.archivedOnly || state.vehicles.customerFilterId
      ? "No vehicles matched this filter."
      : "No vehicles yet. Create the first vehicle record.";
    container.innerHTML = `<div class="empty-card"><strong>No results</strong><p>${escapeHtml(emptyMessage)}</p></div>`;
  } else {
    container.innerHTML = state.vehicles.items.map((vehicle) => `
      <button type="button" class="customer-list-item${state.vehicles.selectedVehicleId === vehicle.id ? " is-active" : ""}" data-vehicle-id="${vehicle.id}">
        <strong>${escapeHtml(vehicle.display_name)}</strong>
        <span>${escapeHtml(vehicleSummaryLine(vehicle) || "Vehicle record")}</span>
      </button>`).join("");
    $$("[data-vehicle-id]", container).forEach((button) => {
      button.addEventListener("click", () => {
        void selectVehicle(Number(button.dataset.vehicleId));
      });
    });
  }
  $("vehicles-page-status").textContent = `Page ${state.vehicles.page} · ${state.vehicles.total} total`;
  $("vehicles-prev").disabled = state.vehicles.page <= 1;
  $("vehicles-next").disabled = !state.vehicles.hasMore;
}

async function rememberSelectedVehicle(vehicle) {
  try {
    await apiFetch("/api/context/vehicles/selected-vehicle?scope=session", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        value: JSON.stringify({
          id: vehicle.id,
          customer_id: vehicle.customer_id,
          display_name: vehicle.display_name,
        }),
      }),
    });
  } catch {
    // Vehicle persistence remains authoritative even if assistive context storage fails.
  }
}

async function selectVehicle(vehicleId, options = {}) {
  const { remember = true, suppressErrors = false } = options;
  try {
    const response = await apiFetch(`/api/vehicles/${vehicleId}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Vehicle lookup failed");
    state.vehicles.selectedVehicleId = data.id;
    state.vehicles.selectedVehicle = data;
    if (data.customer_id) {
      state.customers.selectedCustomerId = data.customer_id;
    }
    renderVehicleDetail(data);
    populateVehicleForm(data);
    renderVehiclesList();
    syncEstimateRecordSummary();
    if (remember) void rememberSelectedVehicle(data);
    return data;
  } catch (error) {
    if (!suppressErrors) showToast(`Vehicle lookup failed: ${error.message}`, "error");
    return null;
  }
}

async function loadVehicles() {
  if (!await requireAuthenticated("login")) return;
  const list = $("vehicles-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading vehicles</strong><br><small>Reading PostgreSQL vehicle records.</small></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.vehicles.page),
    page_size: String(state.vehicles.pageSize),
    archived: String(state.vehicles.archivedOnly),
  });
  if (state.vehicles.search.trim()) searchParams.set("search", state.vehicles.search.trim());
  if (state.vehicles.customerFilterId) searchParams.set("customer_id", String(state.vehicles.customerFilterId));
  try {
    const response = await apiFetch(`/api/vehicles?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Vehicle list failed");
    state.vehicles.items = data.items;
    state.vehicles.total = data.total;
    state.vehicles.hasMore = data.has_more;
    renderVehiclesList();
    if (state.vehicles.selectedVehicleId) {
      const selected = data.items.find((item) => item.id === state.vehicles.selectedVehicleId);
      if (selected) {
        state.vehicles.selectedVehicle = selected;
        renderVehicleDetail(selected);
        populateVehicleForm(selected);
      } else if (!state.vehicles.selectedVehicle || state.vehicles.selectedVehicle.customer_id !== state.vehicles.customerFilterId) {
        state.vehicles.selectedVehicleId = null;
        state.vehicles.selectedVehicle = null;
        renderVehicleDetail(null);
        populateVehicleForm(null, { preferredCustomerId: state.vehicles.customerFilterId });
        syncEstimateRecordSummary();
      }
    } else if (!state.vehicles.selectedVehicle) {
      populateVehicleForm(null, { preferredCustomerId: state.vehicles.customerFilterId });
      syncEstimateRecordSummary();
    }
  } catch (error) {
    list.innerHTML = `<div class="error-card"><strong>Vehicle list failed</strong><p>${escapeHtml(error.message)}</p></div>`;
    showToast(`Vehicle list failed: ${error.message}`, "error");
  }
}

async function submitVehicleForm(event) {
  event.preventDefault();
  if (!await requireAuthenticated("login")) return;
  const vehicleId = $("vehicle-id").value.trim();
  const customerId = $("vehicle-customer-id").value.trim();
  if (!vehicleId && !customerId) {
    showToast("Select a customer before creating a vehicle.", "error");
    $("vehicle-customer-id").focus();
    return;
  }
  const submit = $("vehicle-save");
  submit.disabled = true;
  submit.textContent = vehicleId ? "Saving…" : "Creating…";
  try {
    const response = await apiFetch(vehicleId ? `/api/vehicles/${vehicleId}` : `/api/customers/${customerId}/vehicles`, {
      method: vehicleId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(vehiclePayloadFromForm()),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Vehicle save failed");
    state.vehicles.selectedVehicleId = data.id;
    state.vehicles.selectedVehicle = data;
    state.vehicles.page = 1;
    if (data.customer_id) setVehicleCustomerFilter(data.customer_id);
    populateVehicleForm(data);
    renderVehicleDetail(data);
    await loadVehicles();
    if (state.customers.selectedCustomerId === data.customer_id) {
      await loadCustomerVehiclePreview(data.customer_id);
    }
    showToast(vehicleId ? "Vehicle updated." : "Vehicle created.", "success");
    void rememberSelectedVehicle(data);
  } catch (error) {
    showToast(`Vehicle save failed: ${error.message}`, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Save vehicle";
  }
}

async function archiveSelectedVehicle() {
  const vehicle = state.vehicles.selectedVehicle;
  if (!vehicle) return;
  if (!window.confirm(`Archive ${vehicle.display_name}?`)) return;
  try {
    const response = await apiFetch(`/api/vehicles/${vehicle.id}`, { method: "DELETE" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Vehicle archive failed");
    const archivedVehicle = data.vehicle;
    if (!state.vehicles.archivedOnly) {
      state.vehicles.selectedVehicleId = null;
      state.vehicles.selectedVehicle = null;
      renderVehicleDetail(null);
      populateVehicleForm(null, { preferredCustomerId: archivedVehicle.customer_id });
      syncEstimateRecordSummary();
      void clearSelectedVehicleReference();
    } else {
      state.vehicles.selectedVehicleId = archivedVehicle.id;
      state.vehicles.selectedVehicle = archivedVehicle;
      renderVehicleDetail(archivedVehicle);
      populateVehicleForm(archivedVehicle);
      void rememberSelectedVehicle(archivedVehicle);
    }
    await loadVehicles();
    if (state.customers.selectedCustomerId === archivedVehicle.customer_id) {
      await loadCustomerVehiclePreview(archivedVehicle.customer_id);
    }
    showToast("Vehicle archived.", "success");
  } catch (error) {
    showToast(`Vehicle archive failed: ${error.message}`, "error");
  }
}

async function openCustomerForSelectedVehicle() {
  const vehicle = state.vehicles.selectedVehicle;
  if (!vehicle) return;
  const customer = await selectCustomer(vehicle.customer_id, {
    remember: true,
    refreshVehicles: true,
    suppressErrors: false,
  });
  if (!customer) return;
  navigate("customers");
}

async function restoreSelectionsFromContext() {
  if (!state.auth.authenticated) return;
  try {
    const [customerResponse, vehicleResponse, estimateResponse] = await Promise.all([
      apiFetch("/api/context/customers?scope=session"),
      apiFetch("/api/context/vehicles?scope=session"),
      apiFetch("/api/context/estimates?scope=session"),
    ]);
    const customerPayload = await readApiPayload(customerResponse);
    const vehiclePayload = await readApiPayload(vehicleResponse);
    const estimatePayload = await readApiPayload(estimateResponse);

    const customerEntry = customerPayload?.entries?.find((entry) => entry.context_key === "selected-customer");
    if (customerResponse.ok && customerEntry?.value) {
      try {
        const parsed = JSON.parse(customerEntry.value);
        if (parsed?.id) {
          const restoredCustomer = await selectCustomer(Number(parsed.id), {
            remember: false,
            refreshVehicles: true,
            suppressErrors: true,
          });
          if (!restoredCustomer) {
            void apiFetch("/api/context/customers/selected-customer?scope=session", { method: "DELETE" });
          }
        }
      } catch {
        // Ignore malformed assistive context values.
      }
    }

    const vehicleEntry = vehiclePayload?.entries?.find((entry) => entry.context_key === "selected-vehicle");
    if (vehicleResponse.ok && vehicleEntry?.value) {
      try {
        const parsed = JSON.parse(vehicleEntry.value);
        if (parsed?.customer_id) setVehicleCustomerFilter(parsed.customer_id);
        if (parsed?.id) {
          const restoredVehicle = await selectVehicle(Number(parsed.id), {
            remember: false,
            suppressErrors: true,
          });
          if (!restoredVehicle) {
            void clearSelectedVehicleReference();
          } else if (restoredVehicle.customer_id) {
            await selectCustomer(restoredVehicle.customer_id, {
              remember: false,
              refreshVehicles: true,
              suppressErrors: true,
            });
          }
        }
      } catch {
        // Ignore malformed assistive context values.
      }
    }

    const estimateEntry = estimatePayload?.entries?.find((entry) => entry.context_key === "selected-estimate");
    if (estimateResponse.ok && estimateEntry?.value) {
      try {
        const parsed = JSON.parse(estimateEntry.value);
        if (parsed?.id) {
          const response = await apiFetch(`/api/estimates/${Number(parsed.id)}`);
          const data = await readApiPayload(response);
          if (response.ok && data) {
            data.approval_audit = await loadEstimateApprovalAudit(Number(parsed.id));
            renderEstimate(data);
          }
        }
      } catch {
        // Ignore malformed assistive context values.
      }
    }
  } catch {
    // Context restoration is best-effort only.
  }
}

async function loadPublicApprovalPage() {
  const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const token = fragment.get("token");
  const root = $("approval-public-root");
  if (!token) {
    root.innerHTML = '<div class="empty-card"><strong>Approval link required</strong><p>Open this page from a generated approval link so the estimate token stays in the browser fragment and out of request URLs.</p></div>';
    return;
  }
  root.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading estimate</strong><br><small>Fetching the approval-safe estimate view.</small></div></div>';
  try {
    const response = await apiFetch("/api/estimate-approval/view", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Estimate approval view failed");
    $("approval-estimate-number").textContent = data.estimate_number;
    const estimate = data.revision.estimate;
    const laborItems = estimate.labor_items?.length
      ? estimate.labor_items.map((item) => `
        <tr>
          <td>${escapeHtml(item.description)}</td>
          <td>${escapeHtml(String(item.labor_hours))}</td>
          <td>${money(item.labor_rate)}</td>
          <td>${money(item.labor_total)}</td>
        </tr>`).join("")
      : `<tr><td colspan="4">No customer-facing labor items were captured.</td></tr>`;
    const parts = estimate.selected_parts.map((part) => `
      <tr>
        <td>${escapeHtml(part.part_name)}</td>
        <td>${escapeHtml(String(part.quantity))}</td>
        <td>${money(part.unit_price)}</td>
        <td>${money(part.extended_price)}</td>
      </tr>`).join("") || `<tr><td colspan="4">No customer-facing part pricing was captured.</td></tr>`;
    const feeItems = estimate.fee_items?.map((item) => `
      <tr>
        <td>${escapeHtml(item.label)}</td>
        <td>${money(item.amount)}</td>
      </tr>`).join("") || "";
    const exclusions = estimate.research.warnings?.length
      ? estimate.research.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")
      : "<li>No additional exclusions were recorded.</li>";
    const paymentOptions = data.revision.payment_options.map((option) => {
      const planDetails = option.code === "two_month_plan"
        ? `<small>Deposit due before parts are ordered: ${money(estimate.totals.parts_subtotal)}. Remaining balance after deposit: ${money(Math.max(estimate.totals.estimated_total - estimate.totals.parts_subtotal, 0))}. First payment due 30 days after service, second payment due 60 days after service.</small>`
        : `<small>${escapeHtml(option.description)}</small>`;
      return `
      <label class="field full">
        <input type="radio" name="approval-payment-option" value="${escapeHtml(option.code)}"${option.code === "pay_in_full" ? " checked" : ""}>
        ${escapeHtml(option.label)}
        ${planDetails}
      </label>`;
    }).join("");
    root.innerHTML = `
      <div class="result-hero">
        <div><span class="section-kicker"><i></i> Revision ${data.revision.revision_number}</span><h2>${escapeHtml(data.revision.vehicle.display_name)}</h2><p>${escapeHtml(estimate.job)}</p></div>
        <div class="result-total"><span>Total</span><strong>${money(estimate.totals.estimated_total)}</strong></div>
      </div>
      <div class="money-grid">
        <div class="money-card"><span>Customer</span><strong>${escapeHtml(data.revision.customer.display_name)}</strong></div>
        <div class="money-card"><span>Vehicle</span><strong>${escapeHtml(data.revision.vehicle.display_name)}</strong></div>
        <div class="money-card"><span>Status</span><strong>${escapeHtml(data.status.replaceAll("_", " "))}</strong></div>
        <div class="money-card"><span>Expires</span><strong>${new Date(data.token_expires_at).toLocaleString()}</strong></div>
      </div>
      <div class="result-grid">
        <section class="result-section">
          <h3>Customer and vehicle</h3>
          <p><strong>${escapeHtml(data.revision.customer.display_name)}</strong></p>
          <p>${escapeHtml(data.revision.vehicle.display_name)}${data.revision.vehicle.current_mileage != null ? ` · ${escapeHtml(data.revision.vehicle.current_mileage.toLocaleString())} mi` : ""}</p>
          <p>Estimate ${escapeHtml(data.estimate_number)} · Revision ${data.revision.revision_number} · ${escapeHtml(data.status.replaceAll("_", " "))}</p>
        </section>
        <section class="result-section">
          <h3>Work requested</h3>
          <p>${escapeHtml(estimate.job)}</p>
          <p>${escapeHtml(estimate.research.summary)}</p>
        </section>
        <section class="result-section">
          <h3>Conditions</h3>
          <p>${escapeHtml(data.revision.terms_text)}</p>
        </section>
        <section class="result-section">
          <h3>Exclusions and warnings</h3>
          <ul>${exclusions}</ul>
        </section>
      </div>
      <section class="result-section">
        <h3>Labor</h3>
        <table class="approval-breakdown-table">
          <thead><tr><th>Service</th><th>Hours</th><th>Rate</th><th>Total</th></tr></thead>
          <tbody>${laborItems}</tbody>
        </table>
      </section>
      <section class="result-section">
        <h3>Parts</h3>
        <table class="approval-breakdown-table">
          <thead><tr><th>Part</th><th>Qty</th><th>Unit price</th><th>Line total</th></tr></thead>
          <tbody>${parts}</tbody>
        </table>
      </section>
      <section class="result-section">
        <h3>Fees and totals</h3>
        <table class="approval-breakdown-table">
          <tbody>
            <tr><td>Labor subtotal</td><td>${money(estimate.totals.labor_total)}</td></tr>
            <tr><td>Parts subtotal</td><td>${money(estimate.totals.parts_subtotal)}</td></tr>
            ${feeItems}
            <tr><td><strong>Final estimate total</strong></td><td><strong>${money(estimate.totals.estimated_total)}</strong></td></tr>
          </tbody>
        </table>
      </section>
      <form id="approval-action-form">
        <label class="field full">Approving name <input id="approval-name" maxlength="160" placeholder="Customer name" required></label>
        <label class="field full">Typed authorization evidence <textarea id="approval-typed-authorization" maxlength="1000" placeholder="Example: Jane Customer approves revision 1 of this estimate." required></textarea></label>
        <div class="form-grid one">${paymentOptions}</div>
        <label class="field full"><input id="approval-accept-terms" type="checkbox"> I accept the estimate terms and conditions.</label>
        <label class="field full"><input id="approval-ack-payment-plan" type="checkbox"> For the payment plan: the parts-price deposit is due before parts are ordered, no repair begins until deposit and authorization are complete, and remaining payments are due 30 and 60 days after service.</label>
        <div class="estimate-submit-row">
          <button class="primary-button compact" type="submit">Approve estimate</button>
          <button class="secondary-button compact" type="button" id="approval-decline">Decline estimate</button>
        </div>
      </form>`;
    $("approval-action-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const approvalResponse = await apiFetch("/api/estimate-approval/approve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            token,
            revision_number: data.revision.revision_number,
            approving_name: $("approval-name").value.trim(),
            accepted_terms: $("approval-accept-terms").checked,
            payment_option: document.querySelector('input[name="approval-payment-option"]:checked')?.value || "pay_in_full",
            payment_plan_acknowledged: $("approval-ack-payment-plan").checked,
            typed_authorization: $("approval-typed-authorization").value.trim(),
          }),
        });
        const approvalPayload = await readApiPayload(approvalResponse);
        if (!approvalResponse.ok || !approvalPayload) throw apiError(approvalResponse, approvalPayload, "Estimate approval failed");
        showToast("Estimate approved.", "success");
        root.innerHTML = `<div class="empty-card"><strong>Estimate approved</strong><p>${escapeHtml(approvalPayload.estimate_number)} revision ${approvalPayload.revision_number} was approved at ${new Date(approvalPayload.decided_at).toLocaleString()}.</p></div>`;
      } catch (error) {
        showToast(`Estimate approval failed: ${error.message}`, "error");
      }
    });
    $("approval-decline").addEventListener("click", async () => {
      const name = $("approval-name").value.trim();
      if (!name) {
        showToast("Enter the customer name before declining.", "error");
        $("approval-name").focus();
        return;
      }
      try {
        const declineResponse = await apiFetch("/api/estimate-approval/decline", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            token,
            revision_number: data.revision.revision_number,
            declining_name: name,
            reason: "Declined from customer approval view.",
          }),
        });
        const declinePayload = await readApiPayload(declineResponse);
        if (!declineResponse.ok || !declinePayload) throw apiError(declineResponse, declinePayload, "Estimate decline failed");
        showToast("Estimate declined.", "success");
        root.innerHTML = `<div class="empty-card"><strong>Estimate declined</strong><p>${escapeHtml(declinePayload.estimate_number)} revision ${declinePayload.revision_number} was declined at ${new Date(declinePayload.decided_at).toLocaleString()}.</p></div>`;
      } catch (error) {
        showToast(`Estimate decline failed: ${error.message}`, "error");
      }
    });
  } catch (error) {
    root.innerHTML = `<div class="error-card"><strong>Approval view failed</strong><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function initializeVehicles() {
  $("vehicle-form").addEventListener("submit", (event) => {
    void submitVehicleForm(event);
  });
  $("vehicle-cancel").addEventListener("click", () => {
    state.vehicles.selectedVehicleId = null;
    state.vehicles.selectedVehicle = null;
    populateVehicleForm(null, { preferredCustomerId: state.vehicles.customerFilterId });
    renderVehicleDetail(null);
    syncEstimateRecordSummary();
    void clearSelectedVehicleReference();
  });
  $("vehicles-new").addEventListener("click", async () => {
    await loadCustomerOptions();
    state.vehicles.selectedVehicleId = null;
    state.vehicles.selectedVehicle = null;
    populateVehicleForm(null, { preferredCustomerId: state.vehicles.customerFilterId });
    renderVehicleDetail(null);
    syncEstimateRecordSummary();
    $("vehicle-vin").focus();
  });
  $("vehicles-refresh").addEventListener("click", () => {
    void loadVehicles();
  });
  $("vehicles-search").addEventListener("input", () => {
    state.vehicles.search = $("vehicles-search").value;
    state.vehicles.page = 1;
    void loadVehicles();
  });
  $("vehicles-customer-filter").addEventListener("change", () => {
    setVehicleCustomerFilter($("vehicles-customer-filter").value);
    state.vehicles.page = 1;
    state.vehicles.selectedVehicleId = null;
    state.vehicles.selectedVehicle = null;
    populateVehicleForm(null, { preferredCustomerId: state.vehicles.customerFilterId });
    renderVehicleDetail(null);
    void loadVehicles();
  });
  $("vehicles-archived-only").addEventListener("change", () => {
    state.vehicles.archivedOnly = $("vehicles-archived-only").checked;
    state.vehicles.page = 1;
    state.vehicles.selectedVehicleId = null;
    state.vehicles.selectedVehicle = null;
    populateVehicleForm(null, { preferredCustomerId: state.vehicles.customerFilterId });
    renderVehicleDetail(null);
    void loadVehicles();
  });
  $("vehicles-prev").addEventListener("click", () => {
    state.vehicles.page = Math.max(1, state.vehicles.page - 1);
    void loadVehicles();
  });
  $("vehicles-next").addEventListener("click", () => {
    if (!state.vehicles.hasMore) return;
    state.vehicles.page += 1;
    void loadVehicles();
  });
  $("vehicle-archive").addEventListener("click", () => {
    void archiveSelectedVehicle();
  });
  $("vehicle-open-customer").addEventListener("click", () => {
    void openCustomerForSelectedVehicle();
  });
  populateVehicleForm(null);
  renderVehicleDetail(null);
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
  initializeCustomers();
  initializeVehicles();
  initializeEstimate();
  initializeSystem();
  initializeAuth();
  if (window.location.pathname === "/approval") {
    navigate("approval");
    void loadPublicApprovalPage();
  } else if (window.location.pathname === "/login") {
    navigate("login");
  }
  void loadSession().then((authenticated) => {
    if (!authenticated) {
      if (window.location.pathname !== "/approval") navigate("login");
      return;
    }
    void loadCustomerOptions().catch(() => {
      showToast("Customer options failed to load.", "error");
    });
    void restoreSelectionsFromContext();
    if (window.location.pathname === "/login") navigate("dashboard");
  });
  void loadHealth(false);
  window.setInterval(() => loadHealth(false), 60000);
}

document.addEventListener("DOMContentLoaded", initializeApp);

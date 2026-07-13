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
  technicians: {
    items: [],
    selectedTechnicianId: null,
    selectedTechnician: null,
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
    search: "",
    archivedOnly: false,
  },
  myDay: {
    profile: null,
  },
  serviceDesk: {
    items: [],
    selectedRequestId: null,
    selectedRequest: null,
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
    search: "",
    statusFilter: "",
  },
  diagnostics: {
    items: [],
    selectedFindingId: null,
    selectedFinding: null,
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
    vehicleFilterId: null,
  },
  inspections: {
    items: [],
    selectedInspectionId: null,
    selectedInspection: null,
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
    vehicleFilterId: null,
    draftItems: [],
  },
  parts: {
    items: [],
    selectedPartId: null,
    selectedPart: null,
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
    search: "",
    archivedOnly: false,
  },
  vendors: {
    items: [],
    selectedVendorId: null,
    selectedVendor: null,
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
    search: "",
    archivedOnly: false,
  },
  estimates: {
    selectedEstimateId: null,
    selectedEstimate: null,
  },
  workOrders: {
    items: [],
    selectedWorkOrderId: null,
    selectedWorkOrder: null,
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
    search: "",
    statusFilter: "",
  },
  invoices: {
    items: [],
    selectedInvoiceId: null,
    selectedInvoice: null,
    selectionVersion: 0,
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
    search: "",
    statusFilter: "",
  },
  notifications: {
    items: [],
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
    unreadOnly: false,
    unreadCount: 0,
  },
  square: {
    items: [],
    loading: false,
  },
  dashboard: {
    summary: null,
    rangePreset: "30",
    dateFrom: null,
    dateTo: null,
    revenueChart: null,
    workOrderChart: null,
    sparklineCharts: {},
  },
  approvalQueue: {
    items: [],
    selectedEstimateId: null,
    selectedEstimate: null,
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: false,
  },
  currentView: "dashboard",
  health: null,
  lastEstimate: null,
};

const viewMeta = {
  login: { eyebrow: "Authentication", title: "Sign in" },
  dashboard: { eyebrow: "Operations", title: "Overview" },
  customers: { eyebrow: "Records", title: "Customers" },
  vehicles: { eyebrow: "Fleet", title: "Vehicles" },
  technicians: { eyebrow: "Staff", title: "Technicians" },
  "my-day": { eyebrow: "Technician workspace", title: "My Day" },
  "work-orders": { eyebrow: "Repair execution", title: "Work orders" },
  "approval-queue": { eyebrow: "Customer decisions", title: "Approval Queue" },
  invoices: { eyebrow: "Customer billing", title: "Invoices" },
  notifications: { eyebrow: "Owner alerts", title: "Notifications" },
  square: { eyebrow: "Payment integration", title: "Square" },
  reports: { eyebrow: "Owner reporting", title: "Reports" },
  scheduling: { eyebrow: "Not yet built", title: "Scheduling" },
  "service-desk": { eyebrow: "Intake queue", title: "Service Desk" },
  diagnostics: { eyebrow: "Findings", title: "Diagnostics" },
  inspections: { eyebrow: "Digital inspections", title: "Inspections" },
  parts: { eyebrow: "Inventory", title: "Parts" },
  vendors: { eyebrow: "Vendor directory", title: "Vendors" },
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

function isTechnicianSession() {
  return state.auth.authenticated && state.auth.user?.role === "technician";
}

function applyRoleNavVisibility() {
  const technician = isTechnicianSession();
  $$("[data-owner-only]").forEach((el) => {
    el.hidden = technician;
  });
  $$("[data-technician-only]").forEach((el) => {
    el.hidden = !technician;
  });
}

function setAuthState(authenticated, user = null, expiresAt = null) {
  const wasAuthenticated = state.auth.authenticated;
  state.auth = { authenticated, user, expiresAt };
  applyRoleNavVisibility();
  if (authenticated && !wasAuthenticated && user?.role === "owner") void refreshNotificationsBadge();
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
    if (data.user.role === "technician") {
      navigate("my-day");
    } else {
      void loadCustomerOptions();
      void restoreSelectionsFromContext();
      navigate("dashboard");
    }
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
    state.workOrders.selectedWorkOrderId = null;
    state.workOrders.selectedWorkOrder = null;
    state.notifications.items = [];
    state.notifications.unreadCount = 0;
    updateNotificationsBadge(0);
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
  if (view === "dashboard" && state.auth.authenticated) void loadDashboardSummary();
  if (view === "customers" && state.auth.authenticated) void loadCustomers();
  if (view === "vehicles" && state.auth.authenticated) void loadVehicles();
  if (view === "work-orders" && state.auth.authenticated) {
    void loadWorkOrders();
    if (!isTechnicianSession()) {
      void loadTechnicianOptions().catch(() => {
        // Owner-only convenience dropdown; a failure here shouldn't block work-order browsing.
      });
    }
  }
  if (view === "approval-queue" && state.auth.authenticated) void loadApprovalQueue();
  if (view === "invoices" && state.auth.authenticated) void loadInvoices();
  if (view === "notifications" && state.auth.authenticated) void loadNotifications();
  if (view === "square" && state.auth.authenticated) void loadSquareDashboard();
  if (view === "reports" && state.auth.authenticated) void loadReports();
  if (view === "service-desk" && state.auth.authenticated) void loadServiceDesk();
  if (view === "diagnostics" && state.auth.authenticated) void loadDiagnostics();
  if (view === "inspections" && state.auth.authenticated) void loadInspections();
  if (view === "parts" && state.auth.authenticated) void loadParts();
  if (view === "vendors" && state.auth.authenticated) void loadVendors();
  if (view === "technicians" && state.auth.authenticated) void loadTechnicians();
  if (view === "my-day" && state.auth.authenticated) void loadMyDay();
  if (view === "chat") {
    renderChatContextSummary();
    window.setTimeout(() => $("chat-message").focus(), 180);
  }
  if (view === "login") window.setTimeout(() => $("login-username").focus(), 180);
}

function renderChatContextSummary() {
  const customerEl = $("chat-context-customer");
  if (!customerEl) return;
  customerEl.textContent = state.customers.selectedCustomer?.display_name || "None selected";
  $("chat-context-vehicle").textContent = state.vehicles.selectedVehicle?.display_name || "None selected";
  $("chat-context-estimate").textContent = state.approvalQueue.selectedEstimate?.estimate_number || "None selected";
  $("chat-context-work-order").textContent = state.workOrders.selectedWorkOrder
    ? `${state.workOrders.selectedWorkOrder.estimate_number} · ${workOrderStatusLabel(state.workOrders.selectedWorkOrder.status)}`
    : "None selected";
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
  const canCreateWorkOrder = data.status === "approved";

  result.innerHTML = `
    <div class="result-hero">
      <div><span class="section-kicker"><i></i> Saved estimate ${escapeHtml(data.estimate_number)}</span><h2>${escapeHtml(vehicle)}</h2><p>${escapeHtml(estimate.job)}</p></div>
      <div class="result-total"><span>${escapeHtml(data.status.replaceAll("_", " "))}</span><strong>${money(estimate.totals.estimated_total)}</strong></div>
    </div>
    <div class="result-actions">
      <button class="secondary-button compact" type="button" id="copy-estimate">Copy estimate</button>
      <button class="secondary-button compact" type="button" id="print-estimate">Print estimate</button>
      <button class="secondary-button compact" type="button" id="send-estimate-approval"${data.status === "approved" ? " disabled" : ""}>Send for approval</button>
      <button class="secondary-button compact" type="button" id="create-work-order"${canCreateWorkOrder ? "" : " disabled"}>Create work order</button>
      <button class="text-button" type="button" id="refresh-estimate-record" title="Reload this estimate's current status from the server">Refresh status</button>
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
  $("estimate-form").hidden = true;
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
  $("create-work-order").addEventListener("click", () => {
    void createWorkOrderFromSelectedEstimate();
  });
  $("refresh-estimate-record").addEventListener("click", () => {
    void openEstimateRecord(data.id).then(() => {
      showToast("Estimate status refreshed.", "info");
    });
  });
  $("new-estimate").addEventListener("click", () => {
    result.hidden = true;
    $("estimate-form").hidden = false;
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

function setEstimateRailCollapsed(collapsed) {
  const layout = $("estimate-layout");
  const toggle = $("estimate-side-rail-toggle");
  layout.classList.toggle("rail-collapsed", collapsed);
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.title = collapsed ? "Expand estimate readiness panel" : "Collapse estimate readiness panel";
  try {
    localStorage.setItem("estimateRailCollapsed", collapsed ? "1" : "0");
  } catch {
    // Collapse preference is a convenience only; ignore storage failures (e.g. private browsing).
  }
}

function initializeEstimate() {
  ["labor-rate", "mobile-fee", "supplies", "tax-rate"].forEach((id) => $(id).addEventListener("input", savePricingPreferences));
  syncEstimateRecordSummary();
  let railCollapsed = false;
  try {
    railCollapsed = localStorage.getItem("estimateRailCollapsed") === "1";
  } catch {
    // Ignore storage access failures and default to expanded.
  }
  setEstimateRailCollapsed(railCollapsed);
  $("estimate-side-rail-toggle").addEventListener("click", () => {
    setEstimateRailCollapsed(!$("estimate-layout").classList.contains("rail-collapsed"));
  });
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

function historyStatusLabel(status) {
  return String(status || "").replace(/_/g, " ");
}

function renderCustomerHistory(data) {
  const estimatesEl = $("customer-history-estimates");
  const workOrdersEl = $("customer-history-work-orders");
  const invoicesEl = $("customer-history-invoices");
  if (!estimatesEl || !workOrdersEl || !invoicesEl) return;

  estimatesEl.innerHTML = data.estimates.items.length
    ? data.estimates.items.map((item) => `
      <button type="button" class="vehicle-preview-item" data-history-estimate-id="${item.id}">
        <strong>${escapeHtml(item.estimate_number)} · ${escapeHtml(historyStatusLabel(item.status))}</strong>
        <span>${escapeHtml(item.vehicle_display_name)}${item.estimate_total != null ? ` · $${item.estimate_total.toFixed(2)}` : ""} · ${new Date(item.updated_at).toLocaleString()}</span>
      </button>`).join("") + (data.estimates.total > data.estimates.items.length ? `<p class="history-more">Showing ${data.estimates.items.length} of ${data.estimates.total}.</p>` : "")
    : "<p>No estimates recorded for this customer yet.</p>";

  workOrdersEl.innerHTML = data.work_orders.items.length
    ? data.work_orders.items.map((item) => `
      <button type="button" class="vehicle-preview-item" data-history-work-order-id="${item.id}">
        <strong>${escapeHtml(item.estimate_number)} · ${escapeHtml(historyStatusLabel(item.status))}</strong>
        <span>${escapeHtml(item.title)} · ${new Date(item.updated_at).toLocaleString()}</span>
      </button>`).join("") + (data.work_orders.total > data.work_orders.items.length ? `<p class="history-more">Showing ${data.work_orders.items.length} of ${data.work_orders.total}.</p>` : "")
    : "<p>No work orders for this customer yet.</p>";

  invoicesEl.innerHTML = data.invoices.items.length
    ? data.invoices.items.map((item) => `
      <button type="button" class="vehicle-preview-item" data-history-invoice-id="${item.id}">
        <strong>${escapeHtml(item.invoice_number)} · ${escapeHtml(historyStatusLabel(item.status))}${item.is_overdue ? " · OVERDUE" : ""}</strong>
        <span>Total $${item.invoice_total.toFixed(2)} · Balance $${item.balance_due.toFixed(2)}${item.due_at ? ` · Due ${new Date(item.due_at).toLocaleDateString()}` : ""}</span>
      </button>`).join("") + (data.invoices.total > data.invoices.items.length ? `<p class="history-more">Showing ${data.invoices.items.length} of ${data.invoices.total}.</p>` : "")
    : "<p>No invoices for this customer yet.</p>";

  $$("[data-history-estimate-id]", estimatesEl).forEach((button) => {
    button.addEventListener("click", () => {
      void openEstimateRecord(Number(button.dataset.historyEstimateId));
    });
  });
  $$("[data-history-work-order-id]", workOrdersEl).forEach((button) => {
    button.addEventListener("click", () => {
      navigate("work-orders");
      void selectWorkOrder(Number(button.dataset.historyWorkOrderId));
    });
  });
  $$("[data-history-invoice-id]", invoicesEl).forEach((button) => {
    button.addEventListener("click", () => {
      navigate("invoices");
      void selectInvoice(Number(button.dataset.historyInvoiceId));
    });
  });
}

async function loadCustomerHistory(customerId) {
  const estimatesEl = $("customer-history-estimates");
  if (!estimatesEl) return;
  estimatesEl.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading history</strong><br><small>Reading linked estimates, work orders, and invoices.</small></div></div>';
  try {
    const response = await apiFetch(`/api/customers/${customerId}/history?limit=20`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Customer history failed");
    renderCustomerHistory(data);
  } catch (error) {
    estimatesEl.innerHTML = `<div class="error-card"><strong>Customer history failed</strong><p>${escapeHtml(error.message)}</p></div>`;
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
    void loadCustomerHistory(data.id);
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

function technicianPayloadFromForm() {
  return {
    first_name: $("technician-first-name").value.trim() || null,
    last_name: $("technician-last-name").value.trim() || null,
    job_title: $("technician-job-title").value.trim() || null,
    email: $("technician-email").value.trim() || null,
    phone: $("technician-phone").value.trim() || null,
    employment_status: $("technician-employment-status").value.trim() || null,
    hire_date: $("technician-hire-date").value || null,
    hourly_cost: $("technician-hourly-cost").value ? Number($("technician-hourly-cost").value) : null,
    certifications: $("technician-certifications").value.trim() || null,
    certification_expiration: $("technician-certification-expiration").value || null,
    specialties: $("technician-specialties").value.trim() || null,
    driver_license_valid: $("technician-driver-license-valid").checked,
    insurance_verified: $("technician-insurance-verified").checked,
    normal_availability: $("technician-normal-availability").value.trim() || null,
    safety_notes: $("technician-safety-notes").value.trim() || null,
  };
}

function populateTechnicianForm(technician = null) {
  $("technician-id").value = technician?.id ?? "";
  $("technician-first-name").value = technician?.first_name ?? "";
  $("technician-last-name").value = technician?.last_name ?? "";
  $("technician-job-title").value = technician?.job_title ?? "";
  $("technician-email").value = technician?.email ?? "";
  $("technician-phone").value = technician?.phone ?? "";
  $("technician-employment-status").value = technician?.employment_status ?? "";
  $("technician-hire-date").value = technician?.hire_date ?? "";
  $("technician-hourly-cost").value = technician?.hourly_cost ?? "";
  $("technician-certifications").value = technician?.certifications ?? "";
  $("technician-certification-expiration").value = technician?.certification_expiration ?? "";
  $("technician-specialties").value = technician?.specialties ?? "";
  $("technician-driver-license-valid").checked = Boolean(technician?.driver_license_valid);
  $("technician-insurance-verified").checked = Boolean(technician?.insurance_verified);
  $("technician-normal-availability").value = technician?.normal_availability ?? "";
  $("technician-safety-notes").value = technician?.safety_notes ?? "";
  $("technician-form-title").textContent = technician ? "Edit technician" : "Create technician";
  $("technician-form-mode").textContent = technician ? "EDIT" : "CREATE";
  $("technician-archive").hidden = !technician;
  renderTechnicianLoginPanel(technician);
}

function technicianSummaryLine(technician) {
  return [technician.job_title, technician.email, technician.phone].filter(Boolean).join(" · ");
}

function renderTechnicianLoginPanel(technician) {
  const status = $("technician-login-status");
  const form = $("technician-login-form");
  if (!technician) {
    status.innerHTML = "<p>Select a technician to manage their login.</p>";
    form.hidden = true;
    return;
  }
  if (technician.has_login) {
    status.innerHTML = `<div class="empty-card"><strong>Login active</strong><p>${escapeHtml(technician.display_name)} already has a login. Logins cannot be reissued once created.</p></div>`;
    form.hidden = true;
    return;
  }
  status.innerHTML = "";
  form.hidden = false;
  $("technician-login-username").value = "";
  $("technician-login-password").value = "";
}

function renderTechnicianDetail(technician = null) {
  const detail = $("technician-detail");
  if (!technician) {
    detail.innerHTML = "<p>Select a technician from the list or create a new record.</p>";
    $("technician-archive").hidden = true;
    return;
  }
  detail.innerHTML = `
    <div class="customer-detail-header">
      <strong>${escapeHtml(technician.display_name)}</strong>
      <span>${technician.is_archived ? "Archived" : "Active"}</span>
    </div>
    <p>${escapeHtml(technicianSummaryLine(technician) || "No details provided.")}</p>
    <div class="customer-detail-grid">
      <div><span>Login</span><strong>${technician.has_login ? "Provisioned" : "Not provisioned"}</strong></div>
      <div><span>Clocked in</span><strong>${technician.is_clocked_in ? "Yes" : "No"}</strong></div>
      <div><span>Hourly cost</span><strong>${technician.hourly_cost != null ? `$${technician.hourly_cost.toFixed(2)}` : "Not set"}</strong></div>
      <div><span>Comebacks</span><strong>${technician.comeback_count}</strong></div>
    </div>
    <div class="customer-detail-notes">
      <span>Certifications</span>
      <p>${escapeHtml(technician.certifications || "None recorded.")}</p>
    </div>
    <div class="customer-detail-notes">
      <span>Safety / training notes</span>
      <p>${escapeHtml(technician.safety_notes || "No notes recorded.")}</p>
    </div>`;
  $("technician-archive").hidden = false;
}

function renderTechniciansList() {
  const container = $("technicians-list");
  if (!state.technicians.items.length) {
    const emptyMessage = state.technicians.search || state.technicians.archivedOnly
      ? "No technicians matched this filter."
      : "No technicians yet. Create the first technician record.";
    container.innerHTML = `<div class="empty-card"><strong>No results</strong><p>${escapeHtml(emptyMessage)}</p></div>`;
  } else {
    container.innerHTML = state.technicians.items.map((technician) => `
      <button type="button" class="customer-list-item${state.technicians.selectedTechnicianId === technician.id ? " is-active" : ""}" data-technician-id="${technician.id}">
        <strong>${escapeHtml(technician.display_name)}</strong>
        <span>${escapeHtml(technicianSummaryLine(technician) || "No details")}</span>
      </button>`).join("");
    $$("[data-technician-id]", container).forEach((button) => {
      button.addEventListener("click", () => {
        void selectTechnician(Number(button.dataset.technicianId));
      });
    });
  }
  $("technicians-page-status").textContent = `Page ${state.technicians.page} · ${state.technicians.total} total`;
  $("technicians-prev").disabled = state.technicians.page <= 1;
  $("technicians-next").disabled = !state.technicians.hasMore;
}

async function selectTechnician(technicianId) {
  try {
    const response = await apiFetch(`/api/technicians/${technicianId}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Technician lookup failed");
    state.technicians.selectedTechnicianId = data.id;
    state.technicians.selectedTechnician = data;
    renderTechnicianDetail(data);
    populateTechnicianForm(data);
    renderTechniciansList();
    return data;
  } catch (error) {
    showToast(`Technician lookup failed: ${error.message}`, "error");
    return null;
  }
}

async function loadTechnicians() {
  if (!await requireAuthenticated("login")) return;
  const list = $("technicians-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading technicians</strong><br><small>Reading PostgreSQL technician records.</small></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.technicians.page),
    page_size: String(state.technicians.pageSize),
    archived: String(state.technicians.archivedOnly),
  });
  if (state.technicians.search.trim()) searchParams.set("search", state.technicians.search.trim());
  try {
    const response = await apiFetch(`/api/technicians?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Technician list failed");
    state.technicians.items = data.items;
    state.technicians.total = data.total;
    state.technicians.hasMore = data.has_more;
    renderTechniciansList();
    if (state.technicians.selectedTechnicianId) {
      const selected = data.items.find((item) => item.id === state.technicians.selectedTechnicianId);
      if (selected) {
        state.technicians.selectedTechnician = selected;
        renderTechnicianDetail(selected);
        populateTechnicianForm(selected);
      } else {
        state.technicians.selectedTechnicianId = null;
        state.technicians.selectedTechnician = null;
        populateTechnicianForm(null);
        renderTechnicianDetail(null);
      }
    }
  } catch (error) {
    list.innerHTML = `<div class="error-card"><strong>Technician list failed</strong><p>${escapeHtml(error.message)}</p></div>`;
    showToast(`Technician list failed: ${error.message}`, "error");
  }
}

async function submitTechnicianForm(event) {
  event.preventDefault();
  if (!await requireAuthenticated("login")) return;
  const technicianId = $("technician-id").value.trim();
  const submit = $("technician-save");
  submit.disabled = true;
  submit.textContent = technicianId ? "Saving…" : "Creating…";
  try {
    const response = await apiFetch(technicianId ? `/api/technicians/${technicianId}` : "/api/technicians", {
      method: technicianId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(technicianPayloadFromForm()),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Technician save failed");
    state.technicians.selectedTechnicianId = data.id;
    state.technicians.selectedTechnician = data;
    populateTechnicianForm(data);
    renderTechnicianDetail(data);
    state.technicians.page = 1;
    await loadTechnicians();
    showToast(technicianId ? "Technician updated." : "Technician created.", "success");
  } catch (error) {
    showToast(`Technician save failed: ${error.message}`, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Save technician";
  }
}

async function archiveSelectedTechnician() {
  const technician = state.technicians.selectedTechnician;
  if (!technician) return;
  if (!window.confirm(`Archive ${technician.display_name}?`)) return;
  try {
    const response = await apiFetch(`/api/technicians/${technician.id}`, { method: "DELETE" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Technician archive failed");
    state.technicians.selectedTechnicianId = null;
    state.technicians.selectedTechnician = null;
    populateTechnicianForm(null);
    renderTechnicianDetail(null);
    await loadTechnicians();
    showToast("Technician archived.", "success");
  } catch (error) {
    showToast(`Technician archive failed: ${error.message}`, "error");
  }
}

async function submitTechnicianLoginForm(event) {
  event.preventDefault();
  const technician = state.technicians.selectedTechnician;
  if (!technician) return;
  const username = $("technician-login-username").value.trim();
  const password = $("technician-login-password").value;
  if (!username || password.length < 8) {
    showToast("Enter a username and an 8+ character password.", "error");
    return;
  }
  const submit = $("technician-login-submit");
  submit.disabled = true;
  submit.textContent = "Creating…";
  try {
    const response = await apiFetch(`/api/technicians/${technician.id}/provision-login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Login provisioning failed");
    state.technicians.selectedTechnician = data.technician;
    renderTechnicianDetail(data.technician);
    renderTechnicianLoginPanel(data.technician);
    await loadTechnicians();
    showToast(`Login created for ${data.username}.`, "success");
  } catch (error) {
    showToast(`Login provisioning failed: ${error.message}`, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Create login";
  }
}

function initializeTechnicians() {
  $("technician-form").addEventListener("submit", (event) => {
    void submitTechnicianForm(event);
  });
  $("technician-login-form").addEventListener("submit", (event) => {
    void submitTechnicianLoginForm(event);
  });
  $("technician-cancel").addEventListener("click", () => {
    state.technicians.selectedTechnicianId = null;
    state.technicians.selectedTechnician = null;
    populateTechnicianForm(null);
    renderTechnicianDetail(null);
  });
  $("technicians-new").addEventListener("click", () => {
    navigate("technicians");
    state.technicians.selectedTechnicianId = null;
    state.technicians.selectedTechnician = null;
    populateTechnicianForm(null);
    renderTechnicianDetail(null);
    $("technician-first-name").focus();
  });
  $("technicians-refresh").addEventListener("click", () => {
    void loadTechnicians();
  });
  $("technicians-search").addEventListener("input", () => {
    state.technicians.search = $("technicians-search").value;
    state.technicians.page = 1;
    void loadTechnicians();
  });
  $("technicians-archived-only").addEventListener("change", () => {
    state.technicians.archivedOnly = $("technicians-archived-only").checked;
    state.technicians.page = 1;
    state.technicians.selectedTechnicianId = null;
    state.technicians.selectedTechnician = null;
    populateTechnicianForm(null);
    renderTechnicianDetail(null);
    void loadTechnicians();
  });
  $("technicians-prev").addEventListener("click", () => {
    state.technicians.page = Math.max(1, state.technicians.page - 1);
    void loadTechnicians();
  });
  $("technicians-next").addEventListener("click", () => {
    if (!state.technicians.hasMore) return;
    state.technicians.page += 1;
    void loadTechnicians();
  });
  $("technician-archive").addEventListener("click", () => {
    void archiveSelectedTechnician();
  });
  populateTechnicianForm(null);
  renderTechnicianDetail(null);
}

function renderMyDayClockState() {
  const profile = state.myDay.profile;
  const clockedIn = Boolean(profile?.technician?.is_clocked_in);
  $("my-day-status-title").textContent = profile ? profile.technician.display_name : "Checking status…";
  $("my-day-clock-state").textContent = clockedIn ? "Clocked in" : "Clocked out";
  $("my-day-clock-detail").textContent = clockedIn
    ? "You're on the clock. Clock out when your shift ends."
    : "You're off the clock. Clock in to start your shift.";
  $("my-day-clock-in").hidden = clockedIn;
  $("my-day-clock-out").hidden = !clockedIn;
}

function renderMyDayWorkOrders() {
  const container = $("my-day-work-orders");
  const ids = state.myDay.profile?.assigned_work_order_ids ?? [];
  if (!ids.length) {
    container.innerHTML = "<p>No work orders are assigned to you right now.</p>";
    return;
  }
  container.innerHTML = `<p>${ids.length} work order${ids.length === 1 ? "" : "s"} assigned. Open Work Orders to view status and details.</p>`;
}

function renderMyDayTimeEntries() {
  const container = $("my-day-time-entries");
  const entries = state.myDay.profile?.recent_time_entries ?? [];
  if (!entries.length) {
    container.innerHTML = "<p>No shifts recorded yet.</p>";
    return;
  }
  container.innerHTML = entries.map((entry) => `
    <div class="empty-card">
      <strong>${new Date(entry.clock_in_at).toLocaleString()}</strong>
      <p>${entry.clock_out_at ? `Out ${new Date(entry.clock_out_at).toLocaleString()} · ${entry.duration_minutes} min` : "Still clocked in"}</p>
    </div>`).join("");
}

async function loadMyDay() {
  if (!await requireAuthenticated("login")) return;
  try {
    const response = await apiFetch("/api/technicians/me");
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "My Day failed to load");
    state.myDay.profile = data;
    renderMyDayClockState();
    renderMyDayWorkOrders();
    renderMyDayTimeEntries();
  } catch (error) {
    $("my-day-status-title").textContent = "My Day";
    $("my-day-clock-state").textContent = "Unavailable";
    $("my-day-clock-detail").textContent = error.message;
    showToast(`My Day failed to load: ${error.message}`, "error");
  }
}

async function submitMyDayClock(action) {
  const button = action === "in" ? $("my-day-clock-in") : $("my-day-clock-out");
  button.disabled = true;
  try {
    const response = await apiFetch(`/api/technicians/me/clock-${action}`, { method: "POST" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, `Clock ${action} failed`);
    showToast(action === "in" ? "Clocked in." : "Clocked out.", "success");
    await loadMyDay();
  } catch (error) {
    showToast(`Clock ${action} failed: ${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
}

function initializeMyDay() {
  $("my-day-clock-in").addEventListener("click", () => {
    void submitMyDayClock("in");
  });
  $("my-day-clock-out").addEventListener("click", () => {
    void submitMyDayClock("out");
  });
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

function renderVehicleHistory(data) {
  const estimatesEl = $("vehicle-history-estimates");
  const workOrdersEl = $("vehicle-history-work-orders");
  if (!estimatesEl || !workOrdersEl) return;

  estimatesEl.innerHTML = data.estimates.items.length
    ? data.estimates.items.map((item) => `
      <button type="button" class="vehicle-preview-item" data-history-estimate-id="${item.id}">
        <strong>${escapeHtml(item.estimate_number)} · ${escapeHtml(historyStatusLabel(item.status))}</strong>
        <span>${item.estimate_total != null ? `$${item.estimate_total.toFixed(2)} · ` : ""}${new Date(item.updated_at).toLocaleString()}</span>
      </button>`).join("") + (data.estimates.total > data.estimates.items.length ? `<p class="history-more">Showing ${data.estimates.items.length} of ${data.estimates.total}.</p>` : "")
    : "<p>No estimates recorded for this vehicle yet.</p>";

  workOrdersEl.innerHTML = data.work_orders.items.length
    ? data.work_orders.items.map((item) => `
      <button type="button" class="vehicle-preview-item" data-history-work-order-id="${item.id}">
        <strong>${escapeHtml(item.estimate_number)} · ${escapeHtml(historyStatusLabel(item.status))}</strong>
        <span>${escapeHtml(item.title)} · ${new Date(item.updated_at).toLocaleString()}</span>
      </button>`).join("") + (data.work_orders.total > data.work_orders.items.length ? `<p class="history-more">Showing ${data.work_orders.items.length} of ${data.work_orders.total}.</p>` : "")
    : "<p>No work orders for this vehicle yet.</p>";

  $$("[data-history-estimate-id]", estimatesEl).forEach((button) => {
    button.addEventListener("click", () => {
      void openEstimateRecord(Number(button.dataset.historyEstimateId));
    });
  });
  $$("[data-history-work-order-id]", workOrdersEl).forEach((button) => {
    button.addEventListener("click", () => {
      navigate("work-orders");
      void selectWorkOrder(Number(button.dataset.historyWorkOrderId));
    });
  });
}

async function loadVehicleHistory(vehicleId) {
  const estimatesEl = $("vehicle-history-estimates");
  const workOrdersEl = $("vehicle-history-work-orders");
  if (!estimatesEl || !workOrdersEl) return;
  estimatesEl.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading history</strong><br><small>Reading linked estimates and work orders.</small></div></div>';
  workOrdersEl.innerHTML = "";
  try {
    const [estimatesResponse, workOrdersResponse] = await Promise.all([
      apiFetch(`/api/estimates?vehicle_id=${vehicleId}&page_size=20`),
      apiFetch(`/api/work-orders?vehicle_id=${vehicleId}&page_size=20`),
    ]);
    const estimatesData = await readApiPayload(estimatesResponse);
    const workOrdersData = await readApiPayload(workOrdersResponse);
    if (!estimatesResponse.ok || !estimatesData) throw apiError(estimatesResponse, estimatesData, "Vehicle estimate history failed");
    if (!workOrdersResponse.ok || !workOrdersData) throw apiError(workOrdersResponse, workOrdersData, "Vehicle work-order history failed");
    renderVehicleHistory({ estimates: estimatesData, work_orders: workOrdersData });
  } catch (error) {
    estimatesEl.innerHTML = `<div class="error-card"><strong>Vehicle history failed</strong><p>${escapeHtml(error.message)}</p></div>`;
    workOrdersEl.innerHTML = "";
  }
}

function renderVehicleDetail(vehicle = null) {
  const detail = $("vehicle-detail");
  if (!vehicle) {
    detail.innerHTML = "<p>Select a vehicle from the list or create a new record.</p>";
    $("vehicle-open-customer").hidden = true;
    $("vehicle-archive").hidden = true;
    if ($("vehicle-history-estimates")) $("vehicle-history-estimates").innerHTML = "<p>Select a vehicle to load history.</p>";
    if ($("vehicle-history-work-orders")) $("vehicle-history-work-orders").innerHTML = "<p>No vehicle selected.</p>";
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
    void loadVehicleHistory(data.id);
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

function workOrderStatusLabel(status) {
  return String(status || "").replaceAll("_", " ");
}

function populateWorkOrderStatusOptions(workOrder = null) {
  const select = $("work-order-next-status");
  const options = ['<option value="">Select a status</option>'];
  for (const status of workOrder?.allowed_next_statuses || []) {
    options.push(`<option value="${escapeHtml(status)}">${escapeHtml(workOrderStatusLabel(status))}</option>`);
  }
  select.innerHTML = options.join("");
}

function renderWorkOrderDetail(workOrder = null) {
  const detail = $("work-order-detail");
  if (!workOrder) {
    detail.innerHTML = "<p>Select a work order from the list or convert an approved estimate.</p>";
    $("work-order-id").value = "";
    $("work-order-form-status-detail").textContent = "Select a work order to update deposit, authorization, scheduling, and diagnosis details.";
    $("work-order-diagnosis").value = "";
    $("work-order-scheduled-for").value = "";
    $("work-order-deposit-received").checked = false;
    $("work-order-authorization-confirmed").checked = false;
    $("work-order-open-estimate").disabled = true;
    $("work-order-open-vehicle").disabled = true;
    $("work-order-open-invoice").disabled = true;
    $("work-order-blocked-status").innerHTML = "<strong>No blockers</strong><p>Select a work order to see blocked transitions and prerequisites.</p>";
    populateWorkOrderStatusOptions(null);
    if ($("work-order-assign-technician")) $("work-order-assign-technician").value = "";
    if ($("work-order-is-comeback")) $("work-order-is-comeback").checked = false;
    return;
  }
  const notes = workOrder.notes.map((note) => `
    <li><strong>${escapeHtml(note.visibility)}</strong> · ${escapeHtml(note.note)}<br><small>${new Date(note.created_at).toLocaleString()}</small></li>
  `).join("") || "<li>No notes recorded yet.</li>";
  const history = workOrder.status_history.map((event) => `
    <li><strong>${escapeHtml(workOrderStatusLabel(event.to_status))}</strong>${event.from_status ? ` from ${escapeHtml(workOrderStatusLabel(event.from_status))}` : ""}${event.reason ? ` · ${escapeHtml(event.reason)}` : ""}<br><small>${new Date(event.created_at).toLocaleString()}</small></li>
  `).join("") || "<li>No status history yet.</li>";
  const blocked = Object.entries(workOrder.blocked_transitions || {});
  detail.innerHTML = `
    <div class="customer-detail-header">
      <strong>${escapeHtml(workOrder.estimate_number)} · ${escapeHtml(workOrder.title)}</strong>
      <span>${escapeHtml(workOrderStatusLabel(workOrder.status))}</span>
    </div>
    <p>${escapeHtml(workOrder.complaint)}</p>
    <div class="detail-split">
      <div class="detail-main">
        <section class="result-section"><h3>Approved revision</h3><p>${escapeHtml(workOrder.source_revision.request.job)}</p><p>${money(workOrder.source_revision.estimate.totals.estimated_total)} · revision ${workOrder.source_revision.revision_number}</p></section>
        <section class="result-section"><h3>Status history</h3><ul>${history}</ul></section>
        <section class="result-section"><h3>Notes</h3><ul>${notes}</ul></section>
        <section class="result-section"><h3>Blocked transitions</h3><ul>${blocked.map(([status, reason]) => `<li><strong>${escapeHtml(workOrderStatusLabel(status))}</strong> · ${escapeHtml(reason)}</li>`).join("") || "<li>None.</li>"}</ul></section>
      </div>
      <div class="detail-rail">
        <div class="detail-rail-card"><span>Customer &amp; vehicle</span><div class="customer-detail-grid"><div><span>Customer</span><strong>${escapeHtml(workOrder.customer_display_name)}</strong></div><div><span>Vehicle</span><strong>${escapeHtml(workOrder.vehicle_display_name)}</strong></div><div><span>Technician</span><strong>${escapeHtml(workOrder.assigned_technician_display_name || "Unassigned")}</strong></div><div><span>Comeback</span><strong>${workOrder.is_comeback ? "Yes" : "No"}</strong></div></div></div>
        <div class="detail-rail-card"><span>Appointment</span><div class="customer-detail-grid"><div><span>Scheduled for</span><strong>${escapeHtml(workOrder.scheduled_for ? new Date(workOrder.scheduled_for).toLocaleString() : "Not scheduled")}</strong></div></div></div>
        <div class="detail-rail-card"><span>Totals &amp; invoice</span><div class="detail-totals"><div><span>Estimate total</span><strong>${money(workOrder.estimate_total)}</strong></div><div><span>Labor estimate</span><strong>${escapeHtml(`${workOrder.labor_hours_estimate ?? 0} hr`)}</strong></div><div><span>Payment option</span><strong>${escapeHtml(workOrder.payment_option_selected || "Not selected")}</strong></div><div class="detail-total-emphasis"><span>Invoice</span><strong>${escapeHtml(workOrder.invoice_number || "Not generated yet")}</strong></div><div><span>Invoice status</span><strong>${escapeHtml(workOrder.invoice_status ? workOrder.invoice_status.replaceAll("_", " ") : "Not generated")}</strong></div></div></div>
      </div>
    </div>`;
  $("work-order-id").value = String(workOrder.id);
  $("work-order-diagnosis").value = workOrder.diagnosis || "";
  $("work-order-scheduled-for").value = workOrder.scheduled_for ? new Date(workOrder.scheduled_for).toISOString().slice(0, 16) : "";
  $("work-order-deposit-received").checked = Boolean(workOrder.deposit_received);
  $("work-order-authorization-confirmed").checked = Boolean(workOrder.authorization_confirmed);
  $("work-order-open-estimate").disabled = false;
  $("work-order-open-vehicle").disabled = false;
  $("work-order-open-invoice").disabled = !workOrder.invoice_id;
  $("work-order-form-status-detail").textContent = blocked.length
    ? blocked.map(([, reason]) => reason).join(" ")
    : "Work order is ready for the allowed next status transitions.";
  $("work-order-blocked-status").innerHTML = blocked.length
    ? `<strong>Blocked transitions</strong><p>${blocked.map(([status, reason]) => `${workOrderStatusLabel(status)}: ${reason}`).join(" ")}</p>`
    : "<strong>No blockers</strong><p>The current prerequisites are satisfied for the available next status choices.</p>";
  populateWorkOrderStatusOptions(workOrder);
  if ($("work-order-assign-technician")) {
    $("work-order-assign-technician").value = workOrder.assigned_technician_id ? String(workOrder.assigned_technician_id) : "";
  }
  if ($("work-order-is-comeback")) $("work-order-is-comeback").checked = Boolean(workOrder.is_comeback);
}

function renderWorkOrderList() {
  const container = $("work-orders-list");
  if (!state.workOrders.items.length) {
    container.innerHTML = '<div class="empty-card"><strong>No work orders found</strong><p>Convert an approved estimate to begin execution tracking.</p></div>';
  } else {
    container.innerHTML = state.workOrders.items.map((item) => `
      <button type="button" class="customer-list-item${state.workOrders.selectedWorkOrderId === item.id ? " is-active" : ""}" data-work-order-id="${item.id}">
        <strong>${escapeHtml(item.estimate_number)} · ${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.customer_display_name)} · ${escapeHtml(workOrderStatusLabel(item.status))} · ${money(item.estimate_total)}</span>
      </button>
    `).join("");
    $$("[data-work-order-id]", container).forEach((button) => {
      button.addEventListener("click", () => {
        void selectWorkOrder(Number(button.dataset.workOrderId));
      });
    });
  }
  $("work-orders-page-status").textContent = `Page ${state.workOrders.page} · ${state.workOrders.total} total`;
  $("work-orders-prev").disabled = state.workOrders.page <= 1;
  $("work-orders-next").disabled = !state.workOrders.hasMore;
}

async function selectWorkOrder(workOrderId) {
  try {
    const response = await apiFetch(`/api/work-orders/${workOrderId}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Work-order load failed");
    state.workOrders.selectedWorkOrderId = data.id;
    state.workOrders.selectedWorkOrder = data;
    renderWorkOrderDetail(data);
  } catch (error) {
    showToast(`Work-order load failed: ${error.message}`, "error");
  }
}

async function loadWorkOrders() {
  const list = $("work-orders-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading work orders</strong><br><small>Reading approved repair execution records.</small></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.workOrders.page),
    page_size: String(state.workOrders.pageSize),
  });
  if (state.workOrders.search.trim()) searchParams.set("search", state.workOrders.search.trim());
  if (state.workOrders.statusFilter) searchParams.set("status", state.workOrders.statusFilter);
  try {
    const response = await apiFetch(`/api/work-orders?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Work-order listing failed");
    state.workOrders.items = data.items;
    state.workOrders.total = data.total;
    state.workOrders.hasMore = data.has_more;
    if (state.workOrders.selectedWorkOrderId) {
      const selected = data.items.find((item) => item.id === state.workOrders.selectedWorkOrderId);
      if (selected) {
        state.workOrders.selectedWorkOrder = selected;
      } else {
        state.workOrders.selectedWorkOrderId = null;
        state.workOrders.selectedWorkOrder = null;
      }
    }
    renderWorkOrderList();
    renderWorkOrderDetail(state.workOrders.selectedWorkOrder);
  } catch (error) {
    state.workOrders.items = [];
    state.workOrders.total = 0;
    state.workOrders.hasMore = false;
    renderWorkOrderList();
    renderWorkOrderDetail(null);
    showToast(`Work-order listing failed: ${error.message}`, "error");
  }
}

async function createWorkOrderFromSelectedEstimate() {
  const estimate = state.estimates.selectedEstimate;
  if (!estimate || estimate.status !== "approved") {
    showToast("Select an approved saved estimate before creating a work order.", "error");
    navigate("estimate");
    return;
  }
  try {
    const response = await apiFetch(`/api/estimates/${estimate.id}/work-order`, { method: "POST" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Work-order conversion failed");
    state.workOrders.selectedWorkOrderId = data.id;
    state.workOrders.selectedWorkOrder = data;
    navigate("work-orders");
    await loadWorkOrders();
    renderWorkOrderDetail(data);
    showToast("Work order ready.", "success");
  } catch (error) {
    showToast(`Work-order conversion failed: ${error.message}`, "error");
  }
}

async function openEstimateRecord(estimateId) {
  const response = await apiFetch(`/api/estimates/${estimateId}`);
  const data = await readApiPayload(response);
  if (!response.ok || !data) throw apiError(response, data, "Estimate load failed");
  data.approval_audit = await loadEstimateApprovalAudit(estimateId);
  state.estimates.selectedEstimateId = data.id;
  state.estimates.selectedEstimate = data;
  navigate("estimate");
  renderEstimate(data);
}

async function submitWorkOrderUpdate(event) {
  event.preventDefault();
  const workOrderId = $("work-order-id").value.trim();
  if (!workOrderId) {
    showToast("Select a work order before saving updates.", "error");
    return;
  }
  try {
    const response = await apiFetch(`/api/work-orders/${workOrderId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        diagnosis: $("work-order-diagnosis").value.trim() || null,
        scheduled_for: $("work-order-scheduled-for").value ? new Date($("work-order-scheduled-for").value).toISOString() : null,
        deposit_received: $("work-order-deposit-received").checked,
        authorization_confirmed: $("work-order-authorization-confirmed").checked,
      }),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Work-order update failed");
    state.workOrders.selectedWorkOrder = data;
    state.workOrders.selectedWorkOrderId = data.id;
    renderWorkOrderDetail(data);
    void loadWorkOrders();
    showToast("Work order updated.", "success");
  } catch (error) {
    showToast(`Work-order update failed: ${error.message}`, "error");
  }
}

async function loadTechnicianOptions() {
  const response = await apiFetch("/api/technicians?page=1&page_size=100&archived=false");
  const data = await readApiPayload(response);
  if (!response.ok || !data) throw apiError(response, data, "Technician options failed");
  const select = $("work-order-assign-technician");
  if (!select) return;
  const currentValue = select.value;
  select.innerHTML = ['<option value="">Unassigned</option>', ...data.items.map((technician) => (
    `<option value="${technician.id}">${escapeHtml(technician.display_name)}</option>`
  ))].join("");
  if (currentValue) select.value = currentValue;
}

async function submitWorkOrderAssignment(event) {
  event.preventDefault();
  const workOrderId = $("work-order-id").value.trim();
  if (!workOrderId) {
    showToast("Select a work order before assigning a technician.", "error");
    return;
  }
  const technicianId = $("work-order-assign-technician").value;
  try {
    const assignResponse = await apiFetch(`/api/work-orders/${workOrderId}/assign-technician`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ technician_id: technicianId ? Number(technicianId) : null }),
    });
    const assignData = await readApiPayload(assignResponse);
    if (!assignResponse.ok || !assignData) throw apiError(assignResponse, assignData, "Technician assignment failed");
    const patchResponse = await apiFetch(`/api/work-orders/${workOrderId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_comeback: $("work-order-is-comeback").checked }),
    });
    const patchData = await readApiPayload(patchResponse);
    if (!patchResponse.ok || !patchData) throw apiError(patchResponse, patchData, "Comeback flag update failed");
    state.workOrders.selectedWorkOrder = patchData;
    state.workOrders.selectedWorkOrderId = patchData.id;
    renderWorkOrderDetail(patchData);
    void loadWorkOrders();
    showToast("Assignment saved.", "success");
  } catch (error) {
    showToast(`Assignment save failed: ${error.message}`, "error");
  }
}

async function submitWorkOrderStatus(event) {
  event.preventDefault();
  const workOrderId = $("work-order-id").value.trim();
  const nextStatus = $("work-order-next-status").value;
  if (!workOrderId || !nextStatus) {
    showToast("Select a work order and next status before updating.", "error");
    return;
  }
  try {
    const response = await apiFetch(`/api/work-orders/${workOrderId}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: nextStatus,
        reason: $("work-order-status-reason").value.trim() || null,
      }),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Work-order status update failed");
    state.workOrders.selectedWorkOrder = data;
    state.workOrders.selectedWorkOrderId = data.id;
    $("work-order-status-reason").value = "";
    renderWorkOrderDetail(data);
    void loadWorkOrders();
    showToast("Work-order status updated.", "success");
  } catch (error) {
    showToast(`Work-order status update failed: ${error.message}`, "error");
  }
}

async function submitWorkOrderNote(event) {
  event.preventDefault();
  const workOrderId = $("work-order-id").value.trim();
  const note = $("work-order-note").value.trim();
  if (!workOrderId || !note) {
    showToast("Select a work order and enter a note before saving.", "error");
    return;
  }
  try {
    const response = await apiFetch(`/api/work-orders/${workOrderId}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        note,
        visibility: $("work-order-note-visibility").value,
      }),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Work-order note failed");
    state.workOrders.selectedWorkOrder = data;
    state.workOrders.selectedWorkOrderId = data.id;
    $("work-order-note").value = "";
    $("work-order-note-visibility").value = "internal";
    renderWorkOrderDetail(data);
    void loadWorkOrders();
    showToast("Work-order note added.", "success");
  } catch (error) {
    showToast(`Work-order note failed: ${error.message}`, "error");
  }
}

async function openEstimateForSelectedWorkOrder() {
  const estimateId = state.workOrders.selectedWorkOrder?.estimate_id;
  if (!estimateId) return;
  try {
    if (state.estimates.selectedEstimate?.id === estimateId) {
      navigate("estimate");
      renderEstimate(state.estimates.selectedEstimate);
      return;
    }
    await openEstimateRecord(estimateId);
  } catch (error) {
    showToast(`Estimate load failed: ${error.message}`, "error");
  }
}

function openVehicleForSelectedWorkOrder() {
  const vehicleId = state.workOrders.selectedWorkOrder?.vehicle_id;
  if (!vehicleId) return;
  navigate("vehicles");
  void selectVehicle(vehicleId, { remember: true, suppressErrors: false });
}

async function openInvoiceForSelectedWorkOrder() {
  const invoiceId = state.workOrders.selectedWorkOrder?.invoice_id;
  if (!invoiceId) {
    showToast("This work order does not have an invoice yet.", "error");
    return;
  }
  navigate("invoices");
  await selectInvoice(invoiceId);
}

function initializeWorkOrders() {
  $("work-orders-create").addEventListener("click", () => {
    void createWorkOrderFromSelectedEstimate();
  });
  $("work-orders-refresh").addEventListener("click", () => {
    void loadWorkOrders();
  });
  $("work-orders-search").addEventListener("input", () => {
    state.workOrders.search = $("work-orders-search").value;
    state.workOrders.page = 1;
    void loadWorkOrders();
  });
  $("work-orders-status-filter").addEventListener("change", () => {
    state.workOrders.statusFilter = $("work-orders-status-filter").value;
    state.workOrders.page = 1;
    void loadWorkOrders();
  });
  $("work-orders-prev").addEventListener("click", () => {
    state.workOrders.page = Math.max(1, state.workOrders.page - 1);
    void loadWorkOrders();
  });
  $("work-orders-next").addEventListener("click", () => {
    if (!state.workOrders.hasMore) return;
    state.workOrders.page += 1;
    void loadWorkOrders();
  });
  $("work-order-update-form").addEventListener("submit", (event) => {
    void submitWorkOrderUpdate(event);
  });
  $("work-order-assign-form").addEventListener("submit", (event) => {
    void submitWorkOrderAssignment(event);
  });
  $("work-order-status-form").addEventListener("submit", (event) => {
    void submitWorkOrderStatus(event);
  });
  $("work-order-note-form").addEventListener("submit", (event) => {
    void submitWorkOrderNote(event);
  });
  $("work-order-open-estimate").addEventListener("click", () => {
    void openEstimateForSelectedWorkOrder();
  });
  $("work-order-open-vehicle").addEventListener("click", openVehicleForSelectedWorkOrder);
  $("work-order-open-invoice").addEventListener("click", () => {
    void openInvoiceForSelectedWorkOrder();
  });
  renderWorkOrderDetail(null);
}

function invoiceStatusLabel(status) {
  return String(status || "").replaceAll("_", " ");
}

function invoicePaymentAppliesToLabel(appliesTo) {
  return String(appliesTo || "").replaceAll("_", " ");
}

function renderInvoiceDetail(invoice = null) {
  const detail = $("invoice-detail");
  if (!invoice) {
    detail.innerHTML = "<p>Select a completed-work-order invoice from the list.</p>";
    $("invoice-id").value = "";
    $("invoice-form-mode").textContent = "DRAFT";
    $("invoice-due-days").value = "30";
    $("invoice-open-work-order").disabled = true;
    $("invoice-open-html").disabled = true;
    $("invoice-open-pdf").disabled = true;
    $("invoice-issue-save").disabled = true;
    $("invoice-payment-save").disabled = true;
    $("invoice-square-push").hidden = true;
    $("invoice-square-refresh").hidden = true;
    return;
  }
  const lineItems = invoice.line_items.map((item) => `
    <li><strong>${escapeHtml(item.kind.replaceAll("_", " "))}</strong> · ${escapeHtml(item.description)} · ${escapeHtml(String(item.quantity))} × ${money(item.unit_amount)} = ${money(item.line_total)}</li>
  `).join("") || "<li>No line items.</li>";

  const reversedIds = new Set(
    invoice.payments.filter((payment) => payment.reversal_of_payment_id !== null).map((payment) => payment.reversal_of_payment_id)
  );
  const paymentRows = invoice.payments.map((payment) => {
    const isVoided = reversedIds.has(payment.id);
    const tags = [];
    if (payment.is_reversal) tags.push("Void");
    if (isVoided) tags.push("Voided");
    const canVoid = !payment.is_reversal && !isVoided;
    return `
    <li>
      <strong>${money(payment.amount)}</strong> · ${escapeHtml(invoicePaymentAppliesToLabel(payment.applies_to))} · ${escapeHtml(payment.method_label)}
      · ${escapeHtml(new Date(payment.recorded_at).toLocaleString())}
      ${tags.length ? `<span class="estimate-number">${tags.map((tag) => escapeHtml(tag)).join(" ")}</span>` : ""}
      ${payment.note ? `<br><small>${escapeHtml(payment.note)}</small>` : ""}
      ${canVoid ? `<button type="button" class="text-button" data-void-payment-id="${payment.id}">Void</button>` : ""}
    </li>`;
  }).join("") || "<li>No payments recorded yet.</li>";

  const scheduleRows = invoice.schedule.map((entry) => `
    <li><strong>${escapeHtml(entry.label)}</strong> · ${escapeHtml(entry.due_at ? new Date(entry.due_at).toLocaleDateString() : "No due date")} · ${money(entry.amount)}</li>
  `).join("");

  detail.innerHTML = `
    <div class="customer-detail-header">
      <strong>${escapeHtml(invoice.invoice_number)} · ${escapeHtml(invoice.title)}</strong>
      <span>${escapeHtml(invoiceStatusLabel(invoice.status))}${invoice.is_overdue ? ' <span class="badge">Overdue</span>' : ""}</span>
    </div>
    <p>${escapeHtml(invoice.complaint)}</p>
    <div class="detail-split">
      <div class="detail-main">
        <section class="result-section"><h3>Line items</h3><ul>${lineItems}</ul></section>
        <section class="result-section"><h3>Payment history</h3><ul>${paymentRows}</ul></section>
        ${invoice.schedule.length ? `<section class="result-section"><h3>Payment schedule</h3><ul>${scheduleRows}</ul></section>` : ""}
      </div>
      <div class="detail-rail">
        <div class="detail-rail-card"><span>Customer &amp; vehicle</span><div class="customer-detail-grid"><div><span>Customer</span><strong>${escapeHtml(invoice.customer.display_name)}</strong></div><div><span>Vehicle</span><strong>${escapeHtml(invoice.vehicle.display_name)}</strong></div></div></div>
        <div class="detail-rail-card"><span>Dates</span><div class="customer-detail-grid"><div><span>Issued</span><strong>${escapeHtml(invoice.issued_at ? new Date(invoice.issued_at).toLocaleString() : "Draft")}</strong></div><div><span>Due</span><strong>${escapeHtml(invoice.due_at ? new Date(invoice.due_at).toLocaleString() : "Not issued")}</strong></div></div></div>
        <div class="detail-rail-card"><span>Financial summary</span><div class="detail-totals">
          <div><span>Labor total</span><strong>${money(invoice.labor_total)}</strong></div>
          <div><span>Parts total</span><strong>${money(invoice.parts_total)}</strong></div>
          <div><span>Fees total</span><strong>${money(invoice.fees_total)}</strong></div>
          <div class="detail-total-emphasis"><span>Invoice total</span><strong>${money(invoice.invoice_total)}</strong></div>
          <div><span>Total paid</span><strong>${money(invoice.total_paid)}</strong></div>
          <div class="detail-total-emphasis"><span>Balance due</span><strong>${money(invoice.balance_due)}</strong></div>
        </div></div>
        ${invoice.square_invoice_id || invoice.square_payment_url ? `<div class="detail-rail-card"><span>Square</span><div class="customer-detail-grid">${invoice.square_invoice_id ? `<div><span>Square status</span><strong>${escapeHtml(invoice.square_status || "unknown")}</strong></div>` : ""}${invoice.square_payment_url ? `<div><span>Pay link</span><strong><a href="${escapeHtml(invoice.square_payment_url)}" target="_blank" rel="noopener">Open payment page</a></strong></div>` : ""}</div></div>` : ""}
      </div>
    </div>
  `;
  $$("[data-void-payment-id]", detail).forEach((button) => {
    button.addEventListener("click", () => {
      void voidPayment(Number(button.dataset.voidPaymentId));
    });
  });
  $("invoice-id").value = String(invoice.id);
  $("invoice-form-mode").textContent = invoice.status.toUpperCase();
  $("invoice-open-work-order").disabled = false;
  $("invoice-open-html").disabled = false;
  $("invoice-open-pdf").disabled = false;
  $("invoice-issue-save").disabled = invoice.status !== "draft";
  $("invoice-payment-save").disabled = invoice.status === "draft" || invoice.status === "void";
  const squareConfigured = Boolean(state.health?.square_configured);
  const pushable = squareConfigured && !invoice.square_invoice_id
    && invoice.status !== "draft" && invoice.status !== "void";
  $("invoice-square-push").hidden = !squareConfigured;
  $("invoice-square-push").disabled = !pushable;
  $("invoice-square-refresh").hidden = !squareConfigured;
  $("invoice-square-refresh").disabled = !invoice.square_invoice_id;
}

function renderInvoiceList() {
  const container = $("invoices-list");
  if (!state.invoices.items.length) {
    container.innerHTML = '<div class="empty-card"><strong>No invoices found</strong><p>Complete a work order to generate a draft invoice.</p></div>';
  } else {
    container.innerHTML = state.invoices.items.map((item) => `
      <button type="button" class="customer-list-item${state.invoices.selectedInvoiceId === item.id ? " is-active" : ""}" data-invoice-id="${item.id}">
        <strong>${escapeHtml(item.invoice_number)} · ${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.customer.display_name)} · ${escapeHtml(invoiceStatusLabel(item.status))} · ${money(item.invoice_total)}</span>
      </button>
    `).join("");
    $$("[data-invoice-id]", container).forEach((button) => {
      button.addEventListener("click", () => {
        void selectInvoice(Number(button.dataset.invoiceId));
      });
    });
  }
  $("invoices-page-status").textContent = `Page ${state.invoices.page} · ${state.invoices.total} total`;
  $("invoices-prev").disabled = state.invoices.page <= 1;
  $("invoices-next").disabled = !state.invoices.hasMore;
}

async function selectInvoice(invoiceId) {
  const version = ++state.invoices.selectionVersion;
  try {
    const response = await apiFetch(`/api/invoices/${invoiceId}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Invoice load failed");
    if (version !== state.invoices.selectionVersion) return;
    state.invoices.selectedInvoiceId = data.id;
    state.invoices.selectedInvoice = data;
    renderInvoiceList();
    renderInvoiceDetail(data);
  } catch (error) {
    showToast(`Invoice load failed: ${error.message}`, "error");
  }
}

async function loadInvoices() {
  const version = state.invoices.selectionVersion;
  const list = $("invoices-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading invoices</strong><br><small>Reading completed-work-order billing records.</small></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.invoices.page),
    page_size: String(state.invoices.pageSize),
  });
  if (state.invoices.search.trim()) searchParams.set("search", state.invoices.search.trim());
  if (state.invoices.statusFilter) searchParams.set("status", state.invoices.statusFilter);
  try {
    const response = await apiFetch(`/api/invoices?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Invoice listing failed");
    state.invoices.items = data.items;
    state.invoices.total = data.total;
    state.invoices.hasMore = data.has_more;
    if (state.invoices.selectedInvoiceId) {
      const selected = data.items.find((item) => item.id === state.invoices.selectedInvoiceId);
      if (selected) {
        state.invoices.selectedInvoice = selected;
      } else if (version === state.invoices.selectionVersion) {
        // Only clear the selection if no newer selectInvoice() call has
        // started since this list fetch began -- otherwise this slower,
        // now-stale response would clobber a more recent selection (e.g.
        // opening an invoice from a work order races this list refresh).
        state.invoices.selectedInvoiceId = null;
        state.invoices.selectedInvoice = null;
      }
    }
    renderInvoiceList();
    renderInvoiceDetail(state.invoices.selectedInvoice);
  } catch (error) {
    state.invoices.items = [];
    state.invoices.total = 0;
    state.invoices.hasMore = false;
    renderInvoiceList();
    renderInvoiceDetail(null);
    showToast(`Invoice listing failed: ${error.message}`, "error");
  }
}

async function submitInvoiceIssue(event) {
  event.preventDefault();
  const invoiceId = $("invoice-id").value.trim();
  if (!invoiceId) {
    showToast("Select an invoice before issuing it.", "error");
    return;
  }
  try {
    const response = await apiFetch(`/api/invoices/${invoiceId}/issue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        due_in_days: Number($("invoice-due-days").value || "30"),
      }),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Invoice issue failed");
    state.invoices.selectedInvoice = data;
    state.invoices.selectedInvoiceId = data.id;
    renderInvoiceDetail(data);
    void loadInvoices();
    showToast("Invoice issued.", "success");
  } catch (error) {
    showToast(`Invoice issue failed: ${error.message}`, "error");
  }
}

async function pushInvoiceToSquare() {
  const invoice = state.invoices.selectedInvoice;
  if (!invoice) {
    showToast("Select an invoice before sending it to Square.", "error");
    return;
  }
  if (!window.confirm(`Send invoice ${invoice.invoice_number} to the customer through Square?`)) return;
  try {
    const response = await apiFetch(`/api/invoices/${invoice.id}/square/push`, { method: "POST" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Square send failed");
    state.invoices.selectedInvoice = data;
    state.invoices.selectedInvoiceId = data.id;
    renderInvoiceDetail(data);
    showToast("Invoice sent through Square.", "success");
  } catch (error) {
    showToast(`Square send failed: ${error.message}`, "error");
  }
}

async function refreshSquareInvoice() {
  const invoice = state.invoices.selectedInvoice;
  if (!invoice || !invoice.square_invoice_id) return;
  try {
    const response = await apiFetch(`/api/invoices/${invoice.id}/square/refresh`, { method: "POST" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Square refresh failed");
    state.invoices.selectedInvoice = data;
    renderInvoiceDetail(data);
    showToast(`Square status: ${data.square_status || "unknown"}.`, "info");
  } catch (error) {
    showToast(`Square refresh failed: ${error.message}`, "error");
  }
}

async function submitRecordPayment(event) {
  event.preventDefault();
  const invoiceId = $("invoice-id").value.trim();
  const amount = Number($("invoice-payment-amount").value || "0");
  const methodLabel = $("invoice-payment-method").value.trim();
  if (!invoiceId || !amount || amount <= 0 || !methodLabel) {
    showToast("Select an invoice and enter an amount and method before recording a payment.", "error");
    return;
  }
  const recordedAtValue = $("invoice-payment-recorded-at").value;
  try {
    const response = await apiFetch(`/api/invoices/${invoiceId}/payments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        amount,
        method_label: methodLabel,
        applies_to: $("invoice-payment-applies-to").value,
        note: $("invoice-payment-note").value.trim() || null,
        recorded_at: recordedAtValue ? new Date(recordedAtValue).toISOString() : null,
      }),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Payment recording failed");
    state.invoices.selectedInvoice = data;
    state.invoices.selectedInvoiceId = data.id;
    $("invoice-payment-amount").value = "";
    $("invoice-payment-method").value = "";
    $("invoice-payment-note").value = "";
    $("invoice-payment-recorded-at").value = "";
    $("invoice-payment-applies-to").value = "other";
    renderInvoiceDetail(data);
    void loadInvoices();
    showToast("Payment recorded.", "success");
  } catch (error) {
    showToast(`Payment recording failed: ${error.message}`, "error");
  }
}

async function voidPayment(paymentId) {
  const invoiceId = state.invoices.selectedInvoice?.id;
  if (!invoiceId || !paymentId) return;
  if (!window.confirm("Void this payment? This cannot be undone and creates a reversal entry.")) return;
  try {
    const response = await apiFetch(`/api/invoices/${invoiceId}/payments/${paymentId}/void`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: null }),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Payment void failed");
    state.invoices.selectedInvoice = data;
    state.invoices.selectedInvoiceId = data.id;
    renderInvoiceDetail(data);
    void loadInvoices();
    showToast("Payment voided.", "success");
  } catch (error) {
    showToast(`Payment void failed: ${error.message}`, "error");
  }
}

async function openWorkOrderForSelectedInvoice() {
  const workOrderId = state.invoices.selectedInvoice?.work_order_id;
  if (!workOrderId) return;
  navigate("work-orders");
  await selectWorkOrder(workOrderId);
}

function openInvoiceDocument(kind) {
  const invoiceId = state.invoices.selectedInvoice?.id;
  if (!invoiceId) return;
  window.open(`/api/invoices/${invoiceId}/${kind}`, "_blank", "noopener");
}

function initializeInvoices() {
  $("invoices-refresh").addEventListener("click", () => {
    void loadInvoices();
  });
  $("invoice-square-push").addEventListener("click", () => {
    void pushInvoiceToSquare();
  });
  $("invoice-square-refresh").addEventListener("click", () => {
    void refreshSquareInvoice();
  });
  $("invoices-search").addEventListener("input", () => {
    state.invoices.search = $("invoices-search").value;
    state.invoices.page = 1;
    void loadInvoices();
  });
  $("invoices-status-filter").addEventListener("change", () => {
    state.invoices.statusFilter = $("invoices-status-filter").value;
    state.invoices.page = 1;
    void loadInvoices();
  });
  $("invoices-prev").addEventListener("click", () => {
    state.invoices.page = Math.max(1, state.invoices.page - 1);
    void loadInvoices();
  });
  $("invoices-next").addEventListener("click", () => {
    if (!state.invoices.hasMore) return;
    state.invoices.page += 1;
    void loadInvoices();
  });
  $("invoice-issue-form").addEventListener("submit", (event) => {
    void submitInvoiceIssue(event);
  });
  $("invoice-payment-form").addEventListener("submit", (event) => {
    void submitRecordPayment(event);
  });
  $("invoice-open-work-order").addEventListener("click", () => {
    void openWorkOrderForSelectedInvoice();
  });
  $("invoice-open-html").addEventListener("click", () => {
    openInvoiceDocument("html");
  });
  $("invoice-open-pdf").addEventListener("click", () => {
    openInvoiceDocument("pdf");
  });
  renderInvoiceDetail(null);
}

function updateNotificationsBadge(count) {
  const badge = $("nav-notifications-badge");
  if (!badge) return;
  state.notifications.unreadCount = count;
  badge.textContent = count > 99 ? "99+" : String(count);
  badge.hidden = count === 0;
}

async function refreshNotificationsBadge() {
  try {
    const response = await apiFetch("/api/notifications?page=1&page_size=1&unread=true");
    const data = await readApiPayload(response);
    if (!response.ok || !data) return;
    updateNotificationsBadge(data.unread_count);
  } catch {
    // Badge refresh is best-effort background polling; never toast on failure.
  }
}

function notificationTargetLabel(entityType) {
  if (entityType === "estimate") return "Open estimate";
  if (entityType === "work_order") return "Open work order";
  return "Open invoice";
}

function openNotificationTarget(notification) {
  if (notification.entity_type === "estimate") {
    void openEstimateRecord(notification.entity_id);
  } else if (notification.entity_type === "work_order") {
    navigate("work-orders");
    void selectWorkOrder(notification.entity_id);
  } else {
    navigate("invoices");
    void selectInvoice(notification.entity_id);
  }
}

function renderNotificationsList() {
  const list = $("notifications-list");
  const { items, page, total, hasMore } = state.notifications;
  $("notifications-page-status").textContent = `Page ${page} · ${total} total`;
  $("notifications-prev").disabled = page <= 1;
  $("notifications-next").disabled = !hasMore;
  if (!items.length) {
    list.innerHTML = state.notifications.unreadOnly
      ? "<p>No unread notifications.</p>"
      : "<p>No notifications yet.</p>";
    return;
  }
  list.innerHTML = items.map((item) => `
    <button type="button" class="customer-list-item notification-item${item.read_at ? "" : " is-unread"}" data-notification-id="${item.id}" data-notification-entity="${escapeHtml(item.entity_type)}">
      <strong>${item.read_at ? "" : "● "}${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.body || notificationTargetLabel(item.entity_type))}</span>
      <span>${new Date(item.created_at).toLocaleString()}</span>
    </button>`).join("");
  $$("[data-notification-id]", list).forEach((button) => {
    button.addEventListener("click", () => {
      const notification = state.notifications.items.find(
        (item) => item.id === Number(button.dataset.notificationId),
      );
      if (!notification) return;
      if (!notification.read_at) void markNotificationRead(notification.id);
      openNotificationTarget(notification);
    });
  });
}

async function loadNotifications() {
  if (!await requireAuthenticated("login")) return;
  const list = $("notifications-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading notifications</strong><br><small>Reading status-change alerts.</small></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.notifications.page),
    page_size: String(state.notifications.pageSize),
    unread: String(state.notifications.unreadOnly),
  });
  try {
    const response = await apiFetch(`/api/notifications?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Notification list failed");
    state.notifications.items = data.items;
    state.notifications.total = data.total;
    state.notifications.hasMore = data.has_more;
    updateNotificationsBadge(data.unread_count);
    renderNotificationsList();
  } catch (error) {
    state.notifications.items = [];
    state.notifications.total = 0;
    state.notifications.hasMore = false;
    renderNotificationsList();
    showToast(`Notification list failed: ${error.message}`, "error");
  }
}

async function markNotificationRead(notificationId) {
  try {
    const response = await apiFetch(`/api/notifications/${notificationId}/read`, { method: "POST" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Mark read failed");
    updateNotificationsBadge(data.unread_count);
    const item = state.notifications.items.find((entry) => entry.id === notificationId);
    if (item && !item.read_at) item.read_at = new Date().toISOString();
    renderNotificationsList();
  } catch (error) {
    showToast(`Mark read failed: ${error.message}`, "error");
  }
}

async function markAllNotificationsRead() {
  try {
    const response = await apiFetch("/api/notifications/read-all", { method: "POST" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Mark all read failed");
    updateNotificationsBadge(data.unread_count);
    showToast("All notifications marked read.", "success");
    void loadNotifications();
  } catch (error) {
    showToast(`Mark all read failed: ${error.message}`, "error");
  }
}

function initializeNotifications() {
  $("notifications-refresh").addEventListener("click", () => {
    void loadNotifications();
  });
  $("notifications-mark-all").addEventListener("click", () => {
    void markAllNotificationsRead();
  });
  $("notifications-unread-filter").addEventListener("change", () => {
    state.notifications.unreadOnly = $("notifications-unread-filter").checked;
    state.notifications.page = 1;
    void loadNotifications();
  });
  $("notifications-prev").addEventListener("click", () => {
    if (state.notifications.page > 1) {
      state.notifications.page -= 1;
      void loadNotifications();
    }
  });
  $("notifications-next").addEventListener("click", () => {
    if (state.notifications.hasMore) {
      state.notifications.page += 1;
      void loadNotifications();
    }
  });
}

function renderSquareStatusBanner() {
  const banner = $("square-status-banner");
  const configured = Boolean(state.health?.square_configured);
  const environment = state.health?.square_environment || "sandbox";
  if (configured) {
    banner.innerHTML = `<strong>Square is connected (${escapeHtml(environment)}).</strong><p>Issued invoices can be sent to Square for online card payment below.</p>`;
  } else {
    banner.innerHTML = `<strong>Square is not configured yet.</strong><p>Add <code>SQUARE_ACCESS_TOKEN</code> and <code>SQUARE_LOCATION_ID</code> to this server's environment and restart the backend to enable sending invoices to Square. Until then, invoices stay local-only.</p>`;
  }
}

function squareRowStatusLabel(item) {
  if (!item.square_invoice_id) return "Not sent to Square";
  return `Square: ${item.square_status || "unknown"}`;
}

function renderSquareInvoicesList() {
  const list = $("square-invoices-list");
  const configured = Boolean(state.health?.square_configured);
  const items = state.square.items;
  if (!items.length) {
    list.innerHTML = "<p>No issued invoices yet. Invoices become eligible for Square once they're issued.</p>";
    return;
  }
  list.innerHTML = items.map((item) => {
    const pushable = configured && !item.square_invoice_id && item.status !== "draft" && item.status !== "void";
    const refreshable = configured && Boolean(item.square_invoice_id);
    return `
    <div class="customer-list-item square-invoice-row" data-square-invoice-id="${item.id}">
      <strong>${escapeHtml(item.invoice_number)} · ${escapeHtml(item.customer.display_name)}</strong>
      <span>${escapeHtml(invoiceStatusLabel(item.status))} · ${money(item.invoice_total)} · ${escapeHtml(squareRowStatusLabel(item))}</span>
      ${item.square_payment_url ? `<span><a href="${escapeHtml(item.square_payment_url)}" target="_blank" rel="noopener">Open Square pay link</a></span>` : ""}
      <div class="customers-form-actions">
        <button type="button" class="secondary-button compact" data-square-push="${item.id}"${pushable ? "" : " disabled"}>Send with Square</button>
        <button type="button" class="secondary-button compact" data-square-refresh="${item.id}"${refreshable ? "" : " disabled"}>Refresh status</button>
      </div>
    </div>`;
  }).join("");
  $$("[data-square-push]", list).forEach((button) => {
    button.addEventListener("click", () => {
      void pushInvoiceToSquareFromDashboard(Number(button.dataset.squarePush));
    });
  });
  $$("[data-square-refresh]", list).forEach((button) => {
    button.addEventListener("click", () => {
      void refreshSquareInvoiceFromDashboard(Number(button.dataset.squareRefresh));
    });
  });
}

async function loadSquareDashboard() {
  if (!await requireAuthenticated("login")) return;
  renderSquareStatusBanner();
  const list = $("square-invoices-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading invoices</strong><br><small>Reading issued invoices and Square status.</small></div></div>';
  try {
    const response = await apiFetch("/api/invoices?page=1&page_size=50");
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Invoice list failed");
    state.square.items = data.items.filter((item) => item.status !== "draft");
    renderSquareInvoicesList();
  } catch (error) {
    state.square.items = [];
    list.innerHTML = `<div class="error-card"><strong>Square dashboard failed</strong><p>${escapeHtml(error.message)}</p></div>`;
  }
}

async function pushInvoiceToSquareFromDashboard(invoiceId) {
  const item = state.square.items.find((entry) => entry.id === invoiceId);
  if (!item) return;
  if (!window.confirm(`Send invoice ${item.invoice_number} to the customer through Square?`)) return;
  try {
    const response = await apiFetch(`/api/invoices/${invoiceId}/square/push`, { method: "POST" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Square send failed");
    const index = state.square.items.findIndex((entry) => entry.id === invoiceId);
    if (index !== -1) state.square.items[index] = data;
    renderSquareInvoicesList();
    showToast("Invoice sent through Square.", "success");
  } catch (error) {
    showToast(`Square send failed: ${error.message}`, "error");
  }
}

async function refreshSquareInvoiceFromDashboard(invoiceId) {
  try {
    const response = await apiFetch(`/api/invoices/${invoiceId}/square/refresh`, { method: "POST" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Square refresh failed");
    const index = state.square.items.findIndex((entry) => entry.id === invoiceId);
    if (index !== -1) state.square.items[index] = data;
    renderSquareInvoicesList();
    showToast(`Square status: ${data.square_status || "unknown"}.`, "info");
  } catch (error) {
    showToast(`Square refresh failed: ${error.message}`, "error");
  }
}

function initializeSquareDashboard() {
  $("square-refresh-all").addEventListener("click", () => {
    void loadSquareDashboard();
  });
}

function initializeReports() {
  $("reports-refresh").addEventListener("click", () => {
    void loadReports();
  });
}

async function loadVehicleOptionsInto(selectId, placeholder) {
  const select = $(selectId);
  if (!select) return;
  const currentValue = select.value;
  try {
    const response = await apiFetch("/api/vehicles?page=1&page_size=100&archived=false");
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Vehicle options failed");
    select.innerHTML = [`<option value="">${escapeHtml(placeholder)}</option>`, ...data.items.map((vehicle) => (
      `<option value="${vehicle.id}">${escapeHtml(vehicle.display_name)}</option>`
    ))].join("");
    if (currentValue) select.value = currentValue;
  } catch {
    // Dropdown population is a convenience; a failure here shouldn't block the view.
  }
}

// ---- Service Desk (intake queue) ----

function renderServiceDeskList() {
  const container = $("service-desk-list");
  if (!state.serviceDesk.items.length) {
    container.innerHTML = '<div class="empty-card"><strong>No intake requests</strong><p>New customer contacts will appear here.</p></div>';
  } else {
    container.innerHTML = state.serviceDesk.items.map((item) => `
      <button type="button" class="customer-list-item${state.serviceDesk.selectedRequestId === item.id ? " is-active" : ""}" data-service-desk-id="${item.id}">
        <strong>${escapeHtml(item.customer_name)}</strong>
        <span>${escapeHtml(item.vehicle_description || "No vehicle noted")} · ${escapeHtml(item.status)}</span>
      </button>`).join("");
    $$("[data-service-desk-id]", container).forEach((button) => {
      button.addEventListener("click", () => {
        void selectServiceDeskRequest(Number(button.dataset.serviceDeskId));
      });
    });
  }
  $("service-desk-page-status").textContent = `Page ${state.serviceDesk.page} · ${state.serviceDesk.total} total`;
  $("service-desk-prev").disabled = state.serviceDesk.page <= 1;
  $("service-desk-next").disabled = !state.serviceDesk.hasMore;
}

async function loadServiceDesk() {
  if (!await requireAuthenticated("login")) return;
  const list = $("service-desk-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading intake requests</strong></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.serviceDesk.page),
    page_size: String(state.serviceDesk.pageSize),
  });
  if (state.serviceDesk.search.trim()) searchParams.set("search", state.serviceDesk.search.trim());
  if (state.serviceDesk.statusFilter) searchParams.set("status", state.serviceDesk.statusFilter);
  try {
    const response = await apiFetch(`/api/intake-requests?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Intake request listing failed");
    state.serviceDesk.items = data.items;
    state.serviceDesk.total = data.total;
    state.serviceDesk.hasMore = data.has_more;
    renderServiceDeskList();
  } catch (error) {
    list.innerHTML = `<div class="error-card"><strong>Intake request listing failed</strong><p>${escapeHtml(error.message)}</p></div>`;
    showToast(`Intake request listing failed: ${error.message}`, "error");
  }
}

function renderServiceDeskDetail(request = null) {
  const detail = $("service-desk-detail");
  const convertForm = $("service-desk-convert-form");
  if (!request) {
    detail.innerHTML = "<p>Select an intake request from the list or create a new one.</p>";
    convertForm.hidden = true;
    return;
  }
  detail.innerHTML = `
    <div class="customer-detail-header">
      <strong>${escapeHtml(request.customer_name)}</strong>
      <span>${escapeHtml(request.status)}</span>
    </div>
    <p>${escapeHtml(request.complaint)}</p>
    <div class="customer-detail-grid">
      <div><span>Phone</span><strong>${escapeHtml(request.phone || "Not set")}</strong></div>
      <div><span>Email</span><strong>${escapeHtml(request.email || "Not set")}</strong></div>
      <div><span>Vehicle</span><strong>${escapeHtml(request.vehicle_description || "Not noted")}</strong></div>
      <div><span>Source</span><strong>${escapeHtml(request.source)}</strong></div>
    </div>
    ${request.notes ? `<div class="customer-detail-notes"><span>Internal notes</span><p>${escapeHtml(request.notes)}</p></div>` : ""}
    ${request.converted_customer_id ? `<div class="customer-detail-notes"><span>Converted</span><p>Linked to customer #${request.converted_customer_id}${request.converted_vehicle_id ? ` and vehicle #${request.converted_vehicle_id}` : ""}.</p></div>` : ""}`;
  convertForm.hidden = request.status === "converted";
}

async function selectServiceDeskRequest(requestId) {
  try {
    const response = await apiFetch(`/api/intake-requests/${requestId}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Intake request load failed");
    state.serviceDesk.selectedRequestId = data.id;
    state.serviceDesk.selectedRequest = data;
    renderServiceDeskDetail(data);
    populateServiceDeskForm(data);
    renderServiceDeskList();
  } catch (error) {
    showToast(`Intake request load failed: ${error.message}`, "error");
  }
}

function populateServiceDeskForm(request = null) {
  $("service-desk-id").value = request ? String(request.id) : "";
  $("service-desk-customer-name").value = request ? request.customer_name : "";
  $("service-desk-phone").value = request ? request.phone || "" : "";
  $("service-desk-email").value = request ? request.email || "" : "";
  $("service-desk-vehicle-description").value = request ? request.vehicle_description || "" : "";
  $("service-desk-source").value = request ? request.source : "phone";
  $("service-desk-complaint").value = request ? request.complaint : "";
  $("service-desk-notes").value = request ? request.notes || "" : "";
  $("service-desk-form-title").textContent = request ? "Edit intake request" : "Create intake request";
  $("service-desk-form-mode").textContent = request ? "EDIT" : "CREATE";
}

async function submitServiceDeskForm(event) {
  event.preventDefault();
  if (!await requireAuthenticated("login")) return;
  const requestId = $("service-desk-id").value.trim();
  const submit = $("service-desk-save");
  submit.disabled = true;
  submit.textContent = requestId ? "Saving…" : "Creating…";
  const payload = {
    customer_name: $("service-desk-customer-name").value.trim(),
    phone: $("service-desk-phone").value.trim() || null,
    email: $("service-desk-email").value.trim() || null,
    vehicle_description: $("service-desk-vehicle-description").value.trim() || null,
    source: $("service-desk-source").value,
    complaint: $("service-desk-complaint").value.trim(),
    notes: $("service-desk-notes").value.trim() || null,
  };
  try {
    const response = await apiFetch(requestId ? `/api/intake-requests/${requestId}` : "/api/intake-requests", {
      method: requestId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Intake request save failed");
    state.serviceDesk.selectedRequestId = data.id;
    state.serviceDesk.selectedRequest = data;
    populateServiceDeskForm(data);
    renderServiceDeskDetail(data);
    state.serviceDesk.page = 1;
    await loadServiceDesk();
    showToast(requestId ? "Intake request updated." : "Intake request created.", "success");
  } catch (error) {
    showToast(`Intake request save failed: ${error.message}`, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Save request";
  }
}

async function submitServiceDeskConvert(event) {
  event.preventDefault();
  const request = state.serviceDesk.selectedRequest;
  if (!request) return;
  const submit = $("service-desk-convert-save");
  submit.disabled = true;
  try {
    const payload = {
      vehicle_year: $("service-desk-convert-vehicle-year").value ? Number($("service-desk-convert-vehicle-year").value) : null,
      vehicle_make: $("service-desk-convert-vehicle-make").value.trim() || null,
      vehicle_model: $("service-desk-convert-vehicle-model").value.trim() || null,
    };
    const response = await apiFetch(`/api/intake-requests/${request.id}/convert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Conversion failed");
    state.serviceDesk.selectedRequest = data.intake_request;
    renderServiceDeskDetail(data.intake_request);
    await loadServiceDesk();
    showToast(`Converted to customer ${data.customer.display_name}.`, "success");
  } catch (error) {
    showToast(`Conversion failed: ${error.message}`, "error");
  } finally {
    submit.disabled = false;
  }
}

function initializeServiceDesk() {
  $("service-desk-new").addEventListener("click", () => {
    state.serviceDesk.selectedRequestId = null;
    state.serviceDesk.selectedRequest = null;
    populateServiceDeskForm(null);
    renderServiceDeskDetail(null);
    renderServiceDeskList();
  });
  $("service-desk-cancel").addEventListener("click", () => {
    populateServiceDeskForm(state.serviceDesk.selectedRequest);
  });
  $("service-desk-form").addEventListener("submit", submitServiceDeskForm);
  $("service-desk-convert-form").addEventListener("submit", submitServiceDeskConvert);
  $("service-desk-refresh").addEventListener("click", () => void loadServiceDesk());
  $("service-desk-search").addEventListener("input", () => {
    state.serviceDesk.search = $("service-desk-search").value;
    state.serviceDesk.page = 1;
    void loadServiceDesk();
  });
  $("service-desk-status-filter").addEventListener("change", () => {
    state.serviceDesk.statusFilter = $("service-desk-status-filter").value;
    state.serviceDesk.page = 1;
    void loadServiceDesk();
  });
  $("service-desk-prev").addEventListener("click", () => {
    if (state.serviceDesk.page > 1) {
      state.serviceDesk.page -= 1;
      void loadServiceDesk();
    }
  });
  $("service-desk-next").addEventListener("click", () => {
    if (state.serviceDesk.hasMore) {
      state.serviceDesk.page += 1;
      void loadServiceDesk();
    }
  });
}

// ---- Diagnostics ----

function renderDiagnosticsList() {
  const container = $("diagnostics-list");
  if (!state.diagnostics.items.length) {
    container.innerHTML = '<div class="empty-card"><strong>No findings</strong><p>Create a diagnostic finding for a vehicle.</p></div>';
  } else {
    container.innerHTML = state.diagnostics.items.map((item) => `
      <button type="button" class="customer-list-item${state.diagnostics.selectedFindingId === item.id ? " is-active" : ""}" data-diagnostics-id="${item.id}">
        <strong>${escapeHtml(item.vehicle_display_name || "Vehicle")}</strong>
        <span>${escapeHtml(item.symptoms.slice(0, 80))}</span>
      </button>`).join("");
    $$("[data-diagnostics-id]", container).forEach((button) => {
      button.addEventListener("click", () => {
        void selectDiagnosticFinding(Number(button.dataset.diagnosticsId));
      });
    });
  }
  $("diagnostics-page-status").textContent = `Page ${state.diagnostics.page} · ${state.diagnostics.total} total`;
  $("diagnostics-prev").disabled = state.diagnostics.page <= 1;
  $("diagnostics-next").disabled = !state.diagnostics.hasMore;
}

async function loadDiagnostics() {
  if (!await requireAuthenticated("login")) return;
  void loadVehicleOptionsInto("diagnostics-vehicle-filter", "All vehicles");
  void loadVehicleOptionsInto("diagnostics-vehicle-id", "Select a vehicle");
  const list = $("diagnostics-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading findings</strong></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.diagnostics.page),
    page_size: String(state.diagnostics.pageSize),
  });
  if (state.diagnostics.vehicleFilterId) searchParams.set("vehicle_id", String(state.diagnostics.vehicleFilterId));
  try {
    const response = await apiFetch(`/api/diagnostic-findings?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Diagnostic finding listing failed");
    state.diagnostics.items = data.items;
    state.diagnostics.total = data.total;
    state.diagnostics.hasMore = data.has_more;
    renderDiagnosticsList();
  } catch (error) {
    list.innerHTML = `<div class="error-card"><strong>Diagnostic finding listing failed</strong><p>${escapeHtml(error.message)}</p></div>`;
    showToast(`Diagnostic finding listing failed: ${error.message}`, "error");
  }
}

function renderDiagnosticsDetail(finding = null) {
  const detail = $("diagnostics-detail");
  $("diagnostics-delete").hidden = !finding;
  if (!finding) {
    detail.innerHTML = "<p>Select a finding from the list or create a new one.</p>";
    return;
  }
  detail.innerHTML = `
    <div class="customer-detail-header">
      <strong>${escapeHtml(finding.vehicle_display_name || "Vehicle")}</strong>
      <span>${new Date(finding.updated_at).toLocaleString()}</span>
    </div>
    <div class="customer-detail-grid">
      <div><span>Codes</span><strong>${escapeHtml(finding.codes || "None recorded")}</strong></div>
      <div><span>Technician</span><strong>${escapeHtml(finding.technician_display_name || "Unassigned")}</strong></div>
      <div><span>Work order</span><strong>${finding.work_order_id ? `#${finding.work_order_id}` : "None"}</strong></div>
    </div>
    <div class="customer-detail-notes"><span>Symptoms</span><p>${escapeHtml(finding.symptoms)}</p></div>
    ${finding.tests_performed ? `<div class="customer-detail-notes"><span>Tests performed</span><p>${escapeHtml(finding.tests_performed)}</p></div>` : ""}
    ${finding.conclusion ? `<div class="customer-detail-notes"><span>Conclusion</span><p>${escapeHtml(finding.conclusion)}</p></div>` : ""}`;
}

async function selectDiagnosticFinding(findingId) {
  try {
    const response = await apiFetch(`/api/diagnostic-findings/${findingId}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Finding load failed");
    state.diagnostics.selectedFindingId = data.id;
    state.diagnostics.selectedFinding = data;
    renderDiagnosticsDetail(data);
    populateDiagnosticsForm(data);
    renderDiagnosticsList();
  } catch (error) {
    showToast(`Finding load failed: ${error.message}`, "error");
  }
}

function populateDiagnosticsForm(finding = null) {
  $("diagnostics-id").value = finding ? String(finding.id) : "";
  $("diagnostics-vehicle-id").value = finding ? String(finding.vehicle_id) : "";
  $("diagnostics-work-order-id").value = finding && finding.work_order_id ? String(finding.work_order_id) : "";
  $("diagnostics-codes").value = finding ? finding.codes || "" : "";
  $("diagnostics-symptoms").value = finding ? finding.symptoms : "";
  $("diagnostics-tests-performed").value = finding ? finding.tests_performed || "" : "";
  $("diagnostics-conclusion").value = finding ? finding.conclusion || "" : "";
  $("diagnostics-form-title").textContent = finding ? "Edit finding" : "Create finding";
  $("diagnostics-form-mode").textContent = finding ? "EDIT" : "CREATE";
}

async function submitDiagnosticsForm(event) {
  event.preventDefault();
  if (!await requireAuthenticated("login")) return;
  const vehicleId = $("diagnostics-vehicle-id").value;
  if (!vehicleId) {
    showToast("Select a vehicle first.", "error");
    return;
  }
  const findingId = $("diagnostics-id").value.trim();
  const submit = $("diagnostics-save");
  submit.disabled = true;
  submit.textContent = findingId ? "Saving…" : "Creating…";
  const workOrderId = $("diagnostics-work-order-id").value.trim();
  const payload = {
    vehicle_id: Number(vehicleId),
    work_order_id: workOrderId ? Number(workOrderId) : null,
    codes: $("diagnostics-codes").value.trim() || null,
    symptoms: $("diagnostics-symptoms").value.trim(),
    tests_performed: $("diagnostics-tests-performed").value.trim() || null,
    conclusion: $("diagnostics-conclusion").value.trim() || null,
  };
  if (findingId) delete payload.vehicle_id;
  try {
    const response = await apiFetch(findingId ? `/api/diagnostic-findings/${findingId}` : "/api/diagnostic-findings", {
      method: findingId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Finding save failed");
    state.diagnostics.selectedFindingId = data.id;
    state.diagnostics.selectedFinding = data;
    populateDiagnosticsForm(data);
    renderDiagnosticsDetail(data);
    state.diagnostics.page = 1;
    await loadDiagnostics();
    showToast(findingId ? "Finding updated." : "Finding created.", "success");
  } catch (error) {
    showToast(`Finding save failed: ${error.message}`, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Save finding";
  }
}

async function deleteSelectedDiagnosticFinding() {
  const finding = state.diagnostics.selectedFinding;
  if (!finding) return;
  if (!window.confirm("Delete this diagnostic finding?")) return;
  try {
    const response = await apiFetch(`/api/diagnostic-findings/${finding.id}`, { method: "DELETE" });
    if (!response.ok) throw apiError(response, await readApiPayload(response), "Finding delete failed");
    state.diagnostics.selectedFindingId = null;
    state.diagnostics.selectedFinding = null;
    populateDiagnosticsForm(null);
    renderDiagnosticsDetail(null);
    await loadDiagnostics();
    showToast("Finding deleted.", "success");
  } catch (error) {
    showToast(`Finding delete failed: ${error.message}`, "error");
  }
}

function initializeDiagnostics() {
  $("diagnostics-new").addEventListener("click", () => {
    state.diagnostics.selectedFindingId = null;
    state.diagnostics.selectedFinding = null;
    populateDiagnosticsForm(null);
    renderDiagnosticsDetail(null);
    renderDiagnosticsList();
  });
  $("diagnostics-cancel").addEventListener("click", () => {
    populateDiagnosticsForm(state.diagnostics.selectedFinding);
  });
  $("diagnostics-form").addEventListener("submit", submitDiagnosticsForm);
  $("diagnostics-delete").addEventListener("click", () => void deleteSelectedDiagnosticFinding());
  $("diagnostics-refresh").addEventListener("click", () => void loadDiagnostics());
  $("diagnostics-vehicle-filter").addEventListener("change", () => {
    const value = $("diagnostics-vehicle-filter").value;
    state.diagnostics.vehicleFilterId = value ? Number(value) : null;
    state.diagnostics.page = 1;
    void loadDiagnostics();
  });
  $("diagnostics-prev").addEventListener("click", () => {
    if (state.diagnostics.page > 1) {
      state.diagnostics.page -= 1;
      void loadDiagnostics();
    }
  });
  $("diagnostics-next").addEventListener("click", () => {
    if (state.diagnostics.hasMore) {
      state.diagnostics.page += 1;
      void loadDiagnostics();
    }
  });
}

// ---- Inspections ----

function renderInspectionsList() {
  const container = $("inspections-list");
  if (!state.inspections.items.length) {
    container.innerHTML = '<div class="empty-card"><strong>No inspections</strong><p>Create an inspection for a vehicle.</p></div>';
  } else {
    container.innerHTML = state.inspections.items.map((item) => `
      <button type="button" class="customer-list-item${state.inspections.selectedInspectionId === item.id ? " is-active" : ""}" data-inspections-id="${item.id}">
        <strong>${escapeHtml(item.vehicle_display_name || "Vehicle")}</strong>
        <span>${escapeHtml(item.inspection_type || "Inspection")}${item.has_failed_items ? " · Failed items" : item.has_attention_items ? " · Needs attention" : ""}</span>
      </button>`).join("");
    $$("[data-inspections-id]", container).forEach((button) => {
      button.addEventListener("click", () => {
        void selectInspection(Number(button.dataset.inspectionsId));
      });
    });
  }
  $("inspections-page-status").textContent = `Page ${state.inspections.page} · ${state.inspections.total} total`;
  $("inspections-prev").disabled = state.inspections.page <= 1;
  $("inspections-next").disabled = !state.inspections.hasMore;
}

async function loadInspections() {
  if (!await requireAuthenticated("login")) return;
  void loadVehicleOptionsInto("inspections-vehicle-filter", "All vehicles");
  void loadVehicleOptionsInto("inspections-vehicle-id", "Select a vehicle");
  const list = $("inspections-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading inspections</strong></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.inspections.page),
    page_size: String(state.inspections.pageSize),
  });
  if (state.inspections.vehicleFilterId) searchParams.set("vehicle_id", String(state.inspections.vehicleFilterId));
  try {
    const response = await apiFetch(`/api/inspections?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Inspection listing failed");
    state.inspections.items = data.items;
    state.inspections.total = data.total;
    state.inspections.hasMore = data.has_more;
    renderInspectionsList();
  } catch (error) {
    list.innerHTML = `<div class="error-card"><strong>Inspection listing failed</strong><p>${escapeHtml(error.message)}</p></div>`;
    showToast(`Inspection listing failed: ${error.message}`, "error");
  }
}

function renderInspectionsDetail(inspection = null) {
  const detail = $("inspections-detail");
  $("inspections-delete").hidden = !inspection;
  if (!inspection) {
    detail.innerHTML = "<p>Select an inspection from the list or create a new one.</p>";
    return;
  }
  const itemRows = inspection.items.map((item) => `
    <li><strong>${escapeHtml(item.label)}</strong> · ${escapeHtml(item.status)}${item.note ? ` · ${escapeHtml(item.note)}` : ""}</li>
  `).join("") || "<li>No checklist items recorded.</li>";
  detail.innerHTML = `
    <div class="customer-detail-header">
      <strong>${escapeHtml(inspection.vehicle_display_name || "Vehicle")}</strong>
      <span>${escapeHtml(inspection.inspection_type || "Inspection")}</span>
    </div>
    <div class="customer-detail-grid">
      <div><span>Technician</span><strong>${escapeHtml(inspection.technician_display_name || "Unassigned")}</strong></div>
      <div><span>Work order</span><strong>${inspection.work_order_id ? `#${inspection.work_order_id}` : "None"}</strong></div>
    </div>
    <div class="customer-history-section"><h4>Checklist</h4><ul>${itemRows}</ul></div>
    ${inspection.overall_notes ? `<div class="customer-detail-notes"><span>Overall notes</span><p>${escapeHtml(inspection.overall_notes)}</p></div>` : ""}`;
}

function renderInspectionsDraftItems() {
  const container = $("inspections-items-list");
  if (!state.inspections.draftItems.length) {
    container.innerHTML = "<p>No items added yet.</p>";
    return;
  }
  container.innerHTML = state.inspections.draftItems.map((item, index) => `
    <div class="customer-detail-grid">
      <div><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.status)}${item.note ? ` · ${escapeHtml(item.note)}` : ""}</strong></div>
      <button type="button" class="text-button" data-remove-item-index="${index}">Remove</button>
    </div>`).join("");
  $$("[data-remove-item-index]", container).forEach((button) => {
    button.addEventListener("click", () => {
      state.inspections.draftItems.splice(Number(button.dataset.removeItemIndex), 1);
      renderInspectionsDraftItems();
    });
  });
}

async function selectInspection(inspectionId) {
  try {
    const response = await apiFetch(`/api/inspections/${inspectionId}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Inspection load failed");
    state.inspections.selectedInspectionId = data.id;
    state.inspections.selectedInspection = data;
    renderInspectionsDetail(data);
    populateInspectionsForm(data);
    renderInspectionsList();
  } catch (error) {
    showToast(`Inspection load failed: ${error.message}`, "error");
  }
}

function populateInspectionsForm(inspection = null) {
  $("inspections-id").value = inspection ? String(inspection.id) : "";
  $("inspections-vehicle-id").value = inspection ? String(inspection.vehicle_id) : "";
  $("inspections-work-order-id").value = inspection && inspection.work_order_id ? String(inspection.work_order_id) : "";
  $("inspections-type").value = inspection ? inspection.inspection_type || "" : "";
  $("inspections-overall-notes").value = inspection ? inspection.overall_notes || "" : "";
  state.inspections.draftItems = inspection ? inspection.items.map((item) => ({ ...item })) : [];
  renderInspectionsDraftItems();
  $("inspections-form-title").textContent = inspection ? "Edit inspection" : "Create inspection";
  $("inspections-form-mode").textContent = inspection ? "EDIT" : "CREATE";
}

function addInspectionDraftItem() {
  const label = $("inspections-item-label").value.trim();
  if (!label) {
    showToast("Enter an item label first.", "error");
    return;
  }
  state.inspections.draftItems.push({
    label,
    status: $("inspections-item-status").value,
    note: $("inspections-item-note").value.trim() || null,
  });
  $("inspections-item-label").value = "";
  $("inspections-item-note").value = "";
  renderInspectionsDraftItems();
}

async function submitInspectionsForm(event) {
  event.preventDefault();
  if (!await requireAuthenticated("login")) return;
  const vehicleId = $("inspections-vehicle-id").value;
  if (!vehicleId) {
    showToast("Select a vehicle first.", "error");
    return;
  }
  const inspectionId = $("inspections-id").value.trim();
  const submit = $("inspections-save");
  submit.disabled = true;
  submit.textContent = inspectionId ? "Saving…" : "Creating…";
  const workOrderId = $("inspections-work-order-id").value.trim();
  const payload = {
    vehicle_id: Number(vehicleId),
    work_order_id: workOrderId ? Number(workOrderId) : null,
    inspection_type: $("inspections-type").value.trim() || null,
    items: state.inspections.draftItems,
    overall_notes: $("inspections-overall-notes").value.trim() || null,
  };
  if (inspectionId) delete payload.vehicle_id;
  try {
    const response = await apiFetch(inspectionId ? `/api/inspections/${inspectionId}` : "/api/inspections", {
      method: inspectionId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Inspection save failed");
    state.inspections.selectedInspectionId = data.id;
    state.inspections.selectedInspection = data;
    populateInspectionsForm(data);
    renderInspectionsDetail(data);
    state.inspections.page = 1;
    await loadInspections();
    showToast(inspectionId ? "Inspection updated." : "Inspection created.", "success");
  } catch (error) {
    showToast(`Inspection save failed: ${error.message}`, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Save inspection";
  }
}

async function deleteSelectedInspection() {
  const inspection = state.inspections.selectedInspection;
  if (!inspection) return;
  if (!window.confirm("Delete this inspection?")) return;
  try {
    const response = await apiFetch(`/api/inspections/${inspection.id}`, { method: "DELETE" });
    if (!response.ok) throw apiError(response, await readApiPayload(response), "Inspection delete failed");
    state.inspections.selectedInspectionId = null;
    state.inspections.selectedInspection = null;
    populateInspectionsForm(null);
    renderInspectionsDetail(null);
    await loadInspections();
    showToast("Inspection deleted.", "success");
  } catch (error) {
    showToast(`Inspection delete failed: ${error.message}`, "error");
  }
}

function initializeInspections() {
  $("inspections-new").addEventListener("click", () => {
    state.inspections.selectedInspectionId = null;
    state.inspections.selectedInspection = null;
    populateInspectionsForm(null);
    renderInspectionsDetail(null);
    renderInspectionsList();
  });
  $("inspections-cancel").addEventListener("click", () => {
    populateInspectionsForm(state.inspections.selectedInspection);
  });
  $("inspections-form").addEventListener("submit", submitInspectionsForm);
  $("inspections-item-add").addEventListener("click", addInspectionDraftItem);
  $("inspections-delete").addEventListener("click", () => void deleteSelectedInspection());
  $("inspections-refresh").addEventListener("click", () => void loadInspections());
  $("inspections-vehicle-filter").addEventListener("change", () => {
    const value = $("inspections-vehicle-filter").value;
    state.inspections.vehicleFilterId = value ? Number(value) : null;
    state.inspections.page = 1;
    void loadInspections();
  });
  $("inspections-prev").addEventListener("click", () => {
    if (state.inspections.page > 1) {
      state.inspections.page -= 1;
      void loadInspections();
    }
  });
  $("inspections-next").addEventListener("click", () => {
    if (state.inspections.hasMore) {
      state.inspections.page += 1;
      void loadInspections();
    }
  });
}

// ---- Vendors ----

function renderVendorsList() {
  const container = $("vendors-list");
  if (!state.vendors.items.length) {
    container.innerHTML = '<div class="empty-card"><strong>No vendors</strong><p>Create the first vendor record.</p></div>';
  } else {
    container.innerHTML = state.vendors.items.map((item) => `
      <button type="button" class="customer-list-item${state.vendors.selectedVendorId === item.id ? " is-active" : ""}" data-vendor-id="${item.id}">
        <strong>${escapeHtml(item.name)}</strong>
        <span>${escapeHtml(item.contact_name || "No contact set")} · ${item.part_count} part${item.part_count === 1 ? "" : "s"}</span>
      </button>`).join("");
    $$("[data-vendor-id]", container).forEach((button) => {
      button.addEventListener("click", () => {
        void selectVendor(Number(button.dataset.vendorId));
      });
    });
  }
  $("vendors-page-status").textContent = `Page ${state.vendors.page} · ${state.vendors.total} total`;
  $("vendors-prev").disabled = state.vendors.page <= 1;
  $("vendors-next").disabled = !state.vendors.hasMore;
}

async function loadVendors() {
  if (!await requireAuthenticated("login")) return;
  const list = $("vendors-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading vendors</strong></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.vendors.page),
    page_size: String(state.vendors.pageSize),
    archived: String(state.vendors.archivedOnly),
  });
  if (state.vendors.search.trim()) searchParams.set("search", state.vendors.search.trim());
  try {
    const response = await apiFetch(`/api/vendors?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Vendor listing failed");
    state.vendors.items = data.items;
    state.vendors.total = data.total;
    state.vendors.hasMore = data.has_more;
    renderVendorsList();
  } catch (error) {
    list.innerHTML = `<div class="error-card"><strong>Vendor listing failed</strong><p>${escapeHtml(error.message)}</p></div>`;
    showToast(`Vendor listing failed: ${error.message}`, "error");
  }
}

function renderVendorsDetail(vendor = null) {
  const detail = $("vendors-detail");
  $("vendors-archive").hidden = !vendor;
  if (!vendor) {
    detail.innerHTML = "<p>Select a vendor from the list or create a new record.</p>";
    return;
  }
  const address = [vendor.address_line_1, vendor.address_line_2, [vendor.city, vendor.state, vendor.postal_code].filter(Boolean).join(", ")]
    .filter(Boolean).map((line) => escapeHtml(line)).join("<br>");
  detail.innerHTML = `
    <div class="customer-detail-header">
      <strong>${escapeHtml(vendor.name)}</strong>
      <span>${vendor.is_archived ? "Archived" : "Active"}</span>
    </div>
    <div class="customer-detail-grid">
      <div><span>Contact</span><strong>${escapeHtml(vendor.contact_name || "Not set")}</strong></div>
      <div><span>Phone</span><strong>${escapeHtml(vendor.phone || "Not set")}</strong></div>
      <div><span>Email</span><strong>${escapeHtml(vendor.email || "Not set")}</strong></div>
      <div><span>Active parts</span><strong>${vendor.part_count}</strong></div>
    </div>
    ${address ? `<div class="customer-detail-notes"><span>Address</span><p>${address}</p></div>` : ""}
    ${vendor.notes ? `<div class="customer-detail-notes"><span>Notes</span><p>${escapeHtml(vendor.notes)}</p></div>` : ""}`;
}

async function selectVendor(vendorId) {
  try {
    const response = await apiFetch(`/api/vendors/${vendorId}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Vendor load failed");
    state.vendors.selectedVendorId = data.id;
    state.vendors.selectedVendor = data;
    renderVendorsDetail(data);
    populateVendorsForm(data);
    renderVendorsList();
  } catch (error) {
    showToast(`Vendor load failed: ${error.message}`, "error");
  }
}

function populateVendorsForm(vendor = null) {
  $("vendors-id").value = vendor ? String(vendor.id) : "";
  $("vendors-name").value = vendor ? vendor.name : "";
  $("vendors-contact-name").value = vendor ? vendor.contact_name || "" : "";
  $("vendors-phone").value = vendor ? vendor.phone || "" : "";
  $("vendors-email").value = vendor ? vendor.email || "" : "";
  $("vendors-address-line-1").value = vendor ? vendor.address_line_1 || "" : "";
  $("vendors-address-line-2").value = vendor ? vendor.address_line_2 || "" : "";
  $("vendors-city").value = vendor ? vendor.city || "" : "";
  $("vendors-state").value = vendor ? vendor.state || "" : "";
  $("vendors-postal-code").value = vendor ? vendor.postal_code || "" : "";
  $("vendors-notes").value = vendor ? vendor.notes || "" : "";
  $("vendors-form-title").textContent = vendor ? "Edit vendor" : "Create vendor";
  $("vendors-form-mode").textContent = vendor ? "EDIT" : "CREATE";
}

async function submitVendorsForm(event) {
  event.preventDefault();
  if (!await requireAuthenticated("login")) return;
  const vendorId = $("vendors-id").value.trim();
  const submit = $("vendors-save");
  submit.disabled = true;
  submit.textContent = vendorId ? "Saving…" : "Creating…";
  const payload = {
    name: $("vendors-name").value.trim(),
    contact_name: $("vendors-contact-name").value.trim() || null,
    phone: $("vendors-phone").value.trim() || null,
    email: $("vendors-email").value.trim() || null,
    address_line_1: $("vendors-address-line-1").value.trim() || null,
    address_line_2: $("vendors-address-line-2").value.trim() || null,
    city: $("vendors-city").value.trim() || null,
    state: $("vendors-state").value.trim() || null,
    postal_code: $("vendors-postal-code").value.trim() || null,
    notes: $("vendors-notes").value.trim() || null,
  };
  try {
    const response = await apiFetch(vendorId ? `/api/vendors/${vendorId}` : "/api/vendors", {
      method: vendorId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Vendor save failed");
    state.vendors.selectedVendorId = data.id;
    state.vendors.selectedVendor = data;
    populateVendorsForm(data);
    renderVendorsDetail(data);
    state.vendors.page = 1;
    await loadVendors();
    showToast(vendorId ? "Vendor updated." : "Vendor created.", "success");
  } catch (error) {
    showToast(`Vendor save failed: ${error.message}`, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Save vendor";
  }
}

async function archiveSelectedVendor() {
  const vendor = state.vendors.selectedVendor;
  if (!vendor) return;
  if (!window.confirm(`Archive ${vendor.name}?`)) return;
  try {
    const response = await apiFetch(`/api/vendors/${vendor.id}`, { method: "DELETE" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Vendor archive failed");
    state.vendors.selectedVendorId = null;
    state.vendors.selectedVendor = null;
    populateVendorsForm(null);
    renderVendorsDetail(null);
    await loadVendors();
    showToast("Vendor archived.", "success");
  } catch (error) {
    showToast(`Vendor archive failed: ${error.message}`, "error");
  }
}

function initializeVendors() {
  $("vendors-new").addEventListener("click", () => {
    state.vendors.selectedVendorId = null;
    state.vendors.selectedVendor = null;
    populateVendorsForm(null);
    renderVendorsDetail(null);
    renderVendorsList();
  });
  $("vendors-cancel").addEventListener("click", () => {
    populateVendorsForm(state.vendors.selectedVendor);
  });
  $("vendors-form").addEventListener("submit", submitVendorsForm);
  $("vendors-archive").addEventListener("click", () => void archiveSelectedVendor());
  $("vendors-refresh").addEventListener("click", () => void loadVendors());
  $("vendors-search").addEventListener("input", () => {
    state.vendors.search = $("vendors-search").value;
    state.vendors.page = 1;
    void loadVendors();
  });
  $("vendors-archived-only").addEventListener("change", () => {
    state.vendors.archivedOnly = $("vendors-archived-only").checked;
    state.vendors.page = 1;
    void loadVendors();
  });
  $("vendors-prev").addEventListener("click", () => {
    if (state.vendors.page > 1) {
      state.vendors.page -= 1;
      void loadVendors();
    }
  });
  $("vendors-next").addEventListener("click", () => {
    if (state.vendors.hasMore) {
      state.vendors.page += 1;
      void loadVendors();
    }
  });
}

// ---- Parts ----

async function loadVendorOptionsInto(selectId) {
  const select = $(selectId);
  if (!select) return;
  const currentValue = select.value;
  try {
    const response = await apiFetch("/api/vendors?page=1&page_size=100&archived=false");
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Vendor options failed");
    select.innerHTML = ['<option value="">No vendor</option>', ...data.items.map((vendor) => (
      `<option value="${vendor.id}">${escapeHtml(vendor.name)}</option>`
    ))].join("");
    if (currentValue) select.value = currentValue;
  } catch {
    // Dropdown population is a convenience; a failure here shouldn't block the view.
  }
}

function renderPartsList() {
  const container = $("parts-list");
  if (!state.parts.items.length) {
    container.innerHTML = '<div class="empty-card"><strong>No parts</strong><p>Create the first part record.</p></div>';
  } else {
    container.innerHTML = state.parts.items.map((item) => `
      <button type="button" class="customer-list-item${state.parts.selectedPartId === item.id ? " is-active" : ""}" data-part-id="${item.id}">
        <strong>${escapeHtml(item.part_number)}${item.is_below_reorder_threshold ? " · Reorder" : ""}</strong>
        <span>${escapeHtml(item.description)} · Qty ${item.quantity_on_hand}</span>
      </button>`).join("");
    $$("[data-part-id]", container).forEach((button) => {
      button.addEventListener("click", () => {
        void selectPart(Number(button.dataset.partId));
      });
    });
  }
  $("parts-page-status").textContent = `Page ${state.parts.page} · ${state.parts.total} total`;
  $("parts-prev").disabled = state.parts.page <= 1;
  $("parts-next").disabled = !state.parts.hasMore;
}

async function loadParts() {
  if (!await requireAuthenticated("login")) return;
  void loadVendorOptionsInto("parts-vendor-id");
  const list = $("parts-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading parts</strong></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.parts.page),
    page_size: String(state.parts.pageSize),
    archived: String(state.parts.archivedOnly),
  });
  if (state.parts.search.trim()) searchParams.set("search", state.parts.search.trim());
  try {
    const response = await apiFetch(`/api/parts?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Part listing failed");
    state.parts.items = data.items;
    state.parts.total = data.total;
    state.parts.hasMore = data.has_more;
    renderPartsList();
  } catch (error) {
    list.innerHTML = `<div class="error-card"><strong>Part listing failed</strong><p>${escapeHtml(error.message)}</p></div>`;
    showToast(`Part listing failed: ${error.message}`, "error");
  }
}

function renderPartsDetail(part = null) {
  const detail = $("parts-detail");
  $("parts-archive").hidden = !part;
  if (!part) {
    detail.innerHTML = "<p>Select a part from the list or create a new record.</p>";
    return;
  }
  detail.innerHTML = `
    <div class="customer-detail-header">
      <strong>${escapeHtml(part.part_number)}</strong>
      <span>${part.is_archived ? "Archived" : "Active"}</span>
    </div>
    <p>${escapeHtml(part.description)}</p>
    <div class="customer-detail-grid">
      <div><span>Category</span><strong>${escapeHtml(part.category || "Not set")}</strong></div>
      <div><span>Vendor</span><strong>${escapeHtml(part.vendor_name || "None")}</strong></div>
      <div><span>Quantity on hand</span><strong>${part.quantity_on_hand}${part.is_below_reorder_threshold ? " (below reorder threshold)" : ""}</strong></div>
      <div><span>Reorder threshold</span><strong>${part.reorder_threshold ?? "Not set"}</strong></div>
      <div><span>Unit cost</span><strong>${part.unit_cost != null ? money(part.unit_cost) : "Not set"}</strong></div>
      <div><span>Unit price</span><strong>${part.unit_price != null ? money(part.unit_price) : "Not set"}</strong></div>
      <div><span>Location</span><strong>${escapeHtml(part.location || "Not set")}</strong></div>
    </div>
    ${part.notes ? `<div class="customer-detail-notes"><span>Notes</span><p>${escapeHtml(part.notes)}</p></div>` : ""}`;
}

async function selectPart(partId) {
  try {
    const response = await apiFetch(`/api/parts/${partId}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Part load failed");
    state.parts.selectedPartId = data.id;
    state.parts.selectedPart = data;
    renderPartsDetail(data);
    populatePartsForm(data);
    renderPartsList();
  } catch (error) {
    showToast(`Part load failed: ${error.message}`, "error");
  }
}

function populatePartsForm(part = null) {
  $("parts-id").value = part ? String(part.id) : "";
  $("parts-part-number").value = part ? part.part_number : "";
  $("parts-category").value = part ? part.category || "" : "";
  $("parts-vendor-id").value = part && part.vendor_id ? String(part.vendor_id) : "";
  $("parts-description").value = part ? part.description : "";
  $("parts-quantity").value = part ? String(part.quantity_on_hand) : "0";
  $("parts-reorder-threshold").value = part && part.reorder_threshold != null ? String(part.reorder_threshold) : "";
  $("parts-unit-cost").value = part && part.unit_cost != null ? String(part.unit_cost) : "";
  $("parts-unit-price").value = part && part.unit_price != null ? String(part.unit_price) : "";
  $("parts-location").value = part ? part.location || "" : "";
  $("parts-notes").value = part ? part.notes || "" : "";
  $("parts-form-title").textContent = part ? "Edit part" : "Create part";
  $("parts-form-mode").textContent = part ? "EDIT" : "CREATE";
}

async function submitPartsForm(event) {
  event.preventDefault();
  if (!await requireAuthenticated("login")) return;
  const partId = $("parts-id").value.trim();
  const submit = $("parts-save");
  submit.disabled = true;
  submit.textContent = partId ? "Saving…" : "Creating…";
  const vendorId = $("parts-vendor-id").value;
  const reorderThreshold = $("parts-reorder-threshold").value;
  const unitCost = $("parts-unit-cost").value;
  const unitPrice = $("parts-unit-price").value;
  const payload = {
    part_number: $("parts-part-number").value.trim(),
    description: $("parts-description").value.trim(),
    category: $("parts-category").value.trim() || null,
    quantity_on_hand: Number($("parts-quantity").value || 0),
    reorder_threshold: reorderThreshold ? Number(reorderThreshold) : null,
    unit_cost: unitCost ? Number(unitCost) : null,
    unit_price: unitPrice ? Number(unitPrice) : null,
    location: $("parts-location").value.trim() || null,
    notes: $("parts-notes").value.trim() || null,
    vendor_id: vendorId ? Number(vendorId) : null,
  };
  try {
    const response = await apiFetch(partId ? `/api/parts/${partId}` : "/api/parts", {
      method: partId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Part save failed");
    state.parts.selectedPartId = data.id;
    state.parts.selectedPart = data;
    populatePartsForm(data);
    renderPartsDetail(data);
    state.parts.page = 1;
    await loadParts();
    showToast(partId ? "Part updated." : "Part created.", "success");
  } catch (error) {
    showToast(`Part save failed: ${error.message}`, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Save part";
  }
}

async function archiveSelectedPart() {
  const part = state.parts.selectedPart;
  if (!part) return;
  if (!window.confirm(`Archive ${part.part_number}?`)) return;
  try {
    const response = await apiFetch(`/api/parts/${part.id}`, { method: "DELETE" });
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Part archive failed");
    state.parts.selectedPartId = null;
    state.parts.selectedPart = null;
    populatePartsForm(null);
    renderPartsDetail(null);
    await loadParts();
    showToast("Part archived.", "success");
  } catch (error) {
    showToast(`Part archive failed: ${error.message}`, "error");
  }
}

function initializeParts() {
  $("parts-new").addEventListener("click", () => {
    state.parts.selectedPartId = null;
    state.parts.selectedPart = null;
    populatePartsForm(null);
    renderPartsDetail(null);
    renderPartsList();
  });
  $("parts-cancel").addEventListener("click", () => {
    populatePartsForm(state.parts.selectedPart);
  });
  $("parts-form").addEventListener("submit", submitPartsForm);
  $("parts-archive").addEventListener("click", () => void archiveSelectedPart());
  $("parts-refresh").addEventListener("click", () => void loadParts());
  $("parts-search").addEventListener("input", () => {
    state.parts.search = $("parts-search").value;
    state.parts.page = 1;
    void loadParts();
  });
  $("parts-archived-only").addEventListener("change", () => {
    state.parts.archivedOnly = $("parts-archived-only").checked;
    state.parts.page = 1;
    void loadParts();
  });
  $("parts-prev").addEventListener("click", () => {
    if (state.parts.page > 1) {
      state.parts.page -= 1;
      void loadParts();
    }
  });
  $("parts-next").addEventListener("click", () => {
    if (state.parts.hasMore) {
      state.parts.page += 1;
      void loadParts();
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

// --- Overview dashboard --------------------------------------------------

const DASHBOARD_METRIC_FORMAT = {
  revenue: "currency",
  labor_revenue: "currency",
  parts_revenue: "currency",
  average_repair_order: "currency",
  open_work_orders: "integer",
  awaiting_customer_approval: "integer",
  gross_profit: "currency",
  net_profit: "currency",
};

const DASHBOARD_SPARKLINE_SERIES = {
  revenue: "revenue",
  labor_revenue: "labor",
  parts_revenue: "parts",
};

function dashboardDateRangeFromPreset(days) {
  const to = new Date();
  const from = new Date(to.getTime() - days * 24 * 60 * 60 * 1000);
  return { from, to };
}

function toDateInputValue(date) {
  return date.toISOString().slice(0, 10);
}

async function loadDashboardSummary() {
  if (!(await requireAuthenticated("login"))) return;
  const preset = state.dashboard.rangePreset;
  let dateFrom;
  let dateTo;
  if (preset === "custom") {
    const fromValue = $("dashboard-date-from").value;
    const toValue = $("dashboard-date-to").value;
    if (!fromValue || !toValue) return;
    dateFrom = new Date(`${fromValue}T00:00:00Z`);
    dateTo = new Date(`${toValue}T23:59:59Z`);
  } else {
    const range = dashboardDateRangeFromPreset(Number(preset));
    dateFrom = range.from;
    dateTo = range.to;
    $("dashboard-date-from").value = toDateInputValue(dateFrom);
    $("dashboard-date-to").value = toDateInputValue(dateTo);
  }
  state.dashboard.dateFrom = dateFrom;
  state.dashboard.dateTo = dateTo;
  try {
    const searchParams = new URLSearchParams({
      date_from: dateFrom.toISOString(),
      date_to: dateTo.toISOString(),
    });
    const response = await apiFetch(`/api/dashboard/summary?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Dashboard summary failed");
    state.dashboard.summary = data;
    renderDashboardMetrics(data);
    renderDashboardGauges(data);
    renderDashboardCharts(data);
    renderRevenueBreakdown(data);
    renderDashboardInsights(data);
    renderCurrentOperations(data);
    renderFinancialObligations(data);
  } catch (error) {
    showToast(`Dashboard summary failed: ${error.message}`, "error");
  }
}

async function loadReports() {
  if (!(await requireAuthenticated("login"))) return;
  const revenueTable = $("reports-revenue-table");
  const workOrderTable = $("reports-work-order-table");
  const invoiceStatusTable = $("reports-invoice-status-table");
  const balancesTable = $("reports-balances-table");
  [revenueTable, workOrderTable, invoiceStatusTable, balancesTable].forEach((el) => {
    el.innerHTML = "<tr><td colspan=\"2\">Loading…</td></tr>";
  });
  const range = dashboardDateRangeFromPreset(30);
  $("reports-period-note").textContent = `${range.from.toLocaleDateString()} – ${range.to.toLocaleDateString()} (last 30 days, same window as the Overview dashboard default)`;
  try {
    const searchParams = new URLSearchParams({
      date_from: range.from.toISOString(),
      date_to: range.to.toISOString(),
    });
    const [summaryResponse, invoicesResponse] = await Promise.all([
      apiFetch(`/api/dashboard/summary?${searchParams.toString()}`),
      apiFetch("/api/invoices?page_size=100"),
    ]);
    const summary = await readApiPayload(summaryResponse);
    const invoicesData = await readApiPayload(invoicesResponse);
    if (!summaryResponse.ok || !summary) throw apiError(summaryResponse, summary, "Dashboard summary failed");
    if (!invoicesResponse.ok || !invoicesData) throw apiError(invoicesResponse, invoicesData, "Invoice listing failed");

    const metricsByKey = new Map(summary.metrics.map((metric) => [metric.key, metric]));
    const revenueRows = [
      ["revenue", "Revenue"],
      ["labor_revenue", "Labor revenue"],
      ["parts_revenue", "Parts revenue"],
      ["average_repair_order", "Average repair order"],
    ].map(([key, label]) => {
      const metric = metricsByKey.get(key);
      const value = metric && metric.available ? money(metric.value) : "Not available";
      return `<tr><td>${escapeHtml(label)}</td><td>${value}</td></tr>`;
    });
    revenueTable.innerHTML = revenueRows.join("");

    const ops = summary.current_operations;
    workOrderTable.innerHTML = [
      ["Open", ops.open_work_orders],
      ["In progress", ops.in_progress],
      ["Waiting on parts", ops.waiting_on_parts],
      ["Awaiting customer approval", ops.awaiting_customer_approval],
      ["Completed, not yet invoiced", ops.completed_not_invoiced],
    ].map(([label, count]) => `<tr><td>${escapeHtml(label)}</td><td>${count}</td></tr>`).join("");

    const statusCounts = new Map();
    invoicesData.items.forEach((invoice) => {
      statusCounts.set(invoice.status, (statusCounts.get(invoice.status) || 0) + 1);
    });
    invoiceStatusTable.innerHTML = statusCounts.size
      ? [...statusCounts.entries()].map(([status, count]) => `<tr><td>${escapeHtml(invoiceStatusLabel(status))}</td><td>${count}</td></tr>`).join("")
        + (invoicesData.total > invoicesData.items.length ? `<tr><td colspan="2" class="report-card-note">Showing ${invoicesData.items.length} of ${invoicesData.total} invoices.</td></tr>` : "")
      : "<tr><td colspan=\"2\">No invoices recorded yet.</td></tr>";

    const obligations = summary.financial_obligations;
    balancesTable.innerHTML = [
      ["Outstanding balance", money(obligations.outstanding_balance)],
      ["Overdue balance", money(obligations.overdue_balance)],
      ["Overdue invoice count", String(obligations.overdue_invoice_count)],
      ["Deposits received", money(obligations.deposits_received_total)],
    ].map(([label, value]) => `<tr><td>${escapeHtml(label)}</td><td>${value}</td></tr>`).join("");
  } catch (error) {
    [revenueTable, workOrderTable, invoiceStatusTable, balancesTable].forEach((el) => {
      el.innerHTML = `<tr><td colspan="2">Failed to load: ${escapeHtml(error.message)}</td></tr>`;
    });
    showToast(`Reports load failed: ${error.message}`, "error");
  }
}

function renderDashboardMetrics(summary) {
  const metricsByKey = new Map(summary.metrics.map((metric) => [metric.key, metric]));
  $$("#dashboard-metrics [data-metric]").forEach((card) => {
    const key = card.dataset.metric;
    const metric = metricsByKey.get(key);
    if (!metric) return;
    const valueEl = card.querySelector('[data-role="value"]');
    const deltaEl = card.querySelector('[data-role="delta"]');
    const unavailableEl = card.querySelector('[data-role="unavailable"]');
    if (!metric.available) {
      if (valueEl) valueEl.textContent = "—";
      if (deltaEl) deltaEl.textContent = "";
      if (unavailableEl) {
        unavailableEl.hidden = false;
        unavailableEl.textContent = metric.unavailable_reason || "Not available yet.";
      }
      return;
    }
    if (unavailableEl) unavailableEl.hidden = true;
    const format = DASHBOARD_METRIC_FORMAT[key];
    if (valueEl) {
      valueEl.textContent = format === "currency" ? money(metric.value) : String(Math.round(metric.value));
    }
    if (deltaEl) {
      if (metric.change_percent == null) {
        deltaEl.textContent = "";
        deltaEl.classList.remove("is-up", "is-down");
      } else {
        const change = metric.change_percent;
        deltaEl.textContent = `${change > 0 ? "+" : ""}${change}% vs prior period`;
        deltaEl.classList.toggle("is-up", change > 0);
        deltaEl.classList.toggle("is-down", change < 0);
      }
    }
    const sparklineCanvas = card.querySelector('[data-role="sparkline"]');
    const seriesKey = DASHBOARD_SPARKLINE_SERIES[key];
    if (sparklineCanvas && seriesKey) {
      renderMetricSparkline(sparklineCanvas, key, summary.revenue_trend, seriesKey);
    }
  });
}

function renderMetricSparkline(canvas, chartKey, trend, seriesKey) {
  const existing = state.dashboard.sparklineCharts[chartKey];
  if (existing) existing.destroy();
  if (!trend.length || typeof Chart === "undefined") return;
  state.dashboard.sparklineCharts[chartKey] = new Chart(canvas, {
    type: "line",
    data: {
      labels: trend.map((point) => point.period_label),
      datasets: [{
        data: trend.map((point) => point.values[seriesKey] || 0),
        borderColor: "#ad4634",
        backgroundColor: "rgba(173,70,52,.12)",
        fill: true,
        tension: 0.35,
        pointRadius: 0,
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: { x: { display: false }, y: { display: false } },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
    },
  });
}

function renderGauge(key, metric) {
  const card = document.querySelector(`.gauge-card[data-gauge="${key}"]`);
  if (!card) return;
  const ring = card.querySelector('[data-role="ring"]');
  const label = card.querySelector('[data-role="ring-label"]');
  const unavailableEl = card.querySelector('[data-role="unavailable"]');
  if (!metric.available) {
    if (unavailableEl) {
      unavailableEl.hidden = false;
      unavailableEl.textContent = metric.unavailable_reason || "Not available yet.";
    }
    if (label) label.textContent = "—";
    if (ring) ring.setAttribute("stroke-dashoffset", "100");
    return;
  }
  if (unavailableEl) unavailableEl.hidden = true;
  const percent = Math.max(0, Math.min(100, metric.value));
  if (ring) ring.setAttribute("stroke-dashoffset", String(100 - percent));
  if (label) label.textContent = `${Math.round(percent)}%`;
}

function renderDashboardGauges(summary) {
  renderGauge("gross_profit_margin", summary.gross_profit_margin);
  renderGauge("approval_conversion_rate", summary.approval_conversion_rate);
  renderGauge("accounts_receivable_health", summary.accounts_receivable_health);
}

function renderRevenueTrendChart(trend) {
  const canvas = $("chart-revenue-trend");
  const emptyState = $("chart-revenue-trend-empty");
  if (state.dashboard.revenueChart) {
    state.dashboard.revenueChart.destroy();
    state.dashboard.revenueChart = null;
  }
  if (!trend.length) {
    canvas.hidden = true;
    emptyState.hidden = false;
    return;
  }
  canvas.hidden = false;
  emptyState.hidden = true;
  if (typeof Chart === "undefined") return;
  state.dashboard.revenueChart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: trend.map((point) => point.period_label),
      datasets: [
        { label: "Revenue", data: trend.map((point) => point.values.revenue || 0), backgroundColor: "rgba(173,70,52,.55)" },
        { label: "Labor", data: trend.map((point) => point.values.labor || 0), backgroundColor: "rgba(154,167,173,.6)" },
        { label: "Parts", data: trend.map((point) => point.values.parts || 0), backgroundColor: "rgba(201,138,58,.55)" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#a29e93" }, grid: { color: "rgba(198,192,182,.08)" } },
        y: { ticks: { color: "#a29e93", callback: (value) => money(value) }, grid: { color: "rgba(198,192,182,.08)" } },
      },
      plugins: {
        legend: { labels: { color: "#f1ece3" } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${money(ctx.parsed.y)}` } },
      },
    },
  });
}

function renderWorkOrderTrendChart(trend) {
  const canvas = $("chart-work-order-trend");
  const emptyState = $("chart-work-order-trend-empty");
  if (state.dashboard.workOrderChart) {
    state.dashboard.workOrderChart.destroy();
    state.dashboard.workOrderChart = null;
  }
  const hasData = trend.some((point) => (point.values.opened || 0) > 0 || (point.values.completed || 0) > 0);
  if (!trend.length || !hasData) {
    canvas.hidden = true;
    emptyState.hidden = false;
    return;
  }
  canvas.hidden = false;
  emptyState.hidden = true;
  if (typeof Chart === "undefined") return;
  state.dashboard.workOrderChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: trend.map((point) => point.period_label),
      datasets: [
        { label: "Opened", data: trend.map((point) => point.values.opened || 0), borderColor: "#ad4634", tension: 0.3 },
        { label: "Completed", data: trend.map((point) => point.values.completed || 0), borderColor: "#9aa7ad", tension: 0.3 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#a29e93" }, grid: { color: "rgba(198,192,182,.08)" } },
        y: { ticks: { color: "#a29e93", precision: 0 }, grid: { color: "rgba(198,192,182,.08)" } },
      },
      plugins: { legend: { labels: { color: "#f1ece3" } } },
    },
  });
}

function renderDashboardCharts(summary) {
  renderRevenueTrendChart(summary.revenue_trend);
  renderWorkOrderTrendChart(summary.work_order_trend);
}

function renderRevenueBreakdown(summary) {
  const container = $("revenue-breakdown-list");
  if (!summary.revenue_breakdown.length) {
    container.innerHTML = '<p class="empty-card-inline">No completed repair orders in the selected period.</p>';
    return;
  }
  container.innerHTML = summary.revenue_breakdown.map((item) => `
    <div class="revenue-breakdown-item">
      <div class="revenue-breakdown-item-head"><strong>${escapeHtml(item.label)}</strong><span>${money(item.amount)} · ${item.percent}%</span></div>
      <progress class="revenue-breakdown-bar" value="${item.percent}" max="100"></progress>
    </div>`).join("");
}

function openDashboardInsightTarget(insight) {
  if (insight.link_view === "estimate" && insight.link_record_id) {
    void openEstimateRecord(insight.link_record_id);
  } else if (insight.link_view === "work-orders") {
    navigate("work-orders");
    if (insight.link_record_id) void selectWorkOrder(insight.link_record_id);
  } else if (insight.link_view === "invoices") {
    navigate("invoices");
    if (insight.link_record_id) void selectInvoice(insight.link_record_id);
  }
}

function renderDashboardInsights(summary) {
  const container = $("dashboard-insights-list");
  if (!summary.insights.length) {
    container.innerHTML = '<p class="empty-card-inline">No open items right now.</p>';
    return;
  }
  container.innerHTML = summary.insights.map((insight, index) => `
    <button type="button" class="insight-item priority-${escapeHtml(insight.priority)}" data-insight-index="${index}">
      <span class="insight-item-issue">${escapeHtml(insight.issue)}</span>
      <span class="insight-item-metric">${escapeHtml(insight.metric)}</span>
      <span class="insight-item-action">${escapeHtml(insight.recommended_action)}</span>
    </button>`).join("");
  $$("[data-insight-index]", container).forEach((button) => {
    button.addEventListener("click", () => {
      const insight = summary.insights[Number(button.dataset.insightIndex)];
      if (insight) openDashboardInsightTarget(insight);
    });
  });
}

function renderCurrentOperations(summary) {
  const ops = summary.current_operations;
  $("current-ops-open").textContent = String(ops.open_work_orders);
  $("current-ops-in-progress").textContent = String(ops.in_progress);
  $("current-ops-waiting-parts").textContent = String(ops.waiting_on_parts);
  $("current-ops-awaiting-approval").textContent = String(ops.awaiting_customer_approval);
  $("current-ops-completed-not-invoiced").textContent = String(ops.completed_not_invoiced);
  $("current-ops-note").textContent = ops.ready_for_pickup_note;
}

function renderFinancialObligations(summary) {
  const obligations = summary.financial_obligations;
  $("financial-obligations-outstanding").textContent = money(obligations.outstanding_balance);
  $("financial-obligations-overdue-balance").textContent = money(obligations.overdue_balance);
  $("financial-obligations-overdue-count").textContent = String(obligations.overdue_invoice_count);
  $("financial-obligations-deposits").textContent = money(obligations.deposits_received_total);
  const list = $("upcoming-installments-list");
  if (!obligations.upcoming_installments.length) {
    list.innerHTML = '<p class="empty-card-inline">No upcoming installments.</p>';
    return;
  }
  list.innerHTML = obligations.upcoming_installments.map((item) => `
    <div class="customer-list-item square-invoice-row">
      <strong>${escapeHtml(item.invoice_number)} · ${escapeHtml(item.label)}</strong>
      <span>${money(item.amount)}${item.due_at ? ` · Due ${new Date(item.due_at).toLocaleDateString()}` : ""}</span>
    </div>`).join("");
}

function initializeDashboard() {
  $("dashboard-range-preset").addEventListener("change", () => {
    state.dashboard.rangePreset = $("dashboard-range-preset").value;
    void loadDashboardSummary();
  });
  $("dashboard-date-from").addEventListener("change", () => {
    $("dashboard-range-preset").value = "custom";
    state.dashboard.rangePreset = "custom";
    void loadDashboardSummary();
  });
  $("dashboard-date-to").addEventListener("change", () => {
    $("dashboard-range-preset").value = "custom";
    state.dashboard.rangePreset = "custom";
    void loadDashboardSummary();
  });
  $("dashboard-summary-refresh").addEventListener("click", () => void loadDashboardSummary());
}

// --- Approval Queue --------------------------------------------------------

function updateApprovalQueueBadge(count) {
  const badge = $("nav-approval-queue-badge");
  if (!badge) return;
  badge.textContent = count > 99 ? "99+" : String(count);
  badge.hidden = count === 0;
}

async function refreshApprovalQueueBadge() {
  try {
    const response = await apiFetch("/api/estimates?page=1&page_size=1&status=awaiting_approval");
    const data = await readApiPayload(response);
    if (!response.ok || !data) return;
    updateApprovalQueueBadge(data.total);
  } catch {
    // Badge refresh is best-effort background polling; never toast on failure.
  }
}

function renderApprovalQueueList() {
  const list = $("approval-queue-list");
  const { items, page, total, hasMore } = state.approvalQueue;
  $("approval-queue-page-status").textContent = `Page ${page} · ${total} total`;
  $("approval-queue-prev").disabled = page <= 1;
  $("approval-queue-next").disabled = !hasMore;
  if (!items.length) {
    list.innerHTML = "<p>No estimates awaiting customer approval.</p>";
    return;
  }
  list.innerHTML = items.map((item) => `
    <button type="button" class="customer-list-item${item.id === state.approvalQueue.selectedEstimateId ? " is-active" : ""}" data-approval-estimate-id="${item.id}">
      <strong>${escapeHtml(item.estimate_number)}</strong>
      <span>${escapeHtml(item.vehicle_display_name)}${item.estimate_total != null ? ` · ${money(item.estimate_total)}` : ""}</span>
      <span>Updated ${new Date(item.updated_at).toLocaleString()}</span>
    </button>`).join("");
  $$("[data-approval-estimate-id]", list).forEach((button) => {
    button.addEventListener("click", () => {
      void selectApprovalQueueEstimate(Number(button.dataset.approvalEstimateId));
    });
  });
}

async function loadApprovalQueue() {
  if (!(await requireAuthenticated("login"))) return;
  const list = $("approval-queue-list");
  list.innerHTML = '<div class="loading-panel"><span class="loading-spinner"></span><div><strong>Loading approval queue</strong></div></div>';
  const searchParams = new URLSearchParams({
    page: String(state.approvalQueue.page),
    page_size: String(state.approvalQueue.pageSize),
    status: "awaiting_approval",
  });
  try {
    const response = await apiFetch(`/api/estimates?${searchParams.toString()}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Approval queue load failed");
    state.approvalQueue.items = data.items;
    state.approvalQueue.total = data.total;
    state.approvalQueue.hasMore = data.has_more;
    renderApprovalQueueList();
    updateApprovalQueueBadge(data.total);
  } catch (error) {
    state.approvalQueue.items = [];
    state.approvalQueue.total = 0;
    state.approvalQueue.hasMore = false;
    renderApprovalQueueList();
    showToast(`Approval queue load failed: ${error.message}`, "error");
  }
}

function renderApprovalQueueDetail(estimate) {
  const container = $("approval-queue-detail");
  if (!estimate) {
    container.innerHTML = "<p>Select an estimate from the list to see full detail.</p>";
    return;
  }
  container.innerHTML = `
    <div class="customer-detail-header"><strong>${escapeHtml(estimate.estimate_number)}</strong><span>${escapeHtml(estimate.status.replaceAll("_", " "))}</span></div>
    <div class="detail-rail-card"><span>Required owner action</span><p>This estimate is waiting on the customer's approval decision. No owner action is required unless you want to follow up or extend the link.</p></div>
    <div class="customer-detail-grid">
      <div><span>Customer</span><strong>${escapeHtml(estimate.customer_display_name || "—")}</strong></div>
      <div><span>Vehicle</span><strong>${escapeHtml(estimate.vehicle_display_name || "—")}</strong></div>
      <div><span>Revision</span><strong>${estimate.current_revision_number ?? "—"}</strong></div>
      <div><span>Estimate total</span><strong>${estimate.estimate_total != null ? money(estimate.estimate_total) : "—"}</strong></div>
      <div><span>Sent / updated</span><strong>${estimate.updated_at ? new Date(estimate.updated_at).toLocaleString() : "—"}</strong></div>
      <div><span>Expires</span><strong>${estimate.expires_at ? new Date(estimate.expires_at).toLocaleString() : "—"}</strong></div>
    </div>`;
}

async function selectApprovalQueueEstimate(estimateId) {
  try {
    const response = await apiFetch(`/api/estimates/${estimateId}`);
    const data = await readApiPayload(response);
    if (!response.ok || !data) throw apiError(response, data, "Estimate load failed");
    state.approvalQueue.selectedEstimateId = data.id;
    state.approvalQueue.selectedEstimate = data;
    renderApprovalQueueDetail(data);
    renderApprovalQueueList();
  } catch (error) {
    showToast(`Estimate load failed: ${error.message}`, "error");
  }
}

function initializeApprovalQueue() {
  $("approval-queue-refresh").addEventListener("click", () => void loadApprovalQueue());
  $("approval-queue-prev").addEventListener("click", () => {
    if (state.approvalQueue.page > 1) {
      state.approvalQueue.page -= 1;
      void loadApprovalQueue();
    }
  });
  $("approval-queue-next").addEventListener("click", () => {
    if (state.approvalQueue.hasMore) {
      state.approvalQueue.page += 1;
      void loadApprovalQueue();
    }
  });
  $("approval-queue-open-estimate").addEventListener("click", () => {
    if (state.approvalQueue.selectedEstimateId) void openEstimateRecord(state.approvalQueue.selectedEstimateId);
  });
  $("approval-queue-open-customer").addEventListener("click", () => {
    const estimate = state.approvalQueue.selectedEstimate;
    if (!estimate) return;
    navigate("customers");
    void selectCustomer(estimate.customer_id);
  });
}

function initializeApp() {
  setAuthState(false);
  initializeNavigation();
  loadSavedPreferences();
  initializeLocation();
  initializeChat();
  initializeDashboard();
  initializeCustomers();
  initializeVehicles();
  initializeTechnicians();
  initializeMyDay();
  initializeWorkOrders();
  initializeApprovalQueue();
  initializeInvoices();
  initializeNotifications();
  initializeSquareDashboard();
  initializeReports();
  initializeServiceDesk();
  initializeDiagnostics();
  initializeInspections();
  initializeVendors();
  initializeParts();
  initializeEstimate();
  initializeSystem();
  initializeAuth();
  // "/login" and "/approval" are never the marketing landing page, regardless
  // of auth state. Cleared here (not an inline <script>) so it stays
  // compliant with the app's script-src 'self' CSP.
  if (window.location.pathname === "/login" || window.location.pathname === "/approval") {
    document.body.classList.remove("marketing-mode");
  }
  if (window.location.pathname === "/approval") {
    navigate("approval");
    void loadPublicApprovalPage();
  } else if (window.location.pathname === "/login") {
    navigate("login");
  }
  void loadSession().then((authenticated) => {
    if (!authenticated) {
      // Unauthenticated visitors to "/" see the marketing landing page
      // (default body state) instead of being forced to the login view.
      if (window.location.pathname !== "/approval" && window.location.pathname !== "/") navigate("login");
      return;
    }
    document.body.classList.remove("marketing-mode");
    if (isTechnicianSession()) {
      // Unlike the owner branch below, "my-day" is never the page's static
      // default view (the HTML ships with #view-dashboard marked
      // is-active), so this must fire on every authenticated load -- not
      // just the first login redirect from "/login" -- or a technician
      // reopening/refreshing the app lands on the owner-only Overview shell
      // instead of My Day.
      navigate("my-day");
    } else {
      void loadCustomerOptions().catch(() => {
        showToast("Customer options failed to load.", "error");
      });
      void restoreSelectionsFromContext();
      void loadDashboardSummary();
      void refreshApprovalQueueBadge();
      if (window.location.pathname === "/login") navigate("dashboard");
    }
  });
  void loadHealth(false);
  window.setInterval(() => loadHealth(false), 60000);
  window.setInterval(() => {
    if (state.auth.authenticated && state.auth.user?.role === "owner") {
      void refreshNotificationsBadge();
      void refreshApprovalQueueBadge();
    }
  }, 60000);
}

document.addEventListener("DOMContentLoaded", initializeApp);

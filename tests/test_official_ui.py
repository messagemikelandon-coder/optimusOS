from __future__ import annotations

import re
from pathlib import Path

import anyio
from starlette.requests import Request
from starlette.responses import FileResponse

from app import __version__
from app.main import STATIC_DIR, get_settings, health, index, security_headers

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_official_landon_motor_works_interface_is_packaged() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Landon Motor Works" in html
    assert "Optimus Command Center" in html
    assert (STATIC / "logo-mark.svg").is_file()
    assert (STATIC / "favicon.svg").is_file()
    assert (STATIC / "invoice.css").is_file()
    assert (STATIC / "manifest.webmanifest").is_file()


def test_landing_page_uses_real_photography_and_required_sections() -> None:
    """Regression coverage for the automotive-design landing page rebuild:
    the decorative CSS-drawn hero (mechanic-stage/rotor-assembly/
    diagnostic-tablet/tilt-surface) was replaced with real Landon Motor
    Works photography, and the brief-required sections (founder field
    story, ICON T7 diagnostics, oil-filter-housing case study) must all
    be present with their media assets packaged."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "mechanic-stage" not in html
    assert "rotor-assembly" not in html
    assert "diagnostic-tablet" not in html
    assert "tilt-surface" not in html
    assert "tilt-surface" not in css

    assert "The operating system behind the repair." in html
    assert 'id="field"' in html
    assert 'id="diagnostics"' in html
    assert "Dejake Landon" in html
    assert "ICON T7" in html
    assert "Oil-filter-housing" in html or "oil-filter-housing" in html

    media_dir = STATIC / "media"
    for filename in (
        "impala-field-work.webp",
        "impala-finished.webp",
        "icon-t7-diagnostics.webp",
        "oil-filter-housing-repair.webp",
        "oil-filter-housing-comparison.webp",
    ):
        assert f"/static/media/{filename}" in html
        assert (media_dir / filename).is_file()


def test_shop_management_ui_grouped_nav_and_new_modules() -> None:
    """Regression coverage for the shop-management-UI redesign: the sidebar
    was reorganized into labeled groups (Operations, Customers & vehicles,
    Service & diagnostics, Estimates & approvals, Work orders & scheduling,
    Invoices & payments, Reports, Notifications, Optimus, System) and two
    new modules (Reports, Scheduling) plus a real Optimus nav entry point
    were added. Every original data-view target must still resolve so
    app.js's generic [data-view] click-delegation keeps working."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")

    for group_label in (
        "Operations",
        "Customers &amp; vehicles",
        "Service &amp; diagnostics",
        "Estimates &amp; approvals",
        "Work orders &amp; scheduling",
        "Invoices &amp; payments",
        "Reports",
        "Notifications",
        "Optimus",
        "System",
    ):
        assert f'<span class="nav-group-label">{group_label}</span>' in html

    for data_view in (
        "dashboard",
        "customers",
        "vehicles",
        "work-orders",
        "approval-queue",
        "technicians",
        "my-day",
        "invoices",
        "notifications",
        "square",
        "estimate",
        "system",
        "reports",
        "scheduling",
        "chat",
    ):
        assert f'data-view="{data_view}"' in html

    assert 'id="view-reports"' in html
    assert 'id="view-scheduling"' in html
    assert 'data-view-panel="reports"' in html
    assert 'data-view-panel="scheduling"' in html
    assert "reports:" in javascript
    assert "scheduling:" in javascript
    assert "async function loadReports" in javascript
    assert '"/api/dashboard/summary?' in javascript or "/api/dashboard/summary?" in javascript
    assert "/api/invoices?page_size=100" in javascript

    # The center-timeline + right-rail pattern must exist for the modules
    # that got restructured, and must be defined in CSS.
    assert "detail-split" in html or "detail-split" in javascript
    assert ".detail-split" in (STATIC / "styles.css").read_text(encoding="utf-8")

    # Vehicle history is a genuinely new feature backed by existing
    # /api/estimates and /api/work-orders vehicle_id filters, not fabricated.
    assert 'id="vehicle-history-estimates"' in html
    assert 'id="vehicle-history-work-orders"' in html
    assert "async function loadVehicleHistory" in javascript

    # The decorative CSS-only 3D server-stack and spinning location-radar
    # were removed from both System bay and My Day (a first pass missed My
    # Day, leaving orphaned unstyled markup there — caught in review).
    assert "server-stack" not in html
    assert "location-radar" not in html
    assert "server-stack" not in (STATIC / "styles.css").read_text(encoding="utf-8")


def test_index_html_has_no_inline_scripts() -> None:
    """The app's CSP is script-src 'self' with no nonce/hash/unsafe-inline
    (see security_headers in app/main.py), so any inline <script> block
    (one with no src= attribute) would be silently blocked by a real
    browser instead of raising a visible error. This regression was caught
    in review: an earlier draft of the marketing landing page used an
    inline bootstrap script that would have broken /login and /approval."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script_tags = re.findall(r"<script\b[^>]*>", html, flags=re.IGNORECASE)
    assert script_tags, "expected at least one <script> tag in index.html"
    for tag in script_tags:
        assert re.search(r'\bsrc\s*=\s*"[^"]+"', tag), (
            f"inline script without src= violates script-src 'self': {tag}"
        )


def test_index_html_has_no_inline_style_attributes() -> None:
    """style-src 'self' has the same no-unsafe-inline restriction as
    script-src. A live Playwright check against the real CSP found a
    pre-existing `style="grid-column: 1 / -1;"` attribute on the Square
    panel (unrelated to the landing-page work) silently violating this on
    every page load; it was replaced with the `.square-panel-full` class."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert not re.search(r'<[a-zA-Z][^>]*\sstyle\s*=\s*"', html), (
        "inline style=\"...\" attribute violates style-src 'self'"
    )


def test_marketing_landing_page_gating() -> None:
    """Unauthenticated visitors to "/" should see the marketing landing
    page (body starts with class="marketing-mode"), while the CSP-safe
    external app.js is responsible for revealing the app shell for /login
    and /approval, and for an authenticated session."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '<body class="marketing-mode">' in html
    assert 'id="marketing-site"' in html
    assert 'data-view-panel="landing"' in html
    assert ".marketing-mode .app-shell" in (STATIC / "styles.css").read_text(encoding="utf-8")
    assert (
        'window.location.pathname === "/login" || window.location.pathname === "/approval"'
        in javascript
    )
    assert 'document.body.classList.remove("marketing-mode")' in javascript


def test_overview_dashboard_and_approval_queue_markup() -> None:
    """Regression coverage for the Overview dashboard that replaced the old
    "Shop intelligence online" hero, and the new Approval Queue view."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "Shop intelligence online" not in html

    for element_id in (
        "dashboard-range-preset",
        "dashboard-date-from",
        "dashboard-date-to",
        "dashboard-summary-refresh",
        "dashboard-metrics",
        "dashboard-health",
        "chart-revenue-trend",
        "chart-work-order-trend",
        "revenue-breakdown-list",
        "dashboard-insights-list",
        "current-ops-open",
        "current-ops-in-progress",
        "current-ops-waiting-parts",
        "current-ops-awaiting-approval",
        "current-ops-completed-not-invoiced",
        "financial-obligations-outstanding",
        "financial-obligations-overdue-balance",
        "financial-obligations-overdue-count",
        "financial-obligations-deposits",
        "upcoming-installments-list",
        "dashboard-command",
        "dashboard-send",
        "refresh-health",
        "view-approval-queue",
        "approval-queue-list",
        "approval-queue-detail",
        "approval-queue-open-estimate",
        "approval-queue-open-customer",
        "nav-approval-queue-badge",
    ):
        assert f'id="{element_id}"' in html

    assert 'data-view-panel="approval-queue"' in html
    assert 'data-view="approval-queue"' in html
    assert html.count("nav-item is-disabled") == 0
    # Scheduling was the last "Coming soon" stub; it's now a real module.
    assert html.count("nav-soon-badge") == 0

    assert "async function loadDashboardSummary" in javascript
    assert "/api/dashboard/summary" in javascript
    assert "async function loadApprovalQueue" in javascript
    assert "status=awaiting_approval" in javascript
    assert 'src="/static/vendor/chart.umd.min.js"' in html
    assert (STATIC / "vendor" / "chart.umd.min.js").is_file()
    assert (STATIC / "vendor" / "LICENSE-chart.js").is_file()

    assert ".metric-card" in css
    assert ".gauge-ring" in css


def test_ui_preserves_connected_workflows() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")
    for element_id in (
        "chat-form",
        "chat-message",
        "customer-form",
        "customers-search",
        "customers-list",
        "customer-detail",
        "customer-vehicles-list",
        "customer-history",
        "customer-history-estimates",
        "customer-history-work-orders",
        "customer-history-invoices",
        "vehicle-form",
        "vehicles-search",
        "vehicles-customer-filter",
        "vehicles-list",
        "vehicle-detail",
        "invoices-list",
        "invoice-detail",
        "invoice-issue-form",
        "nav-notifications-badge",
        "notifications-list",
        "notifications-mark-all",
        "notifications-unread-filter",
        "invoice-square-push",
        "invoice-square-refresh",
        "view-square",
        "square-status-banner",
        "square-invoices-list",
        "square-refresh-all",
        "estimate-form",
        "estimate-selected-customer",
        "estimate-selected-vehicle",
        "approval-public-root",
        "use-location",
        "login-form",
        "login-username",
        "login-password",
        "result",
    ):
        assert f'id="{element_id}"' in html
    assert 'apiFetch("/api/auth/login"' in javascript
    assert 'apiFetch("/api/auth/me"' in javascript
    assert "/api/customers" in javascript
    assert "/api/vehicles" in javascript
    assert "/api/context/vehicles/selected-vehicle?scope=session" in javascript
    assert "/api/context/estimates/selected-estimate?scope=session" in javascript
    assert 'apiFetch("/api/chat"' in javascript
    assert "/api/estimates" in javascript
    assert "/api/invoices" in javascript
    assert "apiFetch(`/api/invoices/${invoiceId}/issue`" in javascript
    assert "window.open(`/api/invoices/${invoiceId}/${kind}`" in javascript
    assert "renderInvoiceList();" in javascript
    assert "apiFetch(`/api/estimates/${estimateId}`)" in javascript
    assert "apiFetch(`/api/customers/${customerId}/history?limit=20`)" in javascript
    assert "/api/notifications" in javascript
    assert 'apiFetch("/api/notifications/read-all"' in javascript
    assert "apiFetch(`/api/invoices/${invoice.id}/square/push`" in javascript
    assert "apiFetch(`/api/invoices/${invoice.id}/square/refresh`" in javascript
    assert "async function loadSquareDashboard" in javascript
    assert "/api/estimate-approval/view" in javascript
    assert "async function openEstimateRecord" in javascript
    assert "async function openInvoiceForSelectedWorkOrder" in javascript
    assert 'window.location.pathname === "/approval"' in javascript
    assert 'window.location.hash.replace(/^#/, "")' in javascript
    assert 'history.replaceState(null, "", "/approval" + window.location.hash)' in javascript
    assert "Approval link required" in javascript
    assert 'apiFetch("/health"' in javascript


def test_local_launcher_opens_login_url_without_credentials_in_fragment() -> None:
    launcher = (ROOT / "local.bat").read_text(encoding="utf-8")
    opener = (ROOT / "scripts" / "open_when_ready.ps1").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "Login: http://127.0.0.1:8000/login" in launcher
    assert "Start-Process $Url" in opener
    assert "access_token" not in opener
    assert "optimus_access_token" not in javascript
    assert 'credentials: "same-origin"' in javascript


def test_playwright_audit_supports_safe_authenticated_smoke_mode() -> None:
    audit_script = (ROOT / "scripts" / "ui_connection_audit_playwright.js").read_text(
        encoding="utf-8"
    )
    assert "OPTIMUS_AUDIT_SKIP_DOCKER" in audit_script
    assert "OPTIMUS_AUDIT_SKIP_BILLABLE" in audit_script
    assert "seed_estimate_approval_fixture.py" in audit_script
    assert '"/api/auth/me"' in audit_script
    assert '"/api/location/resolve"' in audit_script
    assert '"/api/vehicles"' in audit_script
    assert '"/api/estimates"' in audit_script
    assert '"/send-for-approval"' in audit_script
    assert '"/approval#token="' in audit_script
    assert '"/api/estimate-approval/approve"' in audit_script
    assert "/api/estimates/${estimateId}/approval-history" in audit_script


def test_health_identifies_official_build() -> None:
    payload = anyio.run(health, get_settings())
    # Compares against the real source of truth (app/__init__.py) rather
    # than a hardcoded duplicate string, so this test can never itself
    # become the stale reference the next version bump breaks.
    assert payload["version"] == __version__
    assert payload["business_name"] == "Landon Motor Works"
    assert payload["business_tagline"] == "Mobile Mechanic Intelligence"


def test_static_command_center_is_served_with_strict_headers() -> None:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "scheme": "http",
            "method": "GET",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
    )

    async def call_next(_: Request) -> FileResponse:
        return await index()

    response = anyio.run(security_headers, request, call_next)
    assert response.status_code == 200
    policy = response.headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "'unsafe-inline'" not in policy
    assert (STATIC_DIR / "styles.css").is_file()
    assert (STATIC_DIR / "manifest.webmanifest").is_file()

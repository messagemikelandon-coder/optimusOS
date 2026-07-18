from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from playwright.sync_api import Page, expect
from sqlalchemy.orm import sessionmaker

from app.db import build_engine
from app.db_models import Technician, TechnicianTimeEntry
from app.shop_store import resolve_shop_id_for_owner
from tests.e2e.conftest import LiveServer, SyntheticCredentials
from tests.e2e.test_core_workflow import _login


def _download_csv_lines(page: Page, export_button_selector: str) -> tuple[str, list[str]]:
    with page.expect_download() as download_info:
        page.click(export_button_selector)
    download = download_info.value
    csv_path = download.path()
    assert csv_path is not None
    csv_text = csv_path.read_text()
    return download.suggested_filename, csv_text.splitlines()


def test_reports_export_csv_downloads_a_real_csv_file(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    """Real browser click on a report card's "Export CSV" button, real
    client-side Blob/download (no server round trip for the export itself),
    asserting the actual downloaded file's exact rows -- not just that a
    click handler exists or that some expected text appears somewhere in the
    file. Covers the no-thead code path (a stat table with only a tbody)."""
    _login(page, live_server, synthetic_owner)
    expect(page.locator("#view-dashboard")).to_be_visible()

    page.click('[data-view="reports"]')
    expect(page.locator("#view-reports")).to_be_visible()
    # The Work order status summary card has no thead, only a real,
    # non-empty tbody even for a brand-new owner with zero activity (every
    # status row still renders showing a 0 count) -- guarantees content to
    # export without needing to first seed business data.
    work_order_table = page.locator("#reports-work-order-table")
    expect(work_order_table.locator("tr")).not_to_have_count(0)
    expect(work_order_table).not_to_contain_text("Loading")

    filename, lines = _download_csv_lines(page, '[data-export-csv="reports-work-order-table"]')

    assert filename.startswith("work-order-status-summary-")
    assert filename.endswith(".csv")
    # Exact-line assertions (not substring-in-file) so a swapped column, a
    # dropped row, or a reordered row would actually fail this test. The
    # last row's label contains a literal comma, so it must come back
    # RFC-4180-quoted -- also exercises the CSV-escaping path for real.
    assert lines == [
        "Open,0",
        "In progress,0",
        "Waiting on parts,0",
        "Awaiting customer approval,0",
        '"Completed, not yet invoiced",0',
    ]


def test_reports_export_csv_includes_header_row_when_table_has_thead(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    """Covers the thead-detection branch of reportTableToCsv, which the
    no-thead test above never exercises. Seeds a real technician with a real
    closed time entry directly against the live server's own database
    (matching the seeding pattern already used by test_core_workflow.py),
    then confirms the exported CSV's first line is the real column headers
    and the second line is the real data row -- not just that the labels
    appear somewhere in the file."""
    engine = build_engine(live_server.database_url)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as seed_session:
        shop_id = resolve_shop_id_for_owner(seed_session, synthetic_owner.user_id)
        technician = Technician(
            owner_user_id=synthetic_owner.user_id,
            shop_id=shop_id,
            first_name="Riley",
            last_name="Chen",
            employment_status="Full-time",
            hourly_cost=Decimal("25.00"),
        )
        seed_session.add(technician)
        seed_session.flush()
        now = datetime.now(UTC)
        seed_session.add(
            TechnicianTimeEntry(
                technician_id=technician.id,
                owner_user_id=synthetic_owner.user_id,
                shop_id=shop_id,
                clock_in_at=now - timedelta(hours=2),
                clock_out_at=now,
            )
        )
        seed_session.commit()

    _login(page, live_server, synthetic_owner)
    expect(page.locator("#view-dashboard")).to_be_visible()
    page.click('[data-view="reports"]')
    expect(page.locator("#view-reports")).to_be_visible()

    technician_time_table = page.locator("#reports-technician-time-table")
    expect(technician_time_table).to_contain_text("Riley Chen")

    filename, lines = _download_csv_lines(page, '[data-export-csv="reports-technician-time-table"]')

    assert filename.startswith("technician-time-")
    assert lines[0] == "Technician,Clocked hours,Labor cost"
    assert lines[1] == "Riley Chen,2,$50.00"

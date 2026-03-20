"""Tuning tests for timesheet entry + project invoice workflow.

Based on production failure (2026-03-20 12:47 PM): agent looked up employee, customer,
project, and product but never registered timesheet hours or created invoice — returned
empty response.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_timesheet_mock() -> MockTripletexClient:
    """Set up mock with employee, customer, project, and activity for timesheet tasks."""
    mock = MockTripletexClient()

    # Employee
    mock.register_entity("employee", {
        "id": 100,
        "firstName": "Anna",
        "lastName": "Becker",
        "email": "anna.becker@example.org",
    })

    # Customer
    mock.register_entity("customer", {
        "id": 200,
        "name": "Windkraft GmbH",
        "organizationNumber": "941944566",
    })

    # Project
    mock.register_entity("project", {
        "id": 300,
        "name": "Website-Redesign",
        "number": "1",
        "customer": {"id": 200},
        "projectManager": {"id": 100},
    })

    # Activity (for timesheet)
    mock.register_entity("activity", {
        "id": 400,
        "name": "Testing",
        "isProjectActivity": True,
        "isChargeable": True,
    })

    # Bank account
    mock.register_entity("ledger/account", {
        "id": 500,
        "number": 1920,
        "name": "Bankinnskudd",
        "isBankAccount": True,
    })

    # VAT type
    mock.register_entity("ledger/vatType", {
        "id": 3,
        "name": "Utgående mva, høy sats",
        "number": "3",
        "percentage": 25.0,
    })

    return mock


@skip_no_vertex
class TestTimesheetAndInvoice:
    """Agent should register timesheet hours and create project invoice."""

    def test_timesheet_and_invoice_german(self, run_agent):
        """Exact production prompt (German): register 25h and create invoice."""
        mock = _make_timesheet_mock()

        prompt = (
            'Erfassen Sie 25 Stunden für Anna Becker (anna.becker@example.org) auf der '
            'Aktivität "Testing" im Projekt "Website-Redesign" für Windkraft GmbH '
            "(Org.-Nr. 941944566). Stundensatz: 1200 NOK/h. Erstellen Sie eine "
            "Projektrechnung an den Kunden basierend auf den erfassten Stunden."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        # Must register timesheet entry
        result.assert_endpoint_called("POST", "/v2/timesheet/entry")
        ts_call = result.find_calls("POST", "/v2/timesheet/entry")[0]
        assert ts_call.body is not None
        assert ts_call.body.get("hours") == 25 or ts_call.body.get("hours") == 25.0, \
            f"Expected 25 hours, got {ts_call.body.get('hours')}"

        # Must create order and invoice
        result.assert_endpoint_called("POST", "/v2/order")
        result.assert_endpoint_called("PUT", "/:invoice")

        result.assert_no_errors()
        result.assert_max_calls(14)

    def test_timesheet_only_norwegian(self, run_agent):
        """Norwegian: just register hours, no invoice."""
        mock = _make_timesheet_mock()

        prompt = (
            'Registrer 10 timer for Anna Becker (anna.becker@example.org) på aktiviteten '
            '"Testing" i prosjektet "Website-Redesign" for Windkraft GmbH '
            "(org.nr 941944566). Timesats: 950 NOK/t."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        # Must register timesheet entry
        result.assert_endpoint_called("POST", "/v2/timesheet/entry")

        result.assert_no_errors()
        result.assert_max_calls(8)

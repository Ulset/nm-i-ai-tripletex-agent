"""Tuning tests for payroll workflow using ledger vouchers.

Recipe L uses POST /v2/ledger/voucher with salary expense (5000) and
payable (2920) postings — NOT /v2/salary/transaction.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_payroll_mock() -> MockTripletexClient:
    """Set up mock with employee and ledger accounts for payroll tasks."""
    mock = MockTripletexClient()

    # Employee (has dateOfBirth and employment already — happy path)
    mock.register_entity("employee", {
        "id": 100,
        "firstName": "Mia",
        "lastName": "Hoffmann",
        "email": "mia.hoffmann@example.org",
        "dateOfBirth": "1990-05-15",
    })

    # Employment exists (so agent doesn't need to create one)
    mock.register_entity("employee/employment", {
        "id": 500,
        "employee": {"id": 100},
        "startDate": "2025-01-01",
        "division": {"id": 1},
    })

    # Ledger accounts for payroll voucher
    mock.register_entity("ledger/account", {
        "id": 5000,
        "number": 5000,
        "name": "Lønn",
    })
    mock.register_entity("ledger/account", {
        "id": 2920,
        "number": 2920,
        "name": "Skyldig lønn",
    })

    return mock


@skip_no_vertex
class TestPayroll:
    """Agent should create payroll voucher with correct postings."""

    def test_payroll_german(self, run_agent):
        """Production prompt (German): register salary with base + bonus."""
        mock = _make_payroll_mock()

        prompt = (
            "Registrieren Sie die Gehaltsabrechnung für Juni 2026 für "
            "Mia Hoffmann (mia.hoffmann@example.org). "
            "Grundgehalt: 40350 NOK, Bonus: 7350 NOK."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        # Must create voucher with salary postings
        result.assert_endpoint_called("POST", "/v2/ledger/voucher")
        voucher_call = result.find_calls("POST", "/v2/ledger/voucher")[0]
        assert voucher_call.body is not None
        assert "postings" in voucher_call.body, \
            f"Voucher must have postings. Keys: {list(voucher_call.body.keys())}"

        result.assert_no_errors()
        result.assert_max_calls(8)

    def test_payroll_norwegian(self, run_agent):
        """Norwegian: register salary."""
        mock = _make_payroll_mock()

        prompt = (
            "Registrer lønnsutbetaling for mars 2026 for "
            "Mia Hoffmann (mia.hoffmann@example.org). "
            "Fastlønn: 45000 NOK."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("POST", "/v2/ledger/voucher")
        result.assert_no_errors()
        result.assert_max_calls(8)

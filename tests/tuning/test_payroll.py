"""Tuning tests for payroll (salary transaction) workflow.

Based on production failure (2026-03-20 15:17): agent hit max iterations because
employee had no employment/dateOfBirth, employment had no division, and agent
forgot the 'year' field on salary/transaction.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_payroll_mock() -> MockTripletexClient:
    """Set up mock with employee and salary types for payroll tasks."""
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

    # Salary types
    mock.register_entity("salary/type", {
        "id": 200,
        "number": "1120",
        "name": "Fastlønn",
        "description": "Fastlønn",
    })
    mock.register_entity("salary/type", {
        "id": 201,
        "number": "1350",
        "name": "Bonus",
        "description": "Bonus",
    })

    return mock


@skip_no_vertex
class TestPayroll:
    """Agent should create salary transactions correctly."""

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

        # Must create salary transaction
        result.assert_endpoint_called("POST", "/v2/salary/transaction")
        tx_call = result.find_calls("POST", "/v2/salary/transaction")[0]
        assert tx_call.body is not None

        # Must include year field
        assert "year" in tx_call.body, \
            f"Must include 'year' in salary/transaction. Keys: {list(tx_call.body.keys())}"

        result.assert_no_errors()
        result.assert_max_calls(7)

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

        result.assert_endpoint_called("POST", "/v2/salary/transaction")
        result.assert_no_errors()
        result.assert_max_calls(7)

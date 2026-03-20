"""Tuning tests for credit note (invoice correction) workflows.

Covers Recipe J — CREDIT NOTE half from agent.py system prompt.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_credit_note_mock() -> MockTripletexClient:
    """Set up mock with customer and existing invoice for credit note."""
    mock = MockTripletexClient()

    mock.register_entity("customer", {
        "id": 100,
        "name": "Havgull AS",
        "organizationNumber": "901234567",
    })
    mock.register_entity("invoice", {
        "id": 200,
        "invoiceNumber": 1,
        "invoiceDate": "2026-02-15",
        "customer": {"id": 100},
        "amount": 62500,
        "amountOutstanding": 62500,
    })

    return mock


@skip_no_vertex
class TestCreditNote:
    """Agent should create credit notes using PUT /:createCreditNote."""

    def test_credit_note_spanish(self, run_agent):
        """Create credit note in Spanish."""
        mock = _make_credit_note_mock()

        prompt = (
            "La factura de Havgull AS (org. nº 901234567) por 62500 NOK es incorrecta. "
            "Cree una nota de crédito para anularla."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("GET", "/v2/invoice")
        result.assert_endpoint_called("PUT", "/:createCreditNote")

        # Must NOT delete voucher — that's for payment reversals
        delete_calls = result.find_calls("DELETE", "/v2/ledger/voucher")
        assert len(delete_calls) == 0, \
            "Should NOT delete voucher for credit notes"

        result.assert_no_errors()
        result.assert_max_calls(4)

    def test_credit_note_norwegian(self, run_agent):
        """Create credit note in Norwegian."""
        mock = _make_credit_note_mock()

        prompt = (
            "Fakturaen til Havgull AS (org.nr 901234567) på 62500 NOK er feil. "
            "Opprett en kreditnota for å reversere den."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("GET", "/v2/invoice")
        result.assert_endpoint_called("PUT", "/:createCreditNote")

        result.assert_no_errors()
        result.assert_max_calls(4)

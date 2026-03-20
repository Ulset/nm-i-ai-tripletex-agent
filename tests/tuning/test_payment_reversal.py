"""Tuning tests for payment reversal workflow.

Based on production issue: agent confused credit note (reverses invoice) with payment
reversal (deletes payment voucher). Payment returned by bank = delete the voucher.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_payment_reversal_mock() -> MockTripletexClient:
    """Set up mock with customer, invoice, and multiple vouchers.

    Registers an invoice voucher (should NOT be deleted) and a payment voucher
    (SHOULD be deleted) to force the agent to distinguish between types.
    """
    mock = MockTripletexClient()

    mock.register_entity("customer", {
        "id": 100,
        "name": "Solmar SL",
        "organizationNumber": "840739201",
    })
    mock.register_entity("invoice", {
        "id": 200,
        "invoiceNumber": 1,
        "invoiceDate": "2026-03-01",
        "customer": {"id": 100},
        "amountOutstanding": 0,
        "amount": 50687.5,
    })
    # Invoice voucher — should NOT be deleted
    mock.register_entity("ledger/voucher", {
        "id": 300,
        "date": "2026-03-01",
        "number": 1,
        "description": "Faktura 1 til Solmar SL",
    })
    # Payment voucher — SHOULD be deleted
    mock.register_entity("ledger/voucher", {
        "id": 301,
        "date": "2026-03-15",
        "number": 2,
        "description": "Betaling: Faktura nummer 1 til Solmar SL (10001)",
    })

    return mock


def _assert_payment_voucher_deleted(result):
    """Assert agent deleted payment voucher(s) but NOT the invoice voucher."""
    delete_calls = result.find_calls("DELETE", "/v2/ledger/voucher")
    assert len(delete_calls) >= 1, "Must delete at least one payment voucher"

    # Should not delete the invoice voucher (id=300)
    for call in delete_calls:
        assert "/300" not in call.endpoint, \
            "Should NOT delete the invoice voucher (id=300)"


@skip_no_vertex
class TestPaymentReversal:
    """Agent should DELETE voucher for payment reversals, NOT createCreditNote."""

    def test_payment_reversal_spanish(self, run_agent):
        """Exact production prompt: payment returned by bank."""
        mock = _make_payment_reversal_mock()

        prompt = (
            'El pago de Solmar SL (org. nº 840739201) por la factura "Horas de consultoría" '
            "(40550 NOK sin IVA) fue devuelto por el banco. Revierta el pago para que la "
            "factura vuelva a mostrar el importe pendiente."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        # Must DELETE the payment voucher, NOT createCreditNote
        result.assert_endpoint_called("DELETE", "/v2/ledger/voucher")
        _assert_payment_voucher_deleted(result)

        credit_note_calls = result.find_calls("PUT", "/:createCreditNote")
        assert len(credit_note_calls) == 0, \
            "Should NOT use createCreditNote for payment reversals"

        result.assert_no_errors()
        result.assert_max_calls(6)

    def test_payment_reversal_french(self, run_agent):
        """French variant: cancel returned payment."""
        mock = _make_payment_reversal_mock()

        prompt = (
            "Le paiement de Solmar SL (nº org. 840739201) pour la facture "
            '"Heures de consultation" (40550 NOK HT) a été retourné par la banque. '
            "Annulez le paiement afin que la facture affiche à nouveau le montant impayé."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("DELETE", "/v2/ledger/voucher")
        _assert_payment_voucher_deleted(result)
        result.assert_no_errors()
        result.assert_max_calls(6)

    def test_payment_reversal_english(self, run_agent):
        """English variant."""
        mock = _make_payment_reversal_mock()

        prompt = (
            "The payment from Solmar SL (org. no. 840739201) for the invoice "
            '"Consulting hours" (40550 NOK excl. VAT) was returned by the bank. '
            "Reverse the payment so the invoice shows the outstanding amount again."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("DELETE", "/v2/ledger/voucher")
        _assert_payment_voucher_deleted(result)
        result.assert_no_errors()
        result.assert_max_calls(6)

    def test_payment_reversal_nynorsk(self, run_agent):
        """Exact production prompt that scored 4/8."""
        mock = _make_payment_reversal_mock()

        prompt = (
            'Betalinga frå Strandvik AS (org.nr 840739201) for fakturaen "Horas de consultoría" '
            "(40550 NOK ekskl. MVA) vart returnert av banken. Reverser betalinga slik at "
            "fakturaen igjen viser uteståande beløp."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("DELETE", "/v2/ledger/voucher")
        _assert_payment_voucher_deleted(result)
        result.assert_no_errors()
        result.assert_max_calls(6)

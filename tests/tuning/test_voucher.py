"""Tuning tests for voucher posting workflows: dimensions, simple vouchers, supplier invoices.

Consolidated from test_voucher_dimension.py and test_supplier_invoice.py.

Covers Recipe I (VOUCHER) from agent.py system prompt.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_voucher_mock() -> MockTripletexClient:
    """Set up mock with ledger accounts for voucher posting tasks."""
    mock = MockTripletexClient()

    mock.register_entity("ledger/account", {
        "id": 300,
        "number": 6340,
        "name": "Lys, varme",
    })
    mock.register_entity("ledger/account", {
        "id": 301,
        "number": 1920,
        "name": "Bankinnskudd",
        "isBankAccount": True,
    })

    return mock


def _make_supplier_invoice_mock() -> MockTripletexClient:
    """Set up mock with supplier and ledger accounts for invoice registration."""
    mock = MockTripletexClient()

    mock.register_entity("supplier", {
        "id": 100,
        "name": "Elvdal AS",
        "organizationNumber": "889157917",
    })
    mock.register_entity("ledger/account", {
        "id": 200,
        "number": 6500,
        "name": "Motordrevet verktøy",
    })
    mock.register_entity("ledger/account", {
        "id": 201,
        "number": 2400,
        "name": "Leverandørgjeld",
    })
    mock.register_entity("ledger/account", {
        "id": 202,
        "number": 2710,
        "name": "Inngående merverdiavgift, høy sats",
    })
    mock.register_entity("ledger/vatType", {
        "id": 1,
        "name": "Fradrag inngående avgift, høy sats",
        "number": "1",
        "percentage": 25.0,
    })

    return mock


@skip_no_vertex
class TestVoucherWithDimension:
    """Agent should create dimensions, then post voucher with correct fields."""

    def test_dimension_and_voucher_nynorsk(self, run_agent):
        """Exact production prompt (Nynorsk): create dimension + post voucher."""
        mock = _make_voucher_mock()

        prompt = (
            'Opprett ein fri rekneskapsdimensjon "Marked" med verdiane "Offentlig" og "Privat". '
            "Bokfør deretter eit bilag på konto 6340 for 25200 kr, knytt til dimensjonsverdien "
            '"Offentlig".'
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("POST", "/v2/ledger/accountingDimensionName")

        dim_val_calls = result.find_calls("POST", "/v2/ledger/accountingDimensionValue")
        assert len(dim_val_calls) >= 2, f"Expected 2 dimension values, got {len(dim_val_calls)}"

        result.assert_endpoint_called("GET", "/v2/ledger/account")

        voucher_call = result.assert_endpoint_called("POST", "/v2/ledger/voucher")
        assert voucher_call.body is not None
        postings = voucher_call.body.get("postings", [])
        assert len(postings) >= 2, f"Expected at least 2 postings (debit+credit), got {len(postings)}"

        for p in postings:
            assert "amountGross" in p or "amountGrossCurrency" in p, \
                f"Posting must use amountGross, not amount. Keys: {list(p.keys())}"

        has_dimension = any(
            "freeAccountingDimension1" in p
            for p in postings
        )
        assert has_dimension, \
            f"Expected freeAccountingDimension1 on at least one posting. Posting keys: {[list(p.keys()) for p in postings]}"

        result.assert_no_errors()
        result.assert_max_calls(10)

    def test_dimension_and_voucher_norwegian(self, run_agent):
        """Norwegian (bokmål) variant."""
        mock = _make_voucher_mock()

        prompt = (
            'Opprett en fri regnskapsdimensjon "Region" med verdiene "Nord" og "Sør". '
            "Bokfør et bilag på konto 6340 for 15000 kr, knyttet til dimensjonsverdien "
            '"Nord".'
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("POST", "/v2/ledger/accountingDimensionName")

        dim_val_calls = result.find_calls("POST", "/v2/ledger/accountingDimensionValue")
        assert len(dim_val_calls) >= 2

        result.assert_endpoint_called("POST", "/v2/ledger/voucher")

        result.assert_no_errors()
        result.assert_max_calls(10)


@skip_no_vertex
class TestSimpleVoucher:
    """Agent should create a simple voucher without dimensions."""

    def test_simple_voucher_english(self, run_agent):
        """Simple voucher posting without dimensions."""
        mock = _make_voucher_mock()

        prompt = (
            "Post a journal entry (voucher) on account 6340 for 18500 NOK "
            "dated 2026-01-15 with description 'Office heating Q4'."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("POST", "/v2/ledger/voucher")

        voucher_call = result.find_calls("POST", "/v2/ledger/voucher")[0]
        postings = voucher_call.body.get("postings", [])
        assert len(postings) >= 2, "Must have debit and credit postings"

        for p in postings:
            assert "amountGross" in p or "amountGrossCurrency" in p, \
                f"Must use amountGross. Keys: {list(p.keys())}"

        result.assert_no_errors()
        result.assert_max_calls(4)


@skip_no_vertex
class TestSupplierInvoice:
    """Agent should register supplier invoices as vouchers with correct postings."""

    def test_supplier_invoice_nynorsk(self, run_agent):
        """Exact production prompt (Nynorsk): register supplier invoice with VAT."""
        mock = _make_supplier_invoice_mock()

        prompt = (
            "Me har motteke faktura INV-2026-8662 frå leverandøren Elvdal AS "
            "(org.nr 889157917) på 39750 kr inklusiv MVA. Beløpet gjeld kontortenester "
            "(konto 6500). Registrer leverandørfakturaen med korrekt inngåande MVA (25 %)."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        voucher_call = result.assert_endpoint_called("POST", "/v2/ledger/voucher")
        assert voucher_call.body is not None

        postings = voucher_call.body.get("postings", [])
        assert len(postings) >= 2, f"Expected at least 2 postings, got {len(postings)}"

        for p in postings:
            assert "amountGross" in p or "amountGrossCurrency" in p, \
                f"Must use amountGross. Keys: {list(p.keys())}"

        body = voucher_call.body
        has_invoice_ref = (
            body.get("vendorInvoiceNumber") or
            "INV-2026-8662" in body.get("description", "")
        )
        assert has_invoice_ref, "Should reference invoice number INV-2026-8662"

        result.assert_no_errors()
        result.assert_max_calls(7)

    def test_supplier_invoice_english(self, run_agent):
        """English variant: register supplier invoice."""
        mock = _make_supplier_invoice_mock()

        prompt = (
            "We have received invoice INV-2026-1234 from supplier Elvdal AS "
            "(org. no. 889157917) for 50000 NOK including VAT. The amount is for "
            "office services (account 6500). Register the supplier invoice with "
            "correct incoming VAT (25%)."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("POST", "/v2/ledger/voucher")
        result.assert_no_errors()
        result.assert_max_calls(7)

"""Tuning tests for voucher posting + accounting dimension workflows.

Based on production failure (2026-03-20 12:20 PM): agent tried 5 wrong field names
for linking dimensions to postings (accountingDimensionValues, freeDimension1, dimensions,
dimensionValue1) and used 'amount' instead of 'amountGross'. Hit max iterations with 6 errors.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_voucher_mock() -> MockTripletexClient:
    """Set up mock with ledger accounts for voucher posting tasks."""
    mock = MockTripletexClient()

    # Ledger accounts
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

        # Must create dimension name
        result.assert_endpoint_called("POST", "/v2/ledger/accountingDimensionName")

        # Must create both dimension values
        dim_val_calls = result.find_calls("POST", "/v2/ledger/accountingDimensionValue")
        assert len(dim_val_calls) >= 2, f"Expected 2 dimension values, got {len(dim_val_calls)}"

        # Must look up account 6340
        result.assert_endpoint_called("GET", "/v2/ledger/account")

        # Must create voucher with postings
        voucher_call = result.assert_endpoint_called("POST", "/v2/ledger/voucher")
        assert voucher_call.body is not None
        postings = voucher_call.body.get("postings", [])
        assert len(postings) >= 2, f"Expected at least 2 postings (debit+credit), got {len(postings)}"

        # Postings must use amountGross, NOT amount
        for p in postings:
            assert "amountGross" in p or "amountGrossCurrency" in p, \
                f"Posting must use amountGross, not amount. Keys: {list(p.keys())}"

        # At least one posting should have freeAccountingDimension1
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
            "dated 2023-11-15 with description 'Office heating Q4'."
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
        result.assert_max_calls(6)

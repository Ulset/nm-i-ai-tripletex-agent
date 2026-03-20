"""Tuning tests for customer and supplier creation workflows.

Covers Recipe C (CUSTOMER/SUPPLIER) from agent.py system prompt.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


@skip_no_vertex
class TestCustomer:
    """Agent should create customers with all provided fields."""

    def test_create_customer_with_address_norwegian(self, run_agent):
        """Create customer with address in Norwegian."""
        mock = MockTripletexClient()

        prompt = (
            "Opprett en kunde: Nordlys AS, org.nr 987654321, "
            "e-post kontakt@nordlys.no, telefon 99887766. "
            "Adresse: Storgata 12, 0182 Oslo."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        post_call = result.assert_endpoint_called("POST", "/v2/customer")
        assert post_call.body is not None
        assert post_call.body.get("name") == "Nordlys AS"
        assert post_call.body.get("organizationNumber") == "987654321"
        assert post_call.body.get("email") == "kontakt@nordlys.no"

        result.assert_no_errors()
        result.assert_max_calls(2)

    def test_update_customer_contact_english(self, run_agent):
        """Update existing customer contact info in English."""
        mock = MockTripletexClient()
        mock.register_entity("customer", {
            "id": 100,
            "name": "Seaside Corp",
            "organizationNumber": "912345678",
            "email": "old@seaside.com",
        })

        prompt = (
            "Update the customer Seaside Corp (org. no. 912345678): "
            "change email to new@seaside.com and phone number to 55443322."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("GET", "/v2/customer")
        put_call = result.assert_endpoint_called("PUT", "/v2/customer")
        assert put_call.body is not None
        assert put_call.body.get("email") == "new@seaside.com"

        result.assert_no_errors()
        result.assert_max_calls(3)


@skip_no_vertex
class TestSupplier:
    """Agent should create suppliers with all provided fields."""

    def test_create_supplier_portuguese(self, run_agent):
        """Create supplier in Portuguese."""
        mock = MockTripletexClient()

        prompt = (
            "Crie um fornecedor: Sol do Norte Lda, nº org. 876543210, "
            "e-mail info@soldonorte.pt, telefone 21987654."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        post_call = result.assert_endpoint_called("POST", "/v2/supplier")
        assert post_call.body is not None
        assert post_call.body.get("name") == "Sol do Norte Lda"

        result.assert_no_errors()
        result.assert_max_calls(2)

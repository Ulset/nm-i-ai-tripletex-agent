from src.knowledge import TRIPLETEX_API_REFERENCE
from src.knowledge.tripletex_api import TRIPLETEX_API_REFERENCE as DIRECT_REFERENCE


class TestTripletexAPIReference:
    """Tests for the Tripletex API knowledge base."""

    def test_reference_is_string(self):
        assert isinstance(TRIPLETEX_API_REFERENCE, str)

    def test_reference_not_empty(self):
        assert len(TRIPLETEX_API_REFERENCE) > 0

    def test_reference_importable_from_package(self):
        """TRIPLETEX_API_REFERENCE is importable from src.knowledge."""
        assert TRIPLETEX_API_REFERENCE == DIRECT_REFERENCE

    def test_reference_fits_within_token_budget(self):
        """Reference should fit within ~4000 tokens (~16000 chars as rough estimate)."""
        # Rough estimate: 1 token ≈ 4 characters for English text
        estimated_tokens = len(TRIPLETEX_API_REFERENCE) / 4
        assert estimated_tokens < 4000, f"Reference is ~{estimated_tokens:.0f} tokens, should be under 4000"

    def test_documents_endpoints(self):
        """All required endpoints are documented."""
        required_endpoints = [
            "/v2/employee",
            "/v2/customer",
            "/v2/product",
            "/v2/invoice",
            "/v2/order",
            "/v2/travelExpense",
            "/v2/project",
            "/v2/department",
            "/v2/ledger/account",
            "/v2/ledger/voucher",
        ]
        for endpoint in required_endpoints:
            assert endpoint in TRIPLETEX_API_REFERENCE, f"Missing endpoint: {endpoint}"

    def test_documents_http_methods(self):
        """GET, POST, PUT, DELETE methods are documented."""
        for method in ["GET", "POST", "PUT", "DELETE"]:
            assert method in TRIPLETEX_API_REFERENCE

    def test_documents_authentication(self):
        """Authentication pattern is documented."""
        assert "Basic Auth" in TRIPLETEX_API_REFERENCE
        assert '"0"' in TRIPLETEX_API_REFERENCE
        assert "session_token" in TRIPLETEX_API_REFERENCE

    def test_documents_pagination(self):
        """Pagination parameters are documented."""
        assert "count" in TRIPLETEX_API_REFERENCE
        assert "from" in TRIPLETEX_API_REFERENCE
        assert "fields" in TRIPLETEX_API_REFERENCE

    def test_documents_date_format(self):
        """Date format is documented."""
        assert "YYYY-MM-DD" in TRIPLETEX_API_REFERENCE

    def test_documents_response_format(self):
        """Response wrapper format is documented."""
        assert "fullResultSize" in TRIPLETEX_API_REFERENCE
        assert "values" in TRIPLETEX_API_REFERENCE

    def test_documents_task_patterns(self):
        """Common task patterns are documented."""
        patterns = [
            "Create Single Entity",
            "Create with Linking",
            "Modify Existing",
            "Delete or Reverse",
        ]
        for pattern in patterns:
            assert pattern in TRIPLETEX_API_REFERENCE, f"Missing pattern: {pattern}"

    def test_documents_module_enablement(self):
        """Module enablement patterns are documented."""
        assert "Module Enablement" in TRIPLETEX_API_REFERENCE
        assert "departmentAccounting" in TRIPLETEX_API_REFERENCE
        assert "projectAccounting" in TRIPLETEX_API_REFERENCE

    def test_documents_common_errors(self):
        """Common error patterns are documented."""
        assert "Missing Prerequisites" in TRIPLETEX_API_REFERENCE
        assert "Duplicate Entities" in TRIPLETEX_API_REFERENCE
        assert "Required Field Omissions" in TRIPLETEX_API_REFERENCE

    def test_documents_norwegian_characters(self):
        """Norwegian character handling is documented."""
        for char in ["æ", "ø", "å", "Æ", "Ø", "Å"]:
            assert char in TRIPLETEX_API_REFERENCE, f"Missing Norwegian character: {char}"

    def test_documents_sandbox_empty_state(self):
        """Documents that sandbox starts empty."""
        assert "sandbox starts EMPTY" in TRIPLETEX_API_REFERENCE

    def test_documents_placeholder_syntax(self):
        """Placeholder syntax for inter-step references is documented."""
        assert "$stepN.value.id" in TRIPLETEX_API_REFERENCE

    def test_documents_efficiency_guidelines(self):
        """Efficiency optimization guidelines are documented."""
        assert "Minimize API calls" in TRIPLETEX_API_REFERENCE
        assert "reuse IDs" in TRIPLETEX_API_REFERENCE

"""Tuning tests for department creation workflows.

Covers Recipe A (DEPARTMENT) from agent.py system prompt.
Recipe A uses POST /v2/department/list with array body for batch creation.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


@skip_no_vertex
class TestDepartment:
    """Agent should create departments with minimal calls."""

    def test_create_department_norwegian(self, run_agent):
        """Create a single department in Norwegian."""
        mock = MockTripletexClient()

        prompt = (
            "Opprett en avdeling med navn 'Økonomi' og avdelingsnummer 300."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        # Recipe A uses /v2/department/list with array body
        post_call = result.assert_endpoint_called("POST", "/v2/department")
        assert post_call.body is not None

        # Body can be a list (batch) or dict (single)
        if isinstance(post_call.body, list):
            assert len(post_call.body) >= 1
            dept = post_call.body[0]
        else:
            dept = post_call.body

        assert dept.get("name") == "Økonomi"
        assert str(dept.get("departmentNumber")) == "300"

        result.assert_no_errors()
        result.assert_max_calls(2)

    def test_create_multiple_departments_english(self, run_agent):
        """Create two departments in English using batch endpoint."""
        mock = MockTripletexClient()

        prompt = (
            "Create two departments: 'Sales' with number 100 and 'Engineering' with number 200."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        # Agent should use /v2/department/list with both departments in one call
        post_call = result.assert_endpoint_called("POST", "/v2/department")
        assert post_call.body is not None

        # Body should be a list with both departments
        if isinstance(post_call.body, list):
            assert len(post_call.body) >= 2, f"Expected 2 departments in batch, got {len(post_call.body)}"
        else:
            # Fallback: multiple separate POSTs
            dept_posts = result.find_calls("POST", "/v2/department")
            assert len(dept_posts) >= 2, f"Expected 2 department POSTs, got {len(dept_posts)}"

        result.assert_no_errors()
        result.assert_max_calls(3)

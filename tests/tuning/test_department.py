"""Tuning tests for department creation workflows.

Covers Recipe A (DEPARTMENT) from agent.py system prompt.
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

        post_call = result.assert_endpoint_called("POST", "/v2/department")
        assert post_call.body is not None
        assert post_call.body.get("name") == "Økonomi"
        assert post_call.body.get("departmentNumber") == 300 or str(post_call.body.get("departmentNumber")) == "300"

        result.assert_no_errors()
        result.assert_max_calls(2)

    def test_create_multiple_departments_english(self, run_agent):
        """Create two departments in English."""
        mock = MockTripletexClient()

        prompt = (
            "Create two departments: 'Sales' with number 100 and 'Engineering' with number 200."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        dept_posts = result.find_calls("POST", "/v2/department")
        assert len(dept_posts) >= 2, f"Expected 2 department POSTs, got {len(dept_posts)}"

        result.assert_no_errors()
        result.assert_max_calls(3)

"""Tuning tests for employee creation workflows.

Covers Recipe B (EMPLOYEE) from agent.py system prompt.
"""

import pytest

from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient


def _make_employee_mock() -> MockTripletexClient:
    """Set up mock with a department for employee creation."""
    mock = MockTripletexClient()

    mock.register_entity("department", {
        "id": 1,
        "name": "Administrasjon",
        "departmentNumber": "1",
    })

    return mock


@skip_no_vertex
class TestEmployee:
    """Agent should create employees with correct fields."""

    def test_create_employee_german(self, run_agent):
        """Create employee in German."""
        mock = _make_employee_mock()

        prompt = (
            "Erstellen Sie einen Mitarbeiter: Max Weber, E-Mail max.weber@example.org, "
            "Geburtsdatum 1985-07-22."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("GET", "/v2/department")
        post_call = result.assert_endpoint_called("POST", "/v2/employee")
        assert post_call.body is not None
        assert post_call.body.get("firstName") == "Max"
        assert post_call.body.get("lastName") == "Weber"
        assert post_call.body.get("email") == "max.weber@example.org"

        result.assert_no_errors()
        result.assert_max_calls(3)

    def test_create_employee_with_employment_spanish(self, run_agent):
        """Create employee + employment in Spanish."""
        mock = _make_employee_mock()

        prompt = (
            "Cree un empleado: Ana García, correo electrónico ana.garcia@example.org, "
            "fecha de nacimiento 1992-03-10. Fecha de inicio del empleo: 2026-04-01."
        )

        result = run_agent(prompt, mock)
        result.print_summary()

        result.assert_endpoint_called("GET", "/v2/department")
        result.assert_endpoint_called("POST", "/v2/employee")
        result.assert_endpoint_called("POST", "/v2/employee/employment")

        result.assert_no_errors()
        result.assert_max_calls(4)

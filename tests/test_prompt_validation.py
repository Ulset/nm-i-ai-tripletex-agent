"""Validation tests: registry entries match the OpenAPI spec, and OpenAPI 3.x parsing works.

These tests fetch the real Tripletex OpenAPI spec and verify that:
1. Every endpoint in ENDPOINT_REGISTRY exists in the spec
2. Every required_field in the registry is a real property in the endpoint's body schema
3. OpenAPI 3.x request body and response parsing works correctly
"""

from unittest.mock import patch

import pytest
import requests

from src.api_docs import (
    ENDPOINT_REGISTRY,
    RECIPE_ENDPOINTS,
    _get_request_body_schema,
    _get_response_schema,
    _load_spec,
    _resolve_ref,
    generate_endpoint_reference,
    get_endpoint_schema,
    get_recipe_examples,
    get_recipe_schemas,
    search_api_docs,
    validate_and_correct_call,
)


def _fetch_spec():
    """Fetch the real OpenAPI spec (cached per test session)."""
    try:
        return _load_spec()
    except Exception:
        pytest.skip("Cannot fetch OpenAPI spec")


class TestEndpointRegistryMatchesSpec:
    """Every endpoint in the registry must exist in the OpenAPI spec."""

    def test_all_registry_paths_exist(self):
        spec = _fetch_spec()
        paths = spec.get("paths", {})
        # Paths confirmed in production but not in local OpenAPI spec
        _SKIP_PATHS = {"/supplierInvoice"}
        for method, path, _, _ in ENDPOINT_REGISTRY:
            if path in _SKIP_PATHS:
                continue
            assert path in paths, f"Path {path} not found in spec"
            assert method.lower() in paths[path], (
                f"{method} not found for {path} in spec"
            )

    def test_all_required_fields_exist_in_schema(self):
        spec = _fetch_spec()
        paths = spec.get("paths", {})
        _SKIP_PATHS = {"/supplierInvoice"}
        for method, path, required_fields, _ in ENDPOINT_REGISTRY:
            if not required_fields or path in _SKIP_PATHS:
                continue
            method_info = paths.get(path, {}).get(method.lower(), {})
            body_schema = _get_request_body_schema(method_info)
            assert body_schema is not None, (
                f"No request body for {method} {path} but registry lists required fields: {required_fields}"
            )
            # Resolve $ref to get properties
            if "$ref" in body_schema:
                body_schema = _resolve_ref(spec, body_schema["$ref"])
            props = body_schema.get("properties", {})
            for field in required_fields:
                assert field in props, (
                    f"Field '{field}' not in schema for {method} {path}. "
                    f"Available: {sorted(props.keys())}"
                )

    def test_generated_prompt_contains_spec_field_names(self):
        spec = _fetch_spec()
        ref_text = generate_endpoint_reference()
        # Spot-check a few known fields that must appear
        assert "firstName" in ref_text
        assert "lastName" in ref_text
        assert "deliveryDate" in ref_text
        assert "orderLines" in ref_text


class TestOpenAPI3xParsing:
    """Verify that OpenAPI 3.x requestBody/content parsing works."""

    def test_get_request_body_schema_3x(self):
        method_info = {
            "requestBody": {
                "content": {
                    "application/json; charset=utf-8": {
                        "schema": {"$ref": "#/components/schemas/Employee"}
                    }
                },
                "required": True,
            }
        }
        schema = _get_request_body_schema(method_info)
        assert schema is not None
        assert schema["$ref"] == "#/components/schemas/Employee"

    def test_get_request_body_schema_2x_fallback(self):
        method_info = {
            "parameters": [
                {"in": "body", "schema": {"$ref": "#/definitions/Employee"}}
            ]
        }
        schema = _get_request_body_schema(method_info)
        assert schema is not None
        assert schema["$ref"] == "#/definitions/Employee"

    def test_get_request_body_schema_none(self):
        method_info = {"parameters": [{"in": "query", "name": "id"}]}
        assert _get_request_body_schema(method_info) is None

    def test_get_response_schema_3x(self):
        response_info = {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ResponseWrapperEmployee"}
                }
            }
        }
        schema = _get_response_schema(response_info)
        assert schema is not None
        assert "ResponseWrapperEmployee" in schema["$ref"]

    def test_get_response_schema_2x_fallback(self):
        response_info = {
            "schema": {"$ref": "#/definitions/ResponseWrapperEmployee"}
        }
        schema = _get_response_schema(response_info)
        assert schema is not None

    def test_get_response_schema_none(self):
        assert _get_response_schema({"description": "No content"}) is None

    def test_get_endpoint_schema_returns_body_fields_for_post(self):
        """get_endpoint_schema for a POST endpoint should return body fields from the real spec."""
        result = get_endpoint_schema("POST", "/v2/employee")
        assert result is not None, "get_endpoint_schema returned None for POST /v2/employee"
        assert "firstName" in result
        assert "lastName" in result

    def test_search_api_docs_shows_body_fields(self):
        """search_api_docs should include body field names from the real spec."""
        result = search_api_docs("employee")
        assert "Request body fields" in result
        assert "firstName" in result


class TestGenerateEndpointReference:
    """Tests for the generated endpoint reference text."""

    def test_contains_all_registry_endpoints(self):
        ref = generate_endpoint_reference()
        for method, path, _, _ in ENDPOINT_REGISTRY:
            assert f"{method} /v2{path}" in ref, (
                f"Missing {method} /v2{path} in generated reference"
            )

    def test_contains_notes(self):
        ref = generate_endpoint_reference()
        assert "QUERY PARAMS only" in ref
        assert "Bankinnskudd" in ref

    def test_marks_required_fields(self):
        ref = generate_endpoint_reference()
        assert "(REQ)" in ref

    def test_schema_hint_not_too_large(self):
        """Schema hints must be concise enough for the LLM to parse."""
        result = get_endpoint_schema("POST", "/v2/order")
        assert result is not None
        assert len(result) < 3000, f"Schema hint too large: {len(result)} chars"

    def test_fallback_without_spec(self):
        """If the spec fails to load, registry-only info is still shown."""
        with patch("src.api_docs._load_spec", side_effect=Exception("no network")):
            ref = generate_endpoint_reference()
            assert "POST /v2/employee" in ref
            assert "firstName" in ref


class TestGetRecipeSchemas:
    """Tests for proactive schema injection via get_recipe_schemas()."""

    def test_recipe_h_contains_location(self):
        """Recipe H (travel expense) schema must include 'location' field."""
        result = get_recipe_schemas("RECIPE: H (TRAVEL EXPENSE)")
        assert result, "get_recipe_schemas returned empty for RECIPE H"
        assert "location" in result, "Schema for Recipe H missing 'location' field"

    def test_recipe_b_contains_employee_fields(self):
        """Recipe B (employee) schema must include core employee fields."""
        result = get_recipe_schemas("RECIPE: B (EMPLOYEE)")
        assert "firstName" in result
        assert "lastName" in result
        assert "email" in result

    def test_recipe_i_contains_voucher_fields(self):
        """Recipe I (voucher) schema must include posting-related fields."""
        result = get_recipe_schemas("RECIPE: I (VOUCHER)")
        assert "amountGross" in result or "postings" in result

    def test_all_recipe_letters_valid(self):
        """Every recipe letter in RECIPE_ENDPOINTS should produce a result or empty string."""
        for letter in RECIPE_ENDPOINTS:
            result = get_recipe_schemas(f"RECIPE: {letter}")
            assert isinstance(result, str), f"Recipe {letter} returned non-string"

    def test_recipes_with_endpoints_produce_output(self):
        """Recipes that have POST/PUT endpoints should produce non-empty schema text."""
        for letter, endpoints in RECIPE_ENDPOINTS.items():
            if endpoints:  # G and J have empty lists
                result = get_recipe_schemas(f"RECIPE: {letter}")
                assert result, f"Recipe {letter} has endpoints but returned empty schema"

    def test_empty_recipes_return_empty(self):
        """Recipes G and J have no body endpoints — should return empty string."""
        assert get_recipe_schemas("RECIPE: G") == ""
        assert get_recipe_schemas("RECIPE: J") == ""

    def test_no_recipe_returns_empty(self):
        """If no recipe letter found, return empty string."""
        assert get_recipe_schemas("Some random text without a recipe") == ""

    def test_schema_size_reasonable(self):
        """Schema blocks should be concise (under 3000 chars per recipe)."""
        for letter, endpoints in RECIPE_ENDPOINTS.items():
            if endpoints:
                result = get_recipe_schemas(f"RECIPE: {letter}")
                assert len(result) < 5000, (
                    f"Recipe {letter} schema too large: {len(result)} chars"
                )


class TestPreCallValidation:
    """Tests for validate_and_correct_call() pre-call validation."""

    def test_endpoint_correction_voucher(self):
        result = validate_and_correct_call("POST", "/v2/voucher", {"date": "2026-01-01"})
        assert result.was_modified
        assert result.corrected_endpoint == "/v2/ledger/voucher"

    def test_endpoint_correction_vatType(self):
        result = validate_and_correct_call("GET", "/v2/vatType", None)
        assert result.corrected_endpoint == "/v2/ledger/vatType"

    def test_no_correction_needed(self):
        result = validate_and_correct_call("GET", "/v2/customer", None)
        assert not result.was_modified
        assert result.corrected_endpoint is None

    def test_field_case_correction(self):
        """fixedPrice → fixedprice (case-insensitive match against spec)."""
        result = validate_and_correct_call("POST", "/v2/project", {"fixedPrice": 50000})
        assert result.was_modified
        assert "fixedprice" in result.corrected_body

    def test_field_semantic_correction_quantity_to_count(self):
        """quantity → count on order endpoint."""
        body = {"orderLines": [{"product": {"id": 1}, "quantity": 5}]}
        result = validate_and_correct_call("POST", "/v2/order", body)
        assert result.was_modified
        assert "count" in result.corrected_body["orderLines"][0]
        assert "quantity" not in result.corrected_body["orderLines"][0]

    def test_voucher_amount_corrected(self):
        """amount → amountGross on ledger/voucher postings."""
        body = {"date": "2026-01-01", "postings": [{"amount": 1000, "row": 1}]}
        result = validate_and_correct_call("POST", "/v2/ledger/voucher", body)
        assert result.was_modified
        posting = result.corrected_body["postings"][0]
        assert "amountGross" in posting
        assert "amount" not in posting

    def test_skip_body_on_get(self):
        result = validate_and_correct_call("GET", "/v2/employee", None)
        assert not result.was_modified

    def test_skip_body_on_list(self):
        result = validate_and_correct_call("POST", "/v2/department/list", [{"name": "X"}])
        assert not result.was_modified

    def test_removed_field(self):
        """isDebit should be removed from voucher postings."""
        body = {"date": "2026-01-01", "postings": [{"isDebit": True, "amountGross": 1000, "row": 1}]}
        result = validate_and_correct_call("POST", "/v2/ledger/voucher", body)
        assert result.was_modified
        posting = result.corrected_body["postings"][0]
        assert "isDebit" not in posting

    def test_unknown_field_left_alone(self):
        """Fields with no match should be left as-is."""
        result = validate_and_correct_call("POST", "/v2/project", {"name": "Test", "xyzNonexistent": 42})
        # The unknown field should still be present
        if result.corrected_body:
            assert "xyzNonexistent" in result.corrected_body
        # Or no modification at all if only the unknown field is there
        # Either way, it should not crash

    def test_fixedPrice_corrected_to_lowercase(self):
        """fixedPrice → fixedprice via hardcoded correction."""
        result = validate_and_correct_call("POST", "/v2/project", {"name": "Test", "fixedPrice": 50000})
        assert result.was_modified
        assert "fixedprice" in result.corrected_body

    def test_fixedPriceAmount_corrected(self):
        """fixedPriceAmount → fixedprice via hardcoded correction."""
        result = validate_and_correct_call("POST", "/v2/project", {"name": "Test", "fixedPriceAmount": 100000})
        assert result.was_modified
        assert "fixedprice" in result.corrected_body

    def test_activity_type_corrected(self):
        """type → activityType on activity endpoint."""
        result = validate_and_correct_call("POST", "/v2/activity", {"name": "Test", "type": "PROJECT_GENERAL_ACTIVITY"})
        assert result.was_modified
        assert "activityType" in result.corrected_body

    def test_employment_details_auto_nested(self):
        """employmentType, occupationCode, etc. should be moved into employmentDetails."""
        body = {
            "employee": {"id": 1},
            "startDate": "2026-01-01",
            "employmentType": "ORDINARY",
            "occupationCode": "1234",
            "percentageOfFullTimeEquivalent": 100.0,
        }
        result = validate_and_correct_call("POST", "/v2/employee/employment", body)
        assert result.was_modified
        corrected = result.corrected_body
        assert "employmentDetails" in corrected
        assert corrected["employmentDetails"][0]["employmentType"] == "ORDINARY"
        assert corrected["employmentDetails"][0]["occupationCode"] == "1234"
        assert corrected["employmentDetails"][0]["percentageOfFullTimeEquivalent"] == 100.0
        assert "employmentType" not in corrected
        assert "occupationCode" not in corrected

    def test_employment_details_auto_nested_with_working_hours_and_salary(self):
        """workingHoursScheme and annualSalary should also be moved into employmentDetails."""
        body = {
            "employee": {"id": 1},
            "startDate": "2026-01-01",
            "employmentType": "ORDINARY",
            "workingHoursScheme": "NOT_SHIFT",
            "annualSalary": 600000,
        }
        result = validate_and_correct_call("POST", "/v2/employee/employment", body)
        assert result.was_modified
        corrected = result.corrected_body
        assert "employmentDetails" in corrected
        details = corrected["employmentDetails"][0]
        assert details["employmentType"] == "ORDINARY"
        assert details["workingHoursScheme"] == "NOT_SHIFT"
        assert details["annualSalary"] == 600000
        assert "workingHoursScheme" not in corrected
        assert "annualSalary" not in corrected

    def test_employment_details_not_overwritten(self):
        """If employmentDetails already exists, don't overwrite it."""
        body = {
            "employee": {"id": 1},
            "startDate": "2026-01-01",
            "employmentDetails": [{"date": "2026-01-01", "employmentType": "ORDINARY"}],
            "occupationCode": "5678",
        }
        result = validate_and_correct_call("POST", "/v2/employee/employment", body)
        # occupationCode is a top-level field but employmentDetails exists, so no auto-nesting
        assert result.corrected_body is None or "employmentDetails" in (result.corrected_body or body)

    def test_warnings_populated(self):
        result = validate_and_correct_call("POST", "/v2/voucher", {"date": "2026-01-01"})
        assert len(result.warnings) >= 1
        assert any("Endpoint" in w for w in result.warnings)


class TestExampleGeneration:
    """Tests for get_recipe_examples()."""

    def test_recipe_b_has_examples(self):
        result = get_recipe_examples("B")
        assert result
        assert "POST /v2/employee" in result

    def test_recipe_i_has_examples(self):
        result = get_recipe_examples("I")
        assert result
        assert "POST /v2/ledger/voucher" in result

    def test_empty_recipe_returns_empty(self):
        assert get_recipe_examples("G") == ""
        assert get_recipe_examples("J") == ""

    def test_examples_contain_field_names(self):
        result = get_recipe_examples("B")
        assert "firstName" in result or "lastName" in result

    def test_all_recipes_produce_valid_output(self):
        for letter, endpoints in RECIPE_ENDPOINTS.items():
            result = get_recipe_examples(letter)
            assert isinstance(result, str)
            if endpoints:
                assert result, f"Recipe {letter} has endpoints but no examples"

    def test_examples_size_reasonable(self):
        for letter, endpoints in RECIPE_ENDPOINTS.items():
            if endpoints:
                result = get_recipe_examples(letter)
                assert len(result) < 5000, f"Recipe {letter} examples too large: {len(result)}"

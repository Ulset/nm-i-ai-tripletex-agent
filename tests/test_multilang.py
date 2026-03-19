import json
from unittest.mock import MagicMock, patch

import pytest

from src.models import ExecutionPlan
from src.plan_generator import PlanGenerator
from tests.fixtures.sample_prompts import SAMPLE_PROMPTS


def _make_openai_response(plan_dict: dict) -> MagicMock:
    choice = MagicMock()
    choice.message.content = json.dumps(plan_dict)
    response = MagicMock()
    response.choices = [choice]
    return response


def _employee_plan(first_name: str, last_name: str) -> dict:
    return {
        "steps": [
            {
                "step_number": 1,
                "action": "POST",
                "endpoint": "/v2/employee",
                "payload": {
                    "firstName": first_name,
                    "lastName": last_name,
                },
                "params": None,
                "description": f"Create employee {first_name} {last_name}",
            }
        ]
    }


@patch("src.plan_generator.OpenAI")
class TestMultiLanguagePrompts:
    """Verify PlanGenerator handles prompts in nb, en, and es with special characters."""

    def test_norwegian_bokmal_prompt(self, mock_openai_cls):
        sample = SAMPLE_PROMPTS["nb"]
        plan_data = _employee_plan(sample["expected_first_name"], sample["expected_last_name"])

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(plan_data)

        generator = PlanGenerator(openai_api_key="test-key")
        plan = generator.generate_plan(sample["prompt"])

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "POST"
        assert plan.steps[0].endpoint == "/v2/employee"
        # Verify special characters preserved
        assert plan.steps[0].payload["firstName"] == "Bjørn"
        assert plan.steps[0].payload["lastName"] == "Ødegård"

        # Verify prompt was passed to LLM
        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert "Bjørn" in user_msg
        assert "Ødegård" in user_msg

    def test_english_prompt(self, mock_openai_cls):
        sample = SAMPLE_PROMPTS["en"]
        plan_data = _employee_plan(sample["expected_first_name"], sample["expected_last_name"])

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(plan_data)

        generator = PlanGenerator(openai_api_key="test-key")
        plan = generator.generate_plan(sample["prompt"])

        assert isinstance(plan, ExecutionPlan)
        assert plan.steps[0].payload["firstName"] == "François"
        assert plan.steps[0].payload["lastName"] == "O'Brien"

    def test_spanish_prompt(self, mock_openai_cls):
        sample = SAMPLE_PROMPTS["es"]
        plan_data = _employee_plan(sample["expected_first_name"], sample["expected_last_name"])

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(plan_data)

        generator = PlanGenerator(openai_api_key="test-key")
        plan = generator.generate_plan(sample["prompt"])

        assert isinstance(plan, ExecutionPlan)
        assert plan.steps[0].payload["firstName"] == "José"
        assert plan.steps[0].payload["lastName"] == "Muñoz"

    def test_special_characters_preserved_in_all_languages(self, mock_openai_cls):
        """Verify special characters are preserved for every supported language."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        generator = PlanGenerator(openai_api_key="test-key")

        for lang, sample in SAMPLE_PROMPTS.items():
            plan_data = _employee_plan(
                sample["expected_first_name"], sample["expected_last_name"]
            )
            mock_client.chat.completions.create.return_value = _make_openai_response(
                plan_data
            )

            plan = generator.generate_plan(sample["prompt"])

            assert plan.steps[0].payload["firstName"] == sample["expected_first_name"], (
                f"firstName mismatch for {lang}"
            )
            assert plan.steps[0].payload["lastName"] == sample["expected_last_name"], (
                f"lastName mismatch for {lang}"
            )

    def test_sample_prompts_cover_all_languages(self, mock_openai_cls):
        """Verify the fixture contains all 7 required languages."""
        required = {"nb", "nn", "en", "es", "pt", "de", "fr"}
        assert set(SAMPLE_PROMPTS.keys()) == required

    def test_all_prompts_have_special_characters(self, mock_openai_cls):
        """Verify each prompt includes names with non-ASCII characters."""
        for lang, sample in SAMPLE_PROMPTS.items():
            name = sample["expected_first_name"] + sample["expected_last_name"]
            has_special = any(ord(c) > 127 for c in name)
            assert has_special, f"Language {lang} prompt missing special characters in name"

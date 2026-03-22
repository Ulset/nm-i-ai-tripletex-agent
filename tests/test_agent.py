from unittest.mock import MagicMock, patch

import pytest

from src.agent import TripletexAgent, CALL_API_TOOL, MAX_ITERATIONS, get_system_prompt
from src.tripletex_client import TripletexAPIError


def _make_text_response(content="Task complete"):
    """Create a mock OpenAI response with a text message (no tool calls)."""
    message = MagicMock()
    message.content = content
    message.tool_calls = None

    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


def _make_tool_call_response(method, endpoint, body=None, params=None, tool_call_id="call_1"):
    """Create a mock OpenAI response with a call_api tool call."""
    import json

    args = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    if params is not None:
        args["params"] = params

    tool_call = MagicMock()
    tool_call.id = tool_call_id
    tool_call.function.name = "call_api"
    tool_call.function.arguments = json.dumps(args)

    message = MagicMock()
    message.content = None
    message.tool_calls = [tool_call]

    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


class TestTripletexAgent:
    def setup_method(self):
        self.client = MagicMock()
        self.agent = TripletexAgent(
            model="google/gemini-2.5-flash",
            tripletex_client=self.client,
        )

    @patch("src.agent.get_openai_client")
    def test_loop_completes_on_text_response(self, mock_openai_cls):
        """Agent should stop when LLM responds with text (no tool calls)."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Done!")

        agent = TripletexAgent(
            model="google/gemini-2.5-flash",
            tripletex_client=self.client,
        )
        agent.solve("Create a customer named Acme")

        mock_openai.chat.completions.create.assert_called_once()
        self.client.get.assert_not_called()
        self.client.post.assert_not_called()

    @patch("src.agent.get_openai_client")
    def test_tool_call_executed_and_result_sent_back(self, mock_openai_cls):
        """Agent should execute tool calls and return result to LLM."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        # First call: LLM makes a tool call, second call: LLM says done
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/customer", body={"name": "Acme"}),
            _make_text_response("Created customer Acme"),
        ]
        self.client.post.return_value = {"value": {"id": 1, "name": "Acme"}}

        agent = TripletexAgent(
            model="google/gemini-2.5-flash",
            tripletex_client=self.client,
        )
        agent.solve("Create a customer named Acme")

        self.client.post.assert_called_once_with("/v2/customer", json={"name": "Acme"})
        assert mock_openai.chat.completions.create.call_count == 2

    @patch("src.agent.get_openai_client")
    def test_max_iterations_stops_loop(self, mock_openai_cls):
        """Agent should stop after MAX_ITERATIONS even if LLM keeps making tool calls."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        # Always return a tool call — agent should still stop at MAX_ITERATIONS
        mock_openai.chat.completions.create.return_value = _make_tool_call_response(
            "GET", "/v2/customer", params={"name": "Acme"}
        )
        self.client.get.return_value = {"values": []}

        agent = TripletexAgent(
            model="google/gemini-2.5-flash",
            tripletex_client=self.client,
        )
        agent.solve("Find customer Acme")

        assert mock_openai.chat.completions.create.call_count == MAX_ITERATIONS
        assert self.client.get.call_count == MAX_ITERATIONS

    @patch("src.agent.get_openai_client")
    def test_api_error_returned_to_llm(self, mock_openai_cls):
        """API errors should be sent back to LLM as tool results so it can adapt."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        # First call: tool call that will fail, second call: LLM gives up
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/employee", body={"firstName": "Ola"}),
            _make_text_response("Could not create employee"),
        ]
        self.client.post.side_effect = TripletexAPIError(422, "Missing required field: lastName")

        agent = TripletexAgent(
            model="google/gemini-2.5-flash",
            tripletex_client=self.client,
        )
        agent.solve("Create an employee named Ola")

        assert mock_openai.chat.completions.create.call_count == 2
        # Verify the error was appended as a tool result
        second_call_messages = mock_openai.chat.completions.create.call_args_list[1].kwargs.get(
            "messages", mock_openai.chat.completions.create.call_args_list[1][1].get("messages", [])
            if len(mock_openai.chat.completions.create.call_args_list[1]) > 1 else []
        )
        if not second_call_messages:
            second_call_messages = mock_openai.chat.completions.create.call_args_list[1].kwargs["messages"]
        tool_results = [m for m in second_call_messages if isinstance(m, dict) and m.get("role") == "tool"]
        assert len(tool_results) == 1
        assert "error" in tool_results[0]["content"]

    @patch("src.agent.get_openai_client")
    def test_file_contents_included_in_prompt(self, mock_openai_cls):
        """File contents should be appended to the user message."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Done")

        file_contents = [{"filename": "invoice.pdf", "extracted_text": "Invoice #123"}]

        agent = TripletexAgent(
            model="google/gemini-2.5-flash",
            tripletex_client=self.client,
            file_contents=file_contents,
        )
        agent.solve("Process this invoice")

        call_args = mock_openai.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
        user_msg = [m for m in messages if m["role"] == "user"][0]
        assert "invoice.pdf" in user_msg["content"]
        assert "Invoice #123" in user_msg["content"]

    @patch("src.agent.get_openai_client")
    def test_get_call_uses_params(self, mock_openai_cls):
        """GET calls should pass params to TripletexClient.get()."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("GET", "/v2/department", params={"fields": "id", "count": "1"}),
            _make_text_response("Found department"),
        ]
        self.client.get.return_value = {"values": [{"id": 5}]}

        agent = TripletexAgent(
            model="google/gemini-2.5-flash",
            tripletex_client=self.client,
        )
        agent.solve("Look up departments")

        self.client.get.assert_called_once_with("/v2/department", params={"fields": "id", "count": "1"})

    @patch("src.agent.get_openai_client")
    def test_delete_call(self, mock_openai_cls):
        """DELETE calls should use TripletexClient.delete()."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("DELETE", "/v2/travelExpense/42"),
            _make_text_response("Deleted"),
        ]
        self.client.delete.return_value = {}

        agent = TripletexAgent(
            model="google/gemini-2.5-flash",
            tripletex_client=self.client,
        )
        agent.solve("Delete travel expense 42")

        self.client.delete.assert_called_once_with("/v2/travelExpense/42")

    def test_call_api_tool_schema(self):
        """Verify the call_api tool definition has correct schema."""
        assert CALL_API_TOOL["type"] == "function"
        func = CALL_API_TOOL["function"]
        assert func["name"] == "call_api"
        props = func["parameters"]["properties"]
        assert "method" in props
        assert "endpoint" in props
        assert "body" in props
        assert "params" in props
        assert set(func["parameters"]["required"]) == {"method", "endpoint"}


class TestSystemPrompt:
    """Tests for system prompt content verification."""

    def _full_prompt(self):
        return get_system_prompt()  # Fallback: all recipes

    def _focused_prompt(self, letter):
        return get_system_prompt(letter)

    def test_instructs_search_docs(self):
        p = self._full_prompt().lower()
        assert "search_api_docs" in p or "search docs" in p

    def test_instructs_include_all_data(self):
        p = self._full_prompt()
        assert "every value" in p.lower() or "every field" in p.lower() or "all data" in p.lower()

    def test_instructs_use_call_api_tool(self):
        p = self._full_prompt()
        assert "call_api" in p or "API call" in p or "API calls" in p

    def test_instructs_text_response_when_done(self):
        p = self._full_prompt().lower()
        assert "text message" in p or "no tool call" in p or "mutation call" in p

    def test_documents_response_shapes(self):
        p = self._full_prompt()
        assert "values" in p
        assert "value" in p

    def test_includes_efficiency_guidelines(self):
        p = self._full_prompt()
        assert "Reuse" in p or "reuse" in p or "NEVER GET after" in p

    def test_handles_all_seven_languages(self):
        from src.agent import _PRE_PARSE_PROMPT
        # Language handling is in the pre-parse prompt, not the system prompt
        assert "nb" in _PRE_PARSE_PROMPT and "en" in _PRE_PARSE_PROMPT and "es" in _PRE_PARSE_PROMPT

    def test_preserves_norwegian_characters(self):
        p = self._full_prompt()
        assert "æ" in p
        assert "ø" in p
        assert "å" in p

    # --- Dynamic focused prompt tests ---

    def test_focused_prompt_contains_only_matched_recipe(self):
        p = self._focused_prompt('I')
        assert "VOUCHER" in p
        assert "## Recipe: DEPARTMENT" not in p
        assert "## Recipe: EMPLOYEE" not in p
        assert "## Recipe: CUSTOMER" not in p

    def test_focused_prompt_contains_row_for_voucher(self):
        """Regression: the exact production failure that motivated this design."""
        p = self._focused_prompt('I')
        assert "row" in p

    def test_focused_prompt_contains_schema(self):
        p = self._focused_prompt('I')
        assert "API fields" in p or "postings" in p

    def test_focused_prompt_contains_core_rules(self):
        p = self._focused_prompt('A')
        assert "every value" in p.lower() or "every field" in p.lower()
        assert "Reuse" in p or "reuse" in p

    def test_focused_prompt_contains_action(self):
        p = self._focused_prompt('A')
        assert "API call" in p or "api call" in p.lower() or "first API call" in p

    def test_fallback_contains_all_recipes(self):
        p = get_system_prompt(None)
        assert "DEPARTMENT" in p
        assert "VOUCHER" in p
        assert "PAYROLL" in p

    def test_unknown_letter_falls_back(self):
        p = get_system_prompt('Z')
        assert "DEPARTMENT" in p  # All recipes present

    def test_all_recipe_letters_produce_focused_prompt(self):
        from src.agent import _RECIPES
        for letter in _RECIPES:
            p = self._focused_prompt(letter)
            assert "Rules" in p, f"Recipe {letter} missing core rules"
            assert "Action" in p, f"Recipe {letter} missing action block"


class TestAgentLogging:
    """Tests for US-005: Comprehensive logging verification."""

    @patch("src.agent.get_openai_client")
    def test_logs_iteration_number(self, mock_openai_cls):
        from src.agent import TripletexAgent

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Done")

        agent = TripletexAgent(model="m", tripletex_client=MagicMock())
        with patch("src.agent.logger") as mock_logger:
            agent.solve("test")

        iteration_logs = [c for c in mock_logger.info.call_args_list if "iteration" in str(c).lower()]
        assert len(iteration_logs) >= 1
        # Verify the format args produce "1/15"
        call_args = iteration_logs[0]
        assert call_args[0][1] == 1  # iteration number
        assert call_args[0][2] == 25  # max iterations (MAX_ITERATIONS)

    @patch("src.agent.get_openai_client")
    def test_logs_tool_call_details(self, mock_openai_cls):
        from src.agent import TripletexAgent

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/customer", body={"name": "Acme"}),
            _make_text_response("Done"),
        ]

        client = MagicMock()
        client.post.return_value = {"value": {"id": 1}}
        agent = TripletexAgent(model="m", tripletex_client=client)
        with patch("src.agent.logger") as mock_logger:
            agent.solve("test")

        tool_logs = [str(c) for c in mock_logger.info.call_args_list if "Tool call" in str(c)]
        assert len(tool_logs) == 1
        assert "POST" in tool_logs[0]
        assert "/v2/customer" in tool_logs[0]

    @patch("src.agent.get_openai_client")
    def test_logs_api_response(self, mock_openai_cls):
        from src.agent import TripletexAgent

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/customer", body={"name": "Acme"}),
            _make_text_response("Done"),
        ]

        client = MagicMock()
        client.post.return_value = {"value": {"id": 1, "name": "Acme"}}
        agent = TripletexAgent(model="m", tripletex_client=client)
        with patch("src.agent.logger") as mock_logger:
            agent.solve("test")

        response_logs = [str(c) for c in mock_logger.info.call_args_list if "API response" in str(c)]
        assert len(response_logs) == 1

    @patch("src.agent.get_openai_client")
    def test_logs_api_error(self, mock_openai_cls):
        from src.agent import TripletexAgent

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/employee", body={"firstName": "Ola"}),
            _make_text_response("Failed"),
        ]

        client = MagicMock()
        client.post.side_effect = TripletexAPIError(422, "Missing field")
        agent = TripletexAgent(model="m", tripletex_client=client)
        with patch("src.agent.logger") as mock_logger:
            agent.solve("test")

        error_logs = [str(c) for c in mock_logger.warning.call_args_list if "API error" in str(c)]
        assert len(error_logs) == 1

    @patch("src.agent.get_openai_client")
    def test_logs_agent_done(self, mock_openai_cls):
        from src.agent import TripletexAgent

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Task complete!")

        agent = TripletexAgent(model="m", tripletex_client=MagicMock())
        with patch("src.agent.logger") as mock_logger:
            agent.solve("test")

        done_logs = [str(c) for c in mock_logger.info.call_args_list if "Agent done" in str(c)]
        assert len(done_logs) == 1
        assert "Task complete!" in done_logs[0]

    @patch("src.agent.get_openai_client")
    def test_logs_max_iterations_reached(self, mock_openai_cls):
        from src.agent import TripletexAgent

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_tool_call_response(
            "GET", "/v2/customer", params={"name": "loop"}
        )

        client = MagicMock()
        client.get.return_value = {"values": []}
        agent = TripletexAgent(model="m", tripletex_client=client)
        with patch("src.agent.logger") as mock_logger:
            agent.solve("test")

        warning_logs = [str(c) for c in mock_logger.warning.call_args_list if "Agent stopped" in str(c)]
        assert len(warning_logs) == 1

    @patch("src.agent.get_openai_client")
    def test_logs_summary_with_counts_and_duration(self, mock_openai_cls):
        from src.agent import TripletexAgent

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/customer", body={"name": "A"}),
            _make_text_response("Done"),
        ]

        client = MagicMock()
        client.post.return_value = {"value": {"id": 1}}
        agent = TripletexAgent(model="m", tripletex_client=client)
        with patch("src.agent.logger") as mock_logger:
            agent.solve("test")

        summary_logs = [str(c) for c in mock_logger.info.call_args_list if "Agent summary" in str(c)]
        assert len(summary_logs) == 1
        assert "api_calls=" in summary_logs[0]
        assert "errors=" in summary_logs[0]
        assert "duration=" in summary_logs[0]

"""Shared fixtures for unit and integration tests (not tuning tests)."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def skip_pre_parse(request):
    """Skip the pre-parse LLM call in unit/integration tests.

    Pre-parsing adds an extra openai.chat.completions.create() call that
    unit tests don't account for in their mock side_effect lists. Patching
    it to return None triggers the fallback (raw prompt) path.

    Tuning tests use the real LLM and need pre-parse enabled.
    """
    # Don't patch for tuning tests (they have the 'tuning' marker or are in tests/tuning/)
    if "tuning" in str(request.fspath):
        yield
        return

    with patch("src.agent.TripletexAgent._pre_parse", return_value=None):
        yield

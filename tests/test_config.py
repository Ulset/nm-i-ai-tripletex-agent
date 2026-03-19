import os
from unittest.mock import patch

from src.config import Settings


def test_settings_defaults():
    with patch.dict(os.environ, {}, clear=True):
        s = Settings()
        assert s.openai_api_key == ""
        assert s.openai_model == "gpt-4o"
        assert s.port == 8000
        assert s.api_key == ""


def test_settings_from_env():
    env = {
        "OPENAI_API_KEY": "test-key",
        "OPENAI_MODEL": "gpt-3.5-turbo",
        "PORT": "9000",
        "API_KEY": "secret",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
        assert s.openai_api_key == "test-key"
        assert s.openai_model == "gpt-3.5-turbo"
        assert s.port == 9000
        assert s.api_key == "secret"

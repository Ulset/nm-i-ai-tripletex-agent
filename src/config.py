from dataclasses import dataclass, field
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))


settings = Settings()

import os

from app.core.config import get_settings


def enable_tracing() -> None:
    """Turn on LangSmith tracing for the whole process.

    LangSmith's SDK reads its configuration from real process environment
    variables (LANGSMITH_TRACING, LANGSMITH_API_KEY, LANGSMITH_PROJECT),
    not from anything we pass it directly — but our own Settings only
    populates a Python object from .env, it never touches os.environ.
    Mirroring the values here, once at startup, is what makes the two
    actually connect. Must run before any traced call happens — called
    from app/main.py at import time, before any service module below it
    creates its OpenAI/Voyage client.
    """
    settings = get_settings()
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project

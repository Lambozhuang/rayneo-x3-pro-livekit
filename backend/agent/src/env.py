"""What both architectures read from backend/.env."""

import os


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Copy backend/.env.example to backend/.env and fill it in.")
    return value


def language() -> str:
    """The language the agent speaks, whatever it hears."""
    return os.environ.get("AGENT_LANGUAGE", "English")

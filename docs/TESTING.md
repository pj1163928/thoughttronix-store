# Testing

pytest + pytest-django; run with `uv run pytest`.

Shared fixtures live in the project-level `conftest.py` — plain fixtures,
no factory-boy. The suite must be green at every phase boundary.

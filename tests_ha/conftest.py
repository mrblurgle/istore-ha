"""Fixtures for tests that run against a real Home Assistant core.

Kept separate from tests/ because tests/conftest.py replaces the homeassistant
modules with mocks. Run with:

    pip install pytest-homeassistant-custom-component
    pytest tests_ha -o asyncio_mode=auto -o pythonpath=.
"""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield

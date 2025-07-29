import pytest
import asyncio
import os
from unittest.mock import patch

# Configure test environment
@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Setup test environment variables"""
    os.environ["ALIBABA_CLOUD_ACCESS_KEY_ID"] = "test_access_key"
    os.environ["ALIBABA_CLOUD_ACCESS_KEY_SECRET"] = "test_secret_key"
    os.environ["RUN_MODE"] = "test"

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(autouse=True)
def mock_env_vars():
    """Mock environment variables for all tests"""
    with patch.dict(os.environ, {
        "ALIBABA_CLOUD_ACCESS_KEY_ID": "test_access_key", 
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test_secret_key",
        "RUN_MODE": "test"
    }):
        yield
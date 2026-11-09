"""Global test isolation for cloud credentials, dotenv, and network access."""

from __future__ import annotations

import os

# Clear these before test modules import backend.main, whose module-level app
# constructs a CloudAdapter during collection.
os.environ.pop("CLOUD_API_KEY", None)
os.environ.pop("CLOUD_MODEL", None)

import dotenv
import httpx
import pytest


def _disable_dotenv_loading(*_args, **_kwargs):
    """Prevent python-dotenv from opening any .env file during tests."""

    return False


dotenv.load_dotenv = _disable_dotenv_loading

import backend.cloud_adapter as cloud_adapter

cloud_adapter.load_dotenv = _disable_dotenv_loading


def _deny_httpx_request(*_args, **_kwargs):
    raise RuntimeError("Real HTTPX network calls are disabled in tests")


@pytest.fixture(autouse=True)
def isolate_cloud_environment_and_network(monkeypatch):
    """Keep real credentials, dotenv files, and cloud network out of every test."""

    monkeypatch.delenv("CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("CLOUD_MODEL", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", _disable_dotenv_loading)
    monkeypatch.setattr(cloud_adapter, "load_dotenv", _disable_dotenv_loading)

    # Mocked-provider tests can replace the patched adapter-level method.
    monkeypatch.setattr(cloud_adapter.httpx, "post", _deny_httpx_request)
    for method_name in ("request", "get", "put", "patch", "delete", "head", "options"):
        monkeypatch.setattr(httpx, method_name, _deny_httpx_request)


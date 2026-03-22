"""Integration tests for the /chat API."""

from importlib import import_module

from fastapi.testclient import TestClient

from aetos.config import settings
from aetos.deep_agent import DeepAgentConfigurationError, DeepAgentExecutionError, DeepAgentInputError

api_app_module = import_module("aetos.api.app")
app = api_app_module.app


def test_chat_success(monkeypatch):
    async def fake_invoke(message: str) -> str:
        assert message == "hello"
        return "optimized"

    monkeypatch.setattr(api_app_module, "invoke_deep_agent", fake_invoke)
    monkeypatch.setattr(settings, "api_write_keys", "")
    monkeypatch.setattr(settings, "api_read_keys", "")
    monkeypatch.setattr(settings, "api_admin_keys", "")

    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == 200
    assert response.json() == {"reply": "optimized"}


def test_chat_rejects_bad_input(monkeypatch):
    async def fake_invoke(message: str) -> str:
        raise DeepAgentInputError("message must not be empty")

    monkeypatch.setattr(api_app_module, "invoke_deep_agent", fake_invoke)
    monkeypatch.setattr(settings, "api_write_keys", "")
    monkeypatch.setattr(settings, "api_read_keys", "")
    monkeypatch.setattr(settings, "api_admin_keys", "")

    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "message must not be empty"


def test_chat_maps_configuration_error(monkeypatch):
    async def fake_invoke(message: str) -> str:
        raise DeepAgentConfigurationError("missing config")

    monkeypatch.setattr(api_app_module, "invoke_deep_agent", fake_invoke)
    monkeypatch.setattr(settings, "api_write_keys", "")
    monkeypatch.setattr(settings, "api_read_keys", "")
    monkeypatch.setattr(settings, "api_admin_keys", "")

    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == 503
    assert response.json()["detail"] == "missing config"


def test_chat_maps_execution_error(monkeypatch):
    async def fake_invoke(message: str) -> str:
        raise DeepAgentExecutionError("llm failed")

    monkeypatch.setattr(api_app_module, "invoke_deep_agent", fake_invoke)
    monkeypatch.setattr(settings, "api_write_keys", "")
    monkeypatch.setattr(settings, "api_read_keys", "")
    monkeypatch.setattr(settings, "api_admin_keys", "")

    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == 502
    assert response.json()["detail"] == "llm failed"


def test_chat_requires_api_key_when_write_scope_enabled(monkeypatch):
    async def fake_invoke(message: str) -> str:
        return "optimized"

    monkeypatch.setattr(api_app_module, "invoke_deep_agent", fake_invoke)
    monkeypatch.setattr(settings, "api_write_keys", "write-key")
    monkeypatch.setattr(settings, "api_read_keys", "")
    monkeypatch.setattr(settings, "api_admin_keys", "")

    with TestClient(app) as client:
        denied = client.post("/chat", json={"message": "hello"})
        allowed = client.post("/chat", json={"message": "hello"}, headers={"x-api-key": "write-key"})

    assert denied.status_code == 401
    assert allowed.status_code == 200

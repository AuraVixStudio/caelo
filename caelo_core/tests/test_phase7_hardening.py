from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from caelo_core.routes.secrets import router as secrets_router
from caelo_core.routes.settings import SettingsPatch, put_settings
from caelo_core.runtime_secrets import RuntimeSecrets
from caelo_core.state import Backend
from oauth_manager import OAuthManager


def test_runtime_secrets_are_versioned_and_never_persist_themselves() -> None:
    store = RuntimeSecrets()
    imported = store.import_snapshot({
        "version": 1, "revision": 7, "xai_api_key": "x",
        "google_api_key": "g", "oauth_tokens": {"access_token": "a"},
    })
    assert imported["version"] == 2
    assert imported["openai_api_key"] == ""
    assert imported["revision"] == 7
    store.set_oauth_tokens({"access_token": "rotated"})
    assert store.snapshot()["revision"] == 8
    assert store.snapshot()["oauth_tokens"]["access_token"] == "rotated"
    store.set_openai_api_key("openai-secret")
    assert store.snapshot()["openai_api_key"] == "openai-secret"


def test_settings_route_strips_secrets_before_json_update() -> None:
    saved = []
    runtime = {}
    backend = SimpleNamespace(
        update_settings=lambda data: saved.append(dict(data)),
        set_api_key=lambda value: runtime.__setitem__("xai", value),
        set_google_api_key=lambda value: runtime.__setitem__("google", value),
        set_openai_api_key=lambda value: runtime.__setitem__("openai", value),
    )
    response = put_settings(SettingsPatch(
        api_key="x-secret", google_api_key="g-secret",
        openai_api_key="o-secret", chat_model="model"
    ), backend)
    assert response == {"ok": True}
    assert saved == [{"chat_model": "model"}]
    assert runtime == {
        "xai": "x-secret", "google": "g-secret", "openai": "o-secret",
    }


def test_xai_auth_resolver_reads_vault_not_legacy_settings(monkeypatch) -> None:
    backend = Backend.__new__(Backend)
    backend._runtime_secrets = RuntimeSecrets()
    backend._runtime_secrets.set_xai_api_key("vault-secret")
    backend.read_settings = lambda: {  # type: ignore[method-assign]
        "auth_source": "api_key",
        "api_key": "legacy-plaintext-must-not-be-used",
    }
    backend.oauth = SimpleNamespace(get_access_token=lambda: None)
    monkeypatch.setenv("XAI_API_KEY", "env-secret")

    assert backend._resolve_auth() == ("api_key", "vault-secret")

    backend._runtime_secrets.set_xai_api_key("")
    assert backend._resolve_auth() == ("env", "env-secret")


def test_secret_channel_rejects_public_token_and_accepts_private_token() -> None:
    runtime = RuntimeSecrets()
    backend = SimpleNamespace(
        import_secret_snapshot=runtime.import_snapshot,
        export_secret_snapshot=runtime.snapshot,
    )
    app = FastAPI()
    app.state.backend = backend
    app.state.secret_channel_token = "private-channel"
    app.include_router(secrets_router)
    client = TestClient(app)
    payload = {
        "version": 1, "revision": 2, "xai_api_key": "x",
        "google_api_key": "", "oauth_tokens": {},
    }
    assert client.post(
        "/internal/secrets/import", json=payload,
        headers={"Authorization": "Bearer public-session"},
    ).status_code == 401
    assert client.post(
        "/internal/secrets/import", json=payload,
        headers={"X-Caelo-Secret-Token": "private-channel"},
    ).status_code == 200
    exported = client.get(
        "/internal/secrets/export?since=1",
        headers={"X-Caelo-Secret-Token": "private-channel"},
    ).json()
    assert exported["changed"] is True
    assert exported["snapshot"]["xai_api_key"] == "x"


def test_sidecar_oauth_manager_notifies_memory_without_writing_plaintext(tmp_path) -> None:
    changes = []
    manager = OAuthManager(
        initial_tokens={}, on_tokens_changed=lambda value: changes.append(value),
        persist_file=False,
    )
    manager._store_token_response({"access_token": "secret", "refresh_token": "refresh"})
    assert changes[-1]["access_token"] == "secret"
    assert list(tmp_path.iterdir()) == []
    manager.logout()
    assert changes[-1] == {}

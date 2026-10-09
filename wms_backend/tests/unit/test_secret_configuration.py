"""Credential configuration tests use copied modules and synthetic keys only."""

from pathlib import Path
import runpy
import shutil

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_KEY = "environment-tests-only-jwt-signing-key"
FILE_KEY = "file-tests-only-jwt-signing-key"


def load_auth(tmp_path, monkeypatch, config=None, environment_key=None):
    source = tmp_path / "Auth.py"
    shutil.copyfile(BACKEND_ROOT / "Auth.py", source)
    if config is not None:
        (tmp_path / "env.toml").write_text(config, encoding="utf-8")
    if environment_key is None:
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET_KEY", environment_key)
    return runpy.run_path(str(source))


def test_environment_key_wins_without_reading_invalid_local_config(tmp_path, monkeypatch):
    auth = load_auth(tmp_path, monkeypatch, 'invalid TOML = [', ENV_KEY)
    assert auth["secret_key"] == ENV_KEY


@pytest.mark.parametrize("environment_key", [None, "", "   "])
def test_file_key_is_used_when_environment_is_unset_or_empty(tmp_path, monkeypatch, environment_key):
    auth = load_auth(tmp_path, monkeypatch, f'jwt_secret_key = "{FILE_KEY}"\n', environment_key)
    assert auth["secret_key"] == FILE_KEY


@pytest.mark.parametrize("config", [None, "", 'jwt_secret_key = ""\n', "jwt_secret_key = 123\n"])
def test_missing_or_invalid_key_fails_without_a_default(tmp_path, monkeypatch, config):
    with pytest.raises(RuntimeError, match="JWT signing key is not configured"):
        load_auth(tmp_path, monkeypatch, config)


def test_bad_local_configuration_error_does_not_echo_contents(tmp_path, monkeypatch):
    marker = "sensitive-config-content-must-not-be-shown"
    with pytest.raises(RuntimeError, match="Cannot read JWT configuration") as caught:
        load_auth(tmp_path, monkeypatch, f'jwt_secret_key = "{marker}')
    assert marker not in str(caught.value)


def test_jwt_round_trip_uses_configured_key_and_rejects_other_key(tmp_path, monkeypatch):
    auth = load_auth(tmp_path, monkeypatch, f'jwt_secret_key = "{FILE_KEY}"\n')
    token = auth["create_jwt"]({"user_id": 7, "role": "worker"})
    valid, payload = auth["verify_jwt"](token, FILE_KEY)
    assert valid
    assert payload["user_id"] == 7
    assert "exp" in payload
    assert not auth["verify_jwt"](token, ENV_KEY)[0]


@pytest.mark.parametrize("configured_token", ["", "tracking-tests-only-token"])
def test_tracking_has_no_builtin_token(tmp_path, monkeypatch, configured_token):
    (tmp_path / "env.toml").write_text(f'17track_token = "{configured_token}"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    tracking = runpy.run_path(str(BACKEND_ROOT / "utils" / "l7track.py"))
    assert tracking["token"] == configured_token
    assert tracking["headers"]["17token"] == configured_token

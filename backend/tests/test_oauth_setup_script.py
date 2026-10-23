"""Test dello script host `scripts/gdrive_oauth_setup.py` (T4, ADR-0035).

Nessuna rete, nessun browser: il flow OAuth e il client Drive sono sostituiti da finti.
Lo script si importa da percorso, indipendentemente dalla cwd.
"""

import importlib.util
import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gdrive_oauth_setup.py"

# Sentinella arbitraria: non e' un token reale, serve solo a verificare che non esca a terminale.
FAKE_TOKEN = "SENTINEL-FAKE-TOKEN-0xC0FFEE"
FOLDER_ID = "FAKE_FOLDER_ID_123"


def _load_script():
    spec = importlib.util.spec_from_file_location("gdrive_oauth_setup_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCreds:
    def __init__(self, refresh_token):
        self.refresh_token = refresh_token

    def to_json(self):
        return json.dumps({"kind": "fake-authorized-user", "sentinel": FAKE_TOKEN})


class FakeFlow:
    def __init__(self, creds):
        self._creds = creds
        self.run_kwargs = None

    def run_local_server(self, **kwargs):
        self.run_kwargs = kwargs
        return self._creds


@pytest.fixture
def script():
    return _load_script()


@pytest.fixture
def secrets_file(tmp_path):
    p = tmp_path / "client.json"
    p.write_text("{}", encoding="utf-8")
    return p


def _install_flow(monkeypatch, script, creds):
    flow = FakeFlow(creds)
    calls = {}

    def fake_build_flow(client_secrets_path, scopes):
        calls["client_secrets_path"] = client_secrets_path
        calls["scopes"] = scopes
        return flow

    monkeypatch.setattr(script, "build_flow", fake_build_flow)
    return flow, calls


def test_writes_file_with_to_json_content(script, monkeypatch, tmp_path, secrets_file):
    creds = FakeCreds(FAKE_TOKEN)
    _install_flow(monkeypatch, script, creds)
    out = tmp_path / "token.json"

    rc = script.main(["--client-secrets", str(secrets_file), "--out", str(out)])

    assert rc == 0
    assert out.read_text(encoding="utf-8") == creds.to_json()


@pytest.mark.skipif(os.name == "nt", reason="permessi POSIX indicativi su Windows")
def test_output_file_mode_is_0600(script, monkeypatch, tmp_path, secrets_file):
    _install_flow(monkeypatch, script, FakeCreds(FAKE_TOKEN))
    out = tmp_path / "token.json"

    script.main(["--client-secrets", str(secrets_file), "--out", str(out)])

    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_flow_called_with_expected_parameters(script, monkeypatch, tmp_path, secrets_file):
    flow, calls = _install_flow(monkeypatch, script, FakeCreds(FAKE_TOKEN))

    script.main(["--client-secrets", str(secrets_file), "--out", str(tmp_path / "t.json")])

    assert calls["scopes"] == ["https://www.googleapis.com/auth/drive.file"]
    assert calls["client_secrets_path"] == str(secrets_file)
    assert flow.run_kwargs == {
        "host": "127.0.0.1",
        "port": 0,
        "access_type": "offline",
        "prompt": "consent",
    }


def test_refuses_existing_out_without_force(script, monkeypatch, tmp_path, secrets_file, capsys):
    flow, _ = _install_flow(monkeypatch, script, FakeCreds(FAKE_TOKEN))
    out = tmp_path / "token.json"
    out.write_text("ORIGINAL", encoding="utf-8")

    rc = script.main(["--client-secrets", str(secrets_file), "--out", str(out)])

    assert rc != 0
    assert out.read_text(encoding="utf-8") == "ORIGINAL"
    # Il rifiuto avviene prima di aprire il browser.
    assert flow.run_kwargs is None
    captured = capsys.readouterr()
    assert str(tmp_path) not in captured.out + captured.err


def test_force_overwrites_and_truncates(script, monkeypatch, tmp_path, secrets_file):
    creds = FakeCreds(FAKE_TOKEN)
    _install_flow(monkeypatch, script, creds)
    out = tmp_path / "token.json"
    out.write_text("X" * 5000, encoding="utf-8")

    rc = script.main(["--client-secrets", str(secrets_file), "--out", str(out), "--force"])

    assert rc == 0
    assert out.read_text(encoding="utf-8") == creds.to_json()


@pytest.mark.skipif(os.name == "nt", reason="permessi POSIX indicativi su Windows")
def test_force_on_permissive_existing_file_ends_with_0600(
    script, monkeypatch, tmp_path, secrets_file
):
    creds = FakeCreds(FAKE_TOKEN)
    _install_flow(monkeypatch, script, creds)
    out = tmp_path / "token.json"
    out.write_text("OLD", encoding="utf-8")
    os.chmod(out, 0o644)

    rc = script.main(["--client-secrets", str(secrets_file), "--out", str(out), "--force"])

    assert rc == 0
    assert out.read_text(encoding="utf-8") == creds.to_json()
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def _failing_fdopen(*_args, **_kwargs):
    raise OSError(f"disco pieno con {FAKE_TOKEN}")


def _failing_replace(*_args, **_kwargs):
    raise OSError(f"replace fallita con {FAKE_TOKEN}")


def test_write_error_without_force_leaves_nothing(
    script, monkeypatch, tmp_path, secrets_file, capsys
):
    _install_flow(monkeypatch, script, FakeCreds(FAKE_TOKEN))
    out_dir = tmp_path / "outdir"
    out_dir.mkdir()
    out = out_dir / "token.json"
    monkeypatch.setattr(os, "fdopen", _failing_fdopen)

    rc = script.main(["--client-secrets", str(secrets_file), "--out", str(out)])

    assert rc != 0
    assert os.listdir(out_dir) == []
    captured = capsys.readouterr()
    assert FAKE_TOKEN not in captured.out + captured.err
    assert str(tmp_path) not in captured.out + captured.err


@pytest.mark.parametrize("failure", ["fdopen", "replace"])
def test_write_error_with_force_preserves_old_file(
    script, monkeypatch, tmp_path, secrets_file, capsys, failure
):
    _install_flow(monkeypatch, script, FakeCreds(FAKE_TOKEN))
    out_dir = tmp_path / "outdir"
    out_dir.mkdir()
    out = out_dir / "token.json"
    out.write_text("OLD-CONTENT", encoding="utf-8")
    if failure == "fdopen":
        monkeypatch.setattr(os, "fdopen", _failing_fdopen)
    else:
        monkeypatch.setattr(os, "replace", _failing_replace)

    rc = script.main(["--client-secrets", str(secrets_file), "--out", str(out), "--force"])

    assert rc != 0
    assert out.read_text(encoding="utf-8") == "OLD-CONTENT"
    assert os.listdir(out_dir) == ["token.json"]
    captured = capsys.readouterr()
    assert FAKE_TOKEN not in captured.out + captured.err
    assert str(tmp_path) not in captured.out + captured.err


def test_success_leaves_no_temporary_files(script, monkeypatch, tmp_path, secrets_file):
    _install_flow(monkeypatch, script, FakeCreds(FAKE_TOKEN))
    out_dir = tmp_path / "outdir"
    out_dir.mkdir()
    out = out_dir / "token.json"
    out.write_text("OLD", encoding="utf-8")

    rc = script.main(["--client-secrets", str(secrets_file), "--out", str(out), "--force"])

    assert rc == 0
    assert os.listdir(out_dir) == ["token.json"]


@pytest.mark.parametrize("missing", [None, ""])
def test_missing_refresh_token_fails_and_writes_nothing(
    script, monkeypatch, tmp_path, secrets_file, capsys, missing
):
    _install_flow(monkeypatch, script, FakeCreds(missing))
    out = tmp_path / "token.json"

    rc = script.main(["--client-secrets", str(secrets_file), "--out", str(out)])

    assert rc != 0
    assert not out.exists()
    captured = capsys.readouterr()
    assert FAKE_TOKEN not in captured.out + captured.err
    assert captured.err.strip() != ""


def test_create_folder_calls_drive_and_prints_only_id(
    script, monkeypatch, tmp_path, secrets_file, capsys
):
    creds = FakeCreds(FAKE_TOKEN)
    _install_flow(monkeypatch, script, creds)
    service = MagicMock()
    service.files.return_value.create.return_value.execute.return_value = {"id": FOLDER_ID}
    seen = {}

    def fake_build_drive_service(c):
        seen["creds"] = c
        return service

    monkeypatch.setattr(script, "build_drive_service", fake_build_drive_service)
    out = tmp_path / "token.json"

    rc = script.main(
        [
            "--client-secrets", str(secrets_file),
            "--out", str(out),
            "--create-folder", "Portfolio Backup",
        ]
    )

    assert rc == 0
    assert seen["creds"] is creds
    service.files.return_value.create.assert_called_once_with(
        body={
            "name": "Portfolio Backup",
            "mimeType": "application/vnd.google-apps.folder",
        },
        fields="id",
    )
    captured = capsys.readouterr()
    assert FOLDER_ID in captured.out
    assert FAKE_TOKEN not in captured.out + captured.err
    assert str(tmp_path) not in captured.out + captured.err


def test_no_create_folder_does_not_touch_drive(script, monkeypatch, tmp_path, secrets_file):
    _install_flow(monkeypatch, script, FakeCreds(FAKE_TOKEN))

    def boom(_creds):
        raise AssertionError("Drive non deve essere contattato senza --create-folder")

    monkeypatch.setattr(script, "build_drive_service", boom)

    rc = script.main(["--client-secrets", str(secrets_file), "--out", str(tmp_path / "t.json")])

    assert rc == 0


def test_create_folder_failure_keeps_token_file_and_hides_details(
    script, monkeypatch, tmp_path, secrets_file, capsys
):
    creds = FakeCreds(FAKE_TOKEN)
    _install_flow(monkeypatch, script, creds)

    def failing_service(_creds):
        raise RuntimeError(f"dettaglio con {FAKE_TOKEN} e {tmp_path}")

    monkeypatch.setattr(script, "build_drive_service", failing_service)
    out = tmp_path / "token.json"

    rc = script.main(
        ["--client-secrets", str(secrets_file), "--out", str(out), "--create-folder", "X"]
    )

    assert rc != 0
    # Il token e' gia' stato salvato: non va perso per un errore sulla cartella.
    assert out.read_text(encoding="utf-8") == creds.to_json()
    captured = capsys.readouterr()
    assert FAKE_TOKEN not in captured.out + captured.err
    assert str(tmp_path) not in captured.out + captured.err


def test_stdout_stderr_never_contain_token_on_success(
    script, monkeypatch, tmp_path, secrets_file, capsys
):
    _install_flow(monkeypatch, script, FakeCreds(FAKE_TOKEN))

    script.main(["--client-secrets", str(secrets_file), "--out", str(tmp_path / "t.json")])

    captured = capsys.readouterr()
    assert FAKE_TOKEN not in captured.out + captured.err
    assert str(tmp_path) not in captured.out + captured.err


def test_flow_failure_is_generic_and_exits_nonzero(
    script, monkeypatch, tmp_path, secrets_file, capsys
):
    def failing_build_flow(client_secrets_path, scopes):
        raise FileNotFoundError(client_secrets_path)

    monkeypatch.setattr(script, "build_flow", failing_build_flow)
    out = tmp_path / "token.json"

    rc = script.main(["--client-secrets", str(secrets_file), "--out", str(out)])

    assert rc != 0
    assert not out.exists()
    captured = capsys.readouterr()
    assert str(tmp_path) not in captured.out + captured.err


def test_help_mentions_windows_permissions_and_force(script, capsys):
    with pytest.raises(SystemExit) as exc:
        script.main(["--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "Windows" in text
    assert "--force" in text
    assert "--create-folder" in text


def test_script_does_not_read_env_or_define_default_paths(script):
    src = SCRIPT.read_text(encoding="utf-8")
    assert ".env" not in src
    assert "secrets/" not in src
    assert "environ" not in src

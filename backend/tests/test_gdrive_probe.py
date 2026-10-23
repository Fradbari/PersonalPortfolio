import dataclasses
import json
import socket

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from app import drive
from app.backup import BACKUP_PREFIX
from app.config import settings
from app.drive import PROBE_PREFIX, classify_drive_error, get_drive_service, redact, run_gdrive_probe

FOLDER = "FOLDERSENTINEL123"
SA_NAME = "TOKENSENTINELPATH456.json"


def http_error(status, reason=None, folder=FOLDER, raw_content=None):
    errors = [{"reason": reason, "message": f"File not found: {folder}."}] if reason else []
    content = raw_content or json.dumps(
        {"error": {"code": status, "message": f"File not found: {folder}.", "errors": errors}}
    ).encode()
    uri = f"https://www.googleapis.com/drive/v3/files?q='{folder}'+in+parents"
    return HttpError(httplib2.Response({"status": str(status)}), content=content, uri=uri)


class _Exec:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeDrive:
    """Fake Drive v3: `fail` mappa operazione -> eccezione da sollevare."""

    def __init__(self, files=None, fail=None, corrupt_read=False):
        self.files_list = list(files or [])
        self.fail = fail or {}
        self.corrupt_read = corrupt_read
        self.calls: list[str] = []
        self.content: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def _maybe_fail(self, op):
        self.calls.append(op)
        if op in self.fail:
            raise self.fail[op]

    def files(self):
        return self

    def list(self, q=None, fields=None, orderBy=None):
        def run():
            self._maybe_fail("list")
            return {"files": list(self.files_list)}

        return _Exec(run)

    def create(self, body=None, media_body=None, fields=None):
        def run():
            self._maybe_fail("create")
            fid = "probe-id"
            self.content[fid] = media_body.getbytes(0, media_body.size())
            self.files_list.append({"id": fid, "name": body["name"]})
            return {"id": fid}

        return _Exec(run)

    def get_media(self, fileId=None):
        def run():
            self._maybe_fail("get_media")
            return b"altro" if self.corrupt_read else self.content[fileId]

        return _Exec(run)

    def delete(self, fileId=None):
        def run():
            self._maybe_fail("delete")
            self.deleted.append(fileId)
            return {}

        return _Exec(run)


@pytest.fixture
def sa_path(tmp_path, monkeypatch):
    path = tmp_path / SA_NAME
    path.write_text("{}")
    monkeypatch.setattr(settings, "gdrive_backup_folder_id", FOLDER)
    monkeypatch.setattr(settings, "google_oauth_token_path", str(path))
    monkeypatch.setattr(settings, "ai_api_key", "")
    return str(path)


def probe(monkeypatch, sa_path, fake, folder=FOLDER):
    monkeypatch.setattr(drive, "get_drive_service", lambda _p: fake)
    return run_gdrive_probe(sa_path, folder)


def assert_clean(res, sa_path):
    dumped = json.dumps(dataclasses.asdict(res))
    assert FOLDER not in dumped
    assert sa_path not in dumped and SA_NAME not in dumped


def test_ok(monkeypatch, sa_path):
    fake = FakeDrive()
    res = probe(monkeypatch, sa_path, fake)
    assert res.ok and res.outcome == "ok" and res.stage is None
    assert res.probe_written and res.probe_deleted and res.orphans_removed == 0
    assert fake.deleted == ["probe-id"]
    assert_clean(res, sa_path)


def test_auth_missing_empty_and_absent(monkeypatch, tmp_path):
    fake = FakeDrive()
    monkeypatch.setattr(drive, "get_drive_service", lambda _p: fake)
    for path in ("", str(tmp_path / "nope.json")):
        res = run_gdrive_probe(path, FOLDER)
        assert (res.outcome, res.stage) == ("auth_missing", "config")
    assert fake.calls == []


def test_auth_invalid_real_parse(monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("non json {")
    res = run_gdrive_probe(str(bad), FOLDER)
    assert (res.outcome, res.stage) == ("auth_invalid", "config")
    incomplete = tmp_path / "inc.json"
    incomplete.write_text("{}")
    assert run_gdrive_probe(str(incomplete), FOLDER).outcome == "auth_invalid"


@pytest.mark.parametrize("exc_type", [ValueError, KeyError, TypeError])
def test_loader_error_is_auth_invalid(monkeypatch, sa_path, caplog, exc_type):
    def loader(_path, _scopes=None):
        raise exc_type(f"boom {sa_path} {FOLDER}")

    monkeypatch.setattr(Credentials, "from_authorized_user_file", staticmethod(loader))
    with caplog.at_level("DEBUG"):
        res = run_gdrive_probe(sa_path, FOLDER)
    assert (res.outcome, res.stage) == ("auth_invalid", "config")
    assert_clean(res, sa_path)
    assert FOLDER not in caplog.text and sa_path not in caplog.text and SA_NAME not in caplog.text


def test_get_drive_service_uses_oauth_user_credentials(monkeypatch, sa_path):
    seen = {}
    sentinel_creds = object()

    def loader(path, scopes=None):
        seen["args"] = (path, scopes)
        return sentinel_creds

    class _Http:
        def __init__(self, credentials, http=None):
            seen["creds"] = credentials
            seen["timeout"] = http.timeout

    monkeypatch.setattr(Credentials, "from_authorized_user_file", staticmethod(loader))
    monkeypatch.setattr(drive, "AuthorizedHttp", _Http)
    monkeypatch.setattr(drive, "build", lambda *a, **k: ("service", a, k))
    out = get_drive_service(sa_path)
    assert seen["args"] == (sa_path, drive.DRIVE_SCOPES)
    assert seen["creds"] is sentinel_creds and seen["timeout"] == drive.DRIVE_TIMEOUT_SECONDS
    assert out[0] == "service"


def test_get_drive_service_none_for_empty_or_absent(tmp_path):
    assert get_drive_service("") is None
    assert get_drive_service(str(tmp_path / "nope.json")) is None


def test_folder_id_missing_zero_calls(monkeypatch, sa_path):
    fake = FakeDrive()
    res = probe(monkeypatch, sa_path, fake, folder="")
    assert (res.outcome, res.stage) == ("folder_id_missing", "config")
    assert fake.calls == [] and not res.probe_written


@pytest.mark.parametrize(
    "op,exc,outcome,stage",
    [
        ("list", RefreshError("x", {"error": "invalid_grant"}), "auth_expired", "cleanup"),
        ("list", RefreshError("x", {"error": "invalid_client"}), "auth_invalid", "cleanup"),
        ("list", RefreshError("invalid_grant"), "auth_invalid", "cleanup"),
        ("create", http_error(401, "authError"), "auth_expired", "write"),
        ("create", http_error(403, "insufficientPermissions"), "auth_invalid", "write"),
        ("create", http_error(403, "ACCESS_TOKEN_SCOPE_INSUFFICIENT"), "auth_invalid", "write"),
        ("list", http_error(404, "notFound"), "folder_not_found", "cleanup"),
        ("create", http_error(404, "notFound"), "folder_not_found", "write"),
        ("create", http_error(403, "insufficientFilePermissions"), "permission_denied", "write"),
        ("create", http_error(403, "storageQuotaExceeded"), "quota_exceeded", "write"),
        ("create", http_error(429, "rateLimitExceeded"), "quota_exceeded", "write"),
        ("create", socket.timeout("timed out"), "timeout", "write"),
        ("create", httplib2.ServerNotFoundError(f"Unable to find {FOLDER}"), "network_error", "write"),
        ("create", ConnectionError(FOLDER), "network_error", "write"),
        ("create", RuntimeError(FOLDER), "unexpected", "write"),
        ("create", PermissionError(FOLDER), "unexpected", "write"),
        ("get_media", http_error(404, "notFound"), "unexpected", "read"),
    ],
)
def test_error_outcomes_and_no_leak(monkeypatch, sa_path, caplog, op, exc, outcome, stage):
    fake = FakeDrive(fail={op: exc})
    with caplog.at_level("DEBUG"):
        res = probe(monkeypatch, sa_path, fake)
    assert (res.outcome, res.stage, res.ok) == (outcome, stage, False)
    assert_clean(res, sa_path)
    assert FOLDER not in caplog.text
    assert sa_path not in caplog.text and SA_NAME not in caplog.text


def test_get_drive_service_unexpected_error_is_redacted(monkeypatch, sa_path, caplog):
    def boom(_p):
        raise PermissionError(f"denied: {sa_path}")

    monkeypatch.setattr(drive, "get_drive_service", boom)
    with caplog.at_level("DEBUG"):
        res = run_gdrive_probe(sa_path, FOLDER)
    assert (res.outcome, res.stage) == ("unexpected", "config")
    assert_clean(res, sa_path)
    assert sa_path not in caplog.text and SA_NAME not in caplog.text


def test_get_drive_service_none_is_auth_missing(monkeypatch, sa_path):
    monkeypatch.setattr(drive, "get_drive_service", lambda _p: None)
    res = run_gdrive_probe(sa_path, FOLDER)
    assert (res.outcome, res.stage) == ("auth_missing", "config")


def test_auth_invalid_precedes_folder_id_missing(monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("non json {")
    assert run_gdrive_probe(str(bad), "").outcome == "auth_invalid"


def test_google_reason_with_folder_id_is_redacted(monkeypatch, sa_path):
    res = probe(monkeypatch, sa_path, FakeDrive(fail={"create": http_error(403, FOLDER)}))
    assert res.google_reason == "<gdrive_backup_folder_id>"
    assert_clean(res, sa_path)


def test_http_error_fields_structured(monkeypatch, sa_path):
    res = probe(monkeypatch, sa_path, FakeDrive(fail={"create": http_error(404, "notFound")}))
    assert (res.google_status, res.google_reason) == (404, "notFound")


def test_delete_404_after_ok_read_is_unexpected_delete(monkeypatch, sa_path):
    res = probe(monkeypatch, sa_path, FakeDrive(fail={"delete": http_error(404, "notFound")}))
    assert (res.outcome, res.stage) == ("unexpected", "delete")
    assert res.probe_written and not res.probe_deleted
    assert_clean(res, sa_path)


def test_delete_failure_after_ok_read_wins(monkeypatch, sa_path):
    res = probe(monkeypatch, sa_path, FakeDrive(fail={"delete": http_error(403, "forbidden")}))
    assert (res.outcome, res.stage) == ("permission_denied", "delete")


def test_read_fails_delete_still_attempted_read_outcome_wins(monkeypatch, sa_path):
    fake = FakeDrive(fail={"get_media": http_error(403, "forbidden")})
    res = probe(monkeypatch, sa_path, fake)
    assert (res.outcome, res.stage) == ("permission_denied", "read")
    assert fake.deleted == ["probe-id"] and res.probe_deleted


def test_read_then_delete_both_fail_read_wins(monkeypatch, sa_path):
    fake = FakeDrive(fail={"get_media": http_error(403, "forbidden"), "delete": http_error(500)})
    res = probe(monkeypatch, sa_path, fake)
    assert (res.outcome, res.stage) == ("permission_denied", "read")
    assert res.probe_written and not res.probe_deleted


def test_content_mismatch_is_unexpected_read(monkeypatch, sa_path):
    fake = FakeDrive(corrupt_read=True)
    res = probe(monkeypatch, sa_path, fake)
    assert (res.outcome, res.stage) == ("unexpected", "read")
    assert fake.deleted == ["probe-id"]


def test_orphans_only_probe_prefix_removed(monkeypatch, sa_path):
    files = [
        {"id": "o1", "name": f"{PROBE_PREFIX}20260101_000000.probe"},
        {"id": "o2", "name": f"{PROBE_PREFIX}20260102_000000.probe"},
        {"id": "b1", "name": f"{BACKUP_PREFIX}20260101_000000.db"},
    ]
    fake = FakeDrive(files=files)
    res = probe(monkeypatch, sa_path, fake)
    assert res.ok and res.orphans_removed == 2
    assert fake.deleted[:2] == ["o1", "o2"] and "b1" not in fake.deleted


def test_orphan_cleanup_error_interrupts(monkeypatch, sa_path):
    fake = FakeDrive(
        files=[{"id": "o1", "name": f"{PROBE_PREFIX}x.probe"}], fail={"delete": http_error(403, "forbidden")}
    )
    res = probe(monkeypatch, sa_path, fake)
    assert (res.outcome, res.stage) == ("permission_denied", "cleanup")
    assert "create" not in fake.calls


def test_quota_message_names_cause_and_remedy(monkeypatch, sa_path):
    res = probe(monkeypatch, sa_path, FakeDrive(fail={"create": http_error(403, "storageQuotaExceeded")}))
    assert "Spazio Google Drive esaurito o limite di richieste" in res.message
    assert "Service Account" not in res.message


def test_no_message_mentions_service_account():
    for text in drive._MESSAGES.values():
        assert "Service Account" not in text and "GOOGLE_SA_KEY_PATH" not in text
    assert not any(key.startswith("sa_") for key in drive._MESSAGES)


def test_auth_messages_name_remedy():
    assert "GOOGLE_OAUTH_TOKEN_PATH" in drive._MESSAGES["auth_missing"]
    assert "rigenera il token" in drive._MESSAGES["auth_invalid"]
    assert "rigenera il token" in drive._MESSAGES["auth_expired"]
    assert "Testing" in drive._MESSAGES["auth_expired"]
    assert "drive.file" in drive._MESSAGES["folder_not_found"]
    assert "client OAuth" in drive._MESSAGES["api_disabled"]


def test_error_details_string_gives_no_reason():
    exc = http_error(403, raw_content=b"not json " + FOLDER.encode())
    assert isinstance(exc.error_details, str)
    assert classify_drive_error(exc, "write") == ("permission_denied", 403, None)


def test_redact_literal_multiple_overlapping_and_empty(monkeypatch):
    monkeypatch.setattr(settings, "gdrive_backup_folder_id", "abc")
    monkeypatch.setattr(settings, "google_oauth_token_path", "/s/abc/tok.json")
    monkeypatch.setattr(settings, "google_sa_key_path", "")
    monkeypatch.setattr(settings, "ai_api_key", "")
    out = redact("p=/s/abc/tok.json f=abc a.c")
    assert out == "p=<google_oauth_token_path> f=<gdrive_backup_folder_id> a.c"


def test_redact_empty_values_leave_text_unchanged(monkeypatch):
    for key in ("gdrive_backup_folder_id", "google_oauth_token_path", "google_sa_key_path", "ai_api_key"):
        monkeypatch.setattr(settings, key, "")
    assert redact("abc") == "abc"


def test_redact_ai_api_key(monkeypatch):
    monkeypatch.setattr(settings, "gdrive_backup_folder_id", "")
    monkeypatch.setattr(settings, "google_oauth_token_path", "")
    monkeypatch.setattr(settings, "google_sa_key_path", "")
    monkeypatch.setattr(settings, "ai_api_key", "K3Y")
    assert redact("x K3Y y") == "x <ai_api_key> y"


@pytest.mark.parametrize("reason", ["accessNotConfigured", "SERVICE_DISABLED"])
def test_api_disabled_names_cause_and_remedy(monkeypatch, sa_path, reason):
    # CP2 reale: 403 accessNotConfigured in cleanup era classificato permission_denied
    # con il rimedio sbagliato ("condividi la cartella").
    res = probe(monkeypatch, sa_path, FakeDrive(fail={"list": http_error(403, reason)}))
    assert (res.outcome, res.stage, res.google_status) == ("api_disabled", "cleanup", 403)
    assert "Google Drive API" in res.message and "condividi" not in res.message
    assert_clean(res, sa_path)


def test_api_disabled_in_post_backup_drive_error():
    exc = http_error(403, "accessNotConfigured")
    assert classify_drive_error(exc, "write")[0] == "api_disabled"
    assert drive.outcome_message("api_disabled") == drive._MESSAGES["api_disabled"]


def _real_transport_error():
    """TransportError REALE: prodotto da google_auth_httplib2.Request (il trasporto del refresh
    del token) quando httplib2 solleva ServerNotFoundError, non iniettato a mano."""
    import google_auth_httplib2
    from google.auth.exceptions import TransportError

    class _DnsDown:
        def request(self, *_a, **_k):
            raise httplib2.ServerNotFoundError(f"Unable to find the server at {FOLDER}")

    with pytest.raises(TransportError) as info:
        google_auth_httplib2.Request(_DnsDown())("https://oauth2.googleapis.com/token")
    return info.value


def test_real_transport_error_hierarchy_is_not_refresh_error():
    exc = _real_transport_error()
    assert not isinstance(exc, RefreshError)
    assert classify_drive_error(exc, "cleanup") == ("network_error", None, None)


def test_real_transport_error_in_probe_is_network_error_not_unexpected(monkeypatch, sa_path, caplog):
    # Primo contatto di rete = refresh del token (credenziali ricostruite a ogni probe), in "cleanup".
    fake = FakeDrive(fail={"list": _real_transport_error()})
    with caplog.at_level("DEBUG"):
        res = probe(monkeypatch, sa_path, fake)
    assert (res.outcome, res.stage, res.ok) == ("network_error", "cleanup", False)
    assert_clean(res, sa_path)
    assert FOLDER not in caplog.text


def test_refresh_error_retryable_is_network_error():
    exc = RefreshError("token endpoint 503", retryable=True)
    assert classify_drive_error(exc, "cleanup") == ("network_error", None, None)


def test_refresh_error_invalid_grant_is_auth_expired():
    exc = RefreshError("x", {"error": "invalid_grant"})
    assert classify_drive_error(exc, "cleanup") == ("auth_expired", None, None)


def test_refresh_error_other_or_unstructured_is_auth_invalid():
    # Senza prova strutturata non si dichiara "scaduto": mai dal testo del messaggio.
    assert classify_drive_error(RefreshError("x", {"error": "invalid_client"}), "cleanup")[0] == "auth_invalid"
    assert classify_drive_error(RefreshError("invalid_grant"), "cleanup")[0] == "auth_invalid"
    assert classify_drive_error(RefreshError("x", "invalid_grant"), "cleanup")[0] == "auth_invalid"
    assert classify_drive_error(RefreshError("x", {}), "cleanup")[0] == "auth_invalid"
    assert classify_drive_error(RefreshError("x", retryable=False), "cleanup")[0] == "auth_invalid"


def test_refresh_error_invalid_grant_but_retryable_is_network_error():
    exc = RefreshError("x", {"error": "invalid_grant"}, retryable=True)
    assert classify_drive_error(exc, "cleanup") == ("network_error", None, None)


def test_refresh_error_content_never_reaches_output(monkeypatch, sa_path, caplog):
    exc = RefreshError(f"token {sa_path} {FOLDER}", {"error": "invalid_grant", "error_description": FOLDER})
    with caplog.at_level("DEBUG"):
        res = probe(monkeypatch, sa_path, FakeDrive(fail={"list": exc}))
    assert res.outcome == "auth_expired"
    assert_clean(res, sa_path)
    assert FOLDER not in caplog.text and sa_path not in caplog.text


def test_refresh_error_retryable_in_probe(monkeypatch, sa_path):
    res = probe(monkeypatch, sa_path, FakeDrive(fail={"list": RefreshError("503", retryable=True)}))
    assert (res.outcome, res.stage) == ("network_error", "cleanup")

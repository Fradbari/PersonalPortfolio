from app.backup import BACKUP_PREFIX
from app.drive import apply_drive_retention, get_drive_service


def test_get_drive_service_returns_none_when_sa_key_missing(tmp_path):
    missing_path = str(tmp_path / "does_not_exist.json")

    service = get_drive_service(missing_path)

    assert service is None


def test_get_drive_service_returns_none_for_empty_path():
    assert get_drive_service("") is None


class _FakeFilesResource:
    def __init__(self, files, deleted_ids):
        self._files = files
        self._deleted_ids = deleted_ids

    def list(self, q=None, fields=None, orderBy=None):
        return _FakeExecute({"files": self._files})

    def delete(self, fileId=None):
        return _FakeDelete(fileId, self._deleted_ids)


class _FakeExecute:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeDelete:
    def __init__(self, file_id, deleted_ids):
        self._file_id = file_id
        self._deleted_ids = deleted_ids

    def execute(self):
        self._deleted_ids.append(self._file_id)
        return {}


class _FakeDriveService:
    def __init__(self, files):
        self._files = files
        self.deleted_ids: list[str] = []

    def files(self):
        return _FakeFilesResource(self._files, self.deleted_ids)


def test_apply_drive_retention_deletes_stale_pairs_only():
    files = [
        {"id": "1", "name": f"{BACKUP_PREFIX}20260101_000000.db"},
        {"id": "2", "name": f"{BACKUP_PREFIX}20260101_000000.xlsx"},
        {"id": "3", "name": f"{BACKUP_PREFIX}20260102_000000.db"},
        {"id": "4", "name": f"{BACKUP_PREFIX}20260102_000000.xlsx"},
        {"id": "5", "name": f"{BACKUP_PREFIX}20260103_000000.db"},
        {"id": "6", "name": f"{BACKUP_PREFIX}20260103_000000.xlsx"},
    ]
    service = _FakeDriveService(files)

    deleted = apply_drive_retention(service, "folder123", retention=1)

    assert sorted(deleted) == sorted(
        [
            f"{BACKUP_PREFIX}20260101_000000.db",
            f"{BACKUP_PREFIX}20260101_000000.xlsx",
            f"{BACKUP_PREFIX}20260102_000000.db",
            f"{BACKUP_PREFIX}20260102_000000.xlsx",
        ]
    )
    assert sorted(service.deleted_ids) == ["1", "2", "3", "4"]

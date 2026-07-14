from app.drive import get_drive_service


def test_get_drive_service_returns_none_when_sa_key_missing(tmp_path):
    missing_path = str(tmp_path / "does_not_exist.json")

    service = get_drive_service(missing_path)

    assert service is None


def test_get_drive_service_returns_none_for_empty_path():
    assert get_drive_service("") is None

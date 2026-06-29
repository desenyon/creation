from types import SimpleNamespace


def test_macos_folder_picker(monkeypatch):
    from creation import composio_api

    monkeypatch.setattr(composio_api.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        composio_api.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="/tmp/creation-project/\n"),
    )

    assert composio_api._choose_local_folder() == "/tmp/creation-project"


def test_cancelled_folder_picker(monkeypatch):
    from creation import composio_api

    monkeypatch.setattr(composio_api.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        composio_api.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
    )

    assert composio_api._choose_local_folder() == ""

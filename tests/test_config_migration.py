"""Config migration and persistence across upgrades."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from creation.config import CONFIG_DIR, CONFIG_FILE, UserSecrets, load_secrets, save_secrets


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    config_dir = tmp_path / ".creation"
    config_file = config_dir / "config.json"
    legacy_dir = tmp_path / ".software-factory"
    monkeypatch.setattr("creation.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("creation.config.CONFIG_FILE", config_file)
    monkeypatch.setattr("creation.config.PROJECTS_DIR", config_dir / "projects")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return config_dir, config_file, legacy_dir


def test_save_preserves_unknown_keys(isolated_config):
    _, config_file, _ = isolated_config
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps({"tavily_api_key": "tv-old", "custom_flag": True}))
    save_secrets(UserSecrets(tavily_api_key="tv-new", nebius_api_key="nb-1"))
    data = json.loads(config_file.read_text())
    assert data["tavily_api_key"] == "tv-new"
    assert data["nebius_api_key"] == "nb-1"
    assert data["custom_flag"] is True


def test_merge_legacy_config_without_overwriting(isolated_config):
    _, config_file, legacy_dir = isolated_config
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "config.json").write_text(
        json.dumps(
            {
                "tavily_api_key": "tv-legacy",
                "nebius_api_key": "nb-legacy",
                "composio_api_key": "cp-legacy",
            }
        )
    )
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps({"tavily_api_key": "tv-current"}))
    secrets = load_secrets()
    assert secrets.tavily_api_key == "tv-current"
    assert secrets.nebius_api_key == "nb-legacy"
    assert secrets.composio_api_key == "cp-legacy"


def test_copy_legacy_tree_when_creation_missing(isolated_config, monkeypatch):
    config_dir, config_file, legacy_dir = isolated_config
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "config.json").write_text(json.dumps({"tavily_api_key": "tv-1", "nebius_api_key": "nb-1"}))
    (legacy_dir / "projects").mkdir()
    load_secrets()
    data = json.loads(config_file.read_text())
    assert data.get("tavily_api_key") == "tv-1"
    assert data.get("forge_api_key") == "nb-1"


@pytest.mark.parametrize("legacy_target", ["auto", "railway", "vercel", None])
def test_old_deploy_targets_are_ignored(legacy_target):
    assert UserSecrets(deploy_target=legacy_target).model_dump().get("deploy_target") is None

"""Tests for email sensor backend config resolution."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import yaml

SENSOR_DIR = Path(__file__).resolve().parents[1] / "sensors" / "email"
SENSOR_MODULE = SENSOR_DIR / "email_sensor.py"
sys.path.insert(0, str(SENSOR_DIR))

spec = importlib.util.spec_from_file_location("email_sensor_module", SENSOR_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load module spec from {SENSOR_MODULE}")
email_sensor_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(email_sensor_module)
EmailSensor = email_sensor_module.EmailSensor


def _base_config() -> dict:
    config_path = SENSOR_DIR / "config.yaml"
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def test_env_db_url_overrides_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _base_config()
    config["koi_backend"]["database_url"] = "postgresql://config-user@localhost:5432/personal_koi"

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    monkeypatch.setenv("PERSONAL_KOI_DB_URL", "postgresql://env-user:secret@localhost:5432/personal_koi")

    sensor = EmailSensor(config_path=str(config_path))
    assert sensor.db_url == "postgresql://env-user:secret@localhost:5432/personal_koi"


def test_missing_db_url_raises_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _base_config()
    config["koi_backend"]["database_url"] = None

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    monkeypatch.delenv("PERSONAL_KOI_DB_URL", raising=False)
    monkeypatch.delenv("KOI_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="koi_backend.database_url"):
        EmailSensor(config_path=str(config_path))

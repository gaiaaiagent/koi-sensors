"""Tests for Claude Sessions metadata extraction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

# Allow importing claude_session_sensor.py directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claude_session_sensor import ClaudeSessionSensor


def _write_config(tmp_path: Path) -> Path:
    config = {
        "sensor": {"name": "claude_sessions"},
        "sessions": {
            "base_path": str(tmp_path),
            "pattern": "**/*.jsonl",
            "exclude": [],
        },
        "processing": {
            "chunk_strategy": "turn_pair",
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "min_messages": 2,
            "max_age_days": 0,
        },
        "embeddings": {
            "enabled": False,
            "model": "text-embedding-3-small",
            "batch_size": 10,
        },
        "entity_extraction": {"enabled": False},
        "koi_backend": {
            "api_url": "http://localhost:8351",
            "database_url": "postgresql://localhost:5432/personal_koi",
        },
        "runtime": {"scan_interval": 10, "mode": "scan", "log_level": "INFO"},
    }

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def test_extract_metadata_tracks_tools_files_and_mcp_servers(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    sensor = ClaudeSessionSensor(config_path=str(config_path))

    transcript_path = tmp_path / "session.jsonl"
    lines = [
        {
            "type": "user",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {"content": [{"type": "text", "text": "hello"}]},
        },
        {
            "type": "assistant",
            "cwd": "/tmp/project",
            "gitBranch": "feature/test",
            "message": {
                "model": "claude-opus-4-5-20251101",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": "/tmp/project/src/index.ts"},
                    },
                    {
                        "type": "tool_use",
                        "name": "mcp__personal-koi__search",
                        "input": {},
                    },
                ],
            },
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {"file_path": "/tmp/project/src/index.ts"},
                    }
                ]
            },
        },
    ]
    transcript_path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")

    metadata = sensor._extract_metadata(str(transcript_path))

    assert metadata["tool_counts"]["Read"] == 1
    assert metadata["tool_counts"]["Edit"] == 1
    assert metadata["tool_counts"]["mcp__personal-koi__search"] == 1
    assert "personal-koi" in metadata["mcp_servers"]
    assert "/tmp/project/src/index.ts" in metadata["files_accessed"]
    assert metadata["model"] == "claude-opus-4-5-20251101"
    assert metadata["cwd"] == "/tmp/project"
    assert metadata["git_branch"] == "feature/test"

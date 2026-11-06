"""The GitHub sensor must mark private-repo content is_private, and that flag must
survive document_to_bundle into contents.metadata (where the event bridge's
3-location bundle_is_private reads it). Regression for: private-repo content was
stored is_private=false and anonymously searchable (2026-11-06)."""
import dataclasses
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Needs the sensor's deps (rid_lib etc.); skip cleanly where they are absent so
# this runs in the deps-complete env (the sensor's own venv / CI).
try:
    from koi_protocol.core.bundle_system import document_to_bundle
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"koi_protocol/rid_lib not importable here: {exc}", allow_module_level=True)


def _doc(is_private):
    return {
        "id": "regen.github:github_koi-processor_README.md",
        "title": "t", "source": "github", "source_type": "github",
        "url": "https://github.com/gaiaaiagent/koi-processor/blob/main/README.md",
        "content": "example", "author": "a",
        "metadata": {
            "repo": "koi-processor",
            "is_private": is_private,
            "access_source": "github_private_repo" if is_private else None,
        },
    }


def _contents_meta(bundle):
    c = getattr(bundle, "contents", None)
    if isinstance(c, dict) and isinstance(c.get("metadata"), dict):
        return c["metadata"]
    if dataclasses.is_dataclass(bundle):
        d = dataclasses.asdict(bundle)
        return ((d.get("contents") or {}).get("metadata") or {})
    to_dict = getattr(bundle, "to_dict", None)
    if callable(to_dict):
        return ((to_dict().get("contents") or {}).get("metadata") or {})
    return {}


def test_private_repo_doc_marks_bundle_private():
    m = _contents_meta(document_to_bundle(_doc(True)))
    assert m.get("is_private") is True, m


def test_public_repo_doc_not_marked_private():
    m = _contents_meta(document_to_bundle(_doc(False)))
    assert not m.get("is_private"), m


if __name__ == "__main__":
    test_private_repo_doc_marks_bundle_private()
    test_public_repo_doc_not_marked_private()
    print("OK: both assertions passed")

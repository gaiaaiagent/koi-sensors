"""
KOI Sensor Network - Developer Tools RID Types
Resource Identifiers for GitHub and other development platforms
"""

import hashlib
from rid_lib.core import ORN


class GitHubFile(ORN):
    """GitHub file resource identifier
    Format: orn:github.file:owner/repo/branch/path_hash
    """
    namespace = "github.file"

    def __init__(self, owner: str, repo: str, branch: str, file_path: str):
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.file_path = file_path
        self.path_hash = hashlib.sha256(file_path.encode('utf-8')).hexdigest()[:16]
        self._reference = f"{owner}/{repo}/{branch}/{self.path_hash}"
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        parts = reference.split('/')
        if len(parts) != 4:
            raise ValueError(f"Invalid GitHubFile reference: {reference}")
        # Can't recover file_path from hash, use placeholder
        return cls(parts[0], parts[1], parts[2], f"unknown-{parts[3]}")

    @property
    def reference(self) -> str:
        return self._reference

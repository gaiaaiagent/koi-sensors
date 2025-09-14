"""
KOI Sensor Network - Productivity Platform RID Types
Resource Identifiers for Notion and other productivity platforms
"""

from typing import Optional
from rid_lib.core import ORN


class NotionPage(ORN):
    """Notion page resource identifier
    Format: orn:notion.page:workspace_id/page_id
    """
    namespace = "notion.page"

    def __init__(self, workspace_id: str, page_id: str):
        self.workspace_id = workspace_id
        self.page_id = page_id
        self._reference = f"{workspace_id}/{page_id}"
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        parts = reference.split('/')
        if len(parts) != 2:
            raise ValueError(f"Invalid NotionPage reference: {reference}")
        return cls(parts[0], parts[1])

    @property
    def reference(self) -> str:
        return self._reference


class NotionBlock(ORN):
    """Notion block resource identifier
    Format: orn:notion.block:page_id/block_id
    """
    namespace = "notion.block"

    def __init__(self, page_id: str, block_id: str):
        self.page_id = page_id
        self.block_id = block_id
        self._reference = f"{page_id}/{block_id}"
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        parts = reference.split('/')
        if len(parts) != 2:
            raise ValueError(f"Invalid NotionBlock reference: {reference}")
        return cls(parts[0], parts[1])

    @property
    def reference(self) -> str:
        return self._reference


class NotionDatabase(ORN):
    """Notion database resource identifier
    Format: orn:notion.database:workspace_id/database_id
    """
    namespace = "notion.database"

    def __init__(self, workspace_id: str, database_id: str):
        self.workspace_id = workspace_id
        self.database_id = database_id
        self._reference = f"{workspace_id}/{database_id}"
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        parts = reference.split('/')
        if len(parts) != 2:
            raise ValueError(f"Invalid NotionDatabase reference: {reference}")
        return cls(parts[0], parts[1])

    @property
    def reference(self) -> str:
        return self._reference


class NotionDatabaseRow(ORN):
    """Notion database row/page resource identifier
    Format: orn:notion.row:database_id/page_id
    """
    namespace = "notion.row"

    def __init__(self, database_id: str, page_id: str):
        self.database_id = database_id
        self.page_id = page_id
        self._reference = f"{database_id}/{page_id}"
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        parts = reference.split('/')
        if len(parts) != 2:
            raise ValueError(f"Invalid NotionDatabaseRow reference: {reference}")
        return cls(parts[0], parts[1])

    @property
    def reference(self) -> str:
        return self._reference
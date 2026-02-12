"""
Tests for MaildirParser
"""

import pytest
from pathlib import Path
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from maildir_parser import MaildirParser


class TestMaildirParser:
    """Tests for MaildirParser class."""

    def test_exclude_folder_matching(self):
        """Test folder exclusion logic."""
        parser = MaildirParser(
            base_path="/tmp/test",
            exclude_folders=["[Gmail]/Spam", "[Gmail]/Trash", "Deleted Messages"],
        )

        # These should be excluded
        assert parser._should_exclude_folder("[Gmail]/Spam") is True
        assert parser._should_exclude_folder("[Gmail]/Trash") is True
        assert parser._should_exclude_folder("Deleted Messages") is True

        # These should not be excluded
        assert parser._should_exclude_folder("INBOX") is False
        assert parser._should_exclude_folder("Sent") is False
        assert parser._should_exclude_folder("[Gmail]/Sent Mail") is False

    def test_valid_name_detection(self):
        """Test name validation logic."""
        parser = MaildirParser(base_path="/tmp/test")

        # Valid names
        # Note: _is_valid_name is an internal method on emails,
        # but we can test via parse_email behavior

        # For now, just test instantiation
        assert parser is not None


class TestGmailRID:
    """Tests for Gmail RID classes."""

    def test_gmail_message_rid(self):
        """Test GmailMessageRID generation."""
        from koi_protocol.core.rid_system import GmailMessageRID

        # Add parent path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

        rid = GmailMessageRID("<test123@example.com>")
        rid_str = rid.to_string()

        assert rid_str.startswith("orn:gmail.message:")
        assert len(rid.message_id_hash) == 16  # SHA256[:16]

    def test_gmail_message_rid_normalization(self):
        """Test Message-ID normalization."""
        from koi_protocol.core.rid_system import GmailMessageRID

        # Without angle brackets
        rid1 = GmailMessageRID.from_raw_message_id("test123@example.com")
        # With angle brackets
        rid2 = GmailMessageRID.from_raw_message_id("<test123@example.com>")

        assert rid1.message_id == rid2.message_id

    def test_gmail_attachment_rid(self):
        """Test GmailAttachmentRID generation."""
        from koi_protocol.core.rid_system import GmailAttachmentRID

        rid = GmailAttachmentRID(
            parent_message_id="<test123@example.com>",
            attachment_index=0,
            content_hash="abc123def456",
        )
        rid_str = rid.to_string()

        assert rid_str.startswith("orn:gmail.attachment:")
        assert "/0_" in rid_str  # index_hash format


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

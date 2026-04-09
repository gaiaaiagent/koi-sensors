"""
KOI Sensor Network - Communication Platform RID Types
Resource Identifiers for Gmail and other communication platforms
"""

import hashlib
from rid_lib.core import ORN


class GmailMessage(ORN):
    """Gmail message resource identifier
    Format: orn:gmail.message:message_id_hash

    Uses SHA256 hash of Message-ID header since X-GM-MSGID is only available via IMAP.
    The hash provides a stable, unique identifier that survives Maildir moves.
    """
    namespace = "gmail.message"

    def __init__(self, message_id: str):
        """
        Create a Gmail message RID from a Message-ID header value.

        Args:
            message_id: The RFC 5322 Message-ID header value (e.g., "<abc123@example.com>")
        """
        self.message_id = message_id
        self.message_id_hash = hashlib.sha256(message_id.encode('utf-8')).hexdigest()[:16]
        self._reference = self.message_id_hash
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string (hash only, original message_id unrecoverable)"""
        # Can't recover original message_id from hash
        instance = cls.__new__(cls)
        instance.message_id = f"<unknown-{reference}>"
        instance.message_id_hash = reference
        instance._reference = reference
        instance.namespace = "gmail.message"
        ORN.__init__(instance)
        return instance

    @classmethod
    def from_raw_message_id(cls, raw_message_id: str) -> 'GmailMessage':
        """
        Create RID from raw Message-ID, normalizing angle brackets.

        Args:
            raw_message_id: Message-ID with or without angle brackets
        """
        message_id = raw_message_id.strip()
        if not message_id.startswith('<'):
            message_id = f'<{message_id}'
        if not message_id.endswith('>'):
            message_id = f'{message_id}>'
        return cls(message_id)

    @property
    def reference(self) -> str:
        return self._reference


class ProtonMessage(ORN):
    """Proton Mail message resource identifier
    Format: orn:proton.message:message_id_hash

    Uses SHA256 hash of Message-ID header, same approach as GmailMessage.
    """
    namespace = "proton.message"

    def __init__(self, message_id: str):
        self.message_id = message_id
        self.message_id_hash = hashlib.sha256(message_id.encode('utf-8')).hexdigest()[:16]
        self._reference = self.message_id_hash
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        instance = cls.__new__(cls)
        instance.message_id = f"<unknown-{reference}>"
        instance.message_id_hash = reference
        instance._reference = reference
        instance.namespace = "proton.message"
        ORN.__init__(instance)
        return instance

    @classmethod
    def from_raw_message_id(cls, raw_message_id: str) -> 'ProtonMessage':
        message_id = raw_message_id.strip()
        if not message_id.startswith('<'):
            message_id = f'<{message_id}'
        if not message_id.endswith('>'):
            message_id = f'{message_id}>'
        return cls(message_id)

    @property
    def reference(self) -> str:
        return self._reference


class GmailAttachment(ORN):
    """Gmail attachment resource identifier
    Format: orn:gmail.attachment:message_hash/index_content_hash

    Attachments are identified by their parent message, index, and content hash.
    """
    namespace = "gmail.attachment"

    def __init__(self, parent_message_id: str, attachment_index: int, content_hash: str):
        """
        Create a Gmail attachment RID.

        Args:
            parent_message_id: The parent email's Message-ID header
            attachment_index: Zero-based index of attachment in the email
            content_hash: SHA256 hash of attachment content (first 16 chars)
        """
        self.parent_message_id = parent_message_id
        self.attachment_index = attachment_index
        self.content_hash = content_hash[:16] if len(content_hash) > 16 else content_hash
        self.parent_hash = hashlib.sha256(parent_message_id.encode('utf-8')).hexdigest()[:16]
        self._reference = f"{self.parent_hash}/{self.attachment_index}_{self.content_hash}"
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        parts = reference.split('/')
        if len(parts) != 2:
            raise ValueError(f"Invalid GmailAttachment reference: {reference}")
        index_content = parts[1].split('_', 1)
        if len(index_content) != 2:
            raise ValueError(f"Invalid GmailAttachment index_content: {parts[1]}")
        # Can't recover parent_message_id from hash
        instance = cls.__new__(cls)
        instance.parent_message_id = f"<unknown-{parts[0]}>"
        instance.attachment_index = int(index_content[0])
        instance.content_hash = index_content[1]
        instance.parent_hash = parts[0]
        instance._reference = reference
        instance.namespace = "gmail.attachment"
        ORN.__init__(instance)
        return instance

    @property
    def reference(self) -> str:
        return self._reference

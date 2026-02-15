"""
Phase 2 RID-lib Migration Tests

Verifies:
1. String format parity between old custom classes and new rid-lib subclasses
2. All RID types produce correct orn: format strings
3. Backward-compatible aliases work
4. New types (GitHubFile, GmailMessage, GmailAttachment) work correctly
5. rid-lib is unconditionally available (no fallback)
"""

import hashlib
import pytest


class TestRidLibAvailable:
    """Verify rid-lib is unconditionally importable."""

    def test_rid_lib_core_import(self):
        from rid_lib.core import ORN
        assert ORN is not None

    def test_rid_lib_ext_import(self):
        from rid_lib.ext import Manifest, Cache, Bundle
        assert Manifest is not None
        assert Cache is not None
        assert Bundle is not None

    def test_rid_lib_utils_import(self):
        from rid_lib.ext.utils import sha256_hash_json
        assert sha256_hash_json is not None

    def test_rid_lib_consts_import(self):
        from rid_lib.consts import NAMESPACE_SCHEMES
        assert 'orn' in NAMESPACE_SCHEMES


class TestSharedRidTypesImport:
    """Verify all shared RID types are importable."""

    def test_social_media_imports(self):
        from shared.rid_types.social_media import (
            TwitterTweet, TwitterUser, TwitterThread,
            DiscordMessage, DiscordChannel, DiscordGuild,
            TelegramMessage, TelegramChat,
            YouTubeVideo, YouTubeComment, YouTubeChannel,
        )

    def test_web_content_imports(self):
        from shared.rid_types.web_content import (
            WebPage, WebSite, DiscoursePost, DiscourseThread,
            RSSFeed, RSSItem,
        )

    def test_productivity_imports(self):
        from shared.rid_types.productivity import (
            NotionPage, NotionBlock, NotionDatabase, NotionDatabaseRow,
        )

    def test_dev_tools_imports(self):
        from shared.rid_types.dev_tools import GitHubFile

    def test_communication_imports(self):
        from shared.rid_types.communication import GmailMessage, GmailAttachment

    def test_package_init_imports(self):
        from shared.rid_types import (
            TwitterTweet, WebPage, NotionPage,
            GitHubFile, GmailMessage, GmailAttachment,
        )


class TestBackwardCompatibleAliases:
    """Verify backward-compatible aliases in rid_system.py."""

    def test_twitter_tweet_alias(self):
        from koi_protocol.core.rid_system import TwitterTweetRID
        from shared.rid_types.social_media import TwitterTweet
        assert TwitterTweetRID is TwitterTweet

    def test_discourse_post_alias(self):
        from koi_protocol.core.rid_system import DiscoursePostRID
        from shared.rid_types.web_content import DiscoursePost
        assert DiscoursePostRID is DiscoursePost

    def test_notion_page_alias(self):
        from koi_protocol.core.rid_system import NotionPageRID
        from shared.rid_types.productivity import NotionPage
        assert NotionPageRID is NotionPage

    def test_web_page_alias(self):
        from koi_protocol.core.rid_system import WebPageRID
        from shared.rid_types.web_content import WebPage
        assert WebPageRID is WebPage

    def test_github_file_alias(self):
        from koi_protocol.core.rid_system import GitHubFileRID
        from shared.rid_types.dev_tools import GitHubFile
        assert GitHubFileRID is GitHubFile

    def test_gmail_message_alias(self):
        from koi_protocol.core.rid_system import GmailMessageRID
        from shared.rid_types.communication import GmailMessage
        assert GmailMessageRID is GmailMessage

    def test_gmail_attachment_alias(self):
        from koi_protocol.core.rid_system import GmailAttachmentRID
        from shared.rid_types.communication import GmailAttachment
        assert GmailAttachmentRID is GmailAttachment

    def test_youtube_video_alias(self):
        from koi_protocol.core.rid_system import YouTubeVideoRID
        from shared.rid_types.social_media import YouTubeVideo
        assert YouTubeVideoRID is YouTubeVideo

    def test_orn_reexport(self):
        from koi_protocol.core.rid_system import ORN
        from rid_lib.core import ORN as RidLibORN
        assert ORN is RidLibORN


class TestStringFormatParity:
    """Verify string output matches between old custom and new rid-lib types."""

    def test_twitter_tweet_format(self):
        from shared.rid_types.social_media import TwitterTweet
        t = TwitterTweet("user1", "tweet1")
        assert str(t) == "orn:twitter.tweet:user1/tweet1"

    def test_discourse_post_format(self):
        from shared.rid_types.web_content import DiscoursePost
        d = DiscoursePost("forum.regen.network", "123", "4")
        assert str(d) == "orn:discourse.post:forum.regen.network/123/4"

    def test_notion_page_format(self):
        from shared.rid_types.productivity import NotionPage
        n = NotionPage("regen", "abc123")
        assert str(n) == "orn:notion.page:regen/abc123"

    def test_web_page_format(self):
        from shared.rid_types.web_content import WebPage
        url = "https://example.com/page"
        w = WebPage("example.com", url)
        expected_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
        assert str(w) == f"orn:web.page:example.com/{expected_hash}"

    def test_github_file_format(self):
        from shared.rid_types.dev_tools import GitHubFile
        g = GitHubFile("regen-network", "regen-ledger", "main", "README.md")
        expected_hash = hashlib.sha256("README.md".encode('utf-8')).hexdigest()[:16]
        assert str(g) == f"orn:github.file:regen-network/regen-ledger/main/{expected_hash}"

    def test_gmail_message_format(self):
        from shared.rid_types.communication import GmailMessage
        msg_id = "<test@example.com>"
        m = GmailMessage(msg_id)
        expected_hash = hashlib.sha256(msg_id.encode('utf-8')).hexdigest()[:16]
        assert str(m) == f"orn:gmail.message:{expected_hash}"

    def test_gmail_attachment_format(self):
        from shared.rid_types.communication import GmailAttachment
        parent_id = "<test@example.com>"
        content_hash = "abcdef1234567890abcdef"
        a = GmailAttachment(parent_id, 0, content_hash)
        expected_parent_hash = hashlib.sha256(parent_id.encode('utf-8')).hexdigest()[:16]
        assert str(a) == f"orn:gmail.attachment:{expected_parent_hash}/0_{content_hash[:16]}"

    def test_youtube_video_format(self):
        from shared.rid_types.social_media import YouTubeVideo
        y = YouTubeVideo("channel1", "video123")
        assert str(y) == "orn:youtube.video:channel1/video123"


class TestGmailMessageFromRaw:
    """Test GmailMessage.from_raw_message_id convenience method."""

    def test_with_angle_brackets(self):
        from shared.rid_types.communication import GmailMessage
        m = GmailMessage.from_raw_message_id("<test@example.com>")
        assert m.message_id == "<test@example.com>"

    def test_without_angle_brackets(self):
        from shared.rid_types.communication import GmailMessage
        m = GmailMessage.from_raw_message_id("test@example.com")
        assert m.message_id == "<test@example.com>"

    def test_normalized_hash_matches(self):
        from shared.rid_types.communication import GmailMessage
        m1 = GmailMessage("<test@example.com>")
        m2 = GmailMessage.from_raw_message_id("test@example.com")
        assert str(m1) == str(m2)


class TestRidSystemNoFallback:
    """Verify rid_system.py no longer uses RID_LIB_AVAILABLE fallback."""

    def test_no_rid_lib_available_flag(self):
        """rid_system.py should not define RID_LIB_AVAILABLE anymore."""
        import koi_protocol.core.rid_system as mod
        assert not hasattr(mod, 'RID_LIB_AVAILABLE')

    def test_namespace_schemes_from_ridlib(self):
        """NAMESPACE_SCHEMES should come from rid-lib, not be a fallback constant."""
        from koi_protocol.core.rid_system import NAMESPACE_SCHEMES
        from rid_lib.consts import NAMESPACE_SCHEMES as ridlib_schemes
        assert NAMESPACE_SCHEMES is ridlib_schemes


class TestDocumentToRid:
    """Verify document_to_rid still works after migration."""

    def test_twitter_document(self):
        from koi_protocol.core.rid_system import document_to_rid
        doc = {
            "source_type": "twitter",
            "metadata": {"author_id": "user1", "tweet_id": "tweet1"}
        }
        rid = document_to_rid(doc)
        assert rid is not None
        assert str(rid) == "orn:twitter.tweet:user1/tweet1"

    def test_youtube_document(self):
        from koi_protocol.core.rid_system import document_to_rid
        doc = {
            "source_type": "youtube",
            "metadata": {"channel_id": "ch1", "video_id": "vid1"}
        }
        rid = document_to_rid(doc)
        assert rid is not None
        assert str(rid) == "orn:youtube.video:ch1/vid1"

    def test_notion_document(self):
        from koi_protocol.core.rid_system import document_to_rid
        doc = {
            "source_type": "notion",
            "metadata": {"page_id": "abc123", "workspace_id": "regen"}
        }
        rid = document_to_rid(doc)
        assert rid is not None
        assert str(rid) == "orn:notion.page:regen/abc123"

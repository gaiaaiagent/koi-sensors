# KOI Sensor Network - Shared RID Types
# Platform-specific Resource Identifiers using rid-lib base classes

from .social_media import (
    TwitterTweet, TwitterUser, TwitterThread,
    DiscordMessage, DiscordChannel, DiscordGuild,
    TelegramMessage, TelegramChat,
    YouTubeVideo, YouTubeComment, YouTubeChannel
)

from .web_content import (
    WebPage, WebSite, DiscoursePost, DiscourseThread,
    RSSFeed, RSSItem
)

from .productivity import (
    NotionPage, NotionBlock, NotionDatabase, NotionDatabaseRow
)

from .dev_tools import (
    GitHubFile
)

from .communication import (
    GmailMessage, GmailAttachment
)

__all__ = [
    # Twitter/X
    'TwitterTweet', 'TwitterUser', 'TwitterThread',

    # Discord
    'DiscordMessage', 'DiscordChannel', 'DiscordGuild',

    # Telegram
    'TelegramMessage', 'TelegramChat',

    # YouTube
    'YouTubeVideo', 'YouTubeComment', 'YouTubeChannel',

    # Web Content
    'WebPage', 'WebSite', 'DiscoursePost', 'DiscourseThread',
    'RSSFeed', 'RSSItem',

    # Productivity
    'NotionPage', 'NotionBlock', 'NotionDatabase', 'NotionDatabaseRow',

    # Developer Tools
    'GitHubFile',

    # Communication
    'GmailMessage', 'GmailAttachment',
]

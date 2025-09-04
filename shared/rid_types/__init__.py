# KOI Sensor Network - Shared RID Types
# Platform-specific Resource Identifiers for social media and web content

from .social_media import (
    TwitterTweet, TwitterUser, TwitterThread,
    DiscordMessage, DiscordChannel, DiscordGuild,
    TelegramMessage, TelegramChat,
    YouTubeVideo, YouTubeComment, YouTubeChannel
)

from .web_content import (
    WebPage, WebSite, DiscoursePost, DiscourseThread
)

from .productivity import (
    NotionPage, NotionBlock, NotionDatabase
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
    
    # Productivity
    'NotionPage', 'NotionBlock', 'NotionDatabase'
]
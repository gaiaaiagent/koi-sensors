"""
KOI Sensor Network - Social Media Platform RID Types
Resource Identifiers for Twitter, Discord, Telegram, and YouTube content
"""

from typing import Optional
from rid_lib import ORN


class TwitterTweet(ORN):
    """Twitter/X tweet resource identifier
    Format: orn:twitter.tweet:user_id/tweet_id
    """
    namespace = "twitter.tweet"
    
    def __init__(self, user_id: str, tweet_id: str):
        self.user_id = user_id
        self.tweet_id = tweet_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.user_id}/{self.tweet_id}"


class TwitterUser(ORN):
    """Twitter/X user profile resource identifier
    Format: orn:twitter.user:user_id
    """
    namespace = "twitter.user"
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return self.user_id


class TwitterThread(ORN):
    """Twitter/X thread resource identifier
    Format: orn:twitter.thread:root_tweet_id
    """
    namespace = "twitter.thread"
    
    def __init__(self, root_tweet_id: str):
        self.root_tweet_id = root_tweet_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return self.root_tweet_id


class DiscordMessage(ORN):
    """Discord message resource identifier
    Format: orn:discord.message:guild_id/channel_id/message_id
    """
    namespace = "discord.message"
    
    def __init__(self, guild_id: str, channel_id: str, message_id: str):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.message_id = message_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.guild_id}/{self.channel_id}/{self.message_id}"


class DiscordChannel(ORN):
    """Discord channel resource identifier
    Format: orn:discord.channel:guild_id/channel_id
    """
    namespace = "discord.channel"
    
    def __init__(self, guild_id: str, channel_id: str):
        self.guild_id = guild_id
        self.channel_id = channel_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.guild_id}/{self.channel_id}"


class DiscordGuild(ORN):
    """Discord guild/server resource identifier
    Format: orn:discord.guild:guild_id
    """
    namespace = "discord.guild"
    
    def __init__(self, guild_id: str):
        self.guild_id = guild_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return self.guild_id


class TelegramMessage(ORN):
    """Telegram message resource identifier
    Format: orn:telegram.message:chat_id/message_id
    """
    namespace = "telegram.message"
    
    def __init__(self, chat_id: str, message_id: str):
        self.chat_id = chat_id
        self.message_id = message_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.chat_id}/{self.message_id}"


class TelegramChat(ORN):
    """Telegram chat/channel resource identifier
    Format: orn:telegram.chat:chat_id
    """
    namespace = "telegram.chat"
    
    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return self.chat_id


class YouTubeVideo(ORN):
    """YouTube video resource identifier
    Format: orn:youtube.video:video_id
    """
    namespace = "youtube.video"
    
    def __init__(self, video_id: str):
        self.video_id = video_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return self.video_id


class YouTubeComment(ORN):
    """YouTube comment resource identifier
    Format: orn:youtube.comment:video_id/comment_id
    """
    namespace = "youtube.comment"
    
    def __init__(self, video_id: str, comment_id: str):
        self.video_id = video_id
        self.comment_id = comment_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.video_id}/{self.comment_id}"


class YouTubeChannel(ORN):
    """YouTube channel resource identifier
    Format: orn:youtube.channel:channel_id
    """
    namespace = "youtube.channel"
    
    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return self.channel_id
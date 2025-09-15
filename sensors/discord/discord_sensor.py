#!/usr/bin/env python3
"""
Discord Sensor for KOI System
Monitors Discord servers for messages and activity
"""

import asyncio
import discord
from discord.ext import commands
import json
import hashlib
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timezone, timedelta
from pathlib import Path
import logging
import sys
import os
from dotenv import load_dotenv

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import Bundle, document_to_bundle


class DiscordMessageRID(RID):
    """Discord message resource identifier: orn:discord.{guild_id}.{channel_id}.{message_id}"""

    def __init__(self, guild_id: str, channel_id: str, message_id: str):
        super().__init__("orn", f"discord.g{guild_id}.c{channel_id}.m{message_id}")


class DiscordKOISensor:
    """Discord sensor using Discord.py for monitoring servers"""

    def __init__(self, token: str, monitored_guilds: List[int] = None):
        """
        Initialize Discord sensor

        Args:
            token: Discord bot token
            monitored_guilds: List of guild IDs to monitor (None = all guilds)
        """
        self.token = token
        self.monitored_guilds = set(monitored_guilds) if monitored_guilds else None

        # Setup logging
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        # Initialize Discord bot
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        self.bot = commands.Bot(command_prefix='!', intents=intents)

        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name="discord-sensor",
            coordinator_url="http://localhost:8005",
            poll_interval=30
        )

        # Track processed messages
        self.processed_messages: Set[str] = set()
        self.message_cache: Dict[str, Dict] = {}

        # Output directory
        self.output_dir = Path(__file__).parent / 'output'
        self.output_dir.mkdir(exist_ok=True)

        # Setup bot events
        self.setup_events()

    async def send_heartbeat_event(self, response_to: str = None):
        """Send a heartbeat event to register with coordinator"""
        try:
            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor_id": "discord-sensor",
                "sensor_type": "discord",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "active",
                "monitoring": [f"{guild.name} ({guild.id})" for guild in self.bot.guilds],
                "message_count": len(self.processed_messages)
            }

            if response_to:
                heartbeat_data["response_to"] = response_to

            # Create document for heartbeat
            heartbeat_document = {
                'id': f"discord_heartbeat_{int(datetime.now().timestamp())}",
                'title': 'Discord Sensor Heartbeat',
                'url': '',
                'type': 'heartbeat',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'content': json.dumps(heartbeat_data),
                'metadata': {
                    'sensor_type': 'discord',
                    'sensor_id': 'discord-sensor',
                    'event_type': 'HEARTBEAT'
                }
            }

            # Convert to bundle and emit
            bundle = document_to_bundle(heartbeat_document)
            await self.koi_node.emit_new_event(bundle)

            if not response_to:
                self.logger.info("Sent heartbeat event to coordinator")
            else:
                self.logger.info(f"Responded to ping request {response_to}")

        except Exception as e:
            self.logger.error(f"Error sending heartbeat: {e}")

    async def send_periodic_heartbeats(self):
        """Send periodic heartbeats every 30 minutes"""
        while True:
            await asyncio.sleep(1800)  # 30 minutes
            await self.send_heartbeat_event()

    async def handle_coordinator_events(self):
        """Listen for ping requests from coordinator"""
        try:
            # Subscribe to coordinator events
            async for event in self.koi_node.event_stream():
                if event.get('type') == 'PING_REQUEST':
                    # Check if this ping is for us
                    target = event.get('target')
                    if target == 'discord-sensor' or target == 'all':
                        self.logger.info(f"Received ping request, responding...")
                        await self.send_heartbeat_event(response_to=event.get('id'))
        except Exception as e:
            self.logger.error(f"Error handling coordinator events: {e}")

    def setup_events(self):
        """Setup Discord bot event handlers"""

        @self.bot.event
        async def on_ready():
            """Called when bot is ready"""
            self.logger.info(f'Discord bot logged in as {self.bot.user}')
            self.logger.info(f'Monitoring {len(self.bot.guilds)} guilds')

            # Start KOI node
            await self.koi_node.start()

            # Send initial heartbeat to register
            await self.send_heartbeat_event()

            # Start background tasks
            asyncio.create_task(self.send_periodic_heartbeats())
            asyncio.create_task(self.handle_coordinator_events())

            # Do initial collection of recent messages
            await self.collect_recent_messages()

        @self.bot.event
        async def on_message(message: discord.Message):
            """Handle new messages"""
            # Skip bot messages
            if message.author.bot:
                return

            # Check if we should monitor this guild
            if self.monitored_guilds and message.guild.id not in self.monitored_guilds:
                return

            # Process the message
            await self.process_message(message, event_type="NEW")

        @self.bot.event
        async def on_message_edit(before: discord.Message, after: discord.Message):
            """Handle message edits"""
            # Skip bot messages
            if after.author.bot:
                return

            # Check if we should monitor this guild
            if self.monitored_guilds and after.guild.id not in self.monitored_guilds:
                return

            # Process the edited message
            await self.process_message(after, event_type="UPDATE")

        @self.bot.event
        async def on_message_delete(message: discord.Message):
            """Handle message deletions"""
            # Generate RID for the deleted message
            rid = DiscordMessageRID(
                str(message.guild.id),
                str(message.channel.id),
                str(message.id)
            )

            # Emit forget event
            try:
                await self.koi_node.emit_forget_event(rid, reason="Message deleted")
                self.logger.info(f"Emitted FORGET event for message {message.id}")
            except Exception as e:
                self.logger.error(f"Error emitting FORGET event: {e}")

    async def collect_recent_messages(self):
        """Collect recent messages from all monitored channels"""
        self.logger.info("Collecting recent messages from all channels...")

        for guild in self.bot.guilds:
            # Check if we should monitor this guild
            if self.monitored_guilds and guild.id not in self.monitored_guilds:
                continue

            self.logger.info(f"Collecting from guild: {guild.name}")

            for channel in guild.text_channels:
                try:
                    # Check if bot has permission to read channel
                    permissions = channel.permissions_for(guild.me)
                    if not permissions.read_messages or not permissions.read_message_history:
                        continue

                    # Fetch recent messages (last 24 hours)
                    after_time = datetime.now(timezone.utc) - timedelta(days=1)

                    message_count = 0
                    async for message in channel.history(limit=100, after=after_time):
                        # Skip bot messages
                        if message.author.bot:
                            continue

                        # Process message
                        await self.process_message(message, event_type="NEW", is_historical=True)
                        message_count += 1

                    if message_count > 0:
                        self.logger.info(f"  Channel #{channel.name}: {message_count} messages")

                except discord.Forbidden:
                    self.logger.warning(f"No permission to read channel: {channel.name}")
                except Exception as e:
                    self.logger.error(f"Error collecting from {channel.name}: {e}")

    async def process_message(self, message: discord.Message, event_type: str = "NEW", is_historical: bool = False):
        """
        Process a Discord message and emit to KOI

        Args:
            message: Discord message object
            event_type: Type of event (NEW, UPDATE)
            is_historical: Whether this is historical data collection
        """
        try:
            # Generate unique ID for the message
            message_key = f"{message.guild.id}_{message.channel.id}_{message.id}"

            # Skip if already processed (for historical messages)
            if is_historical and message_key in self.processed_messages:
                return

            # Extract message data
            message_data = {
                'id': f"discord_{message_key}",
                'source': f'discord:{message.guild.id}',
                'source_type': 'discord',
                'url': message.jump_url,
                'title': f"Message in #{message.channel.name}",
                'content': message.content or "[No text content]",
                'author': {
                    'id': str(message.author.id),
                    'username': message.author.name,
                    'display_name': message.author.display_name,
                    'is_bot': message.author.bot
                },
                'metadata': {
                    'guild_id': str(message.guild.id),
                    'guild_name': message.guild.name,
                    'channel_id': str(message.channel.id),
                    'channel_name': message.channel.name,
                    'message_id': str(message.id),
                    'created_at': message.created_at.isoformat(),
                    'edited_at': message.edited_at.isoformat() if message.edited_at else None,
                    'attachments': [
                        {
                            'filename': att.filename,
                            'url': att.url,
                            'size': att.size
                        } for att in message.attachments
                    ],
                    'embeds': len(message.embeds),
                    'reactions': [
                        {
                            'emoji': str(reaction.emoji),
                            'count': reaction.count
                        } for reaction in message.reactions
                    ],
                    'mentions': {
                        'users': [u.name for u in message.mentions],
                        'roles': [r.name for r in message.role_mentions],
                        'channels': [c.name for c in message.channel_mentions]
                    },
                    'is_pinned': message.pinned,
                    'thread': message.thread.name if hasattr(message, 'thread') and message.thread else None
                },
                'collected_at': datetime.now(timezone.utc).isoformat(),
                'tags': self.generate_tags(message)
            }

            # Generate RID
            rid = DiscordMessageRID(
                str(message.guild.id),
                str(message.channel.id),
                str(message.id)
            )

            # Create KOI Bundle
            bundle = document_to_bundle(message_data, self.koi_node.node_id)

            # Emit KOI event
            if event_type == "NEW":
                await self.koi_node.emit_new_event(bundle)
            else:
                await self.koi_node.emit_update_event(bundle)

            self.logger.info(f"Emitted {event_type} event for message from @{message.author.name} in #{message.channel.name}")

            # Mark as processed
            self.processed_messages.add(message_key)
            self.message_cache[message_key] = message_data

            # Save to local file periodically
            if len(self.message_cache) % 10 == 0:
                await self.save_messages()

        except Exception as e:
            self.logger.error(f"Error processing message {message.id}: {e}")

    def generate_tags(self, message: discord.Message) -> List[str]:
        """Generate tags based on message content and context"""
        tags = []

        # Add channel-based tags
        channel_name = message.channel.name.lower()
        if 'general' in channel_name:
            tags.append('general')
        if 'announce' in channel_name or 'news' in channel_name:
            tags.append('announcement')
        if 'govern' in channel_name:
            tags.append('governance')
        if 'dev' in channel_name or 'tech' in channel_name:
            tags.append('development')
        if 'help' in channel_name or 'support' in channel_name:
            tags.append('support')

        # Content-based tags
        content_lower = message.content.lower()
        if 'proposal' in content_lower or 'vote' in content_lower:
            tags.append('governance')
        if 'regen' in content_lower:
            tags.append('regen')
        if 'carbon' in content_lower or 'climate' in content_lower:
            tags.append('climate')
        if 'eco' in content_lower:
            tags.append('ecological')

        # Add guild name as tag
        tags.append(f"guild:{message.guild.name.lower().replace(' ', '-')}")

        # Message type tags
        if message.attachments:
            tags.append('has-attachments')
        if message.embeds:
            tags.append('has-embeds')
        if message.pinned:
            tags.append('pinned')

        return list(set(tags))  # Remove duplicates

    async def save_messages(self):
        """Save collected messages to file"""
        if not self.message_cache:
            return

        output_file = self.output_dir / f"discord_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(output_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'source': 'discord_sensor',
                'message_count': len(self.message_cache),
                'messages': list(self.message_cache.values())
            }, f, indent=2)

        self.logger.info(f"Saved {len(self.message_cache)} messages to {output_file}")
        self.message_cache.clear()

    async def run(self, poll_interval: int = 3600):
        """
        Run the Discord sensor with periodic message collection

        Args:
            poll_interval: Seconds between collecting historical messages
        """
        # Start the bot (this will run until stopped)
        self.logger.info(f"Starting Discord bot with {poll_interval} second polling interval")

        # Create a task for periodic historical message collection
        async def periodic_collection():
            while True:
                await asyncio.sleep(poll_interval)
                try:
                    await self.collect_recent_messages()
                    await self.save_messages()
                except Exception as e:
                    self.logger.error(f"Error in periodic collection: {e}")

        # Start periodic collection task
        collection_task = asyncio.create_task(periodic_collection())

        try:
            # Run the bot
            await self.bot.start(self.token)
        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal, shutting down...")
        finally:
            # Save any remaining messages
            await self.save_messages()

            # Cancel periodic collection
            collection_task.cancel()

            # Close bot
            await self.bot.close()

            # Stop KOI node
            await self.koi_node.stop()


async def main():
    """Main entry point with continuous monitoring"""
    # Load environment variables
    load_dotenv()

    # Get Discord bot token
    discord_token = os.getenv('DISCORD_BOT_TOKEN')
    if not discord_token:
        print("❌ DISCORD_BOT_TOKEN not found in environment variables")
        print("Please add your Discord bot token to the .env file")
        return

    # Get polling interval (default 1 hour)
    poll_interval = int(os.getenv('DISCORD_POLL_INTERVAL', 3600))

    # Get monitored guilds from environment (comma-separated guild IDs)
    guilds_str = os.getenv('DISCORD_GUILDS', '')
    monitored_guilds = None
    if guilds_str:
        try:
            monitored_guilds = [int(g.strip()) for g in guilds_str.split(',')]
            print(f"Monitoring specific guilds: {monitored_guilds}")
        except ValueError:
            print("Warning: Invalid guild IDs in DISCORD_GUILDS")

    # Create and run sensor
    sensor = DiscordKOISensor(
        token=discord_token,
        monitored_guilds=monitored_guilds
    )

    print(f"🚀 Starting Discord sensor")
    print(f"⏰ Historical message collection every {poll_interval} seconds ({poll_interval/60:.1f} minutes)")

    try:
        await sensor.run(poll_interval=poll_interval)
    except Exception as e:
        print(f"❌ Error running Discord sensor: {e}")


if __name__ == "__main__":
    asyncio.run(main())
#!/usr/bin/env python3
"""
KOI Sensor Network - Telegram Sensor v2
Monitors Telegram channels/groups for messages using KOI protocol
"""

import os
import sys
import json
import asyncio
import logging
import hashlib
from typing import Dict, List, Any, Optional, Set
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID, GenericRID
from koi_protocol.core.bundle_system import Bundle, document_to_bundle

# Import telegram library
try:
    from telegram import Bot, Update
    from telegram.error import TelegramError
    from telegram.ext import Application, MessageHandler, filters, ContextTypes
except ImportError:
    print("Error: python-telegram-bot not installed")
    print("Run: pip install python-telegram-bot")
    sys.exit(1)


@dataclass
class TelegramConfig:
    """Configuration for Telegram sensor"""
    # Bot credentials
    bot_token: str = ""
    bot_username: str = ""

    # Channel to monitor
    channel_username: str = "@regen_network_pub"  # Can be @username or chat_id

    # Collection settings
    message_history_limit: int = 100  # Get last N messages on startup
    include_media: bool = True
    include_forwards: bool = True

    # KOI settings
    coordinator_url: str = "http://localhost:8005"
    node_name: str = "telegram-sensor"


class TelegramMessageRID(RID):
    """Telegram message resource identifier"""

    def __init__(self, chat_id: str, message_id: str):
        self.chat_id = str(chat_id).replace("-", "")  # Remove negative sign
        self.message_id = str(message_id)
        super().__init__("orn", f"telegram.message.{self.chat_id}.{self.message_id}")


class TelegramChatRID(RID):
    """Telegram chat resource identifier"""

    def __init__(self, chat_id: str):
        self.chat_id = str(chat_id).replace("-", "")
        super().__init__("orn", f"telegram.chat.{self.chat_id}")


class TelegramKOISensor:
    """Telegram monitoring sensor using KOI protocol"""

    def __init__(self, config: TelegramConfig):
        self.config = config
        self.logger = self._setup_logging()

        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name=config.node_name,
            coordinator_url=config.coordinator_url,
            poll_interval=30
        )

        # Telegram bot setup
        self.bot = None
        self.application = None
        self.chat_id = None

        # Track processed messages
        self.processed_messages: Set[str] = set()

    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('koi.sensor.telegram')
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            logger.addHandler(handler)

        return logger

    async def setup_telegram(self):
        """Setup Telegram bot and handlers"""
        try:
            # Create bot instance
            self.bot = Bot(token=self.config.bot_token)

            # Test bot connection
            bot_info = await self.bot.get_me()
            self.logger.info(f"Bot connected: @{bot_info.username}")

            # Get chat ID from username
            if self.config.channel_username.startswith('@'):
                # Try to get chat info
                try:
                    chat = await self.bot.get_chat(self.config.channel_username)
                    self.chat_id = chat.id
                    self.logger.info(f"Monitoring channel: {chat.title} (ID: {self.chat_id})")
                except TelegramError as e:
                    self.logger.error(f"Could not access channel {self.config.channel_username}: {e}")
                    self.logger.info("Make sure the bot is added to the channel/group")
                    return False
            else:
                # Direct chat ID provided
                self.chat_id = int(self.config.channel_username)

            # Create application for handling updates
            self.application = Application.builder().token(self.config.bot_token).build()

            # Add message handler
            self.application.add_handler(
                MessageHandler(filters.ALL, self.handle_message)
            )

            return True

        except Exception as e:
            self.logger.error(f"Failed to setup Telegram bot: {e}")
            return False

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming Telegram messages"""
        if not update.message:
            return

        message = update.message

        # Check if message is from monitored chat
        if message.chat_id != self.chat_id:
            return

        # Process the message
        await self.process_message(message)

    async def process_message(self, message):
        """Process a Telegram message and emit as KOI event"""
        try:
            # Create unique ID for message
            message_rid = TelegramMessageRID(
                chat_id=str(message.chat_id),
                message_id=str(message.message_id)
            )

            # Check if already processed
            rid_str = message_rid.to_string()
            if rid_str in self.processed_messages:
                return

            # Extract message content
            content = {
                'message_id': message.message_id,
                'chat_id': message.chat_id,
                'chat_title': message.chat.title if message.chat else None,
                'date': message.date.isoformat() if message.date else None,
                'text': message.text,
                'from_user': {
                    'id': message.from_user.id if message.from_user else None,
                    'username': message.from_user.username if message.from_user else None,
                    'first_name': message.from_user.first_name if message.from_user else None,
                } if message.from_user else None,
            }

            # Add media info if present
            if self.config.include_media:
                if message.photo:
                    content['media_type'] = 'photo'
                    content['media_caption'] = message.caption
                elif message.video:
                    content['media_type'] = 'video'
                    content['media_caption'] = message.caption
                elif message.document:
                    content['media_type'] = 'document'
                    content['media_filename'] = message.document.file_name
                    content['media_caption'] = message.caption

            # Add forward info if present
            if self.config.include_forwards and message.forward_from:
                content['forwarded_from'] = {
                    'id': message.forward_from.id,
                    'username': message.forward_from.username,
                    'first_name': message.forward_from.first_name,
                }

            # Create document
            document = {
                'rid': rid_str,
                'type': 'telegram_message',
                'content': content,
                'metadata': {
                    'source': 'telegram',
                    'channel': self.config.channel_username,
                    'collected_at': datetime.now(timezone.utc).isoformat(),
                    'sensor': self.config.node_name
                }
            }

            # Convert to bundle
            bundle = document_to_bundle(document)

            # Emit as KOI event
            self.koi_node.emit_new_event(bundle)
            self.processed_messages.add(rid_str)

            self.logger.info(f"Emitted message {message.message_id} from {message.chat.title}")

        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    async def fetch_message_history(self):
        """Fetch recent message history from the channel"""
        if not self.chat_id or not self.bot:
            return

        try:
            self.logger.info(f"Fetching message history for chat {self.chat_id}")

            # Note: Getting message history requires additional permissions
            # The bot needs to be an admin in the group/channel
            # For now, we'll just log that we can't fetch history
            self.logger.info("Note: Fetching message history requires admin permissions")
            self.logger.info("Bot will monitor new messages going forward")

        except Exception as e:
            self.logger.error(f"Error fetching message history: {e}")

    async def send_heartbeat_event(self):
        """Send a heartbeat event to register with coordinator"""
        try:
            # Create a heartbeat bundle
            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor": "telegram",
                "node_id": self.config.node_name,
                "channel": self.config.channel_username,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "active"
            }

            # Create RID for heartbeat
            heartbeat_rid = GenericRID("orn", f"telegram.heartbeat.{self.config.node_name}")

            # Create bundle
            bundle = document_to_bundle(
                content=json.dumps(heartbeat_data),
                source_rid=heartbeat_rid,
                document_type="heartbeat",
                metadata={"sensor_type": "telegram"}
            )

            # Emit event
            await self.koi_node.emit_new_event(bundle)
            self.logger.info("Sent heartbeat event to register with coordinator")

        except Exception as e:
            self.logger.error(f"Error sending heartbeat: {e}")

    async def run(self):
        """Main sensor loop"""
        self.logger.info("Starting Telegram KOI Sensor")

        # Start KOI node
        await self.koi_node.start()

        # Send startup/heartbeat event to register with coordinator
        await self.send_heartbeat_event()

        # Setup Telegram bot
        if not await self.setup_telegram():
            self.logger.error("Failed to setup Telegram bot. Check credentials and permissions.")
            self.logger.info("Sensor will run in passive mode (processing events only)")

            # Keep running for event processing
            try:
                while True:
                    await asyncio.sleep(60)
            except KeyboardInterrupt:
                self.logger.info("Shutting down Telegram sensor")
            finally:
                self.koi_node.stop()
            return

        # Fetch initial message history
        await self.fetch_message_history()

        # Start polling for updates
        self.logger.info("Starting Telegram update polling")

        try:
            # Initialize and start polling
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()

            # Keep running
            while True:
                await asyncio.sleep(60)

        except KeyboardInterrupt:
            self.logger.info("Shutting down Telegram sensor")
        except Exception as e:
            self.logger.error(f"Sensor error: {e}")
            raise
        finally:
            # Cleanup
            if self.application:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            self.koi_node.stop()


async def main():
    """Main entry point"""
    # Load environment variables from .env file
    from dotenv import load_dotenv
    load_dotenv()

    # Create configuration
    config = TelegramConfig()

    # Load from environment variables
    config.bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    config.bot_username = os.getenv('TELEGRAM_BOT_USERNAME', '')
    config.channel_username = os.getenv('TELEGRAM_CHANNEL', '@regen_network_pub')

    if not config.bot_token:
        print("Error: TELEGRAM_BOT_TOKEN not set in environment or .env file")
        sys.exit(1)

    if os.getenv('KOI_COORDINATOR_URL'):
        config.coordinator_url = os.getenv('KOI_COORDINATOR_URL')

    # Create and run sensor
    sensor = TelegramKOISensor(config)
    await sensor.run()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
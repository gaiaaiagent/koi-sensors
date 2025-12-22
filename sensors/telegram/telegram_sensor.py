"""
KOI Telegram Sensor - Channel message collector
Collects messages from Telegram channels/groups using bot API
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import hashlib
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import telegram library
try:
    from telegram import Bot
    from telegram.error import TelegramError
except ImportError:
    print("Error: python-telegram-bot not installed")
    print("Run: pip install python-telegram-bot")
    exit(1)

# Import KOI protocol
import sys
import httpx
sys.path.append(str(Path(__file__).parent.parent.parent))

try:
    from koi_protocol.nodes.koi_node import KOIPartialNode
    from koi_protocol.core.bundle_system import document_to_bundle
    from shared.persistent_state import PersistentSensorState
except ImportError:
    print("Error: KOI protocol not found")
    print("Ensure you're running from the koi-sensors directory")
    exit(1)


@dataclass
class TelegramConfig:
    """Telegram sensor configuration"""
    bot_token: str
    channel_username: str  # e.g., @regen_network_pub
    koi_coordinator_url: str = "http://localhost:8005"
    source_sensor: str = "telegram-sensor"
    
    # Collection settings
    message_limit: int = 100  # Number of recent messages to fetch
    include_media: bool = False  # Whether to include media descriptions
    
    @classmethod
    def from_env(cls):
        """Create config from environment variables"""
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        channel = os.getenv("TELEGRAM_CHANNEL", "@regen_network_pub")
        
        if not bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not found in environment")
        
        return cls(
            bot_token=bot_token,
            channel_username=channel,
            koi_coordinator_url=os.getenv("KOI_COORDINATOR_URL", "http://localhost:8005")
        )


class TelegramSensor:
    """Sensor for Telegram channel messages"""

    def __init__(self, config: TelegramConfig, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.bot = Bot(token=config.bot_token)

        # Persistent state for deterministic message tracking (replaces processed_message_ids)
        self.state = PersistentSensorState('telegram', Path(__file__).parent)

        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name=self.config.source_sensor,
            coordinator_url=self.config.koi_coordinator_url,
            poll_interval=30  # Poll coordinator every 30 seconds
        )
    
    async def test_connection(self) -> bool:
        """Test bot connection and permissions"""
        try:
            # Get bot info
            bot_info = await self.bot.get_me()
            self.logger.info(f"Connected as bot: @{bot_info.username}")
            
            # Try to get chat info
            try:
                chat = await self.bot.get_chat(self.config.channel_username)
                self.logger.info(f"Connected to channel: {chat.title} ({chat.type})")
                
                # Check if bot is member of the channel
                try:
                    member = await self.bot.get_chat_member(chat.id, bot_info.id)
                    self.logger.info(f"Bot status in channel: {member.status}")
                    return True
                except Exception as e:
                    self.logger.error(f"Bot is not a member of the channel: {e}")
                    self.logger.info("Please add the bot to the channel as an administrator")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Cannot access channel {self.config.channel_username}: {e}")
                return False
                
        except Exception as e:
            self.logger.error(f"Bot connection failed: {e}")
            return False
    
    async def collect_channel_history(self) -> List[Dict[str, Any]]:
        """
        Collect message history from channel
        Note: Telegram Bot API has limitations on accessing message history
        """
        documents = []
        
        try:
            # Get chat info
            chat = await self.bot.get_chat(self.config.channel_username)
            chat_id = chat.id
            
            self.logger.info(f"Collecting from {chat.title}")
            
            # Note: Bot API doesn't have a direct way to get message history
            # We'll need to either:
            # 1. Use channel updates (forward messages to bot)
            # 2. Use MTProto API (requires user account, not bot)
            # 3. Set up webhook to receive new messages going forward
            
            # For now, we'll collect channel info as a document
            channel_doc = self.create_channel_info_document(chat)
            if channel_doc:
                documents.append(channel_doc)
            
            # Get pinned message if exists
            if chat.pinned_message:
                pinned_doc = self.create_message_document(chat.pinned_message, chat)
                if pinned_doc:
                    documents.append(pinned_doc)
                    self.logger.info(f"Collected pinned message")
            
            # Note about limitations
            self.logger.warning(
                "Note: Telegram Bot API cannot access full message history. "
                "To collect all messages, consider: "
                "1) Setting up a webhook for new messages "
                "2) Using userbot with MTProto API "
                "3) Exporting chat history manually"
            )
            
        except Exception as e:
            self.logger.error(f"Error collecting channel history: {e}")
        
        return documents
    
    def create_channel_info_document(self, chat) -> Optional[Dict[str, Any]]:
        """Create document from channel information"""
        try:
            # Generate RID
            rid = f"telegram:channel:{chat.id}:info"
            
            # Skip if already processed
            if self.state.is_processed(rid):
                return None
            
            # Create content
            content = f"""# {chat.title}

Type: {chat.type}
Username: @{chat.username if chat.username else 'N/A'}
Members: {chat.get_member_count() if hasattr(chat, 'get_member_count') else 'Unknown'}

## Description
{chat.description if chat.description else 'No description available'}

## Bio
{chat.bio if hasattr(chat, 'bio') and chat.bio else 'No bio available'}
"""
            
            # Create document
            doc = {
                "rid": rid,
                "source": "telegram",
                "channel_id": str(chat.id),
                "channel_username": f"@{chat.username}" if chat.username else None,
                "channel_title": chat.title,
                "content": content,
                "metadata": {
                    "type": "channel_info",
                    "chat_type": chat.type,
                    "has_protected_content": chat.has_protected_content if hasattr(chat, 'has_protected_content') else False,
                    "collected_at": datetime.now(timezone.utc).isoformat()
                }
            }
            
            return doc
            
        except Exception as e:
            self.logger.error(f"Error creating channel info document: {e}")
            return None
    
    def create_message_document(self, message, chat) -> Optional[Dict[str, Any]]:
        """Create document from a Telegram message"""
        try:
            # Generate RID
            rid = f"telegram:channel:{chat.id}:message:{message.message_id}"
            
            # Skip if already processed
            if self.state.is_processed(rid):
                return None
            
            # Extract content
            content = ""
            
            # Text content
            if message.text:
                content = message.text
            elif message.caption:
                content = message.caption
            
            # Add media descriptions if configured
            if self.config.include_media:
                if message.photo:
                    content += "\n[Photo attached]"
                if message.video:
                    content += "\n[Video attached]"
                if message.document:
                    content += f"\n[Document: {message.document.file_name}]"
                if message.audio:
                    content += f"\n[Audio: {message.audio.title or 'Untitled'}]"
            
            if not content:
                return None
            
            # Extract author info
            author = "Unknown"
            author_id = None
            if message.from_user:
                author = message.from_user.full_name
                author_id = str(message.from_user.id)
            elif message.sender_chat:
                author = message.sender_chat.title
                author_id = str(message.sender_chat.id)
            
            # Create document
            doc = {
                "rid": rid,
                "source": "telegram",
                "channel_id": str(chat.id),
                "channel_username": f"@{chat.username}" if chat.username else None,
                "channel_title": chat.title,
                "message_id": message.message_id,
                "content": content,
                "metadata": {
                    "type": "message",
                    "author": author,
                    "author_id": author_id,
                    "date": message.date.isoformat() if message.date else None,
                    "reply_to": message.reply_to_message.message_id if message.reply_to_message else None,
                    "has_media": bool(message.photo or message.video or message.document),
                    "collected_at": datetime.now(timezone.utc).isoformat()
                }
            }
            
            # Add URL if message has link
            if chat.username and message.message_id:
                doc["url"] = f"https://t.me/{chat.username}/{message.message_id}"
            
            return doc
            
        except Exception as e:
            self.logger.error(f"Error creating message document: {e}")
            return None
    
    async def send_to_koi(self, documents: List[Dict[str, Any]]) -> int:
        """Send documents to KOI coordinator"""
        success_count = 0

        for doc in documents:
            try:
                rid = doc.get("rid", "unknown")
                self.state.mark_pending(self.config.channel_username, rid)

                # Create bundle from document
                bundle = document_to_bundle(doc, source_node=self.config.source_sensor)

                # Calculate content hash
                content = doc.get('content', '')
                content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
                # Check if content changed
                previous_hash = self.state.metadata.get(f"hash_{rid}")

                if previous_hash and previous_hash != content_hash:
                    # Content changed - emit UPDATE
                    success = await self.koi_node.emit_update_event(bundle)
                    if success:
                        self.logger.info(f"UPDATE: {rid}")
                        success_count += 1
                elif not previous_hash:
                    # New content - emit NEW
                    success = await self.koi_node.emit_new_event(bundle)
                    if success:
                        self.logger.info(f"NEW: {rid}")
                        success_count += 1
                else:
                    # No change - skip
                    self.logger.debug(f"SKIP (no change): {rid}")
                    self.state.mark_processed(self.config.channel_username, rid)
                    continue

                if success:
                    # Store hash
                    self.state.metadata[f"hash_{rid}"] = content_hash
                    self.state.mark_processed(self.config.channel_username, rid)
                else:
                    self.state.clear_pending(self.config.channel_username, rid)

            except Exception as e:
                self.state.clear_pending(self.config.channel_username, rid)
                self.logger.error(f"Error sending document {doc.get('rid', 'unknown')}: {e}")
                continue

        return success_count
    
    async def run_once(self):
        """Run sensor once to collect and send data"""
        try:
            # Test connection
            self.logger.info("Testing Telegram bot connection...")
            if not await self.test_connection():
                self.logger.error("Bot connection test failed")
                return

            # Collect documents
            self.logger.info("Collecting channel information...")
            documents = await self.collect_channel_history()

            if documents:
                self.logger.info(f"Collected {len(documents)} documents")

                # Save locally for inspection
                output_dir = Path("output")
                output_dir.mkdir(exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = output_dir / f"telegram_{timestamp}.json"

                with open(output_file, 'w') as f:
                    json.dump(documents, f, indent=2)

                self.logger.info(f"Saved to {output_file}")

                # Send to KOI
                success_count = await self.send_to_koi(documents)

                # Save persistent state after processing
                self.state.save()
                self.logger.info(f"Sent {success_count}/{len(documents)} documents to KOI")
            else:
                self.logger.info("No new documents to process")

        except Exception as e:
            self.logger.error(f"Error in sensor run: {e}")

    async def send_heartbeat_event(self):
        """Send heartbeat event to coordinator"""
        try:
            heartbeat_event = {
                "rid": f"telegram:heartbeat:{int(datetime.now().timestamp())}",
                "event_type": "HEARTBEAT",
                "source_node": self.config.source_sensor,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "status": "active",
                    "message": "Telegram sensor is running",
                    "channel": self.config.channel_username
                }
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.config.koi_coordinator_url}/events/broadcast",
                    json=heartbeat_event,
                    timeout=30.0
                )

                if response.status_code == 200:
                    self.logger.debug("Sent heartbeat event")
                else:
                    self.logger.warning(f"Failed to send heartbeat: {response.status_code}")

        except Exception as e:
            self.logger.error(f"Error sending heartbeat: {e}")

    async def send_periodic_heartbeats(self):
        """Send heartbeat events every 30 minutes"""
        while True:
            try:
                await self.send_heartbeat_event()
                await asyncio.sleep(1800)  # 30 minutes
            except Exception as e:
                self.logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(60)  # Retry after 1 minute on error

    async def handle_coordinator_events(self):
        """Handle events from the coordinator"""
        while True:
            try:
                # KOIPartialNode polls automatically, just sleep for now
                await asyncio.sleep(30)

            except asyncio.CancelledError:
                self.logger.info("Coordinator event handler cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error handling coordinator events: {e}")
                await asyncio.sleep(30)  # Wait before retrying

    async def start(self):
        """Start the sensor in continuous mode with heartbeats"""
        try:
            # Start KOI node
            await self.koi_node.start()
            self.logger.info(f"Started KOI node: {self.config.source_sensor}")

            # Test connection
            if not await self.test_connection():
                self.logger.error("Bot connection test failed, will retry...")
                # Don't exit, keep trying

            # Send initial heartbeat
            await self.send_heartbeat_event()
            self.logger.info("Sent startup heartbeat")

            # Start background tasks
            heartbeat_task = asyncio.create_task(self.send_periodic_heartbeats())
            coordinator_task = asyncio.create_task(self.handle_coordinator_events())

            # Initial collection
            await self.run_once()

            # Main monitoring loop - check every hour
            while True:
                await asyncio.sleep(3600)  # Wait 1 hour

                # Collect and send new data
                self.logger.info("Running periodic collection...")
                await self.run_once()

        except Exception as e:
            self.logger.error(f"Error in sensor start: {e}")
            raise


async def main():
    """Run the Telegram sensor in continuous mode"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

    try:
        # Load configuration from environment
        config = TelegramConfig.from_env()

        # Create and start sensor in continuous mode
        sensor = TelegramSensor(config, logger)
        await sensor.start()  # Changed from run_once() to start()

    except Exception as e:
        logger.error(f"Failed to run Telegram sensor: {e}")


if __name__ == "__main__":
    asyncio.run(main())

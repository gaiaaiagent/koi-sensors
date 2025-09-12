"""
Draft Storage - Handles storage of draft threads in JSON and PostgreSQL
"""

import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import asyncpg
from loguru import logger


class DraftStorage:
    """
    Manages storage of draft threads in both JSON files and PostgreSQL
    Provides persistence for review and approval workflow
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize with configuration"""
        self.config = config
        self.db_url = config.get('database_url', 'postgresql://postgres:postgres@localhost:5433/eliza')
        
        # File storage paths
        output_config = config.get('output', {})
        self.draft_path = Path(output_config.get('draft_path', 'bots/drafts'))
        self.draft_path.mkdir(parents=True, exist_ok=True)
        
        # Database connection pool
        self.pool = None
        
    async def initialize_db(self):
        """Initialize database connection and create tables if needed"""
        try:
            self.pool = await asyncpg.create_pool(self.db_url)
            
            # Create draft table if it doesn't exist
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS x_bot_drafts (
                        draft_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        thread_date TIMESTAMPTZ NOT NULL,
                        curator_output JSONB NOT NULL,
                        draft_posts JSONB NOT NULL,
                        status VARCHAR(20) DEFAULT 'draft',
                        review_notes TEXT,
                        style_score FLOAT,
                        link_validation JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW(),
                        published_at TIMESTAMPTZ,
                        tweet_ids JSONB
                    );
                    
                    CREATE INDEX IF NOT EXISTS idx_drafts_status ON x_bot_drafts(status);
                    CREATE INDEX IF NOT EXISTS idx_drafts_date ON x_bot_drafts(thread_date);
                ''')
                
                logger.info("Database initialized for draft storage")
                
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            # Continue with file-only storage if DB fails
            self.pool = None
    
    async def save_draft(self, 
                        thread: Dict[str, Any], 
                        curator_output: Dict[str, Any],
                        status: str = 'draft') -> str:
        """
        Save a draft thread to storage
        
        Args:
            thread: Processed thread data
            curator_output: Original curator output
            status: Draft status (draft/approved/rejected/published)
            
        Returns:
            Draft ID (UUID)
        """
        draft_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        
        # Prepare draft data
        draft_data = {
            'draft_id': draft_id,
            'thread_date': thread.get('thread_date', timestamp.isoformat()),
            'status': status,
            'posts': thread.get('posts', []),
            'style_score': thread.get('style_score', 0),
            'validation': thread.get('validation', {}),
            'metadata': thread.get('metadata', {}),
            'curator_output': curator_output,
            'created_at': timestamp.isoformat(),
            'updated_at': timestamp.isoformat()
        }
        
        # Save to JSON file
        json_path = await self._save_to_json(draft_id, draft_data)
        logger.info(f"Saved draft to JSON: {json_path}")
        
        # Save to database if available
        if self.pool is None:
            await self.initialize_db()
        
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute('''
                        INSERT INTO x_bot_drafts 
                        (draft_id, thread_date, curator_output, draft_posts, 
                         status, style_score, link_validation, created_at, updated_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ''',
                    uuid.UUID(draft_id),
                    datetime.fromisoformat(draft_data['thread_date'].replace('Z', '+00:00')),
                    json.dumps(curator_output),
                    json.dumps(thread.get('posts', [])),
                    status,
                    thread.get('style_score', 0),
                    json.dumps(thread.get('validation', {})),
                    timestamp,
                    timestamp
                    )
                    
                logger.info(f"Saved draft to database: {draft_id}")
                
            except Exception as e:
                logger.error(f"Failed to save draft to database: {e}")
        
        return draft_id
    
    async def _save_to_json(self, draft_id: str, draft_data: Dict[str, Any]) -> Path:
        """Save draft to JSON file"""
        filename = f"draft_{draft_id[:8]}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        file_path = self.draft_path / filename
        
        with open(file_path, 'w') as f:
            json.dump(draft_data, f, indent=2, default=str)
        
        return file_path
    
    async def get_draft(self, draft_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a draft by ID
        
        Args:
            draft_id: UUID of the draft
            
        Returns:
            Draft data or None if not found
        """
        # Try database first
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow('''
                        SELECT * FROM x_bot_drafts WHERE draft_id = $1
                    ''', uuid.UUID(draft_id))
                    
                    if row:
                        return {
                            'draft_id': str(row['draft_id']),
                            'thread_date': row['thread_date'].isoformat(),
                            'posts': json.loads(row['draft_posts']),
                            'status': row['status'],
                            'review_notes': row['review_notes'],
                            'style_score': row['style_score'],
                            'validation': json.loads(row['link_validation']) if row['link_validation'] else {},
                            'curator_output': json.loads(row['curator_output']),
                            'created_at': row['created_at'].isoformat(),
                            'updated_at': row['updated_at'].isoformat(),
                            'published_at': row['published_at'].isoformat() if row['published_at'] else None,
                            'tweet_ids': json.loads(row['tweet_ids']) if row['tweet_ids'] else []
                        }
                        
            except Exception as e:
                logger.error(f"Failed to get draft from database: {e}")
        
        # Fallback to JSON files
        for json_file in self.draft_path.glob(f"draft_{draft_id[:8]}*.json"):
            with open(json_file, 'r') as f:
                data = json.load(f)
                if data.get('draft_id') == draft_id:
                    return data
        
        return None
    
    async def update_draft_status(self, 
                                  draft_id: str, 
                                  status: str, 
                                  notes: str = "") -> bool:
        """
        Update the status of a draft
        
        Args:
            draft_id: UUID of the draft
            status: New status (approved/rejected/published)
            notes: Review notes
            
        Returns:
            Success status
        """
        timestamp = datetime.now(timezone.utc)
        
        # Update in database if available
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    result = await conn.execute('''
                        UPDATE x_bot_drafts 
                        SET status = $1, review_notes = $2, updated_at = $3,
                            published_at = CASE WHEN $1 = 'published' THEN $3 ELSE published_at END
                        WHERE draft_id = $4
                    ''', status, notes, timestamp, uuid.UUID(draft_id))
                    
                    if result.split()[-1] == '1':
                        logger.info(f"Updated draft {draft_id} status to {status}")
                        return True
                        
            except Exception as e:
                logger.error(f"Failed to update draft status in database: {e}")
        
        # Update JSON file
        draft = await self.get_draft(draft_id)
        if draft:
            draft['status'] = status
            draft['review_notes'] = notes
            draft['updated_at'] = timestamp.isoformat()
            if status == 'published':
                draft['published_at'] = timestamp.isoformat()
            
            await self._save_to_json(draft_id, draft)
            return True
        
        return False
    
    async def list_drafts(self, 
                          status: Optional[str] = None,
                          limit: int = 10) -> List[Dict[str, Any]]:
        """
        List drafts with optional filtering
        
        Args:
            status: Filter by status (optional)
            limit: Maximum number of drafts to return
            
        Returns:
            List of draft summaries
        """
        drafts = []
        
        # Try database first
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    if status:
                        rows = await conn.fetch('''
                            SELECT draft_id, thread_date, status, style_score, created_at
                            FROM x_bot_drafts 
                            WHERE status = $1
                            ORDER BY created_at DESC
                            LIMIT $2
                        ''', status, limit)
                    else:
                        rows = await conn.fetch('''
                            SELECT draft_id, thread_date, status, style_score, created_at
                            FROM x_bot_drafts 
                            ORDER BY created_at DESC
                            LIMIT $1
                        ''', limit)
                    
                    for row in rows:
                        drafts.append({
                            'draft_id': str(row['draft_id']),
                            'thread_date': row['thread_date'].isoformat(),
                            'status': row['status'],
                            'style_score': row['style_score'],
                            'created_at': row['created_at'].isoformat()
                        })
                    
                    return drafts
                    
            except Exception as e:
                logger.error(f"Failed to list drafts from database: {e}")
        
        # Fallback to JSON files
        json_files = sorted(self.draft_path.glob("draft_*.json"), reverse=True)[:limit]
        for json_file in json_files:
            with open(json_file, 'r') as f:
                data = json.load(f)
                if not status or data.get('status') == status:
                    drafts.append({
                        'draft_id': data.get('draft_id'),
                        'thread_date': data.get('thread_date'),
                        'status': data.get('status'),
                        'style_score': data.get('style_score', 0),
                        'created_at': data.get('created_at')
                    })
        
        return drafts[:limit]
    
    async def cleanup(self):
        """Clean up database connections"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")
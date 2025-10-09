"""
Contradiction Detection for Knowledge Graph

Identifies conflicting statements across extractions with complete source URL preservation.
Uses LLM-assisted detection to classify contradiction types.
"""

import asyncpg
import asyncio
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
import os
from loguru import logger
import json

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI not available - contradiction detection will be limited")


class ContradictionDetector:
    """Detects contradictions between statements in the knowledge graph"""

    CONTRADICTION_TYPES = [
        'temporal',      # Time-based conflicts (e.g., "happened in 2020" vs "happened in 2021")
        'factual',       # Direct factual conflicts (e.g., "is red" vs "is blue")
        'attribution',   # Disagreement about who did/said something
        'quantitative',  # Numerical conflicts (e.g., "$100" vs "$200")
        'categorical'    # Category conflicts (e.g., "is a person" vs "is an organization")
    ]

    def __init__(
        self,
        db_url: str,
        openai_api_key: Optional[str] = None,
        model: str = 'gpt-5-mini',
        use_llm: bool = True
    ):
        """
        Initialize contradiction detector

        Args:
            db_url: PostgreSQL connection URL
            openai_api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: OpenAI model to use for detection
            use_llm: Whether to use LLM for detection (False = rule-based only)
        """
        self.db_url = db_url
        self.use_llm = use_llm and OPENAI_AVAILABLE

        if self.use_llm:
            api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
            if not api_key:
                logger.warning("No OpenAI API key provided - using rule-based detection only")
                self.use_llm = False
            else:
                self.client = AsyncOpenAI(api_key=api_key)
                self.model = model

    async def detect_all_contradictions(
        self,
        entity_type: Optional[str] = None,
        min_confidence: float = 0.7
    ) -> List[Dict]:
        """
        Detect all contradictions in the knowledge graph

        Args:
            entity_type: Optional filter by entity type
            min_confidence: Minimum confidence threshold for contradiction detection

        Returns:
            List of contradiction records
        """
        conn = await asyncpg.connect(self.db_url)

        try:
            # Get all statements with their metadata
            query = """
                SELECT
                    s->>'rid' as statement_rid,
                    s->>'statementType' as statement_type,
                    s->>'subject' as subject,
                    s->>'predicate' as predicate,
                    s->>'object' as object,
                    s->>'confidence' as confidence,
                    kg.extraction_rid,
                    kg.memory_rid,
                    mem.metadata->>'url' as source_url,
                    kg.created_at
                FROM koi_kg_extractions kg
                JOIN koi_memories mem ON kg.memory_rid = mem.rid
                CROSS JOIN jsonb_array_elements(kg.statements) AS s
                WHERE s->>'subject' IS NOT NULL
                  AND s->>'predicate' IS NOT NULL
                  AND s->>'object' IS NOT NULL
                  AND CAST(s->>'confidence' AS FLOAT) >= $1
            """

            params = [min_confidence]

            if entity_type:
                # Filter by entity type if needed (would require entity reference in statement)
                pass

            rows = await conn.fetch(query, *params)

            # Convert to list of dicts
            statements = [
                {
                    'rid': row['statement_rid'],
                    'type': row['statement_type'],
                    'subject': row['subject'],
                    'predicate': row['predicate'],
                    'object': row['object'],
                    'text': f"{row['subject']} {row['predicate']} {row['object']}",  # Construct text from SPO
                    'confidence': float(row['confidence']) if row['confidence'] else 0.0,
                    'extraction_rid': row['extraction_rid'],
                    'memory_rid': row['memory_rid'],
                    'source_url': row['source_url'],
                    'created_at': row['created_at']
                }
                for row in rows
            ]

            logger.info(f"Analyzing {len(statements)} statements for contradictions")

            # Find contradictions
            contradictions = await self._find_contradictions(statements, min_confidence)

            logger.info(f"Found {len(contradictions)} contradictions")

            # Store in database
            for contradiction in contradictions:
                await self._store_contradiction(conn, contradiction)

            return contradictions

        finally:
            await conn.close()

    async def _find_contradictions(
        self,
        statements: List[Dict],
        min_confidence: float
    ) -> List[Dict]:
        """
        Find contradictions between statements

        Uses both rule-based and LLM-based detection
        """
        contradictions = []
        n = len(statements)

        # Compare all pairs of statements
        for i in range(n):
            for j in range(i + 1, n):
                s1, s2 = statements[i], statements[j]

                # Skip if same extraction (not a contradiction across sources)
                if s1['extraction_rid'] == s2['extraction_rid']:
                    continue

                # Quick filter: only compare statements about similar subjects
                if not self._similar_subjects(s1, s2):
                    continue

                # Check for contradiction
                contradiction = await self._check_contradiction(s1, s2, min_confidence)

                if contradiction:
                    contradictions.append(contradiction)

        return contradictions

    def _similar_subjects(self, s1: Dict, s2: Dict) -> bool:
        """
        Check if two statements are about similar subjects

        Quick filter to avoid comparing unrelated statements
        """
        # If subjects are provided, compare them
        if s1.get('subject') and s2.get('subject'):
            subj1 = s1['subject'].lower().strip()
            subj2 = s2['subject'].lower().strip()

            # Exact match or substring match
            if subj1 == subj2 or subj1 in subj2 or subj2 in subj1:
                return True

        # Otherwise, look for common words in text (simple heuristic)
        text1_words = set(s1['text'].lower().split())
        text2_words = set(s2['text'].lower().split())

        # At least 3 common words (excluding common stopwords)
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'is', 'are', 'was', 'were'}
        common = (text1_words & text2_words) - stopwords

        return len(common) >= 3

    async def _check_contradiction(
        self,
        s1: Dict,
        s2: Dict,
        min_confidence: float
    ) -> Optional[Dict]:
        """
        Check if two statements contradict each other

        Returns contradiction dict if found, None otherwise
        """
        # Try rule-based detection first (fast)
        rule_based = self._rule_based_contradiction(s1, s2)

        if rule_based:
            return rule_based

        # Try LLM-based detection (slower but more accurate)
        if self.use_llm:
            llm_based = await self._llm_based_contradiction(s1, s2, min_confidence)
            if llm_based:
                return llm_based

        return None

    def _rule_based_contradiction(self, s1: Dict, s2: Dict) -> Optional[Dict]:
        """
        Rule-based contradiction detection

        Handles simple cases like:
        - Negation ("is X" vs "is not X")
        - Opposite predicates ("increase" vs "decrease")
        """
        # Check for negation
        text1 = s1['text'].lower()
        text2 = s2['text'].lower()

        # Remove negation and see if texts are similar
        text1_no_neg = text1.replace('not ', '').replace("n't ", ' ')
        text2_no_neg = text2.replace('not ', '').replace("n't ", ' ')

        # If texts are similar after negation removal, it's likely a contradiction
        if self._text_similarity(text1_no_neg, text2_no_neg) > 0.8:
            # Check if one is negated and the other isn't
            has_neg1 = 'not ' in text1 or "n't " in text1
            has_neg2 = 'not ' in text2 or "n't " in text2

            if has_neg1 != has_neg2:  # XOR - one is negated, other isn't
                return self._create_contradiction_record(s1, s2, 'factual', 0.9, 'rule_based_negation')

        return None

    def _text_similarity(self, text1: str, text2: str) -> float:
        """Simple text similarity using Jaccard index"""
        words1 = set(text1.split())
        words2 = set(text2.split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    async def _llm_based_contradiction(
        self,
        s1: Dict,
        s2: Dict,
        min_confidence: float
    ) -> Optional[Dict]:
        """
        LLM-based contradiction detection

        Uses GPT to determine if statements contradict
        """
        try:
            prompt = f"""Analyze if these two statements contradict each other.

Statement 1: {s1['text']}
Source 1: {s1['source_url']}

Statement 2: {s2['text']}
Source 2: {s2['source_url']}

Respond with JSON:
{{
    "contradicts": true/false,
    "contradiction_type": "temporal|factual|attribution|quantitative|categorical|none",
    "confidence": 0.0-1.0,
    "explanation": "Brief explanation of why they contradict or don't"
}}

Only mark as contradiction if statements make CONFLICTING claims about the same entity/fact.
Do NOT mark as contradiction if they're just about different aspects or complementary information.
"""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a precise fact-checker. Only identify clear contradictions."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=300
            )

            result = json.loads(response.choices[0].message.content)

            if result.get('contradicts') and result.get('confidence', 0) >= min_confidence:
                return self._create_contradiction_record(
                    s1, s2,
                    result.get('contradiction_type', 'factual'),
                    result['confidence'],
                    f"llm_detection: {result.get('explanation', 'No explanation')}"
                )

        except Exception as e:
            logger.warning(f"LLM contradiction detection failed: {e}")

        return None

    def _create_contradiction_record(
        self,
        s1: Dict,
        s2: Dict,
        contradiction_type: str,
        confidence: float,
        detection_method: str
    ) -> Dict:
        """Create contradiction record with full provenance"""
        return {
            'statement1_rid': s1['rid'],
            'statement1_url': s1['source_url'],
            'statement1_text': s1['text'],
            'statement2_rid': s2['rid'],
            'statement2_url': s2['source_url'],
            'statement2_text': s2['text'],
            'contradiction_type': contradiction_type,
            'confidence_score': confidence,
            'detection_method': detection_method,
            'detected_at': datetime.now(timezone.utc)
        }

    async def _store_contradiction(self, conn: asyncpg.Connection, contradiction: Dict):
        """
        Store contradiction in database

        Includes foreign key references to extractions and transformation receipts
        """
        try:
            # Get extraction IDs for foreign keys
            s1_extraction = await conn.fetchval(
                "SELECT id FROM koi_kg_extractions WHERE $1 LIKE extraction_rid || '%'",
                contradiction['statement1_rid']
            )
            s2_extraction = await conn.fetchval(
                "SELECT id FROM koi_kg_extractions WHERE $1 LIKE extraction_rid || '%'",
                contradiction['statement2_rid']
            )

            # Build contradiction details JSON
            details = {
                'statement1_text': contradiction['statement1_text'],
                'statement2_text': contradiction['statement2_text'],
                'confidence_score': contradiction['confidence_score'],
                'detection_method': contradiction['detection_method'],
                'detected_at': contradiction['detected_at'].isoformat()
            }

            # Insert contradiction
            await conn.execute("""
                INSERT INTO koi_kg_contradictions (
                    statement1_rid, statement1_url,
                    statement2_rid, statement2_url,
                    contradiction_type, contradiction_details,
                    statement1_extraction_id, statement2_extraction_id,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (statement1_rid, statement2_rid) DO UPDATE SET
                    contradiction_details = EXCLUDED.contradiction_details,
                    updated_at = $9
            """,
                contradiction['statement1_rid'],
                contradiction['statement1_url'],
                contradiction['statement2_rid'],
                contradiction['statement2_url'],
                contradiction['contradiction_type'],
                json.dumps(details),
                s1_extraction,
                s2_extraction,
                contradiction['detected_at']
            )

            logger.info(
                f"Stored contradiction: {contradiction['contradiction_type']} "
                f"(conf={contradiction['confidence_score']:.2f})"
            )

        except Exception as e:
            logger.error(f"Failed to store contradiction: {e}")

    async def get_contradictions_for_statement(self, statement_rid: str) -> List[Dict]:
        """
        Get all contradictions involving a specific statement

        Args:
            statement_rid: Statement RID to check

        Returns:
            List of contradiction records
        """
        conn = await asyncpg.connect(self.db_url)

        try:
            rows = await conn.fetch("""
                SELECT * FROM koi_kg_contradictions
                WHERE statement1_rid = $1 OR statement2_rid = $1
                ORDER BY confidence_score DESC
            """, statement_rid)

            return [dict(row) for row in rows]

        finally:
            await conn.close()

    async def get_unresolved_contradictions(self) -> List[Dict]:
        """Get all unresolved contradictions"""
        conn = await asyncpg.connect(self.db_url)

        try:
            rows = await conn.fetch("""
                SELECT
                    id, statement1_rid, statement1_url,
                    statement2_rid, statement2_url,
                    contradiction_type, contradiction_details,
                    resolved, created_at
                FROM koi_kg_contradictions
                WHERE resolved = false
                ORDER BY
                    CAST(contradiction_details->>'confidence_score' AS FLOAT) DESC,
                    created_at DESC
            """)

            return [dict(row) for row in rows]

        finally:
            await conn.close()


async def main():
    """Test contradiction detection"""
    db_url = os.getenv('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5433/eliza')

    detector = ContradictionDetector(db_url, use_llm=True)

    logger.info("Detecting contradictions...")
    contradictions = await detector.detect_all_contradictions(min_confidence=0.6)

    print(f"\nFound {len(contradictions)} contradictions:")
    for i, c in enumerate(contradictions[:10], 1):  # Show first 10
        print(f"\n{i}. {c['contradiction_type'].upper()} (confidence={c['confidence_score']:.2f})")
        print(f"   Statement 1: {c['statement1_text'][:80]}...")
        print(f"   Source 1:    {c['statement1_url'][:60]}...")
        print(f"   Statement 2: {c['statement2_text'][:80]}...")
        print(f"   Source 2:    {c['statement2_url'][:60]}...")
        print(f"   Method:      {c['detection_method']}")

    # Check unresolved contradictions
    unresolved = await detector.get_unresolved_contradictions()
    print(f"\n\nTotal unresolved contradictions: {len(unresolved)}")


if __name__ == '__main__':
    asyncio.run(main())

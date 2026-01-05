"""
KOI Knowledge Graph - Pass A Extractor
LLM-based extraction of entities and statements from content

Uses OpenAI GPT-4o-mini to extract:
- Entities: Person, Organization, Project
- Statements: Claims, evidence, questions with confidence scores
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List
from loguru import logger
import openai

from knowledge_graph.extractors.extractor_base import KGExtractorBase
from knowledge_graph.kg_rid_generator import generate_entity_rid, generate_statement_rid


class PassAExtractor(KGExtractorBase):
    """
    Pass A Extractor: LLM-based entity and statement extraction

    This extractor uses OpenAI's GPT-4o-mini to identify and extract:
    - Entities (Person, Organization, Project) with confidence scores
    - Statements (claims, evidence, questions) with confidence scores

    Each extraction generates unique RIDs following the KOI protocol.
    """

    def __init__(self, *args, **kwargs):
        """Initialize Pass A extractor with OpenAI API configuration"""
        super().__init__(*args, **kwargs)
        self.pass_type = "passA"

        # Load OpenAI API key from environment
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY not found in environment. "
                "Please add it to /opt/projects/koi-sensors/.env"
            )

        # Initialize OpenAI client
        self.client = openai.AsyncOpenAI(api_key=self.api_key)

        # Model configuration (read from env or use default)
        self.model = os.getenv('OPENAI_MODEL', 'gpt-5-mini')  # Latest cost-effective model
        self.temperature = 0.1  # Low temperature for consistent extraction
        self.max_tokens = 4000  # Increased for longer content (e.g., podcasts)

        logger.info(f"Initialized PassAExtractor with model={self.model}")

    async def extract(self, content: str) -> Dict[str, Any]:
        """
        Extract entities and statements from content using LLM

        Args:
            content: The text content to extract from

        Returns:
            Dict containing:
                - entities: List of extracted entities with RIDs
                - statements: List of extracted statements with RIDs
                - relations: List (empty for Pass A)
                - confidence_avg: Average confidence score
                - tokens_consumed: Total tokens used
                - cost_usd: Estimated cost in USD
        """
        logger.info(f"Starting Pass A extraction for content ({len(content)} chars)")

        # Load prompt template
        prompt_template = self._load_prompt_template()

        # Format prompt with content
        prompt = prompt_template.replace('{content}', content)

        # Call GPT-4o-mini
        response = await self._call_gpt(prompt)

        # Parse response JSON
        extraction_data = self._parse_response(response)

        # Generate RIDs for entities and statements
        # Note: We need a parent_rid for RID generation, but extract() doesn't receive it
        # The parent_rid will be passed when extract_and_track() is called
        # For now, we'll use a placeholder and RIDs will be generated properly in extract_and_track
        entities_with_rids = extraction_data.get('entities', [])
        statements_with_rids = extraction_data.get('statements', [])

        # Calculate metrics
        avg_confidence = self._calculate_avg_confidence(entities_with_rids + statements_with_rids)
        tokens_consumed = response.get('usage', {}).get('total_tokens', 0)
        cost_usd = self._calculate_cost(response)

        result = {
            'entities': entities_with_rids,
            'statements': statements_with_rids,
            'relations': [],  # Pass A doesn't extract relations
            'confidence_avg': avg_confidence,
            'tokens_consumed': tokens_consumed,
            'cost_usd': cost_usd
        }

        logger.info(
            f"✓ Pass A extraction complete: "
            f"{len(entities_with_rids)} entities, "
            f"{len(statements_with_rids)} statements, "
            f"avg_confidence={avg_confidence:.2f}, "
            f"tokens={tokens_consumed}, "
            f"cost=${cost_usd:.4f}"
        )

        return result

    def _load_prompt_template(self) -> str:
        """Load the Pass A prompt template from file"""
        prompt_path = Path(__file__).parent.parent / 'prompts' / 'pass_a_prompt.txt'

        if not prompt_path.exists():
            raise FileNotFoundError(
                f"Prompt template not found at {prompt_path}. "
                "Please ensure pass_a_prompt.txt exists in knowledge_graph/prompts/"
            )

        with open(prompt_path, 'r') as f:
            return f.read()

    async def _call_gpt(self, prompt: str) -> Dict[str, Any]:
        """
        Call OpenAI GPT-4o-mini API

        Args:
            prompt: The formatted prompt to send

        Returns:
            Dict containing response and usage data
        """
        try:
            # GPT-5-mini uses max_completion_tokens instead of max_tokens
            # and only supports temperature=1 (default)
            if 'gpt-5' in self.model.lower():
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a knowledge extraction assistant. Extract entities and statements from text and return them as valid JSON."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    # temperature not supported for GPT-5, uses default (1)
                    max_completion_tokens=self.max_tokens,
                    response_format={"type": "json_object"}  # Enforce JSON response
                )
            else:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a knowledge extraction assistant. Extract entities and statements from text and return them as valid JSON."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"}  # Enforce JSON response
                )

            # Extract content and usage
            content = response.choices[0].message.content
            usage = {
                'prompt_tokens': response.usage.prompt_tokens,
                'completion_tokens': response.usage.completion_tokens,
                'total_tokens': response.usage.total_tokens
            }

            return {
                'content': content,
                'usage': usage,
                'model': response.model
            }

        except Exception as e:
            logger.error(f"Error calling OpenAI API: {e}")
            raise

    def _parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse the JSON response from GPT

        Args:
            response: Response dict from _call_gpt

        Returns:
            Dict with entities and statements arrays
        """
        try:
            content = response['content']
            data = json.loads(content)

            # Validate expected structure
            if 'entities' not in data:
                logger.warning("Response missing 'entities' array, defaulting to empty")
                data['entities'] = []

            if 'statements' not in data:
                logger.warning("Response missing 'statements' array, defaulting to empty")
                data['statements'] = []

            return data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response content: {response.get('content', 'N/A')}")
            # Return empty extraction on parse failure
            return {'entities': [], 'statements': []}

    def add_rids_to_extraction(
        self,
        extraction_data: Dict[str, Any],
        parent_rid: str
    ) -> Dict[str, Any]:
        """
        Add RIDs to entities and statements after extraction

        This is called by extract_and_track() to add proper RIDs once
        the parent_rid is known.

        Args:
            extraction_data: The extraction result from extract()
            parent_rid: The parent memory/document RID

        Returns:
            Updated extraction_data with RIDs added
        """
        # Add RIDs to entities
        entities_with_rids = []
        for entity in extraction_data.get('entities', []):
            entity_type = entity.get('type', 'unknown').lower()
            entity_name = entity.get('name', 'unknown')

            entity['rid'] = generate_entity_rid(parent_rid, entity_type, entity_name)
            entities_with_rids.append(entity)

        # Add RIDs to statements
        statements_with_rids = []
        for idx, statement in enumerate(extraction_data.get('statements', [])):
            statement_type = statement.get('statementType', 'claim').lower()

            statement['rid'] = generate_statement_rid(parent_rid, statement_type, idx)
            statements_with_rids.append(statement)

        extraction_data['entities'] = entities_with_rids
        extraction_data['statements'] = statements_with_rids

        return extraction_data

    def _calculate_avg_confidence(self, items: List[Dict[str, Any]]) -> float:
        """
        Calculate average confidence across entities and statements

        Args:
            items: List of entities/statements with confidence scores

        Returns:
            Average confidence (0.0-1.0), or 0.0 if no items
        """
        if not items:
            return 0.0

        confidences = [item.get('confidence', 0.0) for item in items]
        return sum(confidences) / len(confidences)

    def _calculate_cost(self, response: Dict[str, Any]) -> float:
        """
        Calculate estimated USD cost based on token usage

        GPT-5-mini pricing (as of 2025):
        - Input: $0.10 per 1M tokens
        - Output: $0.40 per 1M tokens

        (Note: Update pricing if using different model via OPENAI_MODEL env var)

        Args:
            response: Response dict from _call_gpt

        Returns:
            Estimated cost in USD
        """
        usage = response.get('usage', {})
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)

        # Pricing per 1M tokens (gpt-5-mini)
        input_cost_per_1m = 0.10
        output_cost_per_1m = 0.40

        # Calculate costs
        input_cost = (prompt_tokens / 1_000_000) * input_cost_per_1m
        output_cost = (completion_tokens / 1_000_000) * output_cost_per_1m

        return input_cost + output_cost

    async def extract_and_track(
        self,
        memory_rid: str,
        content: str,
        metadata: Dict[str, Any]
    ) -> tuple[str, str]:
        """
        Override to add RID generation after extraction

        This ensures entities and statements have proper RIDs before storage.
        """
        # Extract source_url from metadata
        source_url = metadata.get('source_url')
        if not source_url:
            raise ValueError("source_url is required in metadata")

        logger.info(f"Starting {self.pass_type} extraction for {memory_rid}")

        # Call extraction logic
        extraction_result = await self.extract(content)

        # Add RIDs to entities and statements now that we have parent_rid
        extraction_result = self.add_rids_to_extraction(extraction_result, memory_rid)

        # Continue with base class logic (storage and CAT receipt)
        from knowledge_graph.kg_rid_generator import generate_kg_extraction_rid
        import asyncpg
        from datetime import datetime, timezone

        extraction_rid = generate_kg_extraction_rid(memory_rid, self.pass_type, self.ontology_version)

        conn = await asyncpg.connect(self.db_url)
        try:
            # Store extraction
            await conn.execute("""
                INSERT INTO koi_kg_extractions (
                    memory_rid, extraction_rid, extraction_type,
                    entities, statements, relations,
                    confidence_score, ontology_version, extractor_version,
                    tokens_consumed, cost_usd, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (extraction_rid) DO UPDATE SET
                    entities = $4, statements = $5, updated_at = $12
            """,
                memory_rid,
                extraction_rid,
                self.pass_type,
                json.dumps(extraction_result.get('entities', [])),
                json.dumps(extraction_result.get('statements', [])),
                json.dumps(extraction_result.get('relations', [])),
                extraction_result.get('confidence_avg', 0.0),
                self.ontology_version,
                self.extractor_version,
                extraction_result.get('tokens_consumed', 0),
                extraction_result.get('cost_usd', 0.0),
                datetime.now(timezone.utc)
            )

            logger.info(f"✓ Stored extraction {extraction_rid[:60]}...")

            # Create CAT receipt
            receipt_id = await self.create_extraction_receipt(
                conn, memory_rid, extraction_rid, extraction_result, source_url
            )

            logger.info(f"✓ Completed {self.pass_type} extraction: {extraction_rid[:60]}... (receipt: {receipt_id[:8]}...)")
            return extraction_rid, receipt_id
        finally:
            await conn.close()


# Example usage for testing
async def test_pass_a_extractor():
    """Test Pass A extractor with sample content"""
    import asyncio

    # Sample content
    test_content = """
    Regen Network is developing a blockchain platform for ecological data and carbon credits.
    The organization was founded by Gregory Landua and partners to create transparent
    systems for tracking environmental claims. Their flagship project involves monitoring
    soil carbon sequestration across multiple farms in the midwest.
    """

    # Initialize extractor
    db_url = "postgresql://koi_user:koi_password@localhost:5432/koi_db"
    extractor = PassAExtractor(
        db_url=db_url,
        ontology_version="op-v1.1",
        extractor_version="1.0.0"
    )

    # Test extraction (without tracking)
    result = await extractor.extract(test_content)

    print("\n=== Pass A Extraction Results ===")
    print(f"Entities: {len(result['entities'])}")
    for entity in result['entities']:
        print(f"  - {entity['name']} ({entity['type']}) [confidence: {entity['confidence']}]")

    print(f"\nStatements: {len(result['statements'])}")
    for statement in result['statements']:
        print(f"  - {statement['subject']} {statement['predicate']} {statement['object']}")
        print(f"    Type: {statement['statementType']}, Confidence: {statement['confidence']}")

    print(f"\nMetrics:")
    print(f"  Average Confidence: {result['confidence_avg']:.2f}")
    print(f"  Tokens Consumed: {result['tokens_consumed']}")
    print(f"  Cost: ${result['cost_usd']:.4f}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_pass_a_extractor())

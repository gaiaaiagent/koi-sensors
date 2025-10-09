"""
Unified KG Extractor supporting multiple LLM providers
Supports OpenAI and Anthropic (Claude) models
"""

import json
import os
from typing import Dict, Any
from loguru import logger
import openai
import anthropic

from knowledge_graph.extractors.extractor_base import KGExtractorBase


class UnifiedExtractor(KGExtractorBase):
    """
    Unified extractor supporting multiple LLM providers
    Automatically detects provider from model name
    """

    def __init__(self, model: str = "gpt-4o-mini", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model = model
        self.pass_type = "passA"

        # Detect provider from model name
        if model.startswith("claude"):
            self.provider = "anthropic"
            self.api_key = os.getenv('ANTHROPIC_API_KEY')
            if not self.api_key:
                raise ValueError("ANTHROPIC_API_KEY not found in environment")
            self.client = anthropic.Anthropic(api_key=self.api_key)

        elif model.startswith("gpt") or model.startswith("o1"):
            self.provider = "openai"
            self.api_key = os.getenv('OPENAI_API_KEY')
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY not found in environment")
            self.client = openai.OpenAI(api_key=self.api_key)

        else:
            raise ValueError(f"Unknown model provider for model: {model}")

        # Max tokens for structured JSON output (entities + statements)
        self.max_tokens = 4000
        logger.info(f"Initialized UnifiedExtractor with model={model}, provider={self.provider}, max_tokens={self.max_tokens}")

    def _compact_content(self, content: str, max_chars: int = 2000) -> str:
        """Compact content by removing HTML, URLs, excess whitespace"""
        import re
        import html

        # Unescape HTML entities
        text = html.unescape(content)

        # Strip HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)

        # Remove URLs
        text = re.sub(r'https?://\S+', ' ', text)

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        # Truncate to max_chars (keep beginning which has most important content)
        if len(text) > max_chars:
            text = text[:max_chars] + '...'

        return text

    async def extract(self, content: str) -> Dict[str, Any]:
        """Extract entities and statements using configured LLM"""

        logger.info(f"Starting extraction with {self.provider}/{self.model} ({len(content)} chars)")

        # Load prompt template
        from pathlib import Path
        prompt_path = Path(__file__).parent.parent / 'prompts' / 'pass_a_prompt.txt'
        with open(prompt_path, 'r') as f:
            prompt_template = f.read()

        prompt = prompt_template.replace('{content}', content)

        # Call appropriate provider
        if self.provider == "anthropic":
            response = await self._call_claude(prompt)
        else:
            response = await self._call_openai(prompt)

        # Parse response
        extraction_data = self._parse_response(response)

        # Calculate metrics
        entities = extraction_data.get('entities', [])
        statements = extraction_data.get('statements', [])
        avg_confidence = self._calculate_avg_confidence(entities + statements)
        tokens_consumed = response.get('usage', {}).get('total_tokens', 0)
        cost_usd = self._calculate_cost(response)

        result = {
            'entities': entities,
            'statements': statements,
            'relations': [],
            'confidence_avg': avg_confidence,
            'tokens_consumed': tokens_consumed,
            'cost_usd': cost_usd
        }

        logger.info(
            f"✓ Extraction complete: {len(entities)} entities, {len(statements)} statements, "
            f"confidence={avg_confidence:.2f}, tokens={tokens_consumed}, cost=${cost_usd:.4f}"
        )

        return result

    async def _call_openai(self, prompt: str) -> Dict[str, Any]:
        """Call OpenAI API with retry logic for rate limits"""
        import asyncio
        import random

        max_retries = 5
        base_delay = 1.0
        max_delay = 30.0
        request_timeout = 90.0

        last_error = None
        for attempt in range(max_retries):
            try:
                # Wrap API call in timeout
                async with asyncio.timeout(request_timeout):
                    # Handle GPT-5 models (different parameters - no temperature support, uses max_completion_tokens)
                    if 'gpt-5' in self.model.lower() or 'gpt-4.1' in self.model.lower():
                        response = self.client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {
                                    "role": "system",
                                    "content": "You are a knowledge extraction assistant. Extract entities and statements from text and return them as valid JSON."
                                },
                                {"role": "user", "content": prompt}
                            ],
                            max_completion_tokens=self.max_tokens
                            # Note: GPT-5 models don't support response_format parameter
                        )
                    else:
                        # Standard GPT-4 models support temperature parameter
                        response = self.client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {
                                    "role": "system",
                                    "content": "You are a knowledge extraction assistant. Extract entities and statements from text and return them as valid JSON."
                                },
                                {"role": "user", "content": prompt}
                            ],
                            temperature=0.1,  # Low temperature for deterministic, structured extraction
                            max_tokens=self.max_tokens,
                            response_format={"type": "json_object"}
                        )

                # Success - return response
                break

            except Exception as e:
                last_error = e
                error_msg = str(e).lower()
                status_code = getattr(e, 'status_code', None)
                headers = getattr(e, 'headers', {}) or {}

                is_rate_limit = status_code == 429 or 'rate' in error_msg or 'quota' in error_msg
                is_server_error = (status_code and 500 <= status_code < 600) or '500' in error_msg or '502' in error_msg or '503' in error_msg
                is_timeout = 'timeout' in error_msg or 'timed out' in error_msg

                is_retryable = is_rate_limit or is_server_error or is_timeout

                if not is_retryable or attempt == max_retries - 1:
                    logger.error(f"OpenAI API call failed (non-retryable or max retries, status={status_code}): {e}")
                    raise

                # Check for Retry-After header
                retry_after = headers.get('retry-after') or headers.get('Retry-After')
                if retry_after:
                    try:
                        delay = float(retry_after)
                        logger.warning(f"OpenAI rate limit (attempt {attempt + 1}/{max_retries}), server says retry after {delay}s")
                    except (ValueError, TypeError):
                        delay = None

                # Decorrelated jitter exponential backoff
                if not retry_after:
                    base = min(max_delay, base_delay * (2 ** attempt))
                    delay = random.uniform(base / 2, base)

                logger.warning(f"OpenAI API error (attempt {attempt + 1}/{max_retries}, status={status_code}): {e}. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

        # If we exhausted retries
        if last_error:
            raise last_error

        content = response.choices[0].message.content
        usage = {
            'prompt_tokens': response.usage.prompt_tokens,
            'completion_tokens': response.usage.completion_tokens,
            'total_tokens': response.usage.total_tokens
        }

        return {
            'content': content,
            'usage': usage,
            'model': response.model,
            'provider': 'openai'
        }

    async def _call_claude(self, prompt: str) -> Dict[str, Any]:
        """Call Anthropic Claude API"""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=0.1,  # Low temperature for deterministic, structured extraction
                messages=[
                    {
                        "role": "user",
                        "content": f"You are a knowledge extraction assistant. Extract entities and statements from text and return them as valid JSON.\n\n{prompt}"
                    }
                ]
            )

            content = response.content[0].text
            usage = {
                'prompt_tokens': response.usage.input_tokens,
                'completion_tokens': response.usage.output_tokens,
                'total_tokens': response.usage.input_tokens + response.usage.output_tokens
            }

            return {
                'content': content,
                'usage': usage,
                'model': response.model,
                'provider': 'anthropic'
            }

        except Exception as e:
            logger.error(f"Error calling Anthropic API: {e}")
            raise

    def _parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse JSON response from LLM"""
        try:
            content = response['content']

            # Strip markdown code blocks if present (Claude returns ```json...```)
            if content.strip().startswith('```'):
                content = content.strip()
                # Remove ```json or ``` from start
                if content.startswith('```json'):
                    content = content[7:]
                elif content.startswith('```'):
                    content = content[3:]
                # Find closing ``` and extract only JSON content
                end_idx = content.find('```')
                if end_idx != -1:
                    content = content[:end_idx]
                content = content.strip()

            data = json.loads(content)

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
            return {'entities': [], 'statements': []}

    def _calculate_avg_confidence(self, items: list) -> float:
        """Calculate average confidence across items"""
        if not items:
            return 0.0
        confidences = [item.get('confidence', 0.0) for item in items]
        return sum(confidences) / len(confidences)

    def _calculate_cost(self, response: Dict[str, Any]) -> float:
        """Calculate cost based on provider and usage"""
        usage = response.get('usage', {})
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)

        if response.get('provider') == 'anthropic':
            # Claude pricing (per 1M tokens)
            model = response.get('model', '')
            if 'opus' in model:
                input_cost_per_1m = 15.00
                output_cost_per_1m = 75.00
            elif 'sonnet' in model:
                if '3.7' in model or '3-7' in model:
                    input_cost_per_1m = 3.00
                    output_cost_per_1m = 15.00
                else:  # 3.5 and newer
                    input_cost_per_1m = 3.00
                    output_cost_per_1m = 15.00
            else:  # haiku
                input_cost_per_1m = 0.80
                output_cost_per_1m = 4.00
        else:
            # OpenAI pricing
            model = response.get('model', '')
            if 'gpt-5' in model:
                if 'nano' in model:
                    input_cost_per_1m = 0.04
                    output_cost_per_1m = 0.16
                else:  # mini
                    input_cost_per_1m = 0.10
                    output_cost_per_1m = 0.40
            elif 'gpt-4o-mini' in model:
                input_cost_per_1m = 0.15
                output_cost_per_1m = 0.60
            else:  # gpt-4o and others
                input_cost_per_1m = 2.50
                output_cost_per_1m = 10.00

        input_cost = (prompt_tokens / 1_000_000) * input_cost_per_1m
        output_cost = (completion_tokens / 1_000_000) * output_cost_per_1m

        return input_cost + output_cost

    def add_rids_to_extraction(self, extraction_data: Dict[str, Any], parent_rid: str) -> Dict[str, Any]:
        """Add RIDs to entities and statements"""
        from knowledge_graph.kg_rid_generator import generate_entity_rid, generate_statement_rid

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

    async def extract_and_track(
        self,
        memory_rid: str,
        content: str,
        metadata: Dict[str, Any]
    ) -> tuple[str, str]:
        """Override to use unified extraction"""
        source_url = metadata.get('source_url')
        if not source_url:
            raise ValueError("source_url is required in metadata")

        logger.info(f"Starting {self.pass_type} extraction for {memory_rid}")

        # Extract
        extraction_result = await self.extract(content)

        # Add RIDs
        extraction_result = self.add_rids_to_extraction(extraction_result, memory_rid)

        # Store
        from knowledge_graph.kg_rid_generator import generate_kg_extraction_rid
        import asyncpg
        from datetime import datetime, timezone

        extraction_rid = generate_kg_extraction_rid(memory_rid, self.pass_type, self.ontology_version)

        conn = await asyncpg.connect(self.db_url)
        try:
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

            receipt_id = await self.create_extraction_receipt(
                conn, memory_rid, extraction_rid, extraction_result, source_url
            )

            logger.info(f"✓ Completed {self.pass_type} extraction: {extraction_rid[:60]}... (receipt: {receipt_id[:8]}...)")
            return extraction_rid, receipt_id
        finally:
            await conn.close()

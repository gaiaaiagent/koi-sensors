"""
Model Comparison for KG Extraction
Compares different LLM models across speed, cost, and quality metrics
"""

import asyncio
import asyncpg
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from knowledge_graph.extractors.unified_extractor import UnifiedExtractor


# Model configurations to compare
MODELS_TO_TEST = {
    # Tier 1: Max Performance 🏆
    "gpt-4o": {
        "provider": "openai",
        "tier": "Tier 1: Max Performance 🏆",
        "pricing": {"input": 2.50, "output": 10.00}
    },
    "claude-opus-4-20250514": {
        "provider": "anthropic",
        "tier": "Tier 1: Max Performance 🏆",
        "pricing": {"input": 15.00, "output": 75.00}
    },

    # Tier 2: Balanced ⚙️
    "gpt-5-mini": {
        "provider": "openai",
        "tier": "Tier 2: Balanced ⚙️",
        "pricing": {"input": 0.10, "output": 0.40}
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "tier": "Tier 2: Balanced ⚙️",
        "pricing": {"input": 0.15, "output": 0.60}
    },
    "claude-3-5-sonnet-20241022": {
        "provider": "anthropic",
        "tier": "Tier 2: Balanced ⚙️",
        "pricing": {"input": 3.00, "output": 15.00}
    },
    "claude-sonnet-4-20250514": {
        "provider": "anthropic",
        "tier": "Tier 2: Balanced ⚙️",
        "pricing": {"input": 3.00, "output": 15.00}
    },

    # Tier 3: Economical ⚡️
    "gpt-5-nano": {
        "provider": "openai",
        "tier": "Tier 3: Economical ⚡️",
        "pricing": {"input": 0.04, "output": 0.16}
    },
    "gpt-4.1-nano": {
        "provider": "openai",
        "tier": "Tier 3: Economical ⚡️",
        "pricing": {"input": 0.04, "output": 0.16}
    },
    "claude-3-5-haiku-20241022": {
        "provider": "anthropic",
        "tier": "Tier 3: Economical ⚡️",
        "pricing": {"input": 0.80, "output": 4.00}
    }
}


class ModelComparator:
    """Compare different LLM models for KG extraction"""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.results = {}

    async def get_test_documents(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get a small set of diverse test documents"""

        conn = await asyncpg.connect(self.db_url)
        try:
            query = """
            WITH diverse_docs AS (
                (SELECT rid, content, metadata, 'website' as sensor_type
                 FROM koi_memories
                 WHERE source_sensor LIKE 'website-sensor%'
                   AND superseded_at IS NULL
                   AND is_chunk = false
                   AND LENGTH(content::text) > 800
                 ORDER BY LENGTH(content::text) DESC LIMIT 1)

                UNION ALL

                (SELECT rid, content, metadata, 'discourse' as sensor_type
                 FROM koi_memories
                 WHERE source_sensor LIKE 'discourse-sensor%'
                   AND superseded_at IS NULL
                   AND is_chunk = false
                   AND LENGTH(content::text) > 800
                 ORDER BY LENGTH(content::text) DESC LIMIT 1)

                UNION ALL

                (SELECT rid, content, metadata, 'github' as sensor_type
                 FROM koi_memories
                 WHERE source_sensor LIKE 'github-sensor%'
                   AND superseded_at IS NULL
                   AND is_chunk = false
                   AND LENGTH(content::text) > 800
                   AND rid ILIKE '%README%'
                 ORDER BY LENGTH(content::text) DESC LIMIT 1)

                UNION ALL

                (SELECT rid, content, metadata, 'notion' as sensor_type
                 FROM koi_memories
                 WHERE source_sensor LIKE 'notion-sensor%'
                   AND superseded_at IS NULL
                   AND is_chunk = false
                   AND LENGTH(content::text) > 800
                 ORDER BY LENGTH(content::text) DESC LIMIT 1)

                UNION ALL

                (SELECT rid, content, metadata, 'github-activity' as sensor_type
                 FROM koi_memories
                 WHERE source_sensor LIKE 'github-activity-sensor%'
                   AND superseded_at IS NULL
                   AND is_chunk = false
                 ORDER BY created_at DESC LIMIT 1)
            )
            SELECT * FROM diverse_docs LIMIT $1;
            """

            rows = await conn.fetch(query, limit)
            documents = []

            for row in rows:
                content_data = json.loads(row['content']) if isinstance(row['content'], str) else row['content']
                text = content_data.get('text', '')
                metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']

                documents.append({
                    'rid': row['rid'],
                    'sensor_type': row['sensor_type'],
                    'text': text,
                    'metadata': metadata
                })

            return documents
        finally:
            await conn.close()

    async def test_model(self, model_name: str, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Test a single model on the document set"""

        print(f"\n🔬 Testing {model_name}...")
        print(f"   Tier: {MODELS_TO_TEST[model_name]['tier']}")

        # Create extractor with this model
        extractor = UnifiedExtractor(model=model_name, db_url=self.db_url)

        results = {
            'model': model_name,
            'tier': MODELS_TO_TEST[model_name]['tier'],
            'provider': MODELS_TO_TEST[model_name]['provider'],
            'documents_tested': len(documents),
            'successful': 0,
            'failed': 0,
            'total_entities': 0,
            'total_statements': 0,
            'total_tokens': 0,
            'total_cost': 0.0,
            'total_time': 0.0,
            'avg_confidence': 0.0,
            'errors': []
        }

        confidences = []

        for i, doc in enumerate(documents, 1):
            print(f"   [{i}/{len(documents)}] {doc['sensor_type'][:15]:15} ", end="", flush=True)

            try:
                start_time = time.time()

                # Run extraction (without tracking to avoid DB conflicts)
                extraction_result = await extractor.extract(doc['text'])

                elapsed = time.time() - start_time

                # Collect metrics
                entity_count = len(extraction_result.get('entities', []))
                statement_count = len(extraction_result.get('statements', []))
                confidence = extraction_result.get('confidence_avg', 0.0)
                tokens = extraction_result.get('tokens_consumed', 0)
                cost = extraction_result.get('cost_usd', 0.0)

                results['successful'] += 1
                results['total_entities'] += entity_count
                results['total_statements'] += statement_count
                results['total_tokens'] += tokens
                results['total_cost'] += cost
                results['total_time'] += elapsed
                confidences.append(confidence)

                print(f"✅ {entity_count}e {statement_count}s {elapsed:.1f}s")

            except Exception as e:
                results['failed'] += 1
                results['errors'].append(str(e))
                print(f"❌ {str(e)[:40]}")

        # Calculate averages
        if results['successful'] > 0:
            results['avg_entities'] = results['total_entities'] / results['successful']
            results['avg_statements'] = results['total_statements'] / results['successful']
            results['avg_tokens'] = results['total_tokens'] / results['successful']
            results['avg_cost'] = results['total_cost'] / results['successful']
            results['avg_time'] = results['total_time'] / results['successful']
            results['avg_confidence'] = sum(confidences) / len(confidences) if confidences else 0.0

        return results

    async def run_comparison(self, num_docs: int = 5, parallel: bool = True):
        """Run full model comparison"""

        print("=" * 80)
        print("LLM MODEL COMPARISON FOR KG EXTRACTION")
        print("=" * 80)
        print()

        # Get test documents
        print(f"📥 Fetching {num_docs} diverse test documents...")
        documents = await self.get_test_documents(num_docs)
        print(f"   Found {len(documents)} documents")
        print()

        if parallel:
            print("🚀 Running model tests in parallel...")
            print()

            # Test all models in parallel
            async def test_with_error_handling(model_name):
                try:
                    return model_name, await self.test_model(model_name, documents)
                except Exception as e:
                    print(f"   ⚠️  Model {model_name} failed: {e}")
                    return model_name, {
                        'model': model_name,
                        'error': str(e),
                        'successful': 0
                    }

            # Run all model tests concurrently
            tasks = [test_with_error_handling(model_name) for model_name in MODELS_TO_TEST.keys()]
            results_list = await asyncio.gather(*tasks)

            # Store results
            for model_name, result in results_list:
                self.results[model_name] = result
        else:
            # Test each model sequentially
            for model_name in MODELS_TO_TEST.keys():
                try:
                    result = await self.test_model(model_name, documents)
                    self.results[model_name] = result
                except Exception as e:
                    print(f"   ⚠️  Model {model_name} failed: {e}")
                    self.results[model_name] = {
                        'model': model_name,
                        'error': str(e),
                        'successful': 0
                    }

    def print_comparison_table(self):
        """Print comparison table"""

        print()
        print("=" * 80)
        print("RESULTS SUMMARY")
        print("=" * 80)
        print()

        # Filter successful results
        successful = {k: v for k, v in self.results.items() if v.get('successful', 0) > 0}

        if not successful:
            print("⚠️  No successful extractions to compare")
            return

        # Print header
        print(f"{'Model':<20} {'Tier':<25} {'Entities':<10} {'Statements':<12} {'Confidence':<12} {'Speed (s)':<12} {'Cost ($)':<10}")
        print("-" * 120)

        # Sort by tier and cost
        sorted_results = sorted(successful.items(), key=lambda x: (
            x[1].get('tier', 'Tier 3'),
            x[1].get('avg_cost', 999)
        ))

        for model_name, result in sorted_results:
            print(f"{model_name:<20} "
                  f"{result.get('tier', 'Unknown'):<25} "
                  f"{result.get('avg_entities', 0):<10.1f} "
                  f"{result.get('avg_statements', 0):<12.1f} "
                  f"{result.get('avg_confidence', 0):<12.3f} "
                  f"{result.get('avg_time', 0):<12.1f} "
                  f"{result.get('avg_cost', 0):<10.6f}")

        print()
        print("=" * 120)

        # Recommendations
        print()
        print("💡 RECOMMENDATIONS")
        print()

        # Best quality
        best_quality = max(successful.items(), key=lambda x: (
            x[1].get('avg_confidence', 0),
            x[1].get('avg_entities', 0) + x[1].get('avg_statements', 0)
        ))
        print(f"🏆 Best Quality: {best_quality[0]}")
        print(f"   Confidence: {best_quality[1].get('avg_confidence', 0):.3f}")
        print(f"   Output: {best_quality[1].get('avg_entities', 0):.1f} entities, {best_quality[1].get('avg_statements', 0):.1f} statements")
        print()

        # Best speed
        best_speed = min(successful.items(), key=lambda x: x[1].get('avg_time', 999))
        print(f"⚡️ Fastest: {best_speed[0]}")
        print(f"   Speed: {best_speed[1].get('avg_time', 0):.1f}s per document")
        print()

        # Best value (quality / cost)
        best_value = max(successful.items(), key=lambda x: (
            (x[1].get('avg_confidence', 0) * (x[1].get('avg_entities', 0) + x[1].get('avg_statements', 0))) /
            max(x[1].get('avg_cost', 0.0001), 0.0001)
        ))
        print(f"💰 Best Value (Quality/Cost): {best_value[0]}")
        print(f"   Quality Score: {best_value[1].get('avg_confidence', 0):.3f}")
        print(f"   Cost: ${best_value[1].get('avg_cost', 0):.6f} per document")
        print()

    async def save_results(self, output_file: str = "model_comparison_results.json"):
        """Save results to JSON"""

        output_path = Path(__file__).parent / output_file

        comparison_data = {
            'timestamp': datetime.now().isoformat(),
            'models_tested': list(self.results.keys()),
            'results': self.results
        }

        with open(output_path, 'w') as f:
            json.dump(comparison_data, f, indent=2)

        print(f"📄 Results saved to: {output_path}")


async def main():
    """Main comparison runner"""

    # Get database URL
    db_url = os.getenv('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5433/eliza')

    # Create comparator
    comparator = ModelComparator(db_url)

    # Run comparison (5 documents to keep it fast)
    await comparator.run_comparison(num_docs=5)

    # Print results
    comparator.print_comparison_table()

    # Save results
    await comparator.save_results()


if __name__ == "__main__":
    asyncio.run(main())

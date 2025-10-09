"""
Golden Test Set for Knowledge Graph Extraction

Tests Pass A extractor against manually validated test documents.
Target: F1 score >= 0.80 for entity and statement extraction
"""

import asyncio
import json
from pathlib import Path
import pytest
import sys

# Add knowledge_graph to path
sys.path.insert(0, '/opt/projects/koi-sensors')

from knowledge_graph.extractors.pass_a_extractor import PassAExtractor


class TestGoldenSet:
    """Test suite for knowledge graph extraction quality"""

    @pytest.fixture(scope="class")
    def extractor(self):
        """Initialize Pass A extractor"""
        db_url = "postgresql://postgres:postgres@localhost:5433/eliza"
        return PassAExtractor(
            db_url=db_url,
            ontology_version="op-v1.1",
            extractor_version="1.0.0"
        )

    @pytest.fixture(scope="class")
    def test_docs_dir(self):
        """Path to test documents"""
        return Path(__file__).parent / 'golden' / 'documents'

    @pytest.fixture(scope="class")
    def expected_dir(self):
        """Path to expected outputs"""
        return Path(__file__).parent / 'golden' / 'expected'

    def normalize_entity(self, entity: dict) -> tuple:
        """
        Normalize entity for comparison
        Returns: (name, type) tuple (case-insensitive)
        """
        return (
            entity.get('name', '').lower().strip(),
            entity.get('type', '').lower().strip()
        )

    def normalize_statement(self, statement: dict) -> tuple:
        """
        Normalize statement for comparison
        Returns: (subject, predicate, object) tuple (case-insensitive)
        """
        return (
            statement.get('subject', '').lower().strip(),
            statement.get('predicate', '').lower().strip(),
            statement.get('object', '').lower().strip()
        )

    def calculate_precision(self, predicted: list, expected: list, normalize_fn) -> float:
        """
        Calculate precision: TP / (TP + FP)

        Args:
            predicted: List of predicted items
            expected: List of expected items
            normalize_fn: Function to normalize items for comparison

        Returns:
            Precision score (0.0-1.0)
        """
        if not predicted:
            return 0.0

        predicted_set = {normalize_fn(item) for item in predicted}
        expected_set = {normalize_fn(item) for item in expected}

        true_positives = len(predicted_set & expected_set)
        return true_positives / len(predicted_set)

    def calculate_recall(self, predicted: list, expected: list, normalize_fn) -> float:
        """
        Calculate recall: TP / (TP + FN)

        Args:
            predicted: List of predicted items
            expected: List of expected items
            normalize_fn: Function to normalize items for comparison

        Returns:
            Recall score (0.0-1.0)
        """
        if not expected:
            return 0.0

        predicted_set = {normalize_fn(item) for item in predicted}
        expected_set = {normalize_fn(item) for item in expected}

        true_positives = len(predicted_set & expected_set)
        return true_positives / len(expected_set)

    def calculate_f1(self, precision: float, recall: float) -> float:
        """
        Calculate F1 score: 2 * (precision * recall) / (precision + recall)

        Args:
            precision: Precision score
            recall: Recall score

        Returns:
            F1 score (0.0-1.0)
        """
        if precision + recall == 0:
            return 0.0
        return 2 * (precision * recall) / (precision + recall)

    @pytest.mark.asyncio
    async def test_entity_extraction_accuracy(self, extractor, test_docs_dir, expected_dir):
        """Test entity extraction meets F1 >= 0.80 threshold"""

        total_precision = 0.0
        total_recall = 0.0
        total_f1 = 0.0
        doc_count = 0

        for doc_file in sorted(test_docs_dir.glob('doc_*.txt')):
            # Load test document
            with open(doc_file, 'r') as f:
                content = f.read()

            # Load expected output
            expected_file = expected_dir / doc_file.name.replace('.txt', '.json')
            with open(expected_file, 'r') as f:
                expected = json.load(f)

            # Extract entities
            result = await extractor.extract(content)

            # Calculate metrics
            precision = self.calculate_precision(
                result['entities'],
                expected['entities'],
                self.normalize_entity
            )
            recall = self.calculate_recall(
                result['entities'],
                expected['entities'],
                self.normalize_entity
            )
            f1 = self.calculate_f1(precision, recall)

            print(f"\n{doc_file.name}: Entity F1={f1:.2f} (P={precision:.2f}, R={recall:.2f})")

            total_precision += precision
            total_recall += recall
            total_f1 += f1
            doc_count += 1

        # Calculate averages
        avg_precision = total_precision / doc_count
        avg_recall = total_recall / doc_count
        avg_f1 = total_f1 / doc_count

        print(f"\n=== Entity Extraction Results ===")
        print(f"Average Precision: {avg_precision:.3f}")
        print(f"Average Recall: {avg_recall:.3f}")
        print(f"Average F1 Score: {avg_f1:.3f}")

        # Assert F1 >= 0.80
        assert avg_f1 >= 0.80, f"Entity extraction F1 score {avg_f1:.3f} is below threshold 0.80"

    @pytest.mark.asyncio
    async def test_statement_extraction_accuracy(self, extractor, test_docs_dir, expected_dir):
        """Test statement extraction meets F1 >= 0.80 threshold"""

        total_precision = 0.0
        total_recall = 0.0
        total_f1 = 0.0
        doc_count = 0

        for doc_file in sorted(test_docs_dir.glob('doc_*.txt')):
            # Load test document
            with open(doc_file, 'r') as f:
                content = f.read()

            # Load expected output
            expected_file = expected_dir / doc_file.name.replace('.txt', '.json')
            with open(expected_file, 'r') as f:
                expected = json.load(f)

            # Extract statements
            result = await extractor.extract(content)

            # Calculate metrics
            precision = self.calculate_precision(
                result['statements'],
                expected['statements'],
                self.normalize_statement
            )
            recall = self.calculate_recall(
                result['statements'],
                expected['statements'],
                self.normalize_statement
            )
            f1 = self.calculate_f1(precision, recall)

            print(f"\n{doc_file.name}: Statement F1={f1:.2f} (P={precision:.2f}, R={recall:.2f})")

            total_precision += precision
            total_recall += recall
            total_f1 += f1
            doc_count += 1

        # Calculate averages
        avg_precision = total_precision / doc_count
        avg_recall = total_recall / doc_count
        avg_f1 = total_f1 / doc_count

        print(f"\n=== Statement Extraction Results ===")
        print(f"Average Precision: {avg_precision:.3f}")
        print(f"Average Recall: {avg_recall:.3f}")
        print(f"Average F1 Score: {avg_f1:.3f}")

        # Assert F1 >= 0.80
        assert avg_f1 >= 0.80, f"Statement extraction F1 score {avg_f1:.3f} is below threshold 0.80"

    @pytest.mark.asyncio
    async def test_provenance_preservation(self, extractor, test_docs_dir):
        """Test that extraction maintains full provenance tracking"""

        doc_file = next(test_docs_dir.glob('doc_*.txt'))

        with open(doc_file, 'r') as f:
            content = f.read()

        # Extract with tracking
        result = await extractor.extract(content)

        # Verify all entities have confidence scores
        for entity in result['entities']:
            assert 'confidence' in entity, f"Entity missing confidence: {entity}"
            assert 0.0 <= entity['confidence'] <= 1.0, f"Invalid confidence: {entity['confidence']}"

        # Verify all statements have confidence scores
        for statement in result['statements']:
            assert 'confidence' in statement, f"Statement missing confidence: {statement}"
            assert 0.0 <= statement['confidence'] <= 1.0, f"Invalid confidence: {statement['confidence']}"

        # Verify token tracking
        assert 'tokens_consumed' in result
        assert result['tokens_consumed'] > 0

        # Verify cost tracking
        assert 'cost_usd' in result
        assert result['cost_usd'] > 0.0

        print(f"\n✓ Provenance tracking verified")
        print(f"  Tokens consumed: {result['tokens_consumed']}")
        print(f"  Cost: ${result['cost_usd']:.4f}")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, '-v', '-s'])

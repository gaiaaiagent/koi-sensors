#!/usr/bin/env python3
"""
Build Knowledge Graph from All Indexed Content
Processes all non-Twitter documents and extracts entities, relationships, and claims
"""

import sys
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass
import argparse
from tqdm import tqdm

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from ontology.regen_ontology import create_ontology
from processors.document_processor import DocumentProcessor, ProcessingResult


@dataclass
class BuildStatistics:
    """Statistics for the knowledge graph build"""
    total_documents: int = 0
    processed_documents: int = 0
    failed_documents: int = 0
    total_entities: int = 0
    total_relationships: int = 0
    total_claims: int = 0
    processing_time_seconds: float = 0
    entities_by_type: Dict[str, int] = None
    
    def __post_init__(self):
        if self.entities_by_type is None:
            self.entities_by_type = {}


class KnowledgeGraphBuilder:
    """
    Main builder for the Regen Network knowledge graph
    Processes all indexed content (excluding Twitter) and extracts structured knowledge
    """
    
    def __init__(self, docs_directory: str = None):
        """
        Initialize the knowledge graph builder
        
        Args:
            docs_directory: Directory containing indexed documents
        """
        self.docs_dir = Path(docs_directory or "/home/regenai/project/indexing/storage/documents")
        self.ontology = create_ontology()
        self.processor = DocumentProcessor(self.ontology)
        
        # Build configuration
        self.batch_size = 10  # Process in batches to show progress
        self.exclude_patterns = ["twitter_"]  # Exclude Twitter data
        
        # Storage for results
        self.results: List[ProcessingResult] = []
        self.stats = BuildStatistics()
        
        print(f"🚀 Initialized Knowledge Graph Builder")
        print(f"   Documents directory: {self.docs_dir}")
        print(f"   Ontology version: {self.ontology.VERSION}")
        print(f"   Batch size: {self.batch_size}")
        
    def find_documents(self) -> List[Path]:
        """Find all documents to process"""
        print("📁 Finding documents to process...")
        
        if not self.docs_dir.exists():
            raise FileNotFoundError(f"Documents directory not found: {self.docs_dir}")
        
        # Find all JSON documents
        all_docs = list(self.docs_dir.glob("*.json"))
        
        # Filter out excluded patterns
        filtered_docs = []
        for doc_path in all_docs:
            exclude = False
            for pattern in self.exclude_patterns:
                if pattern in doc_path.name:
                    exclude = True
                    break
            if not exclude:
                filtered_docs.append(doc_path)
        
        print(f"   Found {len(all_docs)} total documents")
        print(f"   Filtered to {len(filtered_docs)} documents (excluding Twitter)")
        
        return filtered_docs
        
    def categorize_documents(self, doc_paths: List[Path]) -> Dict[str, List[Path]]:
        """Categorize documents by type for prioritized processing"""
        categories = {
            "registry": [],      # Registry and credit data
            "technical": [],     # GitHub technical docs
            "governance": [],    # Governance and proposals
            "blog": [],         # Blog posts and articles
            "podcast": [],      # Podcast transcripts
            "website": [],      # Website content
            "forum": [],        # Forum discussions
            "other": []         # Everything else
        }
        
        for doc_path in doc_paths:
            name = doc_path.name.lower()
            
            if "github_" in name:
                categories["technical"].append(doc_path)
            elif "soundcloud_" in name:
                categories["podcast"].append(doc_path)
            elif "website_" in name:
                categories["website"].append(doc_path)
            elif "discourse_" in name or "forum_" in name:
                categories["forum"].append(doc_path)
            elif "medium_" in name or "blog_" in name:
                categories["blog"].append(doc_path)
            elif any(term in name for term in ["governance", "proposal", "vote"]):
                categories["governance"].append(doc_path)
            elif any(term in name for term in ["registry", "credit", "methodology"]):
                categories["registry"].append(doc_path)
            else:
                categories["other"].append(doc_path)
        
        # Print category summary
        print("📊 Document categories:")
        for category, docs in categories.items():
            if docs:
                print(f"   {category}: {len(docs)} documents")
        
        return categories
        
    def process_document_batch(self, doc_paths: List[Path], batch_num: int, total_batches: int) -> List[ProcessingResult]:
        """Process a batch of documents"""
        print(f"\n🔄 Processing batch {batch_num}/{total_batches} ({len(doc_paths)} documents)")
        
        batch_results = []
        
        for i, doc_path in enumerate(doc_paths):
            try:
                # Load document
                with open(doc_path, 'r', encoding='utf-8') as f:
                    document = json.load(f)
                
                # Show progress
                source = document.get('source', 'unknown')
                title = document.get('title', 'No title')
                print(f"   [{i+1}/{len(doc_paths)}] {source}: {title[:50]}{'...' if len(title) > 50 else ''}")
                
                # Process document
                result = self.processor.process_document(document)
                batch_results.append(result)
                
                # Update statistics
                self.stats.processed_documents += 1
                if result.success:
                    self.stats.total_entities += result.entities_extracted
                    self.stats.total_relationships += result.relationships_found
                else:
                    self.stats.failed_documents += 1
                    
            except Exception as e:
                print(f"   ❌ Error processing {doc_path.name}: {e}")
                self.stats.failed_documents += 1
        
        return batch_results
        
    def process_all_documents(self, doc_paths: List[Path]) -> None:
        """Process all documents in batches"""
        self.stats.total_documents = len(doc_paths)
        start_time = time.time()
        
        # Split into batches
        batches = [doc_paths[i:i + self.batch_size] for i in range(0, len(doc_paths), self.batch_size)]
        
        print(f"\n🚀 Starting knowledge extraction from {len(doc_paths)} documents")
        print(f"   Processing in {len(batches)} batches of {self.batch_size}")
        
        # Process each batch
        for batch_num, batch in enumerate(batches, 1):
            batch_results = self.process_document_batch(batch, batch_num, len(batches))
            self.results.extend(batch_results)
            
            # Show progress after each batch
            self.print_progress()
            
            # Brief pause between batches
            time.sleep(0.5)
        
        self.stats.processing_time_seconds = time.time() - start_time
        
    def analyze_extracted_entities(self) -> None:
        """Analyze the extracted entities by type"""
        print("\n📈 Analyzing extracted entities...")
        
        # Read all entity files
        entities_dir = Path("/home/regenai/project/knowledge_graph/storage/graph/entities")
        
        for entity_file in entities_dir.glob("*.jsonl"):
            entity_type = entity_file.stem.title()  # person.jsonl -> Person
            
            # Count entities in file
            count = 0
            if entity_file.exists():
                with open(entity_file, 'r') as f:
                    for line in f:
                        if line.strip():
                            count += 1
            
            if count > 0:
                self.stats.entities_by_type[entity_type] = count
        
        # Update total
        self.stats.total_entities = sum(self.stats.entities_by_type.values())
        
    def print_progress(self) -> None:
        """Print current progress"""
        if self.stats.total_documents > 0:
            progress_pct = (self.stats.processed_documents / self.stats.total_documents) * 100
            print(f"   Progress: {self.stats.processed_documents}/{self.stats.total_documents} ({progress_pct:.1f}%)")
            print(f"   Entities extracted: {self.stats.total_entities}")
            print(f"   Failed: {self.stats.failed_documents}")
        
    def generate_final_report(self) -> Dict[str, Any]:
        """Generate final build report"""
        report = {
            "build_completed_at": datetime.now().isoformat(),
            "ontology_version": self.ontology.VERSION,
            "statistics": {
                "total_documents": self.stats.total_documents,
                "processed_documents": self.stats.processed_documents,
                "failed_documents": self.stats.failed_documents,
                "success_rate": (self.stats.processed_documents - self.stats.failed_documents) / self.stats.processed_documents * 100 if self.stats.processed_documents > 0 else 0,
                "total_entities": self.stats.total_entities,
                "total_relationships": self.stats.total_relationships,
                "processing_time_seconds": self.stats.processing_time_seconds,
                "documents_per_second": self.stats.processed_documents / self.stats.processing_time_seconds if self.stats.processing_time_seconds > 0 else 0,
                "entities_by_type": self.stats.entities_by_type
            },
            "extraction_methods": {
                "pattern_extractor": "Fast regex-based extraction",
                "claude_extractor": "Semantic analysis by Claude Sonnet",
                "hybrid_approach": "Combined pattern + semantic extraction"
            }
        }
        
        return report
        
    def save_report(self, report: Dict[str, Any]) -> None:
        """Save the final report"""
        report_path = Path("/home/regenai/project/knowledge_graph/storage/build_report.json")
        
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"📄 Build report saved to: {report_path}")
        
    def print_final_summary(self, report: Dict[str, Any]) -> None:
        """Print final build summary"""
        stats = report["statistics"]
        
        print(f"\n🎉 Knowledge Graph Build Complete!")
        print(f"   📊 Documents: {stats['processed_documents']}/{stats['total_documents']} ({stats['success_rate']:.1f}% success)")
        print(f"   🏷️  Entities: {stats['total_entities']} extracted")
        print(f"   ⏱️  Time: {stats['processing_time_seconds']:.1f}s ({stats['documents_per_second']:.1f} docs/sec)")
        
        if stats['entities_by_type']:
            print(f"\n📝 Entities by Type:")
            for entity_type, count in sorted(stats['entities_by_type'].items(), key=lambda x: x[1], reverse=True):
                print(f"   {entity_type}: {count}")
        
        if stats['failed_documents'] > 0:
            print(f"\n⚠️  Failed Documents: {stats['failed_documents']}")
            
        print(f"\n💾 Knowledge graph stored in: /home/regenai/project/knowledge_graph/storage/")
        
    def build(self, prioritized: bool = True) -> Dict[str, Any]:
        """
        Build the complete knowledge graph
        
        Args:
            prioritized: Whether to process documents in priority order
            
        Returns:
            Build report
        """
        try:
            # Find documents
            doc_paths = self.find_documents()
            
            if prioritized:
                # Categorize and prioritize
                categories = self.categorize_documents(doc_paths)
                
                # Process in priority order
                priority_order = ["registry", "technical", "governance", "blog", "website", "podcast", "forum", "other"]
                ordered_docs = []
                
                for category in priority_order:
                    if category in categories:
                        ordered_docs.extend(categories[category])
                
                doc_paths = ordered_docs
            
            # Process all documents
            self.process_all_documents(doc_paths)
            
            # Analyze results
            self.analyze_extracted_entities()
            
            # Generate report
            report = self.generate_final_report()
            self.save_report(report)
            self.print_final_summary(report)
            
            return report
            
        except Exception as e:
            print(f"❌ Build failed: {e}")
            raise


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Build Regen Network Knowledge Graph")
    parser.add_argument("--docs-dir", help="Directory containing indexed documents")
    parser.add_argument("--no-priority", action="store_true", help="Process documents in random order")
    parser.add_argument("--batch-size", type=int, default=10, help="Documents per batch")
    
    args = parser.parse_args()
    
    # Create builder
    builder = KnowledgeGraphBuilder(args.docs_dir)
    
    if args.batch_size:
        builder.batch_size = args.batch_size
    
    # Build knowledge graph
    report = builder.build(prioritized=not args.no_priority)
    
    print(f"\n✅ Knowledge graph build completed successfully!")
    print(f"📋 View full report: /home/regenai/project/knowledge_graph/storage/build_report.json")


if __name__ == "__main__":
    main()
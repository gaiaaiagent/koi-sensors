#!/usr/bin/env python3
"""
Clean rebuild of knowledge graph using whitelist extraction
High-quality entity extraction with proper deduplication
"""

import sys
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from extractors.whitelist_extractor import WhitelistExtractor
from scripts.true_deduplication import TrueDeduplicator


class CleanKnowledgeGraphBuilder:
    """
    Clean knowledge graph builder using high-quality extraction
    """
    
    def __init__(self):
        self.docs_dir = Path("/home/regenai/project/indexing/storage/documents")
        self.storage_dir = Path("/home/regenai/project/knowledge_graph/storage")
        self.entities_dir = self.storage_dir / "graph" / "entities"
        self.extractor = WhitelistExtractor()
        
        # Clean storage directories
        self.clean_storage()
        
    def clean_storage(self):
        """Clean existing storage to start fresh"""
        print("🧹 Cleaning storage directories...")
        
        # Remove old entity files
        if self.entities_dir.exists():
            shutil.rmtree(self.entities_dir)
        self.entities_dir.mkdir(parents=True, exist_ok=True)
        
        # Clean other directories
        for dirname in ["deduplicated_entities", "unique_entities"]:
            dir_path = self.storage_dir / "graph" / dirname
            if dir_path.exists():
                shutil.rmtree(dir_path)
        
        print("   Storage cleaned")
    
    def find_documents(self) -> List[Path]:
        """Find all documents to process (excluding Twitter)"""
        print("📁 Finding documents to process...")
        
        if not self.docs_dir.exists():
            raise FileNotFoundError(f"Documents directory not found: {self.docs_dir}")
        
        # Find all JSON documents
        all_docs = list(self.docs_dir.glob("*.json"))
        
        # Filter out Twitter documents
        filtered_docs = [
            doc for doc in all_docs 
            if "twitter_" not in doc.name
        ]
        
        print(f"   Found {len(all_docs)} total documents")
        print(f"   Filtered to {len(filtered_docs)} documents (excluding Twitter)")
        
        return filtered_docs
    
    def process_documents(self, doc_paths: List[Path]) -> Dict[str, Any]:
        """Process all documents with whitelist extraction"""
        print(f"\n🚀 Processing {len(doc_paths)} documents...")
        
        total_entities = 0
        processed_count = 0
        failed_count = 0
        
        # Process each document
        for i, doc_path in enumerate(doc_paths, 1):
            if i % 10 == 0:
                print(f"   Progress: {i}/{len(doc_paths)} documents")
            
            try:
                # Load document
                with open(doc_path, 'r', encoding='utf-8') as f:
                    document = json.load(f)
                
                # Extract entities using whitelist approach
                result = self.extractor.extract_from_document(document)
                
                # Store entities
                for entity in result['entities']:
                    entity['source_document'] = document.get('id', doc_path.stem)
                    entity['extracted_at'] = datetime.now().isoformat()
                    self.store_entity(entity)
                
                total_entities += len(result['entities'])
                processed_count += 1
                
            except Exception as e:
                print(f"   ❌ Error processing {doc_path.name}: {e}")
                failed_count += 1
        
        return {
            "processed": processed_count,
            "failed": failed_count,
            "total_entities": total_entities
        }
    
    def store_entity(self, entity: Dict[str, Any]):
        """Store an entity to the appropriate file"""
        entity_type = entity.get('entity_type', 'Unknown')
        entity_file = self.entities_dir / f"{entity_type.lower()}.jsonl"
        
        with open(entity_file, 'a') as f:
            f.write(json.dumps(entity) + '\n')
    
    def build(self) -> Dict[str, Any]:
        """Build the clean knowledge graph"""
        print("="*60)
        print("🔧 CLEAN KNOWLEDGE GRAPH REBUILD")
        print("="*60)
        
        start_time = datetime.now()
        
        # Find documents
        doc_paths = self.find_documents()
        
        # Process with whitelist extraction
        extraction_results = self.process_documents(doc_paths)
        
        print(f"\n✅ Extraction complete:")
        print(f"   Processed: {extraction_results['processed']} documents")
        print(f"   Failed: {extraction_results['failed']} documents")
        print(f"   Extracted: {extraction_results['total_entities']} raw entities")
        
        # Apply true deduplication
        print(f"\n🔗 Applying true deduplication...")
        deduplicator = TrueDeduplicator()
        dedup_results = deduplicator.deduplicate_all()
        
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        
        # Final report
        final_stats = {
            "build_completed_at": end_time.isoformat(),
            "processing_time_seconds": processing_time,
            "documents_processed": extraction_results['processed'],
            "raw_entities_extracted": extraction_results['total_entities'],
            "unique_entities_final": dedup_results['total_stats']['unique_entities'],
            "duplicates_removed": dedup_results['total_stats']['duplicates_removed'],
            "bad_entities_excluded": dedup_results['total_stats']['excluded_entities'],
            "extraction_method": "whitelist_v2",
            "quality_score": (dedup_results['total_stats']['unique_entities'] / 
                            extraction_results['total_entities'] * 100)
                           if extraction_results['total_entities'] > 0 else 0
        }
        
        # Save final report
        report_file = self.storage_dir / "clean_build_report.json"
        with open(report_file, 'w') as f:
            json.dump(final_stats, f, indent=2)
        
        return final_stats


def main():
    """Main build process"""
    builder = CleanKnowledgeGraphBuilder()
    stats = builder.build()
    
    print("\n" + "="*60)
    print("🎉 CLEAN BUILD COMPLETE!")
    print("="*60)
    print(f"⏱️  Time: {stats['processing_time_seconds']:.1f} seconds")
    print(f"📄 Documents: {stats['documents_processed']} processed")
    print(f"🔍 Extraction: {stats['raw_entities_extracted']} raw entities")
    print(f"🚫 Excluded: {stats['bad_entities_excluded']} bad entities")
    print(f"🔗 Deduplicated: {stats['duplicates_removed']} duplicates removed")
    print(f"✅ FINAL: {stats['unique_entities_final']} unique high-quality entities")
    print(f"📈 Quality: {stats['quality_score']:.1f}% unique rate")
    print("="*60)
    
    print(f"\n📂 Results saved to:")
    print(f"   /home/regenai/project/knowledge_graph/storage/graph/unique_entities/")
    print(f"   Report: /home/regenai/project/knowledge_graph/storage/clean_build_report.json")


if __name__ == "__main__":
    main()
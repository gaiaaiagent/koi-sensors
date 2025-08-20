#!/usr/bin/env python3
"""
Rebuild knowledge graph with improved filtering
Cleans up bad extractions and re-processes with stricter rules
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from scripts.build_knowledge_graph import KnowledgeGraphBuilder


def clean_storage():
    """Clean existing storage to start fresh"""
    storage_path = Path("/home/regenai/project/knowledge_graph/storage")
    
    # Remove entity files
    entities_dir = storage_path / "graph" / "entities"
    if entities_dir.exists():
        shutil.rmtree(entities_dir)
        entities_dir.mkdir(parents=True, exist_ok=True)
        print("🧹 Cleaned entity storage")
    
    # Remove old build report
    build_report = storage_path / "build_report.json"
    if build_report.exists():
        build_report.unlink()
        print("🧹 Removed old build report")


def main():
    """Main rebuild process"""
    print("🔧 Rebuilding knowledge graph with improved filtering...")
    print(f"   Started at: {datetime.now().isoformat()}")
    
    # Clean storage
    clean_storage()
    
    # Create new builder with improved filtering
    builder = KnowledgeGraphBuilder()
    builder.batch_size = 5  # Smaller batches to better see quality
    
    # Build with improved quality
    print("\n🚀 Starting clean rebuild...")
    report = builder.build(prioritized=True)
    
    print(f"\n✅ Clean rebuild completed!")
    print(f"   Entities extracted: {report['statistics']['total_entities']}")
    print(f"   Processing time: {report['statistics']['processing_time_seconds']:.1f}s")
    
    # Show quality comparison
    entities_by_type = report['statistics']['entities_by_type']
    print(f"\n📊 Clean Entity Counts:")
    for entity_type, count in sorted(entities_by_type.items(), key=lambda x: x[1], reverse=True):
        print(f"   {entity_type}: {count}")


if __name__ == "__main__":
    main()
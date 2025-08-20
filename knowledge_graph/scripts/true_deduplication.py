#!/usr/bin/env python3
"""
True entity deduplication that actually removes duplicates
Keeps only one instance per unique entity with merged metadata
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Set, Tuple
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from extractors.known_entities import (
    is_definitely_not_person,
    is_definitely_not_organization,
    normalize_organization_name
)


class TrueDeduplicator:
    """
    Actual deduplication that results in unique entities only
    """
    
    def __init__(self):
        self.entities_dir = Path("/home/regenai/project/knowledge_graph/storage/graph/entities")
        self.output_dir = Path("/home/regenai/project/knowledge_graph/storage/graph/unique_entities")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def deduplicate_all(self) -> Dict[str, Any]:
        """
        Deduplicate all entity types, keeping only unique entities
        """
        print("🔧 Starting TRUE deduplication (removing all duplicates)...")
        
        total_stats = {
            "raw_entities": 0,
            "excluded_entities": 0,
            "unique_entities": 0,
            "duplicates_removed": 0
        }
        
        entity_types = []
        for entity_file in self.entities_dir.glob("*.jsonl"):
            entity_type = entity_file.stem.title()
            entity_types.append(entity_type)
        
        results = {}
        
        for entity_type in sorted(entity_types):
            print(f"\n📋 Processing {entity_type} entities...")
            result = self.deduplicate_entity_type(entity_type)
            results[entity_type] = result
            
            total_stats["raw_entities"] += result["raw_count"]
            total_stats["excluded_entities"] += result["excluded_count"]
            total_stats["unique_entities"] += result["unique_count"]
            total_stats["duplicates_removed"] += result["duplicates_removed"]
        
        # Save summary
        self.save_summary(total_stats, results)
        
        return {
            "total_stats": total_stats,
            "by_type": results
        }
    
    def deduplicate_entity_type(self, entity_type: str) -> Dict[str, Any]:
        """
        Deduplicate a specific entity type
        
        Args:
            entity_type: Type of entity to deduplicate
            
        Returns:
            Deduplication statistics
        """
        entity_file = self.entities_dir / f"{entity_type.lower()}.jsonl"
        
        if not entity_file.exists():
            return {
                "raw_count": 0,
                "excluded_count": 0,
                "unique_count": 0,
                "duplicates_removed": 0
            }
        
        # Load all entities
        raw_entities = []
        with open(entity_file, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        entity = json.loads(line)
                        raw_entities.append(entity)
                    except json.JSONDecodeError:
                        continue
        
        raw_count = len(raw_entities)
        print(f"  Loaded {raw_count} raw entities")
        
        # Filter out bad entities
        good_entities = []
        excluded_count = 0
        
        for entity in raw_entities:
            if self.should_exclude(entity):
                excluded_count += 1
            else:
                good_entities.append(entity)
        
        print(f"  Excluded {excluded_count} bad entities")
        
        # Deduplicate - keep only ONE per unique value
        unique_entities = self.merge_duplicates(good_entities, entity_type)
        unique_count = len(unique_entities)
        duplicates_removed = len(good_entities) - unique_count
        
        print(f"  Reduced {len(good_entities)} → {unique_count} unique entities")
        print(f"  Removed {duplicates_removed} duplicates")
        
        # Save unique entities
        output_file = self.output_dir / f"{entity_type.lower()}.jsonl"
        with open(output_file, 'w') as f:
            for entity in unique_entities:
                f.write(json.dumps(entity) + '\n')
        
        return {
            "raw_count": raw_count,
            "excluded_count": excluded_count,
            "unique_count": unique_count,
            "duplicates_removed": duplicates_removed
        }
    
    def should_exclude(self, entity: Dict[str, Any]) -> bool:
        """
        Determine if an entity should be excluded
        
        Args:
            entity: Entity to check
            
        Returns:
            True if entity should be excluded
        """
        entity_type = entity.get('entity_type', '')
        value = entity.get('value', '').strip()
        
        # Basic quality checks
        if not value or len(value) < 2:
            return True
        
        # Type-specific exclusions
        if entity_type == 'Person':
            return is_definitely_not_person(value)
        elif entity_type == 'Organization':
            return is_definitely_not_organization(value)
            
        return False
    
    def merge_duplicates(self, entities: List[Dict[str, Any]], entity_type: str) -> List[Dict[str, Any]]:
        """
        Merge duplicate entities into single unique entries
        
        Args:
            entities: List of entities to deduplicate
            entity_type: Type of entities
            
        Returns:
            List of unique entities with merged metadata
        """
        unique_map = {}
        
        for entity in entities:
            # Normalize the value for comparison
            value = entity.get('value', '')
            
            # Special normalization for organizations
            if entity_type == 'Organization':
                value = normalize_organization_name(value)
            
            # Create a key for deduplication
            key = value.lower().strip()
            
            if key not in unique_map:
                # First occurrence - initialize
                unique_map[key] = {
                    "entity_type": entity.get('entity_type'),
                    "value": value,  # Use normalized value
                    "confidence": entity.get('confidence', 0.5),
                    "properties": entity.get('properties', {}),
                    "source_documents": [entity.get('source_document', 'unknown')],
                    "occurrence_count": 1,
                    "first_extracted": entity.get('extracted_at', ''),
                    "last_extracted": entity.get('extracted_at', '')
                }
            else:
                # Duplicate - merge metadata
                existing = unique_map[key]
                
                # Add source document if new
                source_doc = entity.get('source_document', 'unknown')
                if source_doc not in existing['source_documents']:
                    existing['source_documents'].append(source_doc)
                
                # Increment occurrence count
                existing['occurrence_count'] += 1
                
                # Update confidence to max
                existing['confidence'] = max(existing['confidence'], 
                                            entity.get('confidence', 0.5))
                
                # Update extraction times
                extracted_at = entity.get('extracted_at', '')
                if extracted_at:
                    if not existing['first_extracted'] or extracted_at < existing['first_extracted']:
                        existing['first_extracted'] = extracted_at
                    if not existing['last_extracted'] or extracted_at > existing['last_extracted']:
                        existing['last_extracted'] = extracted_at
                
                # Merge properties (keep most complete)
                if len(entity.get('properties', {})) > len(existing['properties']):
                    existing['properties'] = entity.get('properties', {})
        
        # Convert back to list and sort by occurrence count
        unique_list = list(unique_map.values())
        unique_list.sort(key=lambda x: x['occurrence_count'], reverse=True)
        
        return unique_list
    
    def save_summary(self, total_stats: Dict[str, Any], results: Dict[str, Any]):
        """Save deduplication summary"""
        summary = {
            "deduplication_completed_at": datetime.now().isoformat(),
            "total_statistics": total_stats,
            "by_entity_type": results,
            "quality_metrics": {
                "exclusion_rate": (total_stats["excluded_entities"] / total_stats["raw_entities"] * 100) 
                                  if total_stats["raw_entities"] > 0 else 0,
                "deduplication_rate": (total_stats["duplicates_removed"] / 
                                       (total_stats["raw_entities"] - total_stats["excluded_entities"]) * 100)
                                      if (total_stats["raw_entities"] - total_stats["excluded_entities"]) > 0 else 0,
                "final_quality_score": (total_stats["unique_entities"] / total_stats["raw_entities"] * 100)
                                       if total_stats["raw_entities"] > 0 else 0
            }
        }
        
        summary_file = self.output_dir / "deduplication_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"\n📊 Summary saved to: {summary_file}")


def main():
    """Main deduplication process"""
    deduplicator = TrueDeduplicator()
    results = deduplicator.deduplicate_all()
    
    stats = results["total_stats"]
    
    print("\n" + "="*60)
    print("🎉 TRUE DEDUPLICATION COMPLETE!")
    print("="*60)
    print(f"📥 Input: {stats['raw_entities']} raw entities")
    print(f"🚫 Excluded: {stats['excluded_entities']} bad entities")
    print(f"🔗 Removed: {stats['duplicates_removed']} duplicates")
    print(f"✅ Output: {stats['unique_entities']} UNIQUE entities")
    print("="*60)
    
    print(f"\n📂 Unique entities saved to:")
    print(f"   {deduplicator.output_dir}")
    
    # Show breakdown by type
    print(f"\n📊 Breakdown by type:")
    for entity_type, result in results["by_type"].items():
        if result["unique_count"] > 0:
            print(f"   {entity_type}: {result['unique_count']} unique entities")


if __name__ == "__main__":
    main()
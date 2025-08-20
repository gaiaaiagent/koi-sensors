#!/usr/bin/env python3
"""
Global entity deduplication script
Consolidates duplicate entities across all documents with proper merging
"""

import json
import sys
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Any, Set
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))


class EntityDeduplicator:
    """Global entity deduplication with smart merging"""
    
    def __init__(self):
        self.entities_dir = Path("/home/regenai/project/knowledge_graph/storage/graph/entities")
        self.deduplicated_dir = self.entities_dir.parent / "deduplicated_entities"
        self.deduplicated_dir.mkdir(exist_ok=True)
        
    def normalize_value(self, value: str) -> str:
        """Normalize entity values for comparison"""
        return value.strip().lower()
    
    def should_exclude_entity(self, entity: Dict[str, Any]) -> bool:
        """Check if entity should be excluded based on quality rules"""
        entity_type = entity.get('entity_type', '')
        value = entity.get('value', '').strip()
        value_lower = value.lower()
        
        # Basic quality filters
        if len(value) < 2 or not value:
            return True
            
        # Person-specific exclusions
        if entity_type == 'Person':
            person_exclusions = [
                'regen mainnet', 'regen testnet', 'redwood testnet', 'local testnet',
                'cosmos sdk', 'regen ledger', 'regen app', 'regen marketplace', 
                'regen registry', 'regen network', 'credit class', 'credit type',
                'example output', 'quick start', 'line interface', 'install regen',
                'blockchain basics', 'wallet security', 'initial setup',
                'upgrade guide', 'migration guide', 'change log', 'release process',
                'discord server', 'submitting issues', 'reviewing proposals',
                'writing documentation', 'writing specifications', 'additional documentation',
                'for bugs', 'for features', 'getting started', 'requesting reviews',
                'our pledge', 'our standards', 'our responsibilities', 'contributor covenant',
                'legal entity', 'derivative works', 'if you'
            ]
            if value_lower in person_exclusions:
                return True
            
            # Exclude anything that looks like a section header, command, or UI element
            if any(word in value_lower for word in [
                'server', 'issues', 'proposals', 'documentation', 'specifications',
                'features', 'bugs', 'reviews', 'guide', 'overview', 'setup', 'process',
                'checklist', 'basics', 'security', 'covenant', 'pledge', 'standards',
                'responsibilities', 'entity', 'works', 'interface', 'output', 'start'
            ]):
                return True
            
            # Only keep if it looks like a proper name (First Last)
            words = value.split()
            if not (len(words) == 2 and 
                    all(word[0].isupper() and word[1:].islower() for word in words) and
                    all(len(word) >= 2 for word in words)):
                return True
                
        # Organization-specific exclusions  
        elif entity_type == 'Organization':
            org_exclusions = [
                'the network', 'a network', 'the foundation', 'the registry',
                'the app', 'the ledger', 'the marketplace', 'the platform',
                'blockchain network'
            ]
            if value_lower in org_exclusions:
                return True
                
            # Exclude fragments with certain words
            bad_fragments = ['must', 'should', 'will', 'can', 'may', 'inc', 'include']
            if any(bad in value_lower for bad in bad_fragments):
                return True
                
        return False
    
    def merge_entity_occurrences(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge multiple occurrences of the same entity"""
        if not entities:
            return None
            
        # Use the most complete/confident version as base
        base_entity = max(entities, key=lambda e: (
            len(e.get('properties', {})),
            e.get('confidence', 0),
            len(e.get('value', ''))
        ))
        
        # Collect all source documents
        source_docs = set()
        extraction_times = []
        
        for entity in entities:
            source_docs.add(entity.get('source_document', ''))
            extraction_times.append(entity.get('extracted_at', ''))
        
        # Create merged entity
        merged = base_entity.copy()
        merged['source_documents'] = sorted(list(source_docs))
        merged['occurrence_count'] = len(entities)
        merged['first_extracted'] = min(extraction_times) if extraction_times else None
        merged['last_extracted'] = max(extraction_times) if extraction_times else None
        
        return merged
    
    def deduplicate_entity_type(self, entity_type: str) -> Dict[str, Any]:
        """Deduplicate entities of a specific type"""
        entity_file = self.entities_dir / f"{entity_type.lower()}.jsonl"
        
        if not entity_file.exists():
            return {"processed": 0, "deduplicated": 0, "excluded": 0}
            
        print(f"🔍 Processing {entity_type} entities...")
        
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
        
        print(f"   Loaded {len(raw_entities)} raw entities")
        
        # Filter out low-quality entities
        quality_entities = []
        excluded_count = 0
        
        for entity in raw_entities:
            if self.should_exclude_entity(entity):
                excluded_count += 1
            else:
                quality_entities.append(entity)
        
        print(f"   Excluded {excluded_count} low-quality entities")
        print(f"   Keeping {len(quality_entities)} quality entities")
        
        # Group by normalized value
        entity_groups = defaultdict(list)
        for entity in quality_entities:
            normalized = self.normalize_value(entity.get('value', ''))
            entity_groups[normalized].append(entity)
        
        # Merge duplicates
        deduplicated_entities = []
        total_before = len(quality_entities)
        
        for normalized_value, entities in entity_groups.items():
            merged = self.merge_entity_occurrences(entities)
            if merged:
                deduplicated_entities.append(merged)
        
        total_after = len(deduplicated_entities)
        
        # Save deduplicated entities
        output_file = self.deduplicated_dir / f"{entity_type.lower()}.jsonl"
        with open(output_file, 'w') as f:
            for entity in deduplicated_entities:
                f.write(json.dumps(entity) + '\n')
        
        print(f"   ✅ {total_before} → {total_after} entities (removed {total_before - total_after} duplicates)")
        
        return {
            "processed": len(raw_entities),
            "excluded": excluded_count, 
            "deduplicated_from": total_before,
            "deduplicated_to": total_after,
            "duplicates_removed": total_before - total_after
        }
    
    def deduplicate_all(self) -> Dict[str, Any]:
        """Deduplicate all entity types"""
        print("🧹 Starting global entity deduplication...")
        
        entity_types = []
        for entity_file in self.entities_dir.glob("*.jsonl"):
            entity_type = entity_file.stem.title()
            entity_types.append(entity_type)
        
        results = {}
        total_stats = {
            "raw_entities": 0,
            "excluded_entities": 0,
            "final_entities": 0,
            "duplicates_removed": 0
        }
        
        for entity_type in sorted(entity_types):
            result = self.deduplicate_entity_type(entity_type)
            results[entity_type] = result
            
            total_stats["raw_entities"] += result["processed"]
            total_stats["excluded_entities"] += result["excluded"]
            total_stats["final_entities"] += result["deduplicated_to"]
            total_stats["duplicates_removed"] += result["duplicates_removed"]
        
        # Save summary report
        summary = {
            "deduplication_completed_at": datetime.now().isoformat(),
            "total_statistics": total_stats,
            "by_entity_type": results,
            "quality_improvement": {
                "exclusion_rate": (total_stats["excluded_entities"] / total_stats["raw_entities"] * 100) if total_stats["raw_entities"] > 0 else 0,
                "deduplication_rate": (total_stats["duplicates_removed"] / (total_stats["raw_entities"] - total_stats["excluded_entities"]) * 100) if (total_stats["raw_entities"] - total_stats["excluded_entities"]) > 0 else 0
            }
        }
        
        summary_file = self.deduplicated_dir / "deduplication_report.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        return summary


def main():
    """Main deduplication process"""
    deduplicator = EntityDeduplicator()
    summary = deduplicator.deduplicate_all()
    
    stats = summary["total_statistics"]
    quality = summary["quality_improvement"]
    
    print(f"\n🎉 Global Deduplication Complete!")
    print(f"   📊 Raw entities: {stats['raw_entities']}")
    print(f"   🚫 Excluded low-quality: {stats['excluded_entities']} ({quality['exclusion_rate']:.1f}%)")
    print(f"   🔗 Duplicates merged: {stats['duplicates_removed']} ({quality['deduplication_rate']:.1f}%)")
    print(f"   ✅ Final high-quality entities: {stats['final_entities']}")
    
    print(f"\n📂 Deduplicated entities saved to:")
    print(f"   {deduplicator.deduplicated_dir}")


if __name__ == "__main__":
    main()
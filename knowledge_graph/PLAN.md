# Knowledge Graph Implementation Plan

## Overview

Step-by-step plan to build a semantic knowledge graph from Regen Network's indexed content, using ontology-driven extraction with full provenance tracking.

## Phase 1: Setup and Ontology (Day 1)

### Tasks
- [x] Create directory structure
- [x] Write documentation (README.md, PLAN.md)
- [ ] Define Regen ontology v1.0.0
- [ ] Document entity types and relationships
- [ ] Create extraction patterns for known formats
- [ ] Set up versioning system

### Deliverables
- `ontology/regen_ontology.py` - Core ontology definition
- `ontology/versions/v1.0.0.json` - Initial version snapshot
- `ontology/ONTOLOGY.md` - Detailed documentation

## Phase 2: Build Extractors (Day 2-3)

### Day 2: Basic Extractors
- [ ] Implement base extractor class
- [ ] Build pattern extractor for:
  - Credit classes (C01, C02, C03)
  - Projects (P001, P002, etc.)
  - Methodologies (VM0042, etc.)
  - Wallet addresses (regen1...)
- [ ] Test pattern extraction on sample documents

### Day 3: Advanced Extractors
- [ ] Setup spaCy NER pipeline
- [ ] Train/configure for Regen-specific entities
- [ ] Create Claude extractor interface
- [ ] Design extraction prompts for Claude
- [ ] Build hybrid extractor combining all methods

### Deliverables
- `extractors/base_extractor.py`
- `extractors/pattern_extractor.py`
- `extractors/spacy_extractor.py`
- `extractors/claude_extractor.py`

## Phase 3: Process Core Documents (Day 4-5)

### Processing Order (Excluding Twitter)

#### Priority 1: Registry & Credit Data (~50 documents)
- Credit class definitions (C01, C02, C03)
- Methodology documents
- Project registrations
- **Why first**: Core entities, well-structured, high accuracy

#### Priority 2: Technical Documentation (~30 documents)
- Whitepapers
- Technical specifications
- Architecture documents
- **Why second**: Defines key concepts and relationships

#### Priority 3: Governance (~100 documents)
- Proposals
- Voting records
- Discussion threads
- **Why third**: Rich in people/organization relationships

#### Priority 4: Blog & Media (~200 documents)
- Blog posts
- Medium articles
- Announcements
- **Why fourth**: General content, varied structure

#### Priority 5: Forum Posts (~500 documents)
- Discourse discussions
- Community threads
- **Why fifth**: Informal, requires more processing

### Daily Goals
- Day 4: Process Priority 1-2 (80 docs)
- Day 5: Process Priority 3-4 (300 docs)

## Phase 4: Entity Resolution (Day 6)

### Tasks
- [ ] Identify duplicate entities
- [ ] Build alias mapping:
  - "Regen Network" = "RND" = "Regen Network Development"
  - "Gregory Landua" = "Greg Landua"
- [ ] Resolve coreferences within documents
- [ ] Merge entity properties
- [ ] Preserve provenance for all merges

### Deliverables
- `processors/entity_resolver.py`
- `storage/graph/entity_aliases.json`

## Phase 5: Claude Enhancement (Day 7)

### Preparation for Claude Processing
1. **Batch Creation**:
   - Group documents by type
   - Create extraction prompts
   - Prioritize complex documents

2. **Prompt Templates**:
   ```
   Extract relationships from this Regen Network document:
   - Who founded/works for which organizations?
   - Which projects generate which credit classes?
   - What claims are made about methodologies?
   ```

3. **Human Workflow**:
   - Switch to Claude Sonnet model
   - Run prepared prompts
   - Save structured outputs
   - Merge with existing graph

### Expected Extractions
- Complex relationships not caught by patterns
- Implicit claims and assertions
- Temporal information (when things happened)
- Confidence scores for extracted facts

## Phase 6: Validation & Export (Day 8)

### Validation Tasks
- [ ] Check ontology compliance
- [ ] Validate entity properties
- [ ] Verify relationship constraints
- [ ] Flag inconsistencies
- [ ] Generate quality metrics

### Export Formats
- [ ] JSON-LD with context
- [ ] RDF triples (N-Triples format)
- [ ] KOI-compatible format with RIDs
- [ ] Statistics and metrics report

### Deliverables
- `scripts/validate_graph.py`
- `scripts/export_graph.py`
- `storage/exports/knowledge_graph.jsonld`
- `storage/exports/knowledge_graph.nt`

## Success Metrics

### Quantitative Goals
- ✅ 500+ documents processed (excluding Twitter)
- ✅ 1000+ unique entities extracted
- ✅ 2000+ relationships identified
- ✅ 95%+ pattern extraction accuracy
- ✅ Full provenance for all extractions

### Quality Indicators
- Entity resolution accuracy (few false merges)
- Relationship validity (符合 ontology rules)
- Extraction coverage (key facts not missed)
- Processing efficiency (<10s per document)

## Provenance Tracking Schema

```json
{
  "document_id": "doc_123",
  "source_path": "indexing/storage/documents/doc_123.json",
  "processed_at": "2024-01-15T10:30:00Z",
  "ontology_version": "1.0.0",
  "extraction_methods": {
    "pattern": {
      "version": "1.0",
      "runtime_ms": 45,
      "entities_found": 8,
      "patterns_matched": ["credit_class", "project_id"]
    },
    "spacy": {
      "model": "en_core_web_lg",
      "version": "3.7.0",
      "runtime_ms": 230,
      "entities_found": 5
    },
    "claude": {
      "model": "claude-3-sonnet",
      "prompt_version": "v1",
      "runtime_ms": 1500,
      "relationships_extracted": 12,
      "claims_extracted": 8
    }
  },
  "total_entities": 21,
  "total_relationships": 12,
  "total_claims": 8,
  "processing_time_ms": 1775
}
```

## Risk Mitigation

### Potential Issues & Solutions

1. **Entity Over-splitting**
   - Risk: Same entity extracted multiple times
   - Solution: Aggressive entity resolution with aliases

2. **Relationship Hallucination**
   - Risk: Claude inferring non-existent relationships
   - Solution: Confidence thresholds, human validation

3. **Pattern Mismatches**
   - Risk: Patterns too strict/loose
   - Solution: Test on sample, iterate patterns

4. **Processing Time**
   - Risk: Claude processing too slow
   - Solution: Batch processing, selective enhancement

5. **Version Conflicts**
   - Risk: Ontology changes break extractions
   - Solution: Version tracking, migration scripts

## Daily Checklist

### Day 1 ✅
- [x] Directory structure created
- [x] Documentation written
- [ ] Ontology defined
- [ ] Patterns documented

### Day 2
- [ ] Base extractor implemented
- [ ] Pattern extractor tested
- [ ] Sample extractions validated

### Day 3
- [ ] spaCy configured
- [ ] Claude prompts designed
- [ ] Hybrid extractor working

### Day 4
- [ ] Registry data processed
- [ ] Technical docs processed
- [ ] Initial graph populated

### Day 5
- [ ] Governance docs processed
- [ ] Blog posts processed
- [ ] Relationships extracted

### Day 6
- [ ] Entities resolved
- [ ] Aliases mapped
- [ ] Graph consolidated

### Day 7
- [ ] Claude enhancement complete
- [ ] Complex relationships added
- [ ] Claims extracted

### Day 8
- [ ] Validation complete
- [ ] Exports generated
- [ ] Report written

## Next Steps After Completion

1. **Integration with KOI**: Add RID generation for entities
2. **Query Interface**: Build SPARQL or GraphQL endpoint
3. **Visualization**: Create graph visualization tool
4. **Real-time Updates**: Process new documents as indexed
5. **Quality Improvement**: Human-in-the-loop validation
6. **Twitter Processing**: Tackle the 50,000+ Twitter documents

## Notes

- Start simple, iterate based on results
- Preserve all raw extractions before resolution
- Document decisions and assumptions
- Keep extraction methods modular for easy updates
- Focus on accuracy over coverage initially
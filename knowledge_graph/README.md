# Regen Network Knowledge Graph

## Overview

This is a semantic knowledge graph extraction system for Regen Network content. It extracts entities (people, organizations, credit classes, projects) and their relationships from indexed documents using a hybrid approach combining pattern matching, NER, and Claude Sonnet for deep understanding.

## Features

- **Ontology-driven extraction**: Formal ontology defines what to extract
- **Multi-method extraction**: Combines patterns, spaCy NER, and Claude Sonnet
- **Full provenance tracking**: Know exactly how each fact was extracted
- **Incremental processing**: Add new documents without reprocessing everything
- **Entity resolution**: Automatically merges duplicate entities
- **Multiple export formats**: JSON-LD, RDF triples, KOI-compatible

## Quick Start

1. **Ensure documents are indexed**:
   ```bash
   ls /home/regenai/project/indexing/storage/documents/
   ```

2. **Run knowledge graph extraction** (excluding Twitter data):
   ```bash
   python scripts/build_knowledge_graph.py --exclude-twitter
   ```

3. **View extracted knowledge**:
   ```bash
   # Entities
   ls storage/graph/entities/
   
   # Relationships
   ls storage/graph/relationships/
   
   # Processing status
   cat storage/provenance/document_status.json
   ```

## Architecture

### Ontology Layer
- Defines entity types (Person, Organization, CreditClass, Project, etc.)
- Specifies valid relationships between entities
- Provides extraction patterns and rules
- Versioned for reproducibility

### Extraction Layer
- **Pattern Extractor**: Fast regex-based extraction for known formats (C01, P001, VM0042)
- **spaCy Extractor**: Named Entity Recognition for people, organizations, locations
- **Claude Extractor**: Deep semantic extraction using Claude Sonnet (you!)

### Processing Layer
- Document processor orchestrates extraction
- Entity resolver merges duplicates
- Relationship builder connects entities
- Provenance tracker logs all operations

### Storage Layer
- Graph data in JSON format
- Full extraction provenance
- Export to multiple formats
- Incremental update support

## Directory Structure

```
knowledge_graph/
├── ontology/           # Regen Network ontology definition
├── extractors/         # Various extraction methods
├── processors/         # Document processing pipeline
├── storage/           
│   ├── graph/         # Extracted knowledge
│   ├── provenance/    # Processing metadata
│   └── exports/       # Export formats
└── scripts/           # Execution scripts
```

## Entity Types

### Core Entities
- **Person**: Individuals in the ecosystem (founders, developers, validators)
- **Organization**: Companies, foundations, DAOs
- **CreditClass**: Carbon/biodiversity credit types (C01, C02, etc.)
- **Project**: Credit-generating projects (P001, P002, etc.)
- **Methodology**: Verification methodologies (VM0042, etc.)
- **Proposal**: Governance proposals
- **Document**: Source documents and their metadata

### Key Relationships
- Person -> `founded/employs/advises` -> Organization
- Project -> `generates` -> CreditClass
- Project -> `implements` -> Methodology
- Person -> `proposed` -> Proposal
- Document -> `mentions/references` -> Any Entity

## Processing Pipeline

1. **Document Selection**: Prioritize high-value content (registry, whitepapers)
2. **Pattern Extraction**: Fast extraction of known formats
3. **NER Extraction**: Entity recognition using spaCy
4. **Claude Enhancement**: Complex relationship and claim extraction
5. **Entity Resolution**: Merge duplicates, resolve coreferences
6. **Validation**: Check against ontology rules
7. **Export**: Generate various output formats

## Provenance Tracking

Every extraction is tracked with:
- Document ID and source
- Timestamp of extraction
- Ontology version used
- Extraction method(s) employed
- Confidence scores
- Processing time

Example provenance record:
```json
{
  "document_id": "registry_C01",
  "extraction_timestamp": "2024-01-15T10:30:00Z",
  "ontology_version": "1.0.0",
  "methods_used": {
    "pattern": ["C01", "VM0042"],
    "spacy": ["Regen Network"],
    "claude": {
      "relationships": 5,
      "claims": 3
    }
  }
}
```

## Usage Examples

### Process specific document types
```bash
# Process only registry data
python scripts/build_knowledge_graph.py --doc-type registry

# Process governance proposals
python scripts/build_knowledge_graph.py --doc-type governance
```

### Export knowledge graph
```bash
# Export to JSON-LD
python scripts/export_graph.py --format jsonld

# Export to RDF triples
python scripts/export_graph.py --format rdf

# Generate statistics
python scripts/export_graph.py --stats
```

### Validate against ontology
```bash
python scripts/validate_graph.py
```

## Statistics

Track extraction progress:
- Documents processed vs. pending
- Entities extracted by type
- Relationships identified
- Processing time per document
- Extraction method effectiveness

## Integration Points

- **KOI Node**: Entities get RIDs for knowledge tracking
- **Indexing System**: Reads from document storage
- **AI Agents**: Can query knowledge graph for facts
- **Analytics**: Provides structured data for analysis

## Future Enhancements

- [ ] Real-time extraction as documents are indexed
- [ ] SPARQL query endpoint
- [ ] Graph visualization interface
- [ ] Automated quality assessment
- [ ] Cross-document coreference resolution
- [ ] Temporal reasoning (track changes over time)

## Contributing

See `PLAN.md` for the implementation roadmap and `ONTOLOGY.md` for the ontology specification.

## License

Part of the Regen Network AI Infrastructure project.
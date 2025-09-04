# Eliza Knowledge Plugin Optimization Guide

## Key Findings from Documentation Review

After thoroughly reviewing the Eliza knowledge plugin documentation, here are the critical insights for optimizing our document conversion:

## 1. Document Structure Optimization

### Current Approach is Good ✅
Our markdown format with YAML frontmatter aligns well with Eliza's expectations:
- Markdown files are natively supported
- YAML frontmatter preserves metadata
- Clean content without HTML artifacts

### Recommended Adjustments

#### A. Chunk Size Awareness
- **Eliza chunks at 500 tokens** (~1,750 characters) with 100 token overlap
- **Don't pre-chunk**: Our documents should be complete and coherent
- **Let Eliza handle chunking**: The plugin will intelligently split documents

#### B. Content-Based Deduplication
- Eliza uses **first 2KB of content + agent ID + filename** for unique IDs
- **Risk**: Very similar documents might be deduplicated
- **Solution**: Ensure unique introductions or vary content structure

#### C. Optimal Document Size
- **Not too small**: Documents under 500 tokens won't benefit from chunking
- **Not too large**: Consider splitting massive documents (>100KB) into logical parts
- **Sweet spot**: 2-20KB per document for best retrieval

## 2. Metadata Optimization

### Current Frontmatter Structure
```yaml
---
source: github:regen-ledger
source_type: github
repository: regen-ledger
title: Document Title
tags: [technical, governance, blockchain]
category: technical
subcategory: regen-ledger
date: 2025-08-13
document_id: unique_hash
koi_rid: optional_koi_identifier
url: https://original.source.url
---
```

### Recommended Enhancements
```yaml
---
# Core fields for Eliza
title: Clear, Descriptive Title  # Used in retrieval
description: Brief summary (1-2 sentences)  # Helps with search
content_type: technical_guide  # More specific than category

# Source tracking
source: github:regen-ledger
url: https://original.source.url
date: 2025-08-13
version: 1.0  # If applicable

# Categorization
category: technical
subcategory: implementation
tags: 
  - regen-ledger
  - blockchain
  - cosmos-sdk
  - specific-feature  # More specific tags

# Optional enrichment
related_docs: [doc1.md, doc2.md]  # For cross-references
difficulty: intermediate  # If applicable
reading_time: 5min  # Helps users
---
```

## 3. Content Optimization

### Best Practices

#### A. Structure for Contextual Embeddings
When `CTX_KNOWLEDGE_ENABLED=true`, Eliza enriches chunks with document context:

**Good Structure:**
```markdown
# Main Topic

## Overview
Brief introduction that establishes context.

## Specific Section
Detailed content that can stand alone with the enriched context.

### Subsection
More specific details that benefit from hierarchical context.
```

**Avoid:**
- Excessive repetition of context within sections
- Orphaned references without explanation
- Assuming reader has seen previous sections

#### B. Code Block Preservation
```markdown
# Use proper code fencing
​```typescript
// Code with syntax highlighting
const example = "preserved correctly";
​```
```

#### C. Cross-References
```markdown
# Use descriptive links
See [Credit Class Management Guide](./credit_class_guide.md) for details.

# Not just "see here" or "as mentioned above"
```

## 4. Organization Optimization

### Current Structure ✅
```
knowledge/
└── regen-network/
    ├── technical/       # Good categorization
    ├── governance/      
    ├── ecological/      
    ├── community/       
    └── shared/         
```

### Recommended Refinements

#### A. Add Index Files
Create `_index.md` in each category:
```markdown
---
title: Technical Documentation Index
description: Overview of technical resources
---

# Technical Documentation

## Quick Links
- [Getting Started](./getting_started.md)
- [API Reference](./api_reference.md)
...
```

#### B. Consistent Naming Convention
```
# Good - predictable and sortable
governance/proposals/prop_001_initial_parameters.md
governance/proposals/prop_002_upgrade_v2.md

# Avoid - inconsistent
governance/Proposal1.md
governance/upgrade-proposal.md
```

## 5. Special Content Types

### Podcast Transcripts
- **Keep timestamps** for reference
- **Add speaker labels** if available
- **Split very long episodes** into parts (as we're doing)

### Medium Articles
- **Preserve publication date** in filename for chronological sorting
- **Keep author attribution** in metadata
- **Clean marketing CTAs** but preserve article structure

### Technical Documentation
- **Preserve code examples** completely
- **Keep version information** when applicable
- **Maintain internal document links**

## 6. Configuration Recommendations

### For RegenAI Character
```json
{
  "settings": {
    "LOAD_DOCS_ON_STARTUP": true,
    "KNOWLEDGE_PATH": "./knowledge",
    "CTX_KNOWLEDGE_ENABLED": true  // Add for 50% better retrieval
  }
}
```

### Environment Variables
```env
# Enable contextual embeddings for better retrieval
CTX_KNOWLEDGE_ENABLED=true

# If using OpenRouter for cost efficiency
TEXT_PROVIDER=openrouter
TEXT_MODEL=anthropic/claude-3-haiku
OPENROUTER_API_KEY=your-key

# Embedding provider (required)
OPENAI_API_KEY=your-key
```

## 7. Processing Recommendations

### Before Full Conversion

1. **Test Deduplication**: Check if similar documents are being merged
2. **Verify Metadata**: Ensure all required fields are present
3. **Sample Retrieval**: Test with queries to verify search quality
4. **Monitor First Load**: Watch logs when agent loads documents

### Optimization Checklist

- [ ] Documents have unique, descriptive titles
- [ ] Frontmatter includes description field
- [ ] Content is clean (no HTML artifacts)
- [ ] Code blocks are properly fenced
- [ ] Large documents split logically
- [ ] Similar documents have unique introductions
- [ ] Category folders have index files
- [ ] Filenames follow consistent convention
- [ ] Related documents are cross-referenced
- [ ] Tags are specific and useful

## 8. Potential Issues to Address

### Current Conversion Gaps

1. **Document IDs**: Our hash-based IDs might not align with Eliza's content-based IDs
2. **Duplicate Content**: Multiple similar documents might get deduplicated
3. **Large Transcripts**: Some podcasts might be too large even after splitting
4. **HTML Remnants**: Ensure complete HTML cleaning in website docs

### Suggested Improvements

1. **Add Description Field**: Generate 1-2 sentence summaries for each document
2. **Enrich Tags**: Make tags more specific and action-oriented
3. **Version Tracking**: Add version fields where applicable
4. **Reading Time**: Calculate and add reading time estimates
5. **Difficulty Levels**: Add for technical documentation

## 9. Testing Strategy

### Phase 1: Small Batch Test
1. Convert 5 documents per category
2. Load into test agent
3. Test retrieval with various queries
4. Check for deduplication issues

### Phase 2: Category Test
1. Convert one full category
2. Verify folder structure
3. Test cross-references
4. Measure retrieval accuracy

### Phase 3: Full Conversion
1. Run complete conversion
2. Monitor agent startup time
3. Test complex queries
4. Verify all content accessible

## 10. Performance Expectations

With our ~400 documents:
- **Initial Load Time**: 2-5 minutes (with embeddings)
- **Memory Usage**: ~100-200MB for embeddings
- **Query Response**: <2 seconds
- **Deduplication**: Possible 10-20% reduction in similar content

## Summary

Our current conversion approach is fundamentally sound. Key optimizations:

1. **Don't over-process**: Let Eliza handle chunking and embedding
2. **Enrich metadata**: Add descriptions and better tags
3. **Clean content**: Ensure no HTML artifacts remain
4. **Logical organization**: Current structure is good, add indexes
5. **Enable contextual embeddings**: 50% better retrieval with CTX_KNOWLEDGE_ENABLED=true

The most important change is ensuring each document has:
- A clear, unique title
- A brief description in frontmatter
- Clean, well-structured content
- Specific, actionable tags

These optimizations will maximize the effectiveness of Eliza's knowledge retrieval system.
# Regen Network Ontology v1.0.0

## Overview

This document defines the formal ontology for the Regen Network knowledge graph. The ontology specifies entity types, their properties, relationships between entities, and extraction rules.

## Core Principles

1. **Domain-Specific**: Focused on Regen Network's ecosystem
2. **Extraction-Oriented**: Designed to guide information extraction
3. **Extensible**: Can add new types without breaking existing ones
4. **Versioned**: Track changes over time
5. **Validated**: Rules ensure consistency

## Entity Types

### 1. Actor Entities

#### Person
**Definition**: An individual person involved in the Regen Network ecosystem

**Properties**:
- `name` (required): Full name
- `role`: Position or title (founder, developer, validator, advisor)
- `walletAddress`: Regen wallet address (regen1...)
- `socialHandles`: Twitter, Discord, GitHub usernames
- `email`: Contact email
- `affiliations`: Organizations they're associated with

**Extraction Patterns**:
- Look for names with titles: "Gregory Landua, CEO"
- Check document authors and signatories
- Find @mentions in social content
- Look for wallet addresses associated with names

**Examples**:
- Gregory Landua (Founder)
- Will Szal (Technology Lead)
- Validators with regenvaloper addresses

#### Organization
**Definition**: A company, foundation, DAO, or other organized entity

**Subtypes**:
- `CoreOrganization`: Regen Network, Regen Foundation, RND PBC
- `ValidatorOrganization`: Validators in the network
- `PartnerOrganization`: Microsoft, Google, corporate partners
- `StandardsBody`: Verra, Gold Standard, Climate Action Reserve
- `ProjectDeveloper`: Organizations developing credit projects

**Properties**:
- `name` (required): Official organization name
- `type`: Organization type from subtypes above
- `website`: Official website URL
- `walletAddress`: Organization's wallet
- `role`: Role in ecosystem (issuer, validator, buyer)
- `location`: Headquarters or primary location

**Extraction Patterns**:
- Look for "Inc", "Foundation", "Network", "DAO", "Labs"
- Check for known organizations list
- Find URLs and domain names
- Look for "partnered with", "validated by"

#### AIAgent
**Definition**: AI agents in the Regen ecosystem

**Properties**:
- `name` (required): Agent name (Advocate, Politician, etc.)
- `platform`: Where the agent operates (Twitter, Discord)
- `koiRid`: KOI Resource Identifier
- `creator`: Organization that created/operates it
- `purpose`: Agent's primary function

**Extraction Patterns**:
- References to "agent", "bot", "AI"
- Known agent names from contract

### 2. Environmental Entities

#### CreditClass
**Definition**: A class of environmental credits (carbon, biodiversity, etc.)

**Properties**:
- `classId` (required): Unique identifier (C01, C02, C03)
- `creditType`: Type of credit (carbon, biodiversity, soil, water)
- `methodology`: Associated methodology (VM0042, etc.)
- `status`: Active, retired, proposed
- `description`: What the credit represents
- `issuer`: Organization that issues credits

**Extraction Patterns**:
- Regex: `\bC\d{2,3}\b`
- Look for "credit class", "C01", "carbon credits"
- Check registry documents

**Examples**:
- C01: Verified Carbon Credits
- C02: Biodiversity Credits
- C03: Soil Carbon Credits

#### Project
**Definition**: A project that generates environmental credits

**Properties**:
- `projectId` (required): Unique identifier (P001, P002)
- `name`: Project name
- `location`: Geographic location (coordinates, country, region)
- `developer`: Organization developing the project
- `creditClass`: Which credit class it generates
- `startDate`: When project started
- `endDate`: When project ends
- `status`: Planning, active, completed

**Extraction Patterns**:
- Regex: `\bP\d{3,4}\b`
- Look for "project", followed by ID
- Geographic references near project mentions

#### Methodology
**Definition**: Verification methodology for credit generation

**Properties**:
- `methodologyId` (required): Identifier (VM0042, etc.)
- `name`: Full methodology name
- `version`: Version number
- `standardBody`: Organization that created it (Verra, etc.)
- `creditTypes`: What credit types it applies to

**Extraction Patterns**:
- Regex: `\bVM\d{4}\b`
- Look for "methodology", "verification standard"
- References to Verra, Gold Standard

### 3. Governance Entities

#### Proposal
**Definition**: A governance proposal in the Regen Network

**Properties**:
- `proposalId` (required): Numeric ID
- `title`: Proposal title
- `proposer`: Person or Organization that proposed
- `status`: Draft, voting, passed, rejected
- `proposalDate`: When proposed
- `voteEndDate`: When voting ends
- `type`: Parameter change, spend, text, upgrade

**Extraction Patterns**:
- "Proposal #N", "Prop N"
- Look in governance documents
- Check forum discussions about proposals

#### Vote
**Definition**: A vote cast on a proposal

**Properties**:
- `voter` (required): Who voted
- `proposal`: Which proposal
- `voteType`: Yes, No, Abstain, NoWithVeto
- `weight`: Voting power (token amount)
- `timestamp`: When vote was cast
- `reason`: Optional explanation

**Extraction Patterns**:
- "voted yes/no on"
- "supports/opposes proposal"
- Look in voting records

### 4. Content Entities

#### Document
**Definition**: A document containing information

**Types**:
- `Whitepaper`: Technical or strategic papers
- `BlogPost`: Blog articles
- `ForumPost`: Forum discussions
- `Proposal`: Governance proposals
- `Methodology`: Methodology documents
- `TechnicalDoc`: Technical documentation

**Properties**:
- `documentId` (required): Unique identifier
- `title`: Document title
- `url`: Source URL
- `author`: Person or Organization
- `publishDate`: Publication date
- `documentType`: Type from above
- `koiRid`: KOI identifier if available

#### Claim
**Definition**: A factual claim or assertion made in content

**Properties**:
- `statement` (required): The claim text
- `claimant`: Who made the claim
- `source`: Document containing claim
- `confidence`: Extraction confidence (0-1)
- `evidence`: Supporting text
- `subject`: What the claim is about

**Extraction Patterns**:
- Statements with "is", "will", "has"
- Quoted statements
- Statistical claims with numbers

## Relationships

### Person-Organization Relationships
- `founded`: Person founded Organization
- `employs`: Organization employs Person
- `advises`: Person advises Organization
- `represents`: Person represents Organization

### Project-Credit Relationships
- `generates`: Project generates CreditClass
- `implements`: Project implements Methodology
- `validates`: Organization validates Project

### Document Relationships
- `authoredBy`: Document authored by Person/Organization
- `references`: Document references Entity
- `contains`: Document contains Claim

### Governance Relationships
- `proposed`: Person proposed Proposal
- `votedOn`: Person voted on Proposal
- `governs`: Proposal governs Entity

## Extraction Rules

### Priority Rules
1. **Exact Patterns First**: Use regex for known formats (C01, P001)
2. **Context Matters**: "C01" alone might be ambiguous, but "C01 carbon credits" is clear
3. **Prefer Specific**: "Regen Network Development PBC" over just "Regen"

### Validation Rules
1. **Credit Classes**: Must start with 'C' followed by 2-3 digits
2. **Projects**: Must start with 'P' followed by 3-4 digits
3. **Wallet Addresses**: Must start with 'regen1' and be 44 chars
4. **Methodologies**: Must match pattern VM followed by 4 digits

### Relationship Rules
1. **Cardinality**: 
   - Project has ONE credit class
   - Credit class has ONE methodology
   - Person can have MANY organizations

2. **Validity**:
   - Only Organizations can validate Projects
   - Only Persons can propose Proposals
   - Only Projects can generate Credits

### Confidence Scoring
- **High (0.9-1.0)**: Pattern match with context
- **Medium (0.6-0.9)**: NER extraction with validation
- **Low (0.3-0.6)**: Claude inference without strong evidence

## Versioning

### Version 1.0.0 (Current)
- Initial entity types defined
- Core relationships established
- Basic extraction patterns

### Future Versions
- v1.1.0: Add temporal properties
- v1.2.0: Add financial entities (transactions, tokens)
- v2.0.0: Major restructure if needed

## Usage Examples

### Entity Extraction
```python
# Extract credit class from text
text = "The C01 carbon credit class uses VM0042 methodology"
entities = extract_entities(text, ontology)
# Returns: CreditClass(classId="C01", creditType="carbon", methodology="VM0042")
```

### Relationship Extraction
```python
text = "Gregory Landua founded Regen Network"
relationships = extract_relationships(text, ontology)
# Returns: (Person:"Gregory Landua", "founded", Organization:"Regen Network")
```

### Validation
```python
# Validate entity against ontology
entity = CreditClass(classId="X99")  # Invalid format
is_valid = ontology.validate(entity)  # Returns False
```

## Integration with KOI

Each entity gets a KOI RID following Regen's naming convention:
- `core.credit.c01.v1.0.0` - Credit class C01
- `relevant.person.gregory-landua.v1.0.0` - Person entity
- `core.project.p001.v1.0.0` - Project P001

## Notes for Extractors

1. **Start Conservative**: Better to miss some entities than extract wrong ones
2. **Use Context**: "Network" alone is not an organization, "Regen Network" is
3. **Check Aliases**: "RND" = "Regen Network Development"
4. **Preserve Provenance**: Always track how/where entity was extracted
5. **Handle Uncertainty**: Use confidence scores, flag for review

## Quality Assurance

### Test Cases
- Credit class extraction: "C01", "C02", "C03" should extract
- Project extraction: "P001", "P002" should extract  
- Person extraction: "Gregory Landua" with context should extract
- Relationship: "founded by" should create founded relationship

### Common Errors to Avoid
- Don't extract "C" alone as credit class
- Don't extract partial names as persons
- Don't create relationships without clear evidence
- Don't merge entities too aggressively

This ontology will evolve as we process more documents and discover new patterns.
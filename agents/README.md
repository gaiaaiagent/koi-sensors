# AI Agents

## Phase 2 Implementation

This directory will contain the implementation of four specialized AI agents for the Regen Network ecosystem:

### 🎭 Narrative Agent
- Platform: X (Twitter) and Farcaster
- Purpose: Storytelling and content creation
- Posting: 4-6 times daily with three narrative variants

### 🏛️ Politician Agent  
- Platform: Discord and Telegram
- Purpose: Governance facilitation
- Features: Proposal summaries, discussion facilitation, token economics insights

### 🌱 Advocate Agent
- Platform: All platforms
- Purpose: Credit class education and marketplace support
- Features: Real-time availability, methodology explanations, FAQ responses

### 🌿 Voice of Nature Agent
- Platform: Cross-platform
- Purpose: Philosophical content and impact stories
- Features: Weekly content, credit impact stories, foundation mission alignment

## Architecture

```
agents/
├── base/                   # Shared agent infrastructure
├── narrative/              # Storytelling agent implementation
├── politician/             # Governance agent implementation
├── advocate/               # Support agent implementation
├── voice_of_nature/        # Philosophical agent implementation
├── orchestration/          # Cross-platform coordination
└── personalities/          # Agent personality definitions
```

## Integration Points

- **Knowledge Base**: Queries the indexing system for accurate information
- **MCP Server**: Real-time blockchain data for current state
- **Analytics**: Performance tracking and A/B testing
- **KOI**: Content tagging with RIDs for attribution

## Development Status

🔄 **Phase 2** - Pending completion of knowledge infrastructure (Milestone 1.1)
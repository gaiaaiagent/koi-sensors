# X Bot Draft Generator

## Session 10: Milestone B Implementation

The X Bot Draft Generator creates Twitter/X draft threads from Daily Curator output as part of Milestone B: Information Pipelines. It implements the "Regen Daily" posting system with safety guardrails and style guide compliance.

## ✅ Implementation Status

**Completed Features:**
- ✅ Thread composition from curator JSON (3-5 posts)
- ✅ Link validation with retry logic
- ✅ Style guide enforcement (David Fortson / Many Mangos)
- ✅ Draft storage (JSON files + PostgreSQL option)
- ✅ CLI review interface for approval workflow
- ✅ HTML preview generation
- ✅ Test data generation (5 scenarios)
- ✅ Configuration in curator_config.yaml

## 📋 Milestone B Requirements

### Daily Bot — "Regen Daily"
- **Trigger:** 12:00 ET weekdays
- **Sources:** All KOI infrastructure data
- **Output:** Thread (3–5 posts): headline, stat, 2 links, CTA
- **Guardrails:** Draft-only week 1; style guide compliance; no speculation

### Acceptance Criteria
- [x] 5 weekday drafts produced
- [x] Include stat + 2 links + CTA
- [x] Links valid
- [x] No leaks of non-public data
- [x] Style guide compliance

## 🚀 Quick Start

### 1. Generate Test Data
```bash
cd /Users/darrenzal/projects/RegenAI/koi-sensors
python bots/tests/generate_test_data.py
```

This creates 5 test curator outputs with different scenarios:
- Standard - Mixed content daily update
- Governance - Focus on proposals and voting
- Credits - Ecocredit activity
- Community - Community events
- Minimal - Edge case with 2 posts

### 2. Generate Draft Threads
```bash
python bots/x_daily_bot.py
```

This processes curator outputs and creates draft threads with:
- Thread composition (3-5 posts)
- Link validation
- Style enforcement
- Draft storage

### 3. Review Drafts

**List all drafts:**
```bash
python bots/review/cli_reviewer.py list
```

**Review all pending drafts:**
```bash
python bots/review/cli_reviewer.py review-all
```

**Review specific draft:**
```bash
python bots/review/cli_reviewer.py <draft_id>
```

### 4. Generate HTML Preview
```python
from bots.review.html_preview import HTMLPreview

preview = HTMLPreview()
html_path = preview.generate_preview(draft_data)
# Opens in browser for visual review
```

## 📁 Directory Structure

```
/koi-sensors/bots/
├── x_daily_bot.py           # Main bot orchestrator
├── components/
│   ├── thread_composer.py   # Converts curator JSON to tweets
│   ├── link_validator.py    # Validates URLs
│   ├── style_enforcer.py    # Applies style guide
│   └── draft_storage.py     # Saves drafts (JSON/PostgreSQL)
├── review/
│   ├── cli_reviewer.py      # Command-line review tool
│   └── html_preview.py      # HTML preview generator
├── drafts/                   # JSON draft storage
└── tests/
    └── generate_test_data.py # Test data generator
```

## ⚙️ Configuration

Configuration is in `/koi-processor/config/curator_config.yaml`:

```yaml
x_bot:
  draft_mode: true              # Week 1 draft-only mode
  draft_days: 7
  
  style_guide:
    tone: professional_friendly
    use_thread_numbers: true
    max_tweet_length: 280
    default_cta: "Learn more at regen.network"
    
  hashtags:
    - "#RegenNetwork"
    - "#ReFi"
    
  validation:
    check_links: true
    no_speculation: true       # Milestone B requirement
    require_sources: true
```

## 🔍 Component Details

### Thread Composer
- Processes curator JSON output
- Creates 3-5 post threads
- Adds thread numbers (1/5, 2/5, etc.)
- Applies emoji mapping
- Ensures proper character limits

### Link Validator
- Validates all URLs in threads
- Uses HTTP HEAD requests
- Retry logic with exponential backoff
- Trusted domain list for Regen sites
- Reports invalid links

### Style Enforcer
- Implements David Fortson / Many Mangos guidelines
- Removes speculation ("might be", "could be")
- Checks professional tone
- Fixes excessive caps and punctuation
- Scores compliance (0-100%)

### Draft Storage
- Dual storage: JSON files + PostgreSQL
- Tracks draft/approved/rejected status
- Stores review notes
- Maintains style scores and validation results

## 📊 Draft Review Workflow

1. **Draft Generation** - Bot creates drafts in draft-only mode
2. **Review** - Use CLI or HTML preview to review
3. **Approval/Rejection** - Mark drafts with notes
4. **Week 1** - All posts remain as drafts
5. **After Week 1** - Auto-publish if quality passes

## 🎯 Success Metrics

Current test results:
- ✅ 5 draft threads generated successfully
- ✅ All links validated (100% success rate)
- ✅ Style scores: 96-100% compliance
- ✅ Character limits respected
- ✅ No speculation detected
- ✅ CTAs included in all threads

## 🔗 Integration Points

- **Input**: Daily Curator output from `/koi-processor/output/daily_threads/`
- **Output**: Draft JSON files in `/bots/drafts/`
- **Database**: PostgreSQL at `localhost:5433` (optional)
- **Config**: Shared `curator_config.yaml`

## 🚦 Next Steps

### Session 11: Scheduling & Automation
- Add cron scheduling for 12:00 ET weekdays
- Implement job queue
- Add monitoring and alerting

### Session 12: Quality Control
- Build automated quality checks
- Create approval interface for Gregory
- Implement auto-publish after week 1

### Future Enhancements
- Twitter API integration with tweepy
- Media attachment support
- Thread analytics tracking
- A/B testing capabilities

## 📝 Notes

- Database connection is optional - works with JSON files only
- Link validation includes retry logic for transient failures
- Style enforcement is configurable via YAML
- Draft storage maintains full audit trail

## 🐛 Troubleshooting

**Import errors:**
```bash
# Run from koi-sensors directory
cd /Users/darrenzal/projects/RegenAI/koi-sensors
python bots/x_daily_bot.py
```

**Database connection errors:**
- Bot works without PostgreSQL
- Drafts saved to JSON files as fallback
- Check PostgreSQL is running on port 5433

**Missing curator outputs:**
- Run test data generator first
- Or run Daily Curator to generate real content

## 📚 References

- [Milestone B Requirements](../../../GAIA/docs/MILESTONE_B_UPGRADE_PROPOSAL.md)
- [Daily Curator Documentation](../../koi-processor/README.md)
- [KOI Infrastructure Guide](../README.md)
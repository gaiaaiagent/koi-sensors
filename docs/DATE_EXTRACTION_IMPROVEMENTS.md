# Date Extraction Pipeline Improvements

## Overview
Enhanced the KOI sensor network to properly extract, pass through, and store publication dates for all content. This enables accurate daily and weekly digest generation based on actual publication dates rather than collection timestamps.

## Key Improvements

### 1. Bundle System Enhancement
**File:** `koi_protocol/core/bundle_system.py`
- Fixed critical issue where `published_at` metadata was not being passed from documents to bundles
- Now preserves `published_at` and `published_confidence` in bundle manifest metadata

### 2. Event Bridge Date Conversion
**File:** `src/core/koi_event_bridge_v2.py`
- Fixed type mismatch where PostgreSQL expected datetime objects but received strings
- Added automatic conversion of ISO format date strings to datetime objects
- Handles both `published_at` and `created_at` fields with appropriate confidence levels

### 3. Sensor-Specific Improvements

#### Medium Sensor
**File:** `sensors/medium/medium_sensor.py`
- Added fallback date extraction using regex patterns (e.g., "Jul 3, 2024")
- Extracts dates from article content when `<time>` elements are not available
- Fixed coordinator event handling error

#### Discourse Sensor
**File:** `sensors/discourse/discourse_sensor.py`
- Already had proper date extraction from API
- Fixed coordinator event handling error
- Maintains high confidence (0.95) for API-provided timestamps

#### GitHub Sensor
**File:** `sensors/github/github_sensor.py`
- Enhanced to capture git commit messages and authors
- Extracts dates from:
  - Markdown frontmatter (0.8 confidence)
  - Git commit history (0.85 confidence)
  - File modification time (0.6 confidence)
- Fixed coordinator event handling error

#### GitLab Sensor
**File:** `sensors/gitlab/gitlab_sensor.py`
- Removed `--depth 1` to get full git history
- Added git log support for commit dates
- Enhanced to capture commit messages and authors
- Same confidence levels as GitHub sensor

### 4. Daily Curator & Weekly Aggregator
**Files:** `src/content/daily_curator.py`, `src/content/weekly_aggregator.py`
- Fixed content extraction from JSON structures
- Added heartbeat filtering in queries
- Expanded time windows for better coverage
- Integrated Regen MCP for blockchain statistics

## Git Commit Context Enhancement
Both GitHub and GitLab sensors now capture:
- **Commit messages** (subject + body) - explains what changed and why
- **Commit authors** - shows who made changes
- This metadata provides valuable context for digest generation

## Results
- **385 memories with dates** (up from 178 initially)
- **20.9% date coverage** across all content
- **100% coverage** for Discourse posts
- **99% coverage** for Medium articles
- High confidence dates from git history

## Usage for Digest Generation
The daily and weekly curators can now:
1. Filter content by actual publication date
2. Include commit context in summaries
3. Generate more accurate timelines
4. Provide better attribution

## Technical Details

### Date Extraction Priority
1. Content metadata (frontmatter, API data) - Highest confidence
2. Git commit dates - High confidence (0.85)
3. File system dates - Lower confidence (0.6)

### Date Format
All dates are stored as PostgreSQL timestamp with timezone, ensuring consistency across the system.

### Backward Compatibility
The improvements maintain backward compatibility with existing content while enhancing new content collection.
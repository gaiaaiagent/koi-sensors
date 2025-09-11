# GitHub/GitLab Repository Sensors

KOI sensors for collecting documentation from GitHub and GitLab repositories.

## Overview

These sensors index documentation from Regen Network's repositories:
- **GitHub Sensor**: Collects from regen-ledger, regen-web, regenie-corpus, and mcp repositories
- **GitLab Sensor**: Collects from regen-public-docs repository (includes whitepapers)

## Features

- Clones repositories using shallow clones for efficiency
- Extracts documentation files (Markdown, YAML, JSON, config files, etc.)
- Generates unique RIDs for each document
- Sends documents to KOI Event Bridge for processing
- Handles both GitHub and GitLab repository structures
- Filters out binary files and build artifacts
- Supports branch selection (main/master)

## Installation

```bash
# Dependencies are minimal - using standard libraries
pip install httpx aiohttp
```

## Usage

### Test Both Sensors

```bash
cd /Users/darrenzal/projects/RegenAI/koi-sensors/sensors/github
python test_git_sensors.py
```

### Run GitHub Sensor Standalone

```python
from github_sensor import GitHubSensor, GitHubConfig

config = GitHubConfig(
    repos=[
        {
            "name": "regen-ledger",
            "url": "https://github.com/regen-network/regen-ledger",
            "branch": "main",
            "paths": ["."]  # Get all documentation
        }
    ]
)

sensor = GitHubSensor(config)
documents = await sensor.collect_all_repos()
```

### Run GitLab Sensor Standalone

```python
from gitlab_sensor import GitLabSensor, GitLabConfig

config = GitLabConfig(
    repos=[
        {
            "name": "regen-public-docs",
            "url": "https://gitlab.com/regen-network/regen-public-docs",
            "branch": "master",
            "paths": ["."]
        }
    ]
)

sensor = GitLabSensor(config)
documents = await sensor.collect_all_repos()
```

## Document Structure

Each collected document contains:
- `rid`: Unique Resource ID (e.g., "github:regen-ledger:docs:README.md")
- `source`: "github" or "gitlab"
- `repo`: Repository name
- `file_path`: Relative path within repository
- `url`: Full URL to file in repository
- `branch`: Git branch
- `content`: File content (text for most files, metadata for PDFs)
- `metadata`: File type, size, lines, collection timestamp

## File Types Indexed

- Markdown files (*.md, *.mdx)
- Documentation (*.rst, *.txt, *.asciidoc)
- Configuration (*.json, *.yaml, *.yml, *.toml, *.ini)
- PDFs (metadata only, marked for extraction)
- LaTeX source files (*.tex)
- License and copyright files
- README, CHANGELOG, CONTRIBUTING files

## Excluded Directories

The sensors automatically skip:
- node_modules, vendor, dist, build
- .git, __pycache__, .pytest_cache
- coverage, .next, out, target, bin
- .vscode, .idea
- Hidden directories (starting with .)

## Test Results

Successfully tested collection of:
- **54 documents from GitHub** (4 repositories)
  - regen-ledger: 47 files
  - regen-web: 3 files
  - regenie-corpus: 3 files
  - mcp: 1 file
- **7 documents from GitLab** (1 repository)
  - Including 2 whitepapers (PDF and LaTeX)
  - Architecture and Protocol documents

## KOI Integration

Documents are sent to the KOI Event Bridge at `http://localhost:8089` with:
- Event type: "NEW"
- Source sensor: "github-sensor" or "gitlab-sensor"
- Bundle containing RID, CID, content, and metadata
- Automatic embedding generation via BGE pipeline

## Configuration

### GitHub Repositories

```python
repos = [
    {
        "name": "regen-ledger",
        "url": "https://github.com/regen-network/regen-ledger",
        "branch": "main",
        "paths": ["docs", "README.md", "x/ecocredit/spec"]
    },
    {
        "name": "regen-web",
        "url": "https://github.com/regen-network/regen-web",
        "branch": "main",
        "paths": ["docs", "README.md"]
    },
    {
        "name": "regenie-corpus",
        "url": "https://github.com/regen-network/regenie-corpus",
        "branch": "main",
        "paths": ["."]
    },
    {
        "name": "mcp",
        "url": "https://github.com/regen-network/mcp",
        "branch": "main",
        "paths": ["docs", "README.md"]
    }
]
```

### GitLab Repository

```python
repos = [
    {
        "name": "regen-public-docs",
        "url": "https://gitlab.com/regen-network/regen-public-docs",
        "branch": "master",
        "paths": ["."]
    }
]
```

## Output

Test outputs are saved to `test_outputs/` directory:
- `all_git_docs_YYYYMMDD_HHMMSS.json`: Combined documents from all repositories
- Individual test runs create timestamped JSON files

## Next Steps

1. Start KOI Event Bridge for document indexing
2. Configure additional repositories as needed
3. Set up scheduled collection (daily/weekly)
4. Add PDF content extraction for whitepapers
5. Integrate with daily content curator
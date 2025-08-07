# Authentication Setup

This directory contains authentication setup scripts and documentation for various services.

## GitHub Authentication

Since deploy keys are disabled for the gaiaaiagent organization, use Personal Access Tokens:

```bash
cd auth/github
./setup_pat_auth.sh
```

See [github/SETUP_PAT.md](github/SETUP_PAT.md) for detailed instructions.

## Future Authentication

Additional authentication setups will be added here as needed:
- Discord bot tokens
- Discourse API keys
- Twitter API credentials
- Notion API tokens
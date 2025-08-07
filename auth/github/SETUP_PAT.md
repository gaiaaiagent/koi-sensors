# Setting Up GitHub Authentication with Personal Access Token

Since deploy keys are disabled for the gaiaaiagent organization, we'll use Personal Access Tokens (PAT) for authentication.

## Quick Setup Guide

### Step 1: Create a Personal Access Token

1. Go to GitHub Settings: https://github.com/settings/tokens/new
2. Give your token a descriptive name: "regen-ai-server"
3. Set expiration (recommend 90 days for security)
4. Select scopes:
   - ✅ `repo` (Full control of private repositories)
   - ✅ `workflow` (Update GitHub Action workflows)
5. Click "Generate token"
6. **IMPORTANT**: Copy the token immediately (you won't see it again!)

### Step 2: Configure Git to Use the Token

Run these commands (replace `YOUR_TOKEN` with your actual token):

```bash
# Option A: Store token for this repository only
cd /home/regenai/project
git remote set-url origin https://YOUR_GITHUB_USERNAME:YOUR_TOKEN@github.com/gaiaaiagent/regen-ai.git

# Option B: Store token globally (for all repositories)
git config --global credential.helper store
git push origin main
# When prompted:
# Username: your-github-username
# Password: your-personal-access-token
```

### Step 3: For Multiple Users on Same Server

Since multiple developers will use this server, each should:

1. Create their own PAT following Step 1
2. Store it in their own user directory:

```bash
# Create a secure credentials file
echo "https://YOUR_USERNAME:YOUR_TOKEN@github.com" > ~/.git-credentials
chmod 600 ~/.git-credentials

# Configure git to use it
git config --global credential.helper store
```

## Alternative: GitHub CLI (Recommended for Teams)

GitHub CLI provides a more secure and convenient way to authenticate:

```bash
# Install GitHub CLI
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh -y

# Authenticate (interactive)
gh auth login

# Select:
# - GitHub.com
# - HTTPS
# - Authenticate with browser or paste token
```

## Security Best Practices

1. **Token Rotation**: Rotate tokens every 90 days
2. **Minimal Scope**: Only grant necessary permissions
3. **Secure Storage**: Never commit tokens to the repository
4. **User Isolation**: Each developer should use their own token
5. **Revoke Compromised Tokens**: https://github.com/settings/tokens

## Testing Authentication

After setup, test with:

```bash
# Test push
git push origin main

# Test with gh CLI
gh repo view gaiaaiagent/regen-ai
```

## Troubleshooting

### "Authentication failed"
- Verify token hasn't expired
- Check token has `repo` scope
- Ensure correct username/token in URL

### "Permission denied"
- Verify you're a collaborator on the repository
- Check organization settings allow token access

### Token in Command History
If you accidentally put token in shell history:
```bash
# Clear specific line from history
history -d <line_number>

# Clear entire history (careful!)
history -c
```

## For Repository Admins

To add collaborators:
1. Go to: https://github.com/gaiaaiagent/regen-ai/settings/access
2. Click "Add people"
3. Add GitHub usernames
4. Set appropriate permission level

## Next Steps

After authentication is set up:
1. Continue development on indexing system
2. Run full indexing to collect 15,000+ documents
3. Complete Milestone 1.1 requirements

---

Note: Since deploy keys are disabled by the organization, PATs or GitHub CLI are the recommended authentication methods for this project.
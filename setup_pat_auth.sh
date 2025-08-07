#!/bin/bash

# Setup script for GitHub Personal Access Token authentication
# Use this since deploy keys are disabled for gaiaaiagent organization

set -e

echo "=================================="
echo "GitHub PAT Authentication Setup"
echo "=================================="
echo ""
echo "Since deploy keys are disabled, we'll use Personal Access Tokens."
echo ""

# Function to validate token
validate_token() {
    local token=$1
    local username=$2
    
    echo "Validating token..."
    response=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: token $token" \
        https://api.github.com/user)
    
    if [ "$response" == "200" ]; then
        echo "✅ Token is valid!"
        return 0
    else
        echo "❌ Token validation failed (HTTP $response)"
        return 1
    fi
}

# Function to setup repository-specific auth
setup_repo_auth() {
    local username=$1
    local token=$2
    
    echo "Setting up repository authentication..."
    
    # Change to project directory
    cd /home/regenai/project
    
    # Update remote URL with embedded credentials
    git remote set-url origin "https://${username}:${token}@github.com/gaiaaiagent/regen-ai.git"
    
    echo "✅ Repository remote updated with authentication"
}

# Function to setup global auth
setup_global_auth() {
    local username=$1
    local token=$2
    
    echo "Setting up global authentication..."
    
    # Create credentials file
    echo "https://${username}:${token}@github.com" > ~/.git-credentials
    chmod 600 ~/.git-credentials
    
    # Configure credential helper
    git config --global credential.helper store
    git config --global user.name "$username"
    
    echo "✅ Global credentials configured"
}

# Function to install GitHub CLI
install_gh_cli() {
    echo "Installing GitHub CLI..."
    
    if command -v gh &> /dev/null; then
        echo "GitHub CLI already installed"
        return 0
    fi
    
    # Add GitHub CLI repository
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    
    # Install
    sudo apt update
    sudo apt install gh -y
    
    echo "✅ GitHub CLI installed"
}

# Main menu
echo "Choose setup method:"
echo ""
echo "1) Personal Access Token (Quick setup)"
echo "2) GitHub CLI (Recommended for long-term use)"
echo "3) Manual setup (Show instructions only)"
echo "4) Exit"
echo ""

read -p "Enter choice [1-4]: " choice

case $choice in
    1)
        echo ""
        echo "Personal Access Token Setup"
        echo "----------------------------"
        echo ""
        echo "First, create a token at: https://github.com/settings/tokens/new"
        echo "Required scopes: [repo] [workflow]"
        echo ""
        read -p "Enter your GitHub username: " github_username
        echo ""
        echo "Enter your Personal Access Token (hidden):"
        read -s github_token
        echo ""
        
        # Validate token
        if validate_token "$github_token" "$github_username"; then
            echo ""
            echo "Choose authentication scope:"
            echo "1) This repository only"
            echo "2) All repositories (global)"
            read -p "Enter choice [1-2]: " scope_choice
            
            case $scope_choice in
                1)
                    setup_repo_auth "$github_username" "$github_token"
                    ;;
                2)
                    setup_global_auth "$github_username" "$github_token"
                    ;;
                *)
                    echo "Invalid choice"
                    exit 1
                    ;;
            esac
            
            echo ""
            echo "Testing authentication..."
            cd /home/regenai/project
            if git fetch origin &> /dev/null; then
                echo "✅ Authentication successful!"
                echo ""
                echo "You can now push to the repository without entering credentials."
                echo "Test with: git push origin main"
            else
                echo "⚠️  Authentication test failed. Please check your token and permissions."
            fi
        else
            echo "Token validation failed. Please check:"
            echo "1. Token is copied correctly"
            echo "2. Token has 'repo' scope"
            echo "3. Token hasn't expired"
            exit 1
        fi
        ;;
        
    2)
        echo ""
        echo "GitHub CLI Setup"
        echo "----------------"
        
        # Check if gh is installed
        if ! command -v gh &> /dev/null; then
            read -p "GitHub CLI not installed. Install now? [y/n]: " install_choice
            if [ "$install_choice" == "y" ] || [ "$install_choice" == "Y" ]; then
                install_gh_cli
            else
                echo "Please install GitHub CLI manually first"
                exit 1
            fi
        fi
        
        echo ""
        echo "Starting GitHub CLI authentication..."
        echo "Follow the prompts to authenticate via browser or token"
        echo ""
        gh auth login
        
        echo ""
        echo "✅ GitHub CLI configured!"
        echo "You can now use 'gh' commands and git operations will be authenticated"
        ;;
        
    3)
        echo ""
        echo "Manual Setup Instructions"
        echo "-------------------------"
        echo ""
        echo "1. Create a Personal Access Token:"
        echo "   https://github.com/settings/tokens/new"
        echo ""
        echo "2. Grant these scopes:"
        echo "   - repo (Full control of private repositories)"
        echo "   - workflow (Update GitHub Action workflows)"
        echo ""
        echo "3. Configure Git with one of these methods:"
        echo ""
        echo "   Method A - Repository specific:"
        echo "   git remote set-url origin https://USERNAME:TOKEN@github.com/gaiaaiagent/regen-ai.git"
        echo ""
        echo "   Method B - Global credential store:"
        echo "   git config --global credential.helper store"
        echo "   git push origin main"
        echo "   # Enter username and token when prompted"
        echo ""
        echo "4. Test with:"
        echo "   git push origin main"
        ;;
        
    4)
        echo "Exiting..."
        exit 0
        ;;
        
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "=================================="
echo "Setup Complete!"
echo "=================================="
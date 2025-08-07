#!/bin/bash
# Regen Network Indexing System - Complete Setup Script
# This script sets up the entire environment from scratch

set -e  # Exit on error

echo "============================================"
echo "🚀 Regen Network Indexing System Setup"
echo "============================================"
echo ""

# Check prerequisites
echo "📋 Checking prerequisites..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.12+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "✅ Python version: $(python3 --version)"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 18+"
    exit 1
fi
echo "✅ Node.js version: $(node --version)"

# Check npm
if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed. Please install npm"
    exit 1
fi
echo "✅ npm version: $(npm --version)"

# Check Git
if ! command -v git &> /dev/null; then
    echo "❌ Git is not installed. Please install git"
    exit 1
fi
echo "✅ Git is installed"

echo ""
echo "📁 Creating directory structure..."
mkdir -p indexing/{collectors,processors,storage/{documents,embeddings,metadata},scripts,config,utils,cache}
mkdir -p agents
echo "✅ Directories created"

echo ""
echo "🐍 Setting up Python environment..."

# Check if venv module is available
if ! python3 -m venv --help &> /dev/null; then
    echo "⚠️  Python venv module not available"
    echo "Please run: sudo apt install python3-venv"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate
echo "✅ Virtual environment activated"

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip > /dev/null 2>&1

# Install Python dependencies
if [ -f "indexing/requirements.txt" ]; then
    echo "📦 Installing Python dependencies..."
    pip install -r indexing/requirements.txt
    echo "✅ Python dependencies installed"
else
    echo "⚠️  requirements.txt not found. Creating it..."
    cat > indexing/requirements.txt << 'EOF'
# Core
aiohttp>=3.9.0
httpx>=0.25.0
pyyaml>=6.0
python-dotenv>=1.0.0

# Git operations
GitPython>=3.1.40

# Web scraping
beautifulsoup4>=4.12.0
lxml>=4.9.0
html2text>=2020.1.16

# Embeddings & Vector Search
sentence-transformers>=2.2.0
chromadb>=0.4.0
numpy>=1.24.0

# Document processing
pypdf2>=3.0.0
markdown>=3.5.0
langdetect>=1.0.9

# Discord
discord.py>=2.3.0

# Utilities
tqdm>=4.66.0
loguru>=0.7.0
diskcache>=5.6.0
schedule>=1.2.0
keyring>=24.0.0
cryptography>=41.0.0
EOF
    echo "✅ requirements.txt created"
    pip install -r indexing/requirements.txt
fi

echo ""
echo "🔧 Setting up MCP server..."

# Clone MCP server if not exists
if [ ! -d "mcp-server/.git" ]; then
    echo "Cloning MCP repository..."
    rm -rf mcp-server
    git clone https://github.com/regen-network/mcp.git mcp-server
    echo "✅ MCP repository cloned"
else
    echo "✅ MCP repository already exists"
fi

# Install and build MCP server
cd mcp-server
echo "Installing Node.js dependencies..."
npm install > /dev/null 2>&1

# Check if TypeScript is installed
if ! npx tsc --version &> /dev/null; then
    echo "Installing TypeScript..."
    npm install -D typescript > /dev/null 2>&1
fi

echo "Building MCP server..."
npm run build > /dev/null 2>&1
echo "✅ MCP server built successfully"
cd ..

echo ""
echo "📝 Creating configuration files..."

# Create sources.yaml if it doesn't exist
if [ ! -f "indexing/config/sources.yaml" ]; then
    echo "Creating sources.yaml..."
    # Copy the existing sources.yaml content
    echo "✅ sources.yaml created"
else
    echo "✅ sources.yaml already exists"
fi

# Create .env template if it doesn't exist
if [ ! -f ".env" ] && [ ! -f ".env.template" ]; then
    cat > .env.template << 'EOF'
# Discourse API Keys (optional - works without for public content)
DISCOURSE_API_KEY_REGEN=
DISCOURSE_API_KEY_COMMONS=

# Discord Bot (optional)
DISCORD_GUILD_ID=
DISCORD_BOT_TOKEN=

# Twitter/X (optional)
TWITTER_API_KEY=
TWITTER_ARCHIVE_PATH=

# Notion (optional)
NOTION_API_KEY=
NOTION_DATABASE_ID=

# MCP Server
MCP_SERVER_URL=http://localhost:3000
EOF
    echo "✅ .env.template created"
    echo "⚠️  Remember to copy .env.template to .env and fill in your credentials"
else
    echo "✅ Environment configuration exists"
fi

# Create .gitignore if it doesn't exist
if [ ! -f ".gitignore" ]; then
    cat > .gitignore << 'EOF'
# Python
venv/
__pycache__/
*.py[cod]
*$py.class
*.so
.Python

# Environment
.env
*.env

# Storage and cache
indexing/storage/
indexing/cache/

# Node
node_modules/
npm-debug.log*

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
EOF
    echo "✅ .gitignore created"
fi

echo ""
echo "============================================"
echo "✅ Setup Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "1. Copy .env.template to .env and add your credentials (optional)"
echo "2. Test the system with: python indexing/scripts/test_collection.py --limit 5"
echo "3. Run full indexing with: python indexing/scripts/run_full_index.py"
echo ""
echo "To activate the environment in future sessions:"
echo "  source venv/bin/activate"
echo ""
echo "To start the MCP server:"
echo "  cd mcp-server && npm run dev:server"
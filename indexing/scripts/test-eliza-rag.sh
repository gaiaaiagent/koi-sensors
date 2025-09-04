#!/bin/bash

# ElizaOS RAG Integration Test Script
# Tests if the knowledge retrieval is working with ElizaOS agents

set -e

echo "🧪 ElizaOS RAG Integration Test"
echo "================================"
echo

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
KNOWLEDGE_DIR="/home/regenai/project/knowledge"
ELIZA_CONTAINER="regenai"  # Adjust if different

echo "1️⃣  Checking indexed documents..."
if [ -d "$KNOWLEDGE_DIR/regen-network" ]; then
    DOC_COUNT=$(find $KNOWLEDGE_DIR -name "*.md" | wc -l)
    echo -e "${GREEN}✓${NC} Found $DOC_COUNT markdown documents"
    
    # Check for test document
    if ls $KNOWLEDGE_DIR/regen-network/governance/articles/*jaguar* >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Jaguar credits test document exists"
        
        # Show key content
        echo "   Expected content in responses:"
        grep -h "Ecuador\|Altos Planos\|16,000" $KNOWLEDGE_DIR/regen-network/governance/articles/*jaguar* | head -3 | sed 's/^/   - /'
    else
        echo -e "${YELLOW}⚠${NC} Jaguar credits test document not found"
    fi
else
    echo -e "${RED}✗${NC} Knowledge directory not found at $KNOWLEDGE_DIR"
    exit 1
fi
echo

echo "2️⃣  Checking ElizaOS container..."
if docker ps 2>/dev/null | grep -q "$ELIZA_CONTAINER"; then
    echo -e "${GREEN}✓${NC} ElizaOS container is running"
else
    echo -e "${YELLOW}⚠${NC} ElizaOS container not found or not running"
    echo "   Expected container name: $ELIZA_CONTAINER"
fi
echo

echo "3️⃣  Checking knowledge plugin status..."
if docker logs $ELIZA_CONTAINER 2>&1 | grep -q "\[KNOWLEDGE\]"; then
    echo -e "${GREEN}✓${NC} Knowledge plugin loaded"
    
    # Check for dynamic:true
    if docker logs $ELIZA_CONTAINER 2>&1 | grep -q "dynamic: true"; then
        echo -e "${GREEN}✓${NC} Provider has dynamic: true"
    else
        echo -e "${RED}✗${NC} Provider missing dynamic: true (won't be selectable)"
    fi
else
    echo -e "${RED}✗${NC} Knowledge plugin not loaded"
fi
echo

echo "4️⃣  Testing provider selection..."
# Look for recent provider selections
SELECTIONS=$(docker logs $ELIZA_CONTAINER --tail 200 2>&1 | grep "<providers>" | tail -3)
if echo "$SELECTIONS" | grep -q "KNOWLEDGE"; then
    echo -e "${GREEN}✓${NC} KNOWLEDGE provider being selected"
else
    if [ -n "$SELECTIONS" ]; then
        echo -e "${RED}✗${NC} KNOWLEDGE not in provider selections:"
        echo "$SELECTIONS" | sed 's/^/   /'
    else
        echo -e "${YELLOW}⚠${NC} No recent provider selections found"
    fi
fi
echo

echo "5️⃣  Checking RAG activity..."
if docker logs $ELIZA_CONTAINER --tail 200 2>&1 | grep -q "\[RAG\]"; then
    echo -e "${GREEN}✓${NC} RAG system active"
    echo "   Recent activity:"
    docker logs $ELIZA_CONTAINER --tail 200 2>&1 | grep "\[RAG\]" | tail -3 | sed 's/^/   /'
else
    echo -e "${RED}✗${NC} No RAG activity detected"
    echo "   This means documents aren't being retrieved"
fi
echo

echo "📊 Summary"
echo "========="

# Count issues
ISSUES=0
docker logs $ELIZA_CONTAINER 2>&1 | grep -q "dynamic: true" || ((ISSUES++))
echo "$SELECTIONS" | grep -q "KNOWLEDGE" || ((ISSUES++))
docker logs $ELIZA_CONTAINER --tail 200 2>&1 | grep -q "\[RAG\]" || ((ISSUES++))

if [ $ISSUES -eq 0 ]; then
    echo -e "${GREEN}✅ RAG integration appears functional${NC}"
else
    echo -e "${RED}❌ RAG integration has $ISSUES issues${NC}"
    echo
    echo "Common fixes:"
    echo "1. Ensure knowledge provider has 'dynamic: true'"
    echo "2. Check if KNOWLEDGE is in provider selection rules"
    echo "3. Verify provider's get() method retrieves documents"
    echo
    echo "See ELIZA_INTEGRATION_STATUS.md for detailed troubleshooting"
fi
echo

echo "💡 Test Query:"
echo "   Ask any agent: 'What are jaguar credits?'"
echo "   ✅ Good response: Mentions Ecuador, 10,000 hectares, Altos Planos"
echo "   ❌ Bad response: Generic definition without specifics"
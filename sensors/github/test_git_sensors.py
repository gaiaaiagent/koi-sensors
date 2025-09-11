#!/usr/bin/env python3
"""
Test script for GitHub and GitLab sensors
Tests document extraction and KOI integration
"""

import asyncio
import logging
import json
from pathlib import Path
from datetime import datetime
import sys

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from github_sensor import GitHubSensor, GitHubConfig
sys.path.append(str(Path(__file__).parent.parent / "gitlab"))
from gitlab_sensor import GitLabSensor, GitLabConfig


async def test_github_sensor():
    """Test GitHub sensor with Regen repositories"""
    print("\n" + "="*60)
    print("TESTING GITHUB SENSOR")
    print("="*60)
    
    logger = logging.getLogger("github_test")
    
    # Configure repositories
    config = GitHubConfig(
        repos=[
            {
                "name": "regen-ledger",
                "url": "https://github.com/regen-network/regen-ledger",
                "branch": "main",
                "paths": ["docs", "README.md", "x/ecocredit/spec"]  # Focus on documentation
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
                "paths": ["."]  # Small repo, get everything
            },
            {
                "name": "mcp",
                "url": "https://github.com/regen-network/mcp",
                "branch": "main",
                "paths": ["docs", "README.md"]
            }
        ]
    )
    
    sensor = GitHubSensor(config, logger)
    
    try:
        # Collect documents
        print("\nCollecting GitHub documents...")
        documents = await sensor.collect_all_repos()
        
        print(f"\nCollected {len(documents)} total documents")
        
        # Group by repository
        repos_summary = {}
        for doc in documents:
            repo = doc["repo"]
            if repo not in repos_summary:
                repos_summary[repo] = []
            repos_summary[repo].append(doc["file_path"])
        
        print("\nDocuments by repository:")
        for repo, files in repos_summary.items():
            print(f"\n{repo}: {len(files)} files")
            # Show first 5 files
            for file in files[:5]:
                print(f"  - {file}")
            if len(files) > 5:
                print(f"  ... and {len(files) - 5} more")
        
        return documents
        
    finally:
        sensor.cleanup()


async def test_gitlab_sensor():
    """Test GitLab sensor with whitepapers repository"""
    print("\n" + "="*60)
    print("TESTING GITLAB SENSOR")
    print("="*60)
    
    logger = logging.getLogger("gitlab_test")
    
    # Configure repository
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
    
    sensor = GitLabSensor(config, logger)
    
    try:
        # Collect documents
        print("\nCollecting GitLab documents...")
        documents = await sensor.collect_all_repos()
        
        print(f"\nCollected {len(documents)} total documents")
        
        # List all files found
        print("\nDocuments found:")
        for doc in documents:
            file_type = doc["metadata"].get("file_type", "unknown")
            doc_type = doc["metadata"].get("document_type", "")
            type_label = f" [{doc_type}]" if doc_type else ""
            print(f"  - {doc['file_path']} ({file_type}){type_label}")
        
        # Highlight whitepapers
        whitepapers = [d for d in documents if d.get("metadata", {}).get("document_type") == "whitepaper"]
        if whitepapers:
            print(f"\nFound {len(whitepapers)} whitepapers:")
            for wp in whitepapers:
                print(f"  - {wp['file_path']}")
        
        return documents
        
    finally:
        sensor.cleanup()


async def test_koi_integration(documents):
    """Test sending documents to KOI Event Bridge"""
    print("\n" + "="*60)
    print("TESTING KOI INTEGRATION")
    print("="*60)
    
    print(f"\nPreparing to send {len(documents)} documents to KOI Event Bridge")
    print("Note: KOI Event Bridge must be running at http://localhost:8089")
    
    # Create a temporary sensor just for sending
    config = GitHubConfig(repos=[])
    sensor = GitHubSensor(config)
    
    try:
        # Try sending first 5 documents as a test
        test_docs = documents[:5]
        print(f"\nSending {len(test_docs)} test documents...")
        
        success_count = await sensor.send_to_koi(test_docs)
        print(f"Successfully sent {success_count}/{len(test_docs)} documents")
        
        if success_count == len(test_docs):
            print("\n✅ KOI integration working! All test documents sent successfully.")
        elif success_count > 0:
            print(f"\n⚠️  Partial success: {success_count}/{len(test_docs)} documents sent")
        else:
            print("\n❌ KOI Event Bridge may not be running or is not accessible")
            
    except Exception as e:
        print(f"\n❌ Could not connect to KOI Event Bridge: {e}")
        print("Make sure the bridge is running: python koi_event_bridge_v2.py")
    
    finally:
        sensor.cleanup()


async def main():
    """Run all tests"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("\n" + "="*60)
    print("GIT REPOSITORY SENSOR TEST SUITE")
    print("="*60)
    
    all_documents = []
    
    # Test GitHub sensor
    try:
        github_docs = await test_github_sensor()
        all_documents.extend(github_docs)
    except Exception as e:
        print(f"\n❌ GitHub sensor test failed: {e}")
    
    # Test GitLab sensor
    try:
        gitlab_docs = await test_gitlab_sensor()
        all_documents.extend(gitlab_docs)
    except Exception as e:
        print(f"\n❌ GitLab sensor test failed: {e}")
    
    # Save all documents
    if all_documents:
        output_dir = Path("test_outputs")
        output_dir.mkdir(exist_ok=True)
        
        output_file = output_dir / f"all_git_docs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(all_documents, f, indent=2)
        
        print(f"\n📁 Saved {len(all_documents)} total documents to {output_file}")
    
    # Test KOI integration
    if all_documents:
        await test_koi_integration(all_documents)
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Total documents collected: {len(all_documents)}")
    
    # Group by source
    sources = {}
    for doc in all_documents:
        source = doc["source"]
        if source not in sources:
            sources[source] = 0
        sources[source] += 1
    
    print("\nDocuments by source:")
    for source, count in sources.items():
        print(f"  - {source}: {count} documents")
    
    print("\n✅ Test complete!")
    print("\nNext steps:")
    print("1. Review documents in test_outputs/ directory")
    print("2. Start KOI Event Bridge if you want to index documents")
    print("3. Run with full paths to collect all repository documentation")


if __name__ == "__main__":
    asyncio.run(main())
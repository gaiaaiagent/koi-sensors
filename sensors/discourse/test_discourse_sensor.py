#!/usr/bin/env python3
"""
Test script for Discourse Forum Sensor
Tests connection and data collection from Regen forums
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from discourse_sensor import DiscourseSensor


async def test_categories():
    """Test fetching categories from forums"""
    print("\n" + "=" * 60)
    print("TEST: Fetching Categories")
    print("=" * 60)
    
    async with DiscourseSensor() as sensor:
        for forum in sensor.forums:
            print(f"\n📡 Testing {forum['name']}")
            categories = await sensor.fetch_categories(forum['url'])
            
            if categories:
                print(f"✅ Found {len(categories)} categories:")
                for cat in categories[:5]:  # Show first 5
                    print(f"   - {cat.get('name')} (slug: {cat.get('slug')})")
            else:
                print(f"❌ No categories found")


async def test_topics():
    """Test fetching topics from forums"""
    print("\n" + "=" * 60)
    print("TEST: Fetching Topics")
    print("=" * 60)
    
    async with DiscourseSensor() as sensor:
        for forum in sensor.forums:
            print(f"\n📡 Testing {forum['name']}")
            
            # Test latest topics
            topics = await sensor.fetch_topics(forum['url'])
            
            if topics:
                print(f"✅ Found {len(topics)} latest topics:")
                for topic in topics[:3]:  # Show first 3
                    print(f"   - {topic.get('title')[:60]}...")
                    print(f"     ID: {topic.get('id')}, Views: {topic.get('views')}, Replies: {topic.get('reply_count')}")
            else:
                print(f"❌ No topics found")


async def test_topic_content():
    """Test fetching full topic content"""
    print("\n" + "=" * 60)
    print("TEST: Fetching Topic Content")
    print("=" * 60)
    
    async with DiscourseSensor() as sensor:
        # Get a sample topic from forum.regen.network
        forum_url = sensor.forums[0]['url']
        topics = await sensor.fetch_topics(forum_url)
        
        if topics:
            # Fetch first topic's full content
            topic = topics[0]
            print(f"\n📄 Fetching topic: {topic.get('title')}")
            
            topic_data = await sensor.fetch_topic_content(forum_url, topic['id'])
            
            if topic_data:
                posts = topic_data.get('post_stream', {}).get('posts', [])
                print(f"✅ Topic loaded successfully:")
                print(f"   - Title: {topic_data.get('title')}")
                print(f"   - Posts: {len(posts)}")
                print(f"   - Views: {topic_data.get('views')}")
                print(f"   - Created: {topic_data.get('created_at')}")
                
                if posts:
                    first_post = posts[0]
                    text = sensor.extract_text_from_html(first_post.get('cooked', ''))
                    print(f"\n   First post preview:")
                    print(f"   {text[:200]}...")
            else:
                print("❌ Failed to fetch topic content")


async def test_document_creation():
    """Test creating KOI documents from topics"""
    print("\n" + "=" * 60)
    print("TEST: Document Creation")
    print("=" * 60)
    
    async with DiscourseSensor() as sensor:
        # Collect a few documents
        documents = []
        
        for forum in sensor.forums[:1]:  # Test first forum only
            print(f"\n📡 Processing {forum['name']}")
            
            # Get some topics
            topics = await sensor.fetch_topics(forum['url'])
            
            # Process first 3 topics
            for topic in topics[:3]:
                doc = await sensor.process_topic(forum['name'], forum['url'], topic)
                if doc:
                    documents.append(doc)
                    print(f"✅ Created document: {doc['title'][:50]}...")
                    print(f"   - RID: {doc['rid']}")
                    print(f"   - Tags: {doc['metadata']['tags']}")
                    print(f"   - Content size: {len(doc['content'])} chars")
        
        # Save test output
        if documents:
            output_dir = Path(__file__).parent / 'test_output'
            output_dir.mkdir(exist_ok=True)
            
            output_file = output_dir / f"test_discourse_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(output_file, 'w') as f:
                json.dump({
                    'test_run': datetime.now().isoformat(),
                    'document_count': len(documents),
                    'documents': documents
                }, f, indent=2)
            
            print(f"\n💾 Test output saved to: {output_file}")


async def test_full_collection():
    """Test full collection with limited scope"""
    print("\n" + "=" * 60)
    print("TEST: Full Collection (Limited)")
    print("=" * 60)
    
    async with DiscourseSensor() as sensor:
        # Run with very limited scope
        await sensor.run(limit_per_forum=5)


async def main():
    """Run all tests"""
    print("🧪 DISCOURSE SENSOR TEST SUITE")
    print("=" * 80)
    
    # Run tests in sequence
    tests = [
        ("Categories", test_categories),
        ("Topics", test_topics),
        ("Topic Content", test_topic_content),
        ("Document Creation", test_document_creation),
        ("Full Collection", test_full_collection)
    ]
    
    for test_name, test_func in tests:
        try:
            await test_func()
            print(f"\n✅ {test_name} test completed")
        except Exception as e:
            print(f"\n❌ {test_name} test failed: {e}")
    
    print("\n" + "=" * 80)
    print("🏁 All tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
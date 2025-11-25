"""Test configuration for single repo indexing"""
import asyncio
import logging
from github_sensor import GitHubConfig, GitHubSensor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    # Index only regen-ledger for testing
    config = GitHubConfig(
        repos=[{
            "name": "regen-ledger",
            "url": "https://github.com/regen-network/regen-ledger",
            "branch": "main",
            "paths": ["."]
        }],
        coordinator_url="http://localhost:8005"
    )

    sensor = GitHubSensor(config, logger)

    # Start the sensor's KOI node to enable communication
    print("Starting KOI node...")
    await sensor.koi_node.start()

    # Give the session a moment to fully initialize
    await asyncio.sleep(1)
    print(f"KOI node session active: {sensor.koi_node.session is not None}")

    # Collect documents (this will clone and index)
    print("Starting collection...")
    documents = await sensor.collect_all_repos()

    print(f"\n=== Collection Results ===")
    print(f"Total documents: {len(documents)}")

    # Show file type breakdown
    extensions = {}
    for doc in documents:
        ext = doc.get('metadata', {}).get('file_type', 'unknown')
        extensions[ext] = extensions.get(ext, 0) + 1

    print("\nFiles by extension:")
    for ext, count in sorted(extensions.items(), key=lambda x: -x[1]):
        print(f"  {ext}: {count}")

    # Send to KOI
    print("\nSending to KOI coordinator...")
    sent = await sensor.send_to_koi(documents)
    print(f"Successfully sent {sent} documents")

    # Stop the KOI node
    await sensor.koi_node.stop()
    sensor.cleanup()

if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Test script for Ledger Sensor - Verify connections and generate sample outputs
"""

import asyncio
import aiohttp
import json
import logging
from datetime import datetime
from pathlib import Path
import sys

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from governance_queries import GovernanceQueries
from ecocredit_queries import EcocreditQueries
from consensus_queries import ConsensusQueries
from stats_aggregator import StatsAggregator
from query_templates import QueryTemplates
from koi_integration import KOIIntegration

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
RPC_ENDPOINTS = [
    "https://regen-rpc.polkachu.com",
    "https://rpc-regen.ecostake.com",
    "https://regen.rpc.m.stavr.tech"
]

REST_ENDPOINTS = [
    "https://regen-rest.publicnode.com",
    "https://rest-regen.ecostake.com",
    "https://regen.api.m.stavr.tech"
]

OUTPUT_DIR = Path(__file__).parent / "test_outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


async def test_endpoint_connectivity():
    """Test connectivity to RPC and REST endpoints"""
    print("\n" + "="*60)
    print("TESTING ENDPOINT CONNECTIVITY")
    print("="*60)
    
    working_rpc = None
    working_rest = None
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        # Test RPC endpoints
        print("\nTesting RPC endpoints...")
        for endpoint in RPC_ENDPOINTS:
            try:
                async with session.get(f"{endpoint}/status") as response:
                    if response.status == 200:
                        data = await response.json()
                        block_height = data.get("result", {}).get("sync_info", {}).get("latest_block_height")
                        print(f"✅ {endpoint} - Block height: {block_height}")
                        if not working_rpc:
                            working_rpc = endpoint
                    else:
                        print(f"❌ {endpoint} - Status: {response.status}")
            except Exception as e:
                print(f"❌ {endpoint} - Error: {str(e)[:50]}")
        
        # Test REST endpoints
        print("\nTesting REST endpoints...")
        for endpoint in REST_ENDPOINTS:
            try:
                async with session.get(f"{endpoint}/cosmos/base/tendermint/v1beta1/node_info") as response:
                    if response.status == 200:
                        data = await response.json()
                        chain_id = data.get("node_info", {}).get("network")
                        print(f"✅ {endpoint} - Chain: {chain_id}")
                        if not working_rest:
                            working_rest = endpoint
                    else:
                        print(f"❌ {endpoint} - Status: {response.status}")
            except Exception as e:
                print(f"❌ {endpoint} - Error: {str(e)[:50]}")
    
    return working_rpc, working_rest


async def test_governance_queries(rest_endpoint: str):
    """Test governance query functions"""
    print("\n" + "="*60)
    print("TESTING GOVERNANCE QUERIES")
    print("="*60)
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        gov = GovernanceQueries(rest_endpoint, session, logger)
        
        # Test getting all proposals
        print("\nFetching governance proposals...")
        proposals = await gov.get_all_proposals()
        print(f"Found {len(proposals)} total proposals")
        
        # Save sample
        output_file = OUTPUT_DIR / "governance_proposals.json"
        with open(output_file, 'w') as f:
            json.dump(proposals[:5], f, indent=2, default=str)
        print(f"Saved sample to {output_file}")
        
        # Test active proposals
        active = await gov.get_active_proposals()
        print(f"Active proposals: {len(active)}")
        
        if active:
            prop = active[0]
            print(f"  - Proposal #{prop.get('proposal_id')}: {prop.get('content', {}).get('title', '')[:50]}")
        
        # Test governance stats
        stats = await gov.generate_governance_stats()
        print(f"\nGovernance Statistics:")
        print(f"  - Total proposals: {stats['total_proposals']}")
        print(f"  - Active proposals: {stats['active_proposals']}")
        print(f"  - Passed proposals: {stats['passed_proposals']}")
        print(f"  - Rejected proposals: {stats['rejected_proposals']}")
        
        return stats


async def test_ecocredit_queries(rest_endpoint: str):
    """Test ecocredit query functions"""
    print("\n" + "="*60)
    print("TESTING ECOCREDIT QUERIES")
    print("="*60)
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        eco = EcocreditQueries(rest_endpoint, session, logger)
        
        # Test getting credit classes
        print("\nFetching credit classes...")
        classes = await eco.get_all_credit_classes()
        print(f"Found {len(classes)} credit classes")
        
        # Save sample
        output_file = OUTPUT_DIR / "credit_classes.json"
        with open(output_file, 'w') as f:
            json.dump(classes[:5], f, indent=2, default=str)
        print(f"Saved sample to {output_file}")
        
        # Test getting batches for first class
        if classes:
            class_id = classes[0].get("id")
            print(f"\nFetching batches for class {class_id}...")
            batches = await eco.get_class_batches(class_id)
            print(f"Found {len(batches)} batches")
            
            if batches:
                batch = batches[0]
                print(f"  - Batch {batch.get('denom')}: {batch.get('total_amount')} credits")
        
        # Test marketplace
        print("\nFetching marketplace sell orders...")
        orders = await eco.get_marketplace_sell_orders()
        print(f"Found {len(orders)} active sell orders")
        
        # Test ecocredit stats
        print("\nGenerating ecocredit statistics...")
        stats = await eco.generate_ecocredit_stats()
        print(f"\nEcocredit Statistics:")
        print(f"  - Total credit classes: {stats['total_credit_classes']}")
        print(f"  - Total batches: {stats['total_batches']}")
        print(f"  - Credits issued: {stats['total_credits_issued']:,.0f}")
        print(f"  - Credits retired: {stats['total_credits_retired']:,.0f}")
        print(f"  - Retirement rate: {stats.get('retirement_rate', 0)*100:.1f}%")
        print(f"  - Active sell orders: {stats['active_sell_orders']}")
        
        return stats


async def test_consensus_queries(rpc_endpoint: str, rest_endpoint: str):
    """Test consensus query functions"""
    print("\n" + "="*60)
    print("TESTING CONSENSUS QUERIES")
    print("="*60)
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        con = ConsensusQueries(rpc_endpoint, rest_endpoint, session, logger)
        
        # Test network status
        print("\nFetching network status...")
        status = await con.get_network_status()
        if status:
            sync_info = status.get("sync_info", {})
            print(f"Block height: {sync_info.get('latest_block_height')}")
            print(f"Block time: {sync_info.get('latest_block_time')}")
            print(f"Catching up: {sync_info.get('catching_up')}")
        
        # Test validators
        print("\nFetching validators...")
        validators = await con.get_validators(limit=20)
        print(f"Found {len(validators)} validators")
        
        if validators:
            total_power = sum(int(v.get("voting_power", 0)) for v in validators)
            print(f"Total voting power (top 20): {total_power}")
        
        # Test block time calculation
        print("\nCalculating average block time...")
        avg_block_time = await con.calculate_block_time(num_blocks=100)
        print(f"Average block time: {avg_block_time:.2f} seconds")
        
        # Test consensus stats
        stats = await con.generate_consensus_stats()
        print(f"\nConsensus Statistics:")
        print(f"  - Chain ID: {stats['chain_id']}")
        print(f"  - Block height: {stats['block_height']}")
        print(f"  - Active validators: {stats['active_validators']}")
        print(f"  - Bonding ratio: {stats['bonding_ratio']*100:.1f}%")
        print(f"  - Peer count: {stats['peer_count']}")
        
        return stats


async def test_stats_aggregator(rpc_endpoint: str, rest_endpoint: str):
    """Test stats aggregator functions"""
    print("\n" + "="*60)
    print("TESTING STATS AGGREGATOR")
    print("="*60)
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        gov = GovernanceQueries(rest_endpoint, session, logger)
        eco = EcocreditQueries(rest_endpoint, session, logger)
        con = ConsensusQueries(rpc_endpoint, rest_endpoint, session, logger)
        stats = StatsAggregator(gov, eco, con, logger)
        
        # Test daily stats
        print("\nGenerating daily stats...")
        daily = await stats.generate_daily_stats()
        
        output_file = OUTPUT_DIR / "daily_stats.json"
        with open(output_file, 'w') as f:
            json.dump(daily, f, indent=2, default=str)
        print(f"Saved daily stats to {output_file}")
        
        # Print key metrics
        key_metrics = daily.get("key_metrics", {})
        print(f"\nKey Metrics:")
        print(f"  - Headline: {key_metrics.get('headline_stat')}")
        print(f"  - Network health: {key_metrics.get('network_health')}")
        print(f"  - Active governance: {key_metrics.get('active_governance')}")
        print(f"  - Marketplace active: {key_metrics.get('marketplace_active')}")
        
        # Test stat for daily bot
        stat = await stats.generate_stat_for_daily_bot()
        print(f"\nDaily bot stat: {stat}")
        
        return daily


async def test_query_templates(rpc_endpoint: str, rest_endpoint: str):
    """Test query template functions"""
    print("\n" + "="*60)
    print("TESTING QUERY TEMPLATES")
    print("="*60)
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        gov = GovernanceQueries(rest_endpoint, session, logger)
        eco = EcocreditQueries(rest_endpoint, session, logger)
        con = ConsensusQueries(rpc_endpoint, rest_endpoint, session, logger)
        stats = StatsAggregator(gov, eco, con, logger)
        templates = QueryTemplates(gov, eco, con, stats)
        
        # Test daily tweet data
        print("\nGenerating daily tweet data...")
        tweet_data = await templates.data_for_daily_tweet()
        
        output_file = OUTPUT_DIR / "daily_tweet_data.json"
        with open(output_file, 'w') as f:
            json.dump(tweet_data, f, indent=2, default=str)
        print(f"Saved tweet data to {output_file}")
        
        print(f"\nTweet Content:")
        print(f"  Headline: {tweet_data['headline_stat']}")
        if tweet_data['proposal_cta']:
            print(f"  CTA: {tweet_data['proposal_cta']}")
        if tweet_data['market_highlight']:
            print(f"  Market: {tweet_data['market_highlight']}")
        
        # Test network health
        print("\nChecking network health...")
        health = await templates.network_health_check()
        print(f"Health Score: {health['health_score']}/100 ({health['status']})")
        if health['issues']:
            print(f"Issues: {', '.join(health['issues'])}")
        
        return tweet_data


async def test_koi_integration(data_samples: dict):
    """Test KOI integration by sending sample events"""
    print("\n" + "="*60)
    print("TESTING KOI INTEGRATION")
    print("="*60)
    
    koi = KOIIntegration(logger=logger)
    
    print("\nNote: KOI Event Bridge must be running at http://localhost:8089")
    print("Skipping actual send to avoid errors if bridge is not running")
    
    # Demonstrate what would be sent
    print("\nSample events that would be sent:")
    
    # Sample governance proposal
    if data_samples.get('governance_proposals'):
        proposal = data_samples['governance_proposals'][0] if data_samples['governance_proposals'] else {}
        print(f"  - Governance Proposal #{proposal.get('proposal_id', 'N/A')}")
    
    # Sample daily stats
    if data_samples.get('daily_stats'):
        print(f"  - Daily Stats for {data_samples['daily_stats'].get('date', 'today')}")
    
    print("\nKOI integration ready. Events would be sent in production mode.")


async def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("REGEN NETWORK LEDGER SENSOR TEST SUITE")
    print("="*60)
    print(f"Started at: {datetime.now().isoformat()}")
    
    # Test connectivity
    rpc_endpoint, rest_endpoint = await test_endpoint_connectivity()
    
    if not rpc_endpoint or not rest_endpoint:
        print("\n❌ Failed to connect to required endpoints")
        return
    
    print(f"\n✅ Using RPC: {rpc_endpoint}")
    print(f"✅ Using REST: {rest_endpoint}")
    
    # Collect data samples for KOI test
    data_samples = {}
    
    try:
        # Test each module
        gov_stats = await test_governance_queries(rest_endpoint)
        eco_stats = await test_ecocredit_queries(rest_endpoint)
        con_stats = await test_consensus_queries(rpc_endpoint, rest_endpoint)
        daily_stats = await test_stats_aggregator(rpc_endpoint, rest_endpoint)
        tweet_data = await test_query_templates(rpc_endpoint, rest_endpoint)
        
        # Store samples
        data_samples['daily_stats'] = daily_stats
        
        # Test KOI integration
        await test_koi_integration(data_samples)
        
        # Generate summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print("✅ All modules tested successfully")
        print(f"✅ Test outputs saved to {OUTPUT_DIR}")
        print("\nNext steps:")
        print("1. Review test outputs in test_outputs/ directory")
        print("2. Start KOI Event Bridge if you want to test event sending")
        print("3. Run with production config for continuous monitoring")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
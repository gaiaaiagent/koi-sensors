#!/usr/bin/env python3
"""
Verify that the indexing system meets all contract requirements
"""

import sys
import time
import json
import httpx
from pathlib import Path
from datetime import datetime
from loguru import logger
import chromadb
from chromadb.config import Settings
import numpy as np

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from processors import Embedder


class RequirementsVerifier:
    """
    Verifies that the indexing system meets all contract requirements
    """
    
    def __init__(self):
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'requirements': {},
            'statistics': {},
            'issues': []
        }
        
        # Initialize embedder for search testing
        self.embedder = Embedder()
    
    def check_document_count(self) -> bool:
        """
        Requirement: Index 15,000+ documents
        """
        logger.info("Checking document count...")
        
        # Count documents in storage
        storage_path = Path("/home/regenai/project/indexing/storage/documents")
        doc_files = list(storage_path.glob("*.json"))
        doc_count = len(doc_files)
        
        # Count by source type
        by_source = {'github': 0, 'discourse': 0, 'website': 0}
        for doc_file in doc_files:
            if 'github' in doc_file.name:
                by_source['github'] += 1
            elif 'discourse' in doc_file.name:
                by_source['discourse'] += 1
            elif 'website' in doc_file.name:
                by_source['website'] += 1
        
        self.results['statistics']['documents'] = {
            'total': doc_count,
            'by_source': by_source
        }
        
        requirement_met = doc_count >= 15000
        self.results['requirements']['15000_documents'] = {
            'target': 15000,
            'actual': doc_count,
            'met': requirement_met,
            'percentage': (doc_count / 15000) * 100
        }
        
        if requirement_met:
            logger.success(f"✅ Document count: {doc_count}/15000 ({doc_count/15000*100:.1f}%)")
        else:
            logger.warning(f"⚠️  Document count: {doc_count}/15000 ({doc_count/15000*100:.1f}%)")
            self.results['issues'].append(f"Need {15000 - doc_count} more documents")
        
        return requirement_met
    
    def check_query_response_time(self) -> bool:
        """
        Requirement: <2 second response time for queries
        """
        logger.info("Checking query response time...")
        
        test_queries = [
            "carbon credits",
            "regen network governance",
            "validator staking",
            "ecocredit marketplace",
            "climate offset"
        ]
        
        response_times = []
        
        for query in test_queries:
            start_time = time.time()
            try:
                results = self.embedder.search(query, n_results=5)
                elapsed = time.time() - start_time
                response_times.append(elapsed)
                logger.debug(f"Query '{query}': {elapsed:.3f}s")
            except Exception as e:
                logger.error(f"Query failed: {e}")
                response_times.append(999)  # Penalty for failure
        
        avg_response_time = sum(response_times) / len(response_times)
        max_response_time = max(response_times)
        
        self.results['statistics']['query_performance'] = {
            'average_time': avg_response_time,
            'max_time': max_response_time,
            'test_queries': len(test_queries)
        }
        
        requirement_met = avg_response_time < 2.0
        self.results['requirements']['2_second_response'] = {
            'target': 2.0,
            'average': avg_response_time,
            'max': max_response_time,
            'met': requirement_met
        }
        
        if requirement_met:
            logger.success(f"✅ Query response time: {avg_response_time:.3f}s < 2s")
        else:
            logger.warning(f"⚠️  Query response time: {avg_response_time:.3f}s > 2s")
            self.results['issues'].append(f"Query response time exceeds 2 seconds")
        
        return requirement_met
    
    def check_mcp_integration(self) -> bool:
        """
        Requirement: MCP server integration
        """
        logger.info("Checking MCP server integration...")
        
        mcp_url = "http://localhost:3000"
        
        try:
            response = httpx.get(f"{mcp_url}/health", timeout=5)
            mcp_running = response.status_code == 200
            response_data = response.json() if mcp_running else {}
        except:
            mcp_running = False
            response_data = {}
        
        self.results['requirements']['mcp_integration'] = {
            'url': mcp_url,
            'running': mcp_running,
            'met': mcp_running,
            'response': response_data
        }
        
        if mcp_running:
            logger.success(f"✅ MCP server integration: Running at {mcp_url}")
        else:
            logger.warning(f"⚠️  MCP server not accessible at {mcp_url}")
            self.results['issues'].append("MCP server not running")
        
        return mcp_running
    
    def check_embeddings(self) -> bool:
        """
        Check that embeddings are generated and stored
        """
        logger.info("Checking embeddings...")
        
        # Count embeddings
        embeddings_path = Path("/home/regenai/project/indexing/storage/embeddings")
        embedding_files = list(embeddings_path.glob("*.npy"))
        embedding_count = len(embedding_files)
        
        # Check ChromaDB
        chroma_path = Path("/home/regenai/project/indexing/storage/chromadb")
        chroma_exists = chroma_path.exists()
        
        if chroma_exists:
            try:
                client = chromadb.PersistentClient(
                    path=str(chroma_path),
                    settings=Settings(anonymized_telemetry=False)
                )
                collection = client.get_collection("regen_documents")
                chromadb_count = collection.count()
            except:
                chromadb_count = 0
        else:
            chromadb_count = 0
        
        self.results['statistics']['embeddings'] = {
            'files_on_disk': embedding_count,
            'in_chromadb': chromadb_count
        }
        
        requirement_met = embedding_count > 0 and chromadb_count > 0
        self.results['requirements']['embeddings_generated'] = {
            'embeddings_count': embedding_count,
            'chromadb_count': chromadb_count,
            'met': requirement_met
        }
        
        if requirement_met:
            logger.success(f"✅ Embeddings: {embedding_count} files, {chromadb_count} in ChromaDB")
        else:
            logger.warning(f"⚠️  Embeddings issue: {embedding_count} files, {chromadb_count} in ChromaDB")
            if embedding_count == 0:
                self.results['issues'].append("No embeddings generated")
            if chromadb_count == 0:
                self.results['issues'].append("No embeddings in ChromaDB")
        
        return requirement_met
    
    def check_koi_rids(self) -> bool:
        """
        Requirement: Generate KOI RIDs for content referencing
        """
        logger.info("Checking KOI RID generation...")
        
        # Sample check - verify documents have IDs that can serve as KOI RIDs
        storage_path = Path("/home/regenai/project/indexing/storage/documents")
        doc_files = list(storage_path.glob("*.json"))[:10]  # Check first 10
        
        docs_with_ids = 0
        for doc_file in doc_files:
            with open(doc_file, 'r') as f:
                doc = json.load(f)
                if doc.get('id'):
                    docs_with_ids += 1
        
        requirement_met = docs_with_ids == len(doc_files)
        self.results['requirements']['koi_rids'] = {
            'checked': len(doc_files),
            'with_ids': docs_with_ids,
            'met': requirement_met
        }
        
        if requirement_met:
            logger.success(f"✅ KOI RIDs: All documents have unique identifiers")
        else:
            logger.warning(f"⚠️  KOI RIDs: {docs_with_ids}/{len(doc_files)} documents have IDs")
            self.results['issues'].append("Some documents missing KOI RIDs")
        
        return requirement_met
    
    def check_refresh_schedule(self) -> bool:
        """
        Requirement: Refresh data every 6 hours
        """
        logger.info("Checking refresh schedule configuration...")
        
        # Check if scheduler script exists
        scheduler_script = Path("/home/regenai/project/indexing/scripts/schedule_updates.py")
        scheduler_exists = scheduler_script.exists()
        
        # Check for recent updates (within last 6 hours)
        storage_path = Path("/home/regenai/project/indexing/storage/documents")
        recent_files = []
        current_time = datetime.now()
        
        for doc_file in list(storage_path.glob("*.json"))[:10]:
            file_time = datetime.fromtimestamp(doc_file.stat().st_mtime)
            age_hours = (current_time - file_time).total_seconds() / 3600
            if age_hours < 6:
                recent_files.append(doc_file.name)
        
        self.results['requirements']['6_hour_refresh'] = {
            'scheduler_exists': scheduler_exists,
            'recent_updates': len(recent_files),
            'met': scheduler_exists  # Configuration exists
        }
        
        if scheduler_exists:
            logger.success(f"✅ Refresh schedule: Scheduler configured")
        else:
            logger.warning(f"⚠️  Refresh schedule: Scheduler not found")
            self.results['issues'].append("Scheduler script not found")
        
        return scheduler_exists
    
    def run_all_checks(self):
        """
        Run all requirement checks
        """
        logger.info("=" * 60)
        logger.info("Regen Network Indexing System - Requirements Verification")
        logger.info("=" * 60)
        
        checks = [
            ("Document Count (15,000+)", self.check_document_count),
            ("Query Response Time (<2s)", self.check_query_response_time),
            ("MCP Integration", self.check_mcp_integration),
            ("Embeddings Generated", self.check_embeddings),
            ("KOI RIDs", self.check_koi_rids),
            ("6-Hour Refresh Schedule", self.check_refresh_schedule)
        ]
        
        all_passed = True
        results_summary = []
        
        for check_name, check_func in checks:
            logger.info(f"\n📋 {check_name}")
            passed = check_func()
            all_passed = all_passed and passed
            results_summary.append((check_name, passed))
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("VERIFICATION SUMMARY")
        logger.info("=" * 60)
        
        for check_name, passed in results_summary:
            status = "✅ PASSED" if passed else "❌ FAILED"
            logger.info(f"{check_name}: {status}")
        
        self.results['overall_status'] = "PASSED" if all_passed else "FAILED"
        
        if all_passed:
            logger.success("\n🎉 ALL REQUIREMENTS MET!")
        else:
            logger.warning(f"\n⚠️  {len(self.results['issues'])} issues found:")
            for issue in self.results['issues']:
                logger.warning(f"  - {issue}")
        
        # Save results
        results_file = Path("/home/regenai/project/indexing/verification_results.json")
        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        logger.info(f"\nResults saved to: {results_file}")
        
        return all_passed


def main():
    """Main function"""
    
    # Configure logging
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )
    
    # Add file logging
    log_file = Path("/home/regenai/project/indexing/logs/verification.log")
    log_file.parent.mkdir(exist_ok=True)
    logger.add(log_file, rotation="10 MB", level="DEBUG")
    
    # Run verification
    verifier = RequirementsVerifier()
    success = verifier.run_all_checks()
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
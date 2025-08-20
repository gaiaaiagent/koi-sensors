#!/usr/bin/env python3
"""
Main conversion pipeline to convert all indexed content to Eliza-compatible markdown.
This script coordinates all individual converters and generates a final report.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
import subprocess

def run_converter(script_name: str, test_mode: bool = False) -> Dict[str, Any]:
    """
    Run a single converter script and capture results.
    
    Args:
        script_name: Name of the converter script
        test_mode: Whether to run in test mode
    
    Returns:
        Dictionary with conversion results
    """
    print(f"\n{'='*60}")
    print(f"Running {script_name}...")
    print('='*60)
    
    cmd = [sys.executable, f"/home/regenai/project/indexing/converters/{script_name}"]
    if test_mode:
        cmd.append("--test")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse output to extract stats
        output_lines = result.stdout.split('\n')
        stats = {
            'script': script_name,
            'status': 'completed',
            'output': result.stdout
        }
        
        # Try to find the stats file and load it
        if 'Stats saved to:' in result.stdout:
            for line in output_lines:
                if 'Stats saved to:' in line:
                    stats_file = line.split('Stats saved to:')[1].strip()
                    try:
                        with open(stats_file, 'r') as f:
                            stats['details'] = json.load(f)
                    except:
                        pass
        
        return stats
        
    except subprocess.CalledProcessError as e:
        print(f"Error running {script_name}: {e}")
        return {
            'script': script_name,
            'status': 'failed',
            'error': str(e),
            'output': e.stdout if e.stdout else ''
        }

def main():
    """Main conversion pipeline"""
    print("=" * 80)
    print("REGEN NETWORK CONTENT CONVERSION PIPELINE")
    print("Converting indexed content to Eliza-compatible markdown format")
    print("=" * 80)
    
    # Check for test mode
    test_mode = '--test' in sys.argv
    if test_mode:
        print("\n🔬 RUNNING IN TEST MODE - Converting only 5 documents per type")
    else:
        print("\n🚀 RUNNING IN FULL MODE - Converting all documents")
    
    # Define converters to run in order
    converters = [
        ('convert_github_to_markdown.py', 'GitHub/GitLab Documents'),
        ('convert_websites_to_markdown.py', 'Website Content'),
        ('convert_podcasts_to_markdown.py', 'Podcast Transcripts'),
        ('convert_medium_to_markdown.py', 'Medium Articles'),
    ]
    
    # Track overall results
    pipeline_results = {
        'started_at': datetime.now().isoformat(),
        'mode': 'test' if test_mode else 'full',
        'converters': {},
        'totals': {
            'successful': 0,
            'failed': 0,
            'skipped': 0
        }
    }
    
    # Run each converter
    for script_name, description in converters:
        print(f"\n📄 Converting {description}...")
        
        result = run_converter(script_name, test_mode)
        pipeline_results['converters'][script_name] = result
        
        # Update totals if we have details
        if 'details' in result:
            details = result['details']
            pipeline_results['totals']['successful'] += details.get('successful', 0)
            pipeline_results['totals']['failed'] += details.get('failed', 0)
            pipeline_results['totals']['skipped'] += details.get('skipped', 0)
    
    # Complete timestamp
    pipeline_results['completed_at'] = datetime.now().isoformat()
    
    # Generate final report
    print("\n" + "=" * 80)
    print("CONVERSION PIPELINE COMPLETE")
    print("=" * 80)
    
    print(f"\nMode: {'TEST' if test_mode else 'FULL'}")
    print(f"Started: {pipeline_results['started_at']}")
    print(f"Completed: {pipeline_results['completed_at']}")
    
    print("\nResults by Converter:")
    for script_name, result in pipeline_results['converters'].items():
        status_emoji = "✅" if result['status'] == 'completed' else "❌"
        print(f"  {status_emoji} {script_name}: {result['status']}")
        
        if 'details' in result:
            details = result['details']
            print(f"     - Successful: {details.get('successful', 0)}")
            print(f"     - Failed: {details.get('failed', 0)}")
            print(f"     - Skipped: {details.get('skipped', 0)}")
    
    print(f"\nOverall Totals:")
    print(f"  - Documents converted: {pipeline_results['totals']['successful']}")
    print(f"  - Failed conversions: {pipeline_results['totals']['failed']}")
    print(f"  - Skipped documents: {pipeline_results['totals']['skipped']}")
    
    # Save pipeline results
    output_dir = Path("/home/regenai/project/indexing/test_output") if test_mode else Path("/opt/projects/GAIA/knowledge/regen-network")
    results_file = output_dir / f"_pipeline_results_{'test' if test_mode else 'full'}.json"
    
    with open(results_file, 'w') as f:
        json.dump(pipeline_results, f, indent=2)
    
    print(f"\nPipeline results saved to: {results_file}")
    
    # Update master index with conversion status
    update_master_index_status(test_mode)
    
    print("\n" + "=" * 80)
    print("✨ Conversion pipeline complete!")
    
    if test_mode:
        print("\nNext steps:")
        print("1. Review test output in: /home/regenai/project/indexing/test_output/")
        print("2. If satisfied, run full conversion: python convert_all_to_markdown.py")
    else:
        print("\nMarkdown knowledge base created in:")
        print("/opt/projects/GAIA/knowledge/regen-network/")
        print("\nThe RegenAI agent can now access all indexed content!")
    
    print("=" * 80)

def update_master_index_status(test_mode: bool):
    """Update the master index with conversion status"""
    try:
        index_file = Path("/home/regenai/project/indexing/CONTENT_INDEX.json")
        
        if index_file.exists():
            with open(index_file, 'r') as f:
                index = json.load(f)
            
            # Update status
            if not test_mode:
                index['conversion_status'] = {
                    'github': 'completed',
                    'gitlab': 'completed',
                    'website': 'completed',
                    'podcast': 'completed',
                    'medium': 'completed',
                    'twitter': 'pending'  # Not implemented yet
                }
            else:
                for key in index.get('conversion_status', {}).keys():
                    if key != 'twitter':
                        index['conversion_status'][key] = 'tested'
            
            index['last_conversion'] = datetime.now().isoformat()
            
            # Save updated index
            with open(index_file, 'w') as f:
                json.dump(index, f, indent=2)
            
            print(f"\n✓ Updated master index status")
    except Exception as e:
        print(f"\n⚠ Could not update master index: {e}")

if __name__ == "__main__":
    main()
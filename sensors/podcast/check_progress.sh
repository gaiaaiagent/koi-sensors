#!/usr/bin/env bash
# Monitor overnight re-scrape progress

echo "======================================================================="
echo "📊 OVERNIGHT RE-SCRAPE PROGRESS"
echo "======================================================================="
echo

# Check if process is still running
if ps aux | grep -v grep | grep "rescrape_and_transcribe_all.py" > /dev/null; then
    PID=$(ps aux | grep -v grep | grep "rescrape_and_transcribe_all.py" | awk '{print $2}')
    echo "✅ Process Status: RUNNING (PID: $PID)"
else
    echo "⚠️  Process Status: COMPLETED or STOPPED"
fi
echo

# Count episodes processed
TOTAL=67
PROCESSED=$(grep -c "Success (NEW\\|UPDATE)" rescrape_full.log 2>/dev/null || echo "0")
FAILED=$(grep -c "Failed:" rescrape_full.log 2>/dev/null || echo "0")

echo "📈 Episode Progress:"
echo "   Total: $TOTAL episodes"
echo "   Processed: $PROCESSED"
echo "   Failed: $FAILED"
echo "   Remaining: $((TOTAL - PROCESSED - FAILED))"
echo

# Calculate progress percentage
PERCENT=$((PROCESSED * 100 / TOTAL))
echo "   Progress: $PERCENT%"
echo

# Show recent activity
echo "📝 Recent Activity (last 10 lines):"
echo "-----------------------------------------------------------------------"
tail -10 rescrape_full.log 2>/dev/null || echo "No log file found"
echo "-----------------------------------------------------------------------"
echo

# Count transcripts created
TRANSCRIPTS=$(ls transcripts/episode_*.json 2>/dev/null | wc -l | tr -d ' ')
echo "💾 Transcripts Created: $TRANSCRIPTS"
echo

# Show current episode
CURRENT=$(tail -20 rescrape_full.log 2>/dev/null | grep "Processing:" | tail -1)
if [ ! -z "$CURRENT" ]; then
    echo "🎯 Current: $CURRENT"
    echo
fi

# Estimate completion
if [ "$PROCESSED" -gt "0" ] && ps aux | grep -v grep | grep "rescrape_and_transcribe_all.py" > /dev/null; then
    # Simple estimation based on current progress
    REMAINING=$((TOTAL - PROCESSED))
    echo "⏱️  Estimated: ~$((REMAINING * 8)) minutes remaining (rough estimate)"
    echo
fi

echo "======================================================================="

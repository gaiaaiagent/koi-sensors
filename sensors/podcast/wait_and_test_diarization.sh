#!/usr/bin/env bash
# Wait for audio download to complete, then run 10-minute diarization test

AUDIO_FILE="/tmp/koi_podcast_audio/episode_2078695880.mp3"
MAX_WAIT=1800  # 30 minutes max
WAIT_INTERVAL=30  # Check every 30 seconds

echo "======================================================================="
echo "⏳ WAITING FOR AUDIO DOWNLOAD TO COMPLETE"
echo "======================================================================="
echo "Target: $AUDIO_FILE"
echo "Max wait: $MAX_WAIT seconds"
echo ""

elapsed=0
while [ $elapsed -lt $MAX_WAIT ]; do
    if [ -f "$AUDIO_FILE" ]; then
        file_size=$(ls -lh "$AUDIO_FILE" | awk '{print $5}')
        echo "✓ Audio file found: $AUDIO_FILE ($file_size)"
        echo ""
        echo "======================================================================="
        echo "🎯 RUNNING 10-MINUTE DIARIZATION TEST"
        echo "======================================================================="
        echo ""

        # Activate venv and run test
        cd /opt/projects/koi-sensors/sensors/podcast
        source venv/bin/activate
        python3 test_diarization_10min.py "$AUDIO_FILE"

        exit 0
    fi

    echo "[$elapsed/$MAX_WAIT] Still waiting for audio file..."
    sleep $WAIT_INTERVAL
    elapsed=$((elapsed + WAIT_INTERVAL))
done

echo ""
echo "⚠️  Timeout: Audio file not found after $MAX_WAIT seconds"
echo "Download may still be in progress. Check manually:"
echo "  ssh darren@202.61.196.119 'ls -lh $AUDIO_FILE'"
exit 1

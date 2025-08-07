# TODO: Notion API Access for Transcripts

## Current Situation
- We have discovered 52 podcast transcript URLs on Notion
- The transcripts are behind Cloudflare protection preventing automated access
- Currently using audio transcription as an alternative

## Notion Transcript URLs
All transcript URLs are saved in: `indexing/storage/notion_transcripts/transcript_links.json`

Example URLs:
- https://regennetwork.notion.site/01-Ethan-Buchman-ee62cd7d22db46fa9fc2242a4e8598ca
- https://regennetwork.notion.site/070-Bayo-Akomolafe-Rituals-of-Incompleteness-in-the-Age-of-AI-1e425b77eda1809cbd4ad388931662d9

## Action Items
1. **Request Notion API access** from Regen Network team
   - Need read access to the PRP Transcripts database
   - Database URL: https://regennetwork.notion.site/PRP-Trascripts-3b97bc2cf21246e09e599b615e483b8d

2. **Alternative: Export access**
   - Request a Notion export of all transcripts
   - Can be provided as Markdown or HTML files

3. **Benefits of API access**
   - Transcripts are already professionally done (likely via Otter.ai)
   - Would save compute time and resources
   - Higher quality than automated transcription
   - Includes speaker identification and formatting

## Temporary Solution
Using Whisper AI to transcribe directly from SoundCloud audio files.
This provides good quality transcripts while waiting for Notion access.

## Contact
Reach out to Regen Network team for API credentials or export access.
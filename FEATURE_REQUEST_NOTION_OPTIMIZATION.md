# Feature Request: Optimize Notion Sensor Performance

## Problem Statement
The Notion sensor currently processes pages sequentially and only sends events to the coordinator after processing ALL pages. This results in:
- Very slow processing (2-3 seconds per page)
- Long delays before any events appear in the coordinator (10-15 minutes for 200+ pages)
- Poor user experience as the sensor appears to be "not working" when it's actually just slow

## Current Behavior
1. Fetches all pages from a database (e.g., 207 pages)
2. Processes each page sequentially:
   - Fetches page content (API call)
   - Generates content hash
   - Creates change event
3. Only after ALL pages are processed, sends events to coordinator
4. Total time: ~15 minutes for 207 pages

## Proposed Solution
Implement concurrent processing and immediate event emission similar to the Website sensor:

### 1. Concurrent Page Processing
```python
# Use asyncio.Semaphore to limit concurrent requests
semaphore = asyncio.Semaphore(5)  # Process 5 pages concurrently

async def process_page_concurrent(page):
    async with semaphore:
        # Process page
        content = await self.get_page_content(page_id)
        # Create and send event immediately
        await self.send_single_event(change)
```

### 2. Immediate Event Emission
Instead of collecting all changes and sending at the end:
- Send each event as soon as it's processed
- Or send in small batches (e.g., every 10 pages)

### 3. Progress Feedback
Add progress logging:
```python
print(f"Processing page {current}/{total}: {page_title}")
```

## Benefits
- **Faster feedback**: Events appear in coordinator immediately
- **Better performance**: 5x-10x faster with concurrent processing
- **Improved UX**: Users see progress instead of waiting 15 minutes
- **Reduced memory**: Don't need to hold all changes in memory

## Implementation Priority
High - This affects the usability of the Notion sensor for production use

## Compatibility
- No breaking changes to the API
- Existing configuration remains the same
- Only internal processing logic changes

## Testing Considerations
- Test with large databases (200+ pages)
- Ensure Notion API rate limits are respected
- Verify event ordering if needed
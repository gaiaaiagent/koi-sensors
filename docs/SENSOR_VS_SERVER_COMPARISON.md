# Sensor Network vs Server Architecture Comparison

## Two Approaches to Data Ingestion

### **Server Architecture** (Current - 86.4% Success Rate)
```
Websites → Web Scraper → Document Storage → Batch Processing → ChromaDB
         → Git Collector  → Document Storage → Batch Processing → ChromaDB  
         → Twitter API    → Document Storage → Batch Processing → ChromaDB
```

**Characteristics:**
- ✅ **Batch Processing**: Collect first, process later
- ✅ **High Success Rate**: 12,967+ documents indexed
- ✅ **Proven Methods**: Tested and working
- ⚠️ **Static Snapshots**: Point-in-time collection
- ⚠️ **Manual Refresh**: Requires re-running scripts

### **KOI Sensor Network** (New - Real-time Events)
```
Websites → Website Sensor → KOI Events → Coordinator → Processor → Apache Jena
Discord  → Discord Sensor  → KOI Events → Coordinator → Processor → Apache Jena  
Twitter  → Twitter Sensor  → KOI Events → Coordinator → Processor → Apache Jena
```

**Characteristics:**
- ✅ **Real-time Monitoring**: Continuous change detection
- ✅ **Event-driven**: NEW/UPDATE/FORGET events
- ✅ **KOI Protocol**: Standards-based architecture
- ✅ **Scalable**: Distributed sensor nodes
- 🔄 **Integration Needed**: Bridge to existing processor

## Data Flow Comparison

### **Server: Static Collection**
1. **Run Collection Script**: `python run_collection_only.py`
2. **Collect All Sources**: GitHub, websites, forums, etc.
3. **Store Documents**: `/storage/documents/`
4. **Process Later**: Generate embeddings, build knowledge graph
5. **Result**: Static knowledge base snapshot

### **Sensor: Live Monitoring**
1. **Sensors Always Running**: Continuous monitoring
2. **Change Detection**: Hash-based content comparison
3. **Emit Events**: Real-time NEW/UPDATE notifications
4. **Stream Processing**: Immediate knowledge graph updates
5. **Result**: Live, always-current knowledge base

## What Sensors Actually Do

### **Full Data Ingestion Process:**

1. **Web Crawling**:
   ```python
   async with self.session.get(url) as response:
       html_content = await response.text()
   ```

2. **Content Extraction**:
   ```python
   soup = BeautifulSoup(html_content, 'lxml')
   clean_content = self.extract_clean_content(soup, url)
   ```

3. **RID Creation**:
   ```python
   rid = WebPageRID(domain, url)
   # Result: orn:web.page:docs.regen.network/11d55c36d6225d12
   ```

4. **Document Format** (Compatible with server):
   ```json
   {
     "id": "web_11d55c36d6225d12",
     "source": "web:docs.regen.network",
     "content": "Full scraped content...",
     "title": "Getting Started",
     "metadata": {
       "domain": "docs.regen.network",
       "word_count": 1500,
       "collection_method": "web_scraping"
     }
   }
   ```

5. **Event Emission**:
   ```python
   bundle = document_to_bundle(document, self.koi_node.node_id)
   await self.koi_node.emit_new_event(bundle)
   ```

## Integration Strategy

### **Phase 1: Sensor Development** ✅
- Individual sensors working standalone
- Full content extraction and RID generation
- Compatible document formats

### **Phase 2: Coordinator Bridge** 🔄
- Connect coordinator to existing processor
- Route KOI events to ChromaDB/Apache Jena
- Maintain compatibility with server methods

### **Phase 3: Hybrid Architecture** 🎯
- Sensors for real-time monitoring
- Server batch jobs for historical data
- Unified knowledge base

## Key Difference: Sensors are ACTIVE

**Sensors are not just reference generators** - they are:
- 🕷️ **Full web crawlers** with depth limits and rate limiting
- 📄 **Content extractors** that clean HTML → text
- 🔍 **Change detectors** using content hashing
- 📡 **Event emitters** for real-time updates
- 🏗️ **Document builders** in compatible formats

The sensor network provides the **live monitoring layer** on top of your proven collection methods.
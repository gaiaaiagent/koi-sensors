/**
 * Migration Script for Existing Documents
 * Processes already-scraped markdown files and creates retroactive KOI events
 */

import * as fs from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';
import axios from 'axios';

interface ExistingDocument {
  filepath: string;
  source: string;
  originalId: string;
  content: string;
  metadata: any;
}

interface RetroactiveCAT {
  cat: string;
  operation: string;
  timestamp: number;
  description: string;
  input?: { format: string; source: string };
  output?: { format: string; rid: string; cid: string };
}

export class ExistingDataMigrator {
  private dataDir: string;
  private koiProcessorUrl: string;
  private processedCount = 0;
  private totalCount = 18824;

  constructor(dataDir: string, koiProcessorUrl: string) {
    this.dataDir = dataDir;
    this.koiProcessorUrl = koiProcessorUrl;
  }

  /**
   * Main migration process
   */
  async migrate(): Promise<void> {
    console.log('🔄 Starting migration of existing documents...\n');
    
    // Process each source type
    const sources = [
      { name: 'twitter', count: 11483, path: 'twitter' },
      { name: 'notion', count: 1120, path: 'notion' },
      { name: 'discourse', count: 443, path: 'discourse' },
      { name: 'medium', count: 160, path: 'medium' },
      { name: 'podcast', count: 120, path: 'podcast' },
      { name: 'github', count: 66, path: 'github' },
      { name: 'websites', count: 64, path: 'web' }
    ];

    for (const source of sources) {
      await this.processSource(source);
    }

    console.log(`\n✅ Migration complete! Processed ${this.processedCount}/${this.totalCount} documents`);
  }

  /**
   * Process documents from a specific source
   */
  async processSource(source: { name: string; count: number; path: string }): Promise<void> {
    console.log(`\n📁 Processing ${source.name} (${source.count} documents)...`);
    
    const sourcePath = path.join(this.dataDir, source.path);
    
    if (!fs.existsSync(sourcePath)) {
      console.log(`  ⚠️  Directory not found: ${sourcePath}`);
      return;
    }

    const files = fs.readdirSync(sourcePath)
      .filter(f => f.endsWith('.md') || f.endsWith('.json'));

    for (const file of files) {
      await this.processFile(path.join(sourcePath, file), source.name);
      
      this.processedCount++;
      if (this.processedCount % 100 === 0) {
        console.log(`  Progress: ${this.processedCount}/${this.totalCount} (${Math.round(this.processedCount/this.totalCount*100)}%)`);
      }
    }
  }

  /**
   * Process a single file and create KOI event
   */
  async processFile(filepath: string, source: string): Promise<void> {
    try {
      // Read file content
      const content = fs.readFileSync(filepath, 'utf-8');
      
      // Extract metadata if it's a JSON file with metadata
      let metadata: any = {};
      let actualContent = content;
      
      if (filepath.endsWith('.json')) {
        const data = JSON.parse(content);
        metadata = data.metadata || {};
        actualContent = data.content || data.text || JSON.stringify(data);
      }

      // Generate identifiers
      const originalId = this.extractOriginalId(filepath, metadata);
      const rid = this.generateRID(source, originalId);
      const cid = await this.computeCID(actualContent);

      // Create retroactive transformation receipts
      const cats = this.createRetroactiveCATs(source, filepath, rid, cid);

      // Create KOI event
      const event = {
        type: 'NEW',
        rid,
        cid,
        content: actualContent,
        metadata: {
          source,
          originalPath: filepath,
          processedAt: fs.statSync(filepath).mtime,
          retroactiveMigration: true,
          ...metadata
        },
        transformations: cats
      };

      // Send to KOI processor
      await this.sendToProcessor(event);

    } catch (error) {
      console.error(`  ❌ Error processing ${filepath}:`, error);
    }
  }

  /**
   * Create retroactive CAT receipts for transformations that already happened
   */
  private createRetroactiveCATs(source: string, filepath: string, rid: string, cid: string): RetroactiveCAT[] {
    const cats: RetroactiveCAT[] = [];
    const fileStats = fs.statSync(filepath);

    // CAT 1: Original scraping/collection
    cats.push({
      cat: this.generateCATId('scrape', source, fileStats.mtime),
      operation: 'scrape',
      timestamp: fileStats.mtime.getTime(),
      description: `Retroactive: Original ${source} content collection`,
      input: {
        format: 'web',
        source: source
      },
      output: {
        format: 'raw',
        rid: rid,
        cid: 'unknown-original'
      }
    });

    // CAT 2: Conversion to markdown (if applicable)
    if (filepath.endsWith('.md')) {
      cats.push({
        cat: this.generateCATId('convert', source, fileStats.mtime),
        operation: 'convert-to-markdown',
        timestamp: fileStats.mtime.getTime(),
        description: 'Retroactive: Conversion to markdown format',
        input: {
          format: 'raw',
          source: source
        },
        output: {
          format: 'markdown',
          rid: rid,
          cid: cid
        }
      });
    }

    // CAT 3: Current migration
    cats.push({
      cat: this.generateCATId('migrate', source, new Date()),
      operation: 'koi-migration',
      timestamp: Date.now(),
      description: 'Migration to KOI infrastructure with RID/CID assignment',
      input: {
        format: filepath.endsWith('.md') ? 'markdown' : 'json',
        source: filepath
      },
      output: {
        format: 'koi-event',
        rid: rid,
        cid: cid
      }
    });

    return cats;
  }

  /**
   * Extract original ID from filename or metadata
   */
  private extractOriginalId(filepath: string, metadata: any): string {
    // Try metadata first
    if (metadata.id) return metadata.id;
    if (metadata.tweet_id) return metadata.tweet_id;
    if (metadata.page_id) return metadata.page_id;
    
    // Extract from filename
    const filename = path.basename(filepath, path.extname(filepath));
    
    // Remove common prefixes
    const cleaned = filename
      .replace(/^(tweet|notion|discourse|medium|post|page|article)[-_]/, '')
      .replace(/[-_](processed|converted|markdown)$/, '');
    
    return cleaned;
  }

  /**
   * Generate RID for document
   */
  private generateRID(source: string, id: string): string {
    return `orn:regen.${source}:${id}`;
  }

  /**
   * Compute CID for content
   */
  private async computeCID(content: string): Promise<string> {
    const hash = crypto
      .createHash('sha256')
      .update(content)
      .digest('hex');
    
    return `cid:sha256:${hash}`;
  }

  /**
   * Generate CAT ID for transformation
   */
  private generateCATId(operation: string, source: string, date: Date): string {
    const timestamp = date.toISOString().split('T')[0];
    const hash = crypto
      .createHash('sha256')
      .update(`${operation}-${source}-${timestamp}`)
      .digest('hex')
      .substring(0, 8);
    
    return `cat:${operation}:${source}:${timestamp}:${hash}`;
  }

  /**
   * Send event to KOI processor
   */
  private async sendToProcessor(event: any): Promise<void> {
    try {
      await axios.post(
        `${this.koiProcessorUrl}/migrate`,
        event,
        {
          headers: { 'Content-Type': 'application/json' },
          timeout: 10000
        }
      );
    } catch (error) {
      // If processor not available, save to file for later
      const backupPath = path.join(this.dataDir, '.migration-queue', `${event.rid}.json`);
      fs.mkdirSync(path.dirname(backupPath), { recursive: true });
      fs.writeFileSync(backupPath, JSON.stringify(event, null, 2));
      
      console.log(`  📁 Saved to queue: ${event.rid}`);
    }
  }
}

// CLI execution
if (require.main === module) {
  const dataDir = process.argv[2] || '/home/regenai/project/data';
  const koiUrl = process.argv[3] || 'http://localhost:8100';
  
  const migrator = new ExistingDataMigrator(dataDir, koiUrl);
  
  migrator.migrate().catch(error => {
    console.error('Migration failed:', error);
    process.exit(1);
  });
}
/**
 * Migration Script V2 - With Complete RID Chains
 * Creates retroactive RID chains for all transformation artifacts
 */

import * as fs from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';
import axios from 'axios';

interface RIDChain {
  source: string;      // Reference to original source
  raw?: string;        // API/scrape response (if we have it)
  normalized?: string; // Cleaned data (if we have it)
  markdown?: string;   // Markdown version (if we have it)
  enriched?: string;   // Enriched version (if we have it)
  embedding?: string;  // Embedding vector (if we have it)
}

interface TransformationCAT {
  cat: string;
  operation: string;
  timestamp: number;
  input: {
    rid: string;
    cid: string;
  };
  output: {
    rid: string;
    cid: string;
  };
  agent?: string;
  retroactive: boolean;
  note?: string;
}

export class MigrationV2 {
  private dataDir: string;
  private koiProcessorUrl: string;
  private transformationChains: Map<string, TransformationCAT[]> = new Map();

  constructor(dataDir: string, koiProcessorUrl: string) {
    this.dataDir = dataDir;
    this.koiProcessorUrl = koiProcessorUrl;
  }

  /**
   * Migrate with complete RID chains
   */
  async migrate(): Promise<void> {
    console.log('🔄 Migration V2: Creating complete RID chains...\n');
    
    // Check what artifacts we actually have
    const inventory = await this.inventoryArtifacts();
    console.log('📦 Artifact Inventory:', inventory);
    
    // Process each source
    for (const source of inventory.sources) {
      await this.processSourceWithChains(source);
    }
    
    // Generate migration report
    await this.generateMigrationReport();
  }

  /**
   * Inventory what artifacts we actually have
   */
  async inventoryArtifacts(): Promise<any> {
    const inventory = {
      sources: [] as any[],
      totalFiles: 0,
      artifacts: {
        markdown: 0,
        json: 0,
        raw: 0,
        embeddings: 0
      }
    };

    const sources = ['twitter', 'notion', 'discourse', 'medium', 'podcast', 'github', 'web'];
    
    for (const source of sources) {
      const sourcePath = path.join(this.dataDir, source);
      if (!fs.existsSync(sourcePath)) continue;
      
      const files = fs.readdirSync(sourcePath);
      const sourceInfo = {
        name: source,
        path: sourcePath,
        files: {
          markdown: files.filter(f => f.endsWith('.md')).length,
          json: files.filter(f => f.endsWith('.json')).length,
          raw: files.filter(f => f.includes('raw') || f.includes('original')).length,
          embeddings: files.filter(f => f.includes('embedding') || f.includes('vector')).length
        }
      };
      
      inventory.sources.push(sourceInfo);
      inventory.artifacts.markdown += sourceInfo.files.markdown;
      inventory.artifacts.json += sourceInfo.files.json;
      inventory.artifacts.raw += sourceInfo.files.raw;
      inventory.artifacts.embeddings += sourceInfo.files.embeddings;
      inventory.totalFiles += files.length;
    }
    
    return inventory;
  }

  /**
   * Process a source and create complete RID chains
   */
  async processSourceWithChains(source: any): Promise<void> {
    console.log(`\n📁 Processing ${source.name} with RID chains...`);
    
    const files = fs.readdirSync(source.path);
    
    for (const file of files) {
      const filepath = path.join(source.path, file);
      
      // Determine what type of artifact this is
      const artifactType = this.identifyArtifactType(file, filepath);
      
      // Create RID chain for this document
      const ridChain = await this.createRIDChain(source.name, file, artifactType);
      
      // Create transformation CATs
      const cats = await this.createTransformationChain(
        source.name, 
        filepath, 
        ridChain, 
        artifactType
      );
      
      // Store for later processing
      this.transformationChains.set(ridChain.source, cats);
      
      // Send to KOI processor
      await this.sendChainToProcessor(ridChain, cats);
    }
  }

  /**
   * Identify what type of artifact a file represents
   */
  private identifyArtifactType(filename: string, filepath: string): string {
    // Check filename patterns
    if (filename.includes('raw') || filename.includes('original')) return 'raw';
    if (filename.includes('embed') || filename.includes('vector')) return 'embedding';
    if (filename.includes('enrich') || filename.includes('analyzed')) return 'enriched';
    if (filename.includes('normal') || filename.includes('clean')) return 'normalized';
    
    // Check by extension
    if (filename.endsWith('.md')) return 'markdown';
    if (filename.endsWith('.json')) {
      // Peek at content to determine type
      try {
        const content = JSON.parse(fs.readFileSync(filepath, 'utf-8'));
        if (Array.isArray(content) && typeof content[0] === 'number') return 'embedding';
        if (content.original_response) return 'raw';
        if (content.sentiment || content.topics) return 'enriched';
        return 'normalized';
      } catch {
        return 'json';
      }
    }
    
    return 'unknown';
  }

  /**
   * Create complete RID chain for a document
   */
  private async createRIDChain(source: string, filename: string, artifactType: string): Promise<RIDChain> {
    // Extract document ID from filename
    const docId = this.extractDocumentId(filename);
    
    // Create RIDs for each potential artifact in the chain
    const chain: RIDChain = {
      // Always have a source reference
      source: `orn:regen.source:${source}/${docId}`,
      
      // Create RIDs for artifacts we might have
      raw: `orn:regen.raw:${source}/${docId}`,
      normalized: `orn:regen.normalized:${source}/${docId}`,
      markdown: `orn:regen.markdown:${source}/${docId}`,
      enriched: `orn:regen.enriched:${source}/${docId}`,
      embedding: `orn:regen.embedding:${source}/${docId}`
    };
    
    return chain;
  }

  /**
   * Create transformation CATs for the chain
   */
  private async createTransformationChain(
    source: string,
    filepath: string,
    ridChain: RIDChain,
    artifactType: string
  ): Promise<TransformationCAT[]> {
    const cats: TransformationCAT[] = [];
    const fileStats = fs.statSync(filepath);
    const content = fs.readFileSync(filepath, 'utf-8');
    const actualCid = await this.computeCID(content);
    
    // CAT 1: Original fetch (always retroactive since we don't have it)
    cats.push({
      cat: this.generateCATId('fetch', source, fileStats.mtime),
      operation: 'fetch',
      timestamp: fileStats.mtime.getTime() - 86400000, // Assume 1 day before file
      input: {
        rid: ridChain.source,
        cid: 'source:reference:only' // We can't compute CID of source
      },
      output: {
        rid: ridChain.raw!,
        cid: 'cid:unknown:retroactive' // We likely don't have raw
      },
      agent: `${source}-collector-v1`,
      retroactive: true,
      note: 'Retroactive: Original fetch not tracked'
    });
    
    // Add intermediate transformations based on what we have
    if (artifactType === 'markdown' || artifactType === 'normalized') {
      // CAT 2: Normalization
      cats.push({
        cat: this.generateCATId('normalize', source, fileStats.mtime),
        operation: 'normalize',
        timestamp: fileStats.mtime.getTime() - 43200000, // 12 hours before
        input: {
          rid: ridChain.raw!,
          cid: 'cid:unknown:retroactive'
        },
        output: {
          rid: ridChain.normalized!,
          cid: artifactType === 'normalized' ? actualCid : 'cid:unknown:retroactive'
        },
        agent: `${source}-normalizer-v1`,
        retroactive: true,
        note: 'Retroactive: Normalization step reconstructed'
      });
    }
    
    if (artifactType === 'markdown') {
      // CAT 3: Markdown conversion
      cats.push({
        cat: this.generateCATId('markdown', source, fileStats.mtime),
        operation: 'convert-markdown',
        timestamp: fileStats.mtime.getTime(),
        input: {
          rid: ridChain.normalized || ridChain.raw!,
          cid: 'cid:unknown:retroactive'
        },
        output: {
          rid: ridChain.markdown!,
          cid: actualCid // We have this!
        },
        agent: 'markdown-converter-v1',
        retroactive: true,
        note: 'Retroactive: Have markdown artifact'
      });
    }
    
    if (artifactType === 'enriched') {
      // CAT 4: Enrichment
      cats.push({
        cat: this.generateCATId('enrich', source, fileStats.mtime),
        operation: 'enrich',
        timestamp: fileStats.mtime.getTime(),
        input: {
          rid: ridChain.normalized || ridChain.markdown || ridChain.raw!,
          cid: 'cid:unknown:retroactive'
        },
        output: {
          rid: ridChain.enriched!,
          cid: actualCid
        },
        agent: 'enrichment-service-v1',
        retroactive: true,
        note: 'Retroactive: Have enriched artifact'
      });
    }
    
    if (artifactType === 'embedding') {
      // CAT 5: Embedding generation
      cats.push({
        cat: this.generateCATId('embed', source, fileStats.mtime),
        operation: 'generate-embedding',
        timestamp: fileStats.mtime.getTime(),
        input: {
          rid: ridChain.markdown || ridChain.normalized || ridChain.raw!,
          cid: 'cid:unknown:retroactive'
        },
        output: {
          rid: ridChain.embedding!,
          cid: actualCid
        },
        agent: 'embedding-service-v1',
        retroactive: true,
        note: 'Retroactive: Have embedding artifact'
      });
    }
    
    // CAT 6: Current migration
    cats.push({
      cat: this.generateCATId('migrate-koi', source, new Date()),
      operation: 'koi-migration',
      timestamp: Date.now(),
      input: {
        rid: ridChain[artifactType as keyof RIDChain] || ridChain.source,
        cid: actualCid
      },
      output: {
        rid: `orn:regen.koi:${source}/${this.extractDocumentId(filepath)}`,
        cid: actualCid
      },
      agent: 'koi-migrator-v2',
      retroactive: false,
      note: 'Active migration to KOI infrastructure'
    });
    
    return cats;
  }

  /**
   * Extract document ID from filename
   */
  private extractDocumentId(filename: string): string {
    // Remove extension
    let id = path.basename(filename, path.extname(filename));
    
    // Remove common prefixes/suffixes
    id = id
      .replace(/^(tweet|notion|discourse|medium|post|page|article|doc)[-_]/, '')
      .replace(/[-_](raw|original|normalized|enriched|markdown|embed|vector)$/, '')
      .replace(/[-_](processed|converted|final)$/, '');
    
    return id;
  }

  /**
   * Generate CAT ID
   */
  private generateCATId(operation: string, source: string, date: Date): string {
    const timestamp = date.toISOString();
    const hash = crypto
      .createHash('sha256')
      .update(`${operation}-${source}-${timestamp}`)
      .digest('hex')
      .substring(0, 12);
    
    return `cat:${operation}:${hash}`;
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
   * Send RID chain to KOI processor
   */
  private async sendChainToProcessor(ridChain: RIDChain, cats: TransformationCAT[]): Promise<void> {
    const payload = {
      ridChain,
      transformations: cats,
      migrationTimestamp: Date.now(),
      migrationVersion: 'v2-with-chains'
    };
    
    try {
      await axios.post(
        `${this.koiProcessorUrl}/migration/chain`,
        payload,
        { timeout: 10000 }
      );
      console.log(`  ✅ Migrated chain for ${ridChain.source}`);
    } catch (error) {
      // Save to file for later processing
      const backupDir = path.join(this.dataDir, '.migration-v2-queue');
      fs.mkdirSync(backupDir, { recursive: true });
      
      const filename = ridChain.source.replace(/[^a-z0-9]/gi, '_') + '.json';
      fs.writeFileSync(
        path.join(backupDir, filename),
        JSON.stringify(payload, null, 2)
      );
      
      console.log(`  📁 Queued chain for ${ridChain.source}`);
    }
  }

  /**
   * Generate migration report
   */
  private async generateMigrationReport(): Promise<void> {
    const report = {
      timestamp: new Date().toISOString(),
      totalChains: this.transformationChains.size,
      transformations: Array.from(this.transformationChains.entries()).map(([source, cats]) => ({
        source,
        transformationCount: cats.length,
        retroactiveCount: cats.filter(c => c.retroactive).length,
        operations: cats.map(c => c.operation)
      }))
    };
    
    const reportPath = path.join(this.dataDir, 'migration-report-v2.json');
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
    
    console.log(`\n📊 Migration report saved to: ${reportPath}`);
    console.log(`Total RID chains created: ${report.totalChains}`);
  }
}

// CLI
if (require.main === module) {
  const migrator = new MigrationV2(
    process.argv[2] || '/home/regenai/project/data',
    process.argv[3] || 'http://localhost:8100'
  );
  
  migrator.migrate().catch(console.error);
}
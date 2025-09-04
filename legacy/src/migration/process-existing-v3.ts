/**
 * Migration Script V3 - Complete Chain from True Sources
 * Creates RIDs for original URLs/sources, then tracks every transformation
 */

import * as fs from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';
import axios from 'axios';

interface SourceReference {
  rid: string;           // Points to actual source (URL, database record, etc.)
  type: 'url' | 'api' | 'database' | 'file' | 'archive';
  location: string;      // The actual URL, API endpoint, etc.
  accessible: boolean;   // Can we still access it?
  lastVerified?: Date;   // When we last confirmed it exists
}

interface ArtifactChain {
  // Level 0: True source reference (the actual thing out there)
  sourceRef: SourceReference;
  
  // Level 1: Our first capture of it
  raw?: {
    rid: string;
    cid: string;
    format: 'html' | 'json' | 'xml' | 'text' | 'binary';
    capturedAt: Date;
    captureMethod: 'scrape' | 'api' | 'download' | 'archive';
  };
  
  // Level 2: Cleaned/parsed version
  parsed?: {
    rid: string;
    cid: string;
    format: 'json' | 'structured';
  };
  
  // Level 3: Normalized version
  normalized?: {
    rid: string;
    cid: string;
    format: 'json';
  };
  
  // Level 4: Markdown version
  markdown?: {
    rid: string;
    cid: string;
    format: 'markdown';
  };
  
  // Level 5: Enriched version
  enriched?: {
    rid: string;
    cid: string;
    additions: string[]; // ['sentiment', 'topics', 'entities']
  };
  
  // Level 6: Embeddings
  embedding?: {
    rid: string;
    cid: string;
    model: string;
    dimensions: number;
  };
}

export class MigrationV3 {
  private dataDir: string;
  private koiProcessorUrl: string;
  private artifactChains: Map<string, ArtifactChain> = new Map();

  constructor(dataDir: string, koiProcessorUrl: string) {
    this.dataDir = dataDir;
    this.koiProcessorUrl = koiProcessorUrl;
  }

  /**
   * Main migration with complete source tracking
   */
  async migrate(): Promise<void> {
    console.log('🔄 Migration V3: Complete chains from true sources...\n');
    
    // First, inventory what we have
    const inventory = await this.inventoryArtifacts();
    
    // Process each source type with proper source references
    await this.processTwitter();
    await this.processNotion();
    await this.processDiscourse();
    await this.processMedium();
    await this.processPodcast();
    await this.processGitHub();
    await this.processWebsites();
    
    // Generate comprehensive report
    await this.generateReport();
  }

  /**
   * Process Twitter artifacts with proper source references
   */
  async processTwitter(): Promise<void> {
    console.log('\n🐦 Processing Twitter with source references...');
    
    const twitterDir = path.join(this.dataDir, 'twitter');
    if (!fs.existsSync(twitterDir)) {
      console.log('  No Twitter data found');
      return;
    }
    
    const files = fs.readdirSync(twitterDir);
    
    for (const file of files) {
      const filepath = path.join(twitterDir, file);
      const content = fs.readFileSync(filepath, 'utf-8');
      
      // Parse to get tweet ID
      let tweetData: any;
      let tweetId: string;
      
      try {
        tweetData = JSON.parse(content);
        tweetId = tweetData.id_str || tweetData.id || this.extractIdFromFilename(file);
      } catch {
        // If not JSON, extract from filename
        tweetId = this.extractIdFromFilename(file);
      }
      
      // Create complete artifact chain
      const chain: ArtifactChain = {
        // True source reference - the actual tweet URL
        sourceRef: {
          rid: `orn:regen.source:twitter.com/RegenNetwork/status/${tweetId}`,
          type: 'url',
          location: `https://twitter.com/RegenNetwork/status/${tweetId}`,
          accessible: true, // Assume true, could verify
        },
        
        // Our capture of it (if we have the raw API response)
        raw: await this.findRawArtifact(twitterDir, tweetId, 'twitter'),
        
        // Normalized version (if we have it)
        normalized: await this.findNormalizedArtifact(twitterDir, tweetId, 'twitter'),
        
        // Markdown version (if we have it)
        markdown: await this.findMarkdownArtifact(twitterDir, tweetId, 'twitter'),
        
        // Enriched version (if we have it)
        enriched: await this.findEnrichedArtifact(twitterDir, tweetId, 'twitter'),
        
        // Embeddings (if we have them)
        embedding: await this.findEmbeddingArtifact(twitterDir, tweetId, 'twitter')
      };
      
      // Store the chain
      this.artifactChains.set(chain.sourceRef.rid, chain);
      
      // Create CAT receipts for the transformation chain
      await this.createCATChain(chain, 'twitter');
    }
    
    console.log(`  ✅ Processed ${files.length} Twitter artifacts`);
  }

  /**
   * Process Notion artifacts with proper source references
   */
  async processNotion(): Promise<void> {
    console.log('\n📝 Processing Notion with source references...');
    
    const notionDir = path.join(this.dataDir, 'notion');
    if (!fs.existsSync(notionDir)) {
      console.log('  No Notion data found');
      return;
    }
    
    const files = fs.readdirSync(notionDir);
    
    for (const file of files) {
      const filepath = path.join(notionDir, file);
      const content = fs.readFileSync(filepath, 'utf-8');
      
      let pageId: string;
      let pageUrl: string;
      
      try {
        const data = JSON.parse(content);
        pageId = data.id || this.extractIdFromFilename(file);
        pageUrl = data.url || `https://notion.so/${pageId.replace(/-/g, '')}`;
      } catch {
        pageId = this.extractIdFromFilename(file);
        pageUrl = `https://notion.so/${pageId}`;
      }
      
      // Create complete artifact chain
      const chain: ArtifactChain = {
        // True source - the actual Notion page
        sourceRef: {
          rid: `orn:regen.source:notion.so/${pageId}`,
          type: 'database',
          location: pageUrl,
          accessible: true, // Requires API key to verify
        },
        
        // Our API response
        raw: await this.findRawArtifact(notionDir, pageId, 'notion'),
        
        // Parsed/normalized versions
        normalized: await this.findNormalizedArtifact(notionDir, pageId, 'notion'),
        markdown: await this.findMarkdownArtifact(notionDir, pageId, 'notion'),
        enriched: await this.findEnrichedArtifact(notionDir, pageId, 'notion'),
        embedding: await this.findEmbeddingArtifact(notionDir, pageId, 'notion')
      };
      
      this.artifactChains.set(chain.sourceRef.rid, chain);
      await this.createCATChain(chain, 'notion');
    }
    
    console.log(`  ✅ Processed ${files.length} Notion artifacts`);
  }

  /**
   * Process Discourse forum posts
   */
  async processDiscourse(): Promise<void> {
    console.log('\n💬 Processing Discourse with source references...');
    
    const discourseDir = path.join(this.dataDir, 'discourse');
    if (!fs.existsSync(discourseDir)) {
      console.log('  No Discourse data found');
      return;
    }
    
    const files = fs.readdirSync(discourseDir);
    
    for (const file of files) {
      const filepath = path.join(discourseDir, file);
      const content = fs.readFileSync(filepath, 'utf-8');
      
      let topicId: string;
      let postId: string;
      let forumUrl: string;
      
      try {
        const data = JSON.parse(content);
        topicId = data.topic_id || data.id;
        postId = data.post_number || '1';
        forumUrl = `https://forum.regen.network/t/${topicId}/${postId}`;
      } catch {
        topicId = this.extractIdFromFilename(file);
        postId = '1'; // Default to first post
        forumUrl = `https://forum.regen.network/t/${topicId}`;
      }
      
      const chain: ArtifactChain = {
        sourceRef: {
          rid: `orn:regen.source:forum.regen.network/t/${topicId}/${postId}`,
          type: 'url',
          location: forumUrl,
          accessible: true,
        },
        raw: await this.findRawArtifact(discourseDir, topicId, 'discourse'),
        normalized: await this.findNormalizedArtifact(discourseDir, topicId, 'discourse'),
        markdown: await this.findMarkdownArtifact(discourseDir, topicId, 'discourse')
      };
      
      this.artifactChains.set(chain.sourceRef.rid, chain);
      await this.createCATChain(chain, 'discourse');
    }
    
    console.log(`  ✅ Processed ${files.length} Discourse artifacts`);
  }

  /**
   * Process Medium articles
   */
  async processMedium(): Promise<void> {
    console.log('\n📚 Processing Medium with source references...');
    
    const mediumDir = path.join(this.dataDir, 'medium');
    if (!fs.existsSync(mediumDir)) {
      console.log('  No Medium data found');
      return;
    }
    
    const files = fs.readdirSync(mediumDir);
    
    for (const file of files) {
      const filepath = path.join(mediumDir, file);
      const content = fs.readFileSync(filepath, 'utf-8');
      
      let articleId: string;
      let articleUrl: string;
      
      try {
        const data = JSON.parse(content);
        articleUrl = data.url || data.link;
        articleId = this.extractMediumId(articleUrl) || this.extractIdFromFilename(file);
      } catch {
        articleId = this.extractIdFromFilename(file);
        articleUrl = `https://medium.com/regen-network/${articleId}`;
      }
      
      const chain: ArtifactChain = {
        sourceRef: {
          rid: `orn:regen.source:medium.com/${articleId}`,
          type: 'url',
          location: articleUrl,
          accessible: true,
        },
        raw: await this.findRawArtifact(mediumDir, articleId, 'medium'),
        normalized: await this.findNormalizedArtifact(mediumDir, articleId, 'medium'),
        markdown: await this.findMarkdownArtifact(mediumDir, articleId, 'medium')
      };
      
      this.artifactChains.set(chain.sourceRef.rid, chain);
      await this.createCATChain(chain, 'medium');
    }
    
    console.log(`  ✅ Processed ${files.length} Medium artifacts`);
  }

  /**
   * Process Podcast episodes
   */
  async processPodcast(): Promise<void> {
    console.log('\n🎙️ Processing Podcasts with source references...');
    
    const podcastDir = path.join(this.dataDir, 'podcast');
    if (!fs.existsSync(podcastDir)) {
      console.log('  No Podcast data found');
      return;
    }
    
    const files = fs.readdirSync(podcastDir);
    
    for (const file of files) {
      const filepath = path.join(podcastDir, file);
      
      let episodeId: string;
      let episodeUrl: string;
      
      // Extract episode info from filename or content
      episodeId = this.extractIdFromFilename(file);
      
      // Podcast URLs might be various platforms
      episodeUrl = `https://podcast.regen.network/episode/${episodeId}`;
      
      const chain: ArtifactChain = {
        sourceRef: {
          rid: `orn:regen.source:podcast/episode/${episodeId}`,
          type: 'url',
          location: episodeUrl,
          accessible: true,
        },
        raw: await this.findRawArtifact(podcastDir, episodeId, 'podcast'),
        normalized: await this.findNormalizedArtifact(podcastDir, episodeId, 'podcast'),
        markdown: await this.findMarkdownArtifact(podcastDir, episodeId, 'podcast')
      };
      
      this.artifactChains.set(chain.sourceRef.rid, chain);
      await this.createCATChain(chain, 'podcast');
    }
    
    console.log(`  ✅ Processed ${files.length} Podcast artifacts`);
  }

  /**
   * Process GitHub repositories and issues
   */
  async processGitHub(): Promise<void> {
    console.log('\n🐙 Processing GitHub with source references...');
    
    const githubDir = path.join(this.dataDir, 'github');
    if (!fs.existsSync(githubDir)) {
      console.log('  No GitHub data found');
      return;
    }
    
    const files = fs.readdirSync(githubDir);
    
    for (const file of files) {
      const filepath = path.join(githubDir, file);
      const content = fs.readFileSync(filepath, 'utf-8');
      
      let resourceType: 'repo' | 'issue' | 'pr' | 'readme';
      let resourceId: string;
      let githubUrl: string;
      
      try {
        const data = JSON.parse(content);
        if (data.html_url) {
          githubUrl = data.html_url;
          resourceId = this.extractGitHubId(githubUrl);
          resourceType = this.detectGitHubType(githubUrl);
        } else {
          resourceId = this.extractIdFromFilename(file);
          resourceType = 'repo';
          githubUrl = `https://github.com/regen-network/${resourceId}`;
        }
      } catch {
        resourceId = this.extractIdFromFilename(file);
        resourceType = 'repo';
        githubUrl = `https://github.com/regen-network/${resourceId}`;
      }
      
      const chain: ArtifactChain = {
        sourceRef: {
          rid: `orn:regen.source:github.com/${resourceType}/${resourceId}`,
          type: 'url',
          location: githubUrl,
          accessible: true,
        },
        raw: await this.findRawArtifact(githubDir, resourceId, 'github'),
        normalized: await this.findNormalizedArtifact(githubDir, resourceId, 'github'),
        markdown: await this.findMarkdownArtifact(githubDir, resourceId, 'github')
      };
      
      this.artifactChains.set(chain.sourceRef.rid, chain);
      await this.createCATChain(chain, 'github');
    }
    
    console.log(`  ✅ Processed ${files.length} GitHub artifacts`);
  }

  /**
   * Process generic website content
   */
  async processWebsites(): Promise<void> {
    console.log('\n🌐 Processing Websites with source references...');
    
    const webDir = path.join(this.dataDir, 'web');
    if (!fs.existsSync(webDir)) {
      console.log('  No Website data found');
      return;
    }
    
    const files = fs.readdirSync(webDir);
    
    for (const file of files) {
      const filepath = path.join(webDir, file);
      const content = fs.readFileSync(filepath, 'utf-8');
      
      let pageUrl: string;
      let pageId: string;
      
      // Try to extract URL from content or filename
      const urlMatch = content.match(/https?:\/\/[^\s"']+/);
      if (urlMatch) {
        pageUrl = urlMatch[0];
        pageId = this.urlToId(pageUrl);
      } else {
        pageId = this.extractIdFromFilename(file);
        pageUrl = `https://regen.network/${pageId}`;
      }
      
      const chain: ArtifactChain = {
        sourceRef: {
          rid: `orn:regen.source:web/${pageId}`,
          type: 'url',
          location: pageUrl,
          accessible: true,
        },
        raw: await this.findRawArtifact(webDir, pageId, 'web'),
        normalized: await this.findNormalizedArtifact(webDir, pageId, 'web'),
        markdown: await this.findMarkdownArtifact(webDir, pageId, 'web')
      };
      
      this.artifactChains.set(chain.sourceRef.rid, chain);
      await this.createCATChain(chain, 'web');
    }
    
    console.log(`  ✅ Processed ${files.length} Website artifacts`);
  }

  /**
   * Find raw artifact if it exists
   */
  private async findRawArtifact(dir: string, id: string, source: string): Promise<any> {
    // Look for files with 'raw', 'original', 'api' in name
    const patterns = ['raw', 'original', 'api', 'response'];
    
    for (const pattern of patterns) {
      const files = fs.readdirSync(dir).filter(f => 
        f.includes(id) && f.includes(pattern)
      );
      
      if (files.length > 0) {
        const filepath = path.join(dir, files[0]);
        const content = fs.readFileSync(filepath, 'utf-8');
        const cid = await this.computeCID(content);
        
        return {
          rid: `orn:regen.raw:${source}/${id}`,
          cid,
          format: this.detectFormat(content),
          capturedAt: fs.statSync(filepath).mtime,
          captureMethod: source === 'twitter' ? 'archive' : 'api'
        };
      }
    }
    
    // If no raw file found, but we have something, create retroactive entry
    const anyFile = fs.readdirSync(dir).find(f => f.includes(id));
    if (anyFile) {
      return {
        rid: `orn:regen.raw:${source}/${id}`,
        cid: 'cid:unknown:no-raw-artifact',
        format: 'unknown',
        capturedAt: new Date('2024-01-01'), // Approximate
        captureMethod: 'unknown'
      };
    }
    
    return undefined;
  }

  /**
   * Find normalized artifact if it exists
   */
  private async findNormalizedArtifact(dir: string, id: string, source: string): Promise<any> {
    const patterns = ['normalized', 'cleaned', 'processed'];
    
    for (const pattern of patterns) {
      const files = fs.readdirSync(dir).filter(f => 
        f.includes(id) && f.includes(pattern) && f.endsWith('.json')
      );
      
      if (files.length > 0) {
        const filepath = path.join(dir, files[0]);
        const content = fs.readFileSync(filepath, 'utf-8');
        const cid = await this.computeCID(content);
        
        return {
          rid: `orn:regen.normalized:${source}/${id}`,
          cid,
          format: 'json'
        };
      }
    }
    
    return undefined;
  }

  /**
   * Find markdown artifact if it exists
   */
  private async findMarkdownArtifact(dir: string, id: string, source: string): Promise<any> {
    const files = fs.readdirSync(dir).filter(f => 
      f.includes(id) && f.endsWith('.md')
    );
    
    if (files.length > 0) {
      const filepath = path.join(dir, files[0]);
      const content = fs.readFileSync(filepath, 'utf-8');
      const cid = await this.computeCID(content);
      
      return {
        rid: `orn:regen.markdown:${source}/${id}`,
        cid,
        format: 'markdown'
      };
    }
    
    return undefined;
  }

  /**
   * Find enriched artifact if it exists
   */
  private async findEnrichedArtifact(dir: string, id: string, source: string): Promise<any> {
    const patterns = ['enriched', 'analyzed', 'sentiment', 'topics'];
    
    for (const pattern of patterns) {
      const files = fs.readdirSync(dir).filter(f => 
        f.includes(id) && f.includes(pattern)
      );
      
      if (files.length > 0) {
        const filepath = path.join(dir, files[0]);
        const content = fs.readFileSync(filepath, 'utf-8');
        const cid = await this.computeCID(content);
        
        // Detect what enrichments were added
        const additions = [];
        if (content.includes('sentiment')) additions.push('sentiment');
        if (content.includes('topics')) additions.push('topics');
        if (content.includes('entities')) additions.push('entities');
        
        return {
          rid: `orn:regen.enriched:${source}/${id}`,
          cid,
          additions
        };
      }
    }
    
    return undefined;
  }

  /**
   * Find embedding artifact if it exists
   */
  private async findEmbeddingArtifact(dir: string, id: string, source: string): Promise<any> {
    const patterns = ['embedding', 'vector', 'embed'];
    
    for (const pattern of patterns) {
      const files = fs.readdirSync(dir).filter(f => 
        f.includes(id) && f.includes(pattern)
      );
      
      if (files.length > 0) {
        const filepath = path.join(dir, files[0]);
        const content = fs.readFileSync(filepath, 'utf-8');
        const cid = await this.computeCID(content);
        
        let dimensions = 0;
        try {
          const data = JSON.parse(content);
          if (Array.isArray(data)) dimensions = data.length;
          else if (data.embedding) dimensions = data.embedding.length;
        } catch {}
        
        return {
          rid: `orn:regen.embedding:${source}/${id}`,
          cid,
          model: 'text-embedding-3-small', // Assume OpenAI
          dimensions: dimensions || 1536
        };
      }
    }
    
    return undefined;
  }

  /**
   * Create CAT receipts for the entire transformation chain
   */
  private async createCATChain(chain: ArtifactChain, source: string): Promise<void> {
    const cats = [];
    
    // CAT 1: Initial fetch from source
    if (chain.raw) {
      cats.push({
        cat: this.generateCATId('fetch', source),
        operation: 'fetch',
        timestamp: chain.raw.capturedAt.getTime(),
        input: {
          rid: chain.sourceRef.rid,
          cid: 'source:external'
        },
        output: {
          rid: chain.raw.rid,
          cid: chain.raw.cid
        },
        method: chain.raw.captureMethod,
        retroactive: chain.raw.cid.includes('unknown')
      });
    }
    
    // CAT 2: Parse/clean if we have it
    if (chain.parsed) {
      cats.push({
        cat: this.generateCATId('parse', source),
        operation: 'parse',
        timestamp: Date.now() - 86400000, // Approximate
        input: {
          rid: chain.raw?.rid || chain.sourceRef.rid,
          cid: chain.raw?.cid || 'unknown'
        },
        output: {
          rid: chain.parsed.rid,
          cid: chain.parsed.cid
        },
        retroactive: true
      });
    }
    
    // CAT 3: Normalize if we have it
    if (chain.normalized) {
      cats.push({
        cat: this.generateCATId('normalize', source),
        operation: 'normalize',
        timestamp: Date.now() - 43200000, // Approximate
        input: {
          rid: chain.parsed?.rid || chain.raw?.rid || chain.sourceRef.rid,
          cid: chain.parsed?.cid || chain.raw?.cid || 'unknown'
        },
        output: {
          rid: chain.normalized.rid,
          cid: chain.normalized.cid
        },
        retroactive: true
      });
    }
    
    // CAT 4: Convert to markdown if we have it
    if (chain.markdown) {
      cats.push({
        cat: this.generateCATId('markdown', source),
        operation: 'convert-markdown',
        timestamp: Date.now() - 21600000, // Approximate
        input: {
          rid: chain.normalized?.rid || chain.raw?.rid || chain.sourceRef.rid,
          cid: chain.normalized?.cid || chain.raw?.cid || 'unknown'
        },
        output: {
          rid: chain.markdown.rid,
          cid: chain.markdown.cid
        },
        retroactive: true
      });
    }
    
    // CAT 5: Enrich if we have it
    if (chain.enriched) {
      cats.push({
        cat: this.generateCATId('enrich', source),
        operation: 'enrich',
        timestamp: Date.now() - 10800000, // Approximate
        input: {
          rid: chain.markdown?.rid || chain.normalized?.rid || chain.raw?.rid,
          cid: chain.markdown?.cid || chain.normalized?.cid || chain.raw?.cid || 'unknown'
        },
        output: {
          rid: chain.enriched.rid,
          cid: chain.enriched.cid
        },
        additions: chain.enriched.additions,
        retroactive: true
      });
    }
    
    // CAT 6: Generate embeddings if we have them
    if (chain.embedding) {
      cats.push({
        cat: this.generateCATId('embed', source),
        operation: 'generate-embedding',
        timestamp: Date.now() - 3600000, // Approximate
        input: {
          rid: chain.markdown?.rid || chain.normalized?.rid || chain.raw?.rid,
          cid: chain.markdown?.cid || chain.normalized?.cid || chain.raw?.cid || 'unknown'
        },
        output: {
          rid: chain.embedding.rid,
          cid: chain.embedding.cid
        },
        model: chain.embedding.model,
        dimensions: chain.embedding.dimensions,
        retroactive: true
      });
    }
    
    // Store CATs with the chain
    (chain as any).cats = cats;
  }

  /**
   * Helper functions
   */
  private extractIdFromFilename(filename: string): string {
    return path.basename(filename, path.extname(filename))
      .replace(/^(tweet|notion|discourse|medium|post|page|article|doc)[-_]/, '')
      .replace(/[-_](raw|original|normalized|enriched|markdown|embed)$/, '');
  }

  private extractMediumId(url: string): string {
    const match = url.match(/medium\.com\/.*\/([^\/]+)$/);
    return match ? match[1] : '';
  }

  private extractGitHubId(url: string): string {
    const parts = url.replace('https://github.com/', '').split('/');
    return parts.join('/');
  }

  private detectGitHubType(url: string): 'repo' | 'issue' | 'pr' | 'readme' {
    if (url.includes('/issues/')) return 'issue';
    if (url.includes('/pull/')) return 'pr';
    if (url.includes('README')) return 'readme';
    return 'repo';
  }

  private urlToId(url: string): string {
    return url
      .replace(/https?:\/\//, '')
      .replace(/[^a-z0-9]/gi, '_');
  }

  private detectFormat(content: string): 'html' | 'json' | 'xml' | 'text' | 'binary' {
    if (content.trim().startsWith('<')) return content.includes('<!DOCTYPE') ? 'html' : 'xml';
    if (content.trim().startsWith('{') || content.trim().startsWith('[')) return 'json';
    return 'text';
  }

  private generateCATId(operation: string, source: string): string {
    const hash = crypto
      .createHash('sha256')
      .update(`${operation}-${source}-${Date.now()}`)
      .digest('hex')
      .substring(0, 12);
    return `cat:${operation}:${hash}`;
  }

  private async computeCID(content: string): Promise<string> {
    const hash = crypto
      .createHash('sha256')
      .update(content)
      .digest('hex');
    return `cid:sha256:${hash}`;
  }

  /**
   * Inventory all artifacts
   */
  private async inventoryArtifacts(): Promise<any> {
    const sources = ['twitter', 'notion', 'discourse', 'medium', 'podcast', 'github', 'gitlab', 'web'];
    const inventory: any = {};
    
    for (const source of sources) {
      const dir = path.join(this.dataDir, source);
      if (!fs.existsSync(dir)) continue;
      
      const files = fs.readdirSync(dir);
      inventory[source] = {
        total: files.length,
        byType: {
          raw: files.filter(f => f.includes('raw') || f.includes('original')).length,
          json: files.filter(f => f.endsWith('.json')).length,
          markdown: files.filter(f => f.endsWith('.md')).length,
          enriched: files.filter(f => f.includes('enrich') || f.includes('analyzed')).length,
          embeddings: files.filter(f => f.includes('embed') || f.includes('vector')).length
        }
      };
    }
    
    console.log('📦 Artifact Inventory:');
    console.log(JSON.stringify(inventory, null, 2));
    return inventory;
  }

  /**
   * Generate comprehensive migration report
   */
  private async generateReport(): Promise<void> {
    const report = {
      version: 'v3-complete-chains',
      timestamp: new Date().toISOString(),
      statistics: {
        totalChains: this.artifactChains.size,
        bySource: {} as any,
        artifactCoverage: {
          hasRaw: 0,
          hasNormalized: 0,
          hasMarkdown: 0,
          hasEnriched: 0,
          hasEmbeddings: 0
        }
      },
      chains: Array.from(this.artifactChains.entries()).map(([rid, chain]) => ({
        sourceRid: rid,
        sourceUrl: chain.sourceRef.location,
        artifacts: {
          raw: !!chain.raw,
          normalized: !!chain.normalized,
          markdown: !!chain.markdown,
          enriched: !!chain.enriched,
          embedding: !!chain.embedding
        },
        transformations: (chain as any).cats?.length || 0
      }))
    };
    
    // Calculate statistics
    for (const [rid, chain] of this.artifactChains) {
      const source = rid.split(':')[2].split('.')[0];
      report.statistics.bySource[source] = (report.statistics.bySource[source] || 0) + 1;
      
      if (chain.raw) report.statistics.artifactCoverage.hasRaw++;
      if (chain.normalized) report.statistics.artifactCoverage.hasNormalized++;
      if (chain.markdown) report.statistics.artifactCoverage.hasMarkdown++;
      if (chain.enriched) report.statistics.artifactCoverage.hasEnriched++;
      if (chain.embedding) report.statistics.artifactCoverage.hasEmbeddings++;
    }
    
    const reportPath = path.join(this.dataDir, 'migration-report-v3.json');
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
    
    console.log('\n📊 Migration Report Summary:');
    console.log(`  Total artifact chains: ${report.statistics.totalChains}`);
    console.log(`  Sources processed: ${Object.keys(report.statistics.bySource).length}`);
    console.log(`  Artifacts with raw data: ${report.statistics.artifactCoverage.hasRaw}`);
    console.log(`  Artifacts with markdown: ${report.statistics.artifactCoverage.hasMarkdown}`);
    console.log(`\n✅ Full report saved to: ${reportPath}`);
  }
}

// CLI
if (require.main === module) {
  const migrator = new MigrationV3(
    process.argv[2] || './data',
    process.argv[3] || 'http://localhost:8100'
  );
  
  migrator.migrate().catch(console.error);
}
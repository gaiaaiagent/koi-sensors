/**
 * Notion Sensor Node
 * Wraps the existing Notion collector as a KOI sensor
 */

import { SensorNode } from '../../framework/SensorNode';
import { SensorEvent, SensorConfig } from '../../types';
import { execSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

export class NotionSensorNode extends SensorNode {
  private pythonScriptPath: string;
  private outputDir: string;

  constructor(config: SensorConfig) {
    super(config);
    
    // Path to existing Python collector
    this.pythonScriptPath = path.join(
      __dirname, 
      '../../../indexing/collectors/notion_transcript_collector.py'
    );
    
    // Output directory for collected documents
    this.outputDir = path.join(
      __dirname,
      '../../../data/notion'
    );
    
    // Ensure output directory exists
    if (!fs.existsSync(this.outputDir)) {
      fs.mkdirSync(this.outputDir, { recursive: true });
    }
  }

  async sense(): Promise<SensorEvent[]> {
    console.log('[NotionSensor] Starting Notion content collection...');
    
    const events: SensorEvent[] = [];
    
    try {
      // Check for existing processed files to avoid duplicates
      const processedFiles = this.getProcessedFiles();
      
      // Run the existing Python collector
      const result = await this.runPythonCollector();
      
      // Read collected documents and convert to events
      const files = fs.readdirSync(this.outputDir)
        .filter(f => f.endsWith('.json'))
        .filter(f => !processedFiles.has(f));
      
      for (const file of files) {
        const filePath = path.join(this.outputDir, file);
        const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
        
        // Extract identifier from filename or content
        const identifier = this.extractIdentifier(file, content);
        
        // Generate RID and CID
        const rid = this.generateRID('notion', identifier);
        const cid = await this.computeCID(content);
        
        // Create sensor event
        const event = this.createEvent(
          'NEW',
          rid,
          content,
          {
            title: content.title || content.properties?.title,
            url: content.url,
            author: content.created_by?.name,
            lastEdited: content.last_edited_time,
            type: content.object, // 'page' or 'database'
            tags: this.extractTags(content)
          }
        );
        
        // Add CID to event
        event.cid = cid;
        
        events.push(event);
        
        // Mark file as processed
        this.markAsProcessed(file);
      }
      
      console.log(`[NotionSensor] Created ${events.length} events from Notion content`);
      
    } catch (error) {
      console.error('[NotionSensor] Error during collection:', error);
      throw error;
    }
    
    return events;
  }

  /**
   * Run the existing Python collector script
   */
  private async runPythonCollector(): Promise<string> {
    return new Promise((resolve, reject) => {
      try {
        // Prepare environment variables
        const env = { ...process.env };
        
        if (this.config.credentials?.notionApiKey) {
          env.NOTION_API_KEY = this.config.credentials.notionApiKey;
        }
        
        // Build Python command
        const command = `python3 ${this.pythonScriptPath} --output ${this.outputDir}`;
        
        console.log('[NotionSensor] Running Python collector...');
        
        // Execute Python script
        const output = execSync(command, {
          env,
          encoding: 'utf-8',
          maxBuffer: 10 * 1024 * 1024 // 10MB buffer
        });
        
        resolve(output);
      } catch (error) {
        reject(error);
      }
    });
  }

  /**
   * Extract unique identifier from Notion content
   */
  private extractIdentifier(filename: string, content: any): string {
    // Try to use Notion page/database ID
    if (content.id) {
      return content.id.replace(/-/g, '');
    }
    
    // Fallback to filename without extension
    return path.basename(filename, '.json');
  }

  /**
   * Extract tags from Notion content
   */
  private extractTags(content: any): string[] {
    const tags: string[] = [];
    
    // Add object type as tag
    if (content.object) {
      tags.push(`notion:${content.object}`);
    }
    
    // Extract tags from properties
    if (content.properties?.tags?.multi_select) {
      const notionTags = content.properties.tags.multi_select;
      tags.push(...notionTags.map((t: any) => t.name));
    }
    
    // Extract categories
    if (content.properties?.category?.select) {
      tags.push(content.properties.category.select.name);
    }
    
    return tags;
  }

  /**
   * Get list of already processed files
   */
  private getProcessedFiles(): Set<string> {
    const processedFile = path.join(this.outputDir, '.processed');
    
    if (fs.existsSync(processedFile)) {
      const content = fs.readFileSync(processedFile, 'utf-8');
      return new Set(content.split('\n').filter(f => f));
    }
    
    return new Set();
  }

  /**
   * Mark a file as processed
   */
  private markAsProcessed(filename: string): void {
    const processedFile = path.join(this.outputDir, '.processed');
    fs.appendFileSync(processedFile, `${filename}\n`);
  }
}
/**
 * Twitter Sensor Node
 * Wraps the existing Twitter collector as a KOI sensor
 */

import { SensorNode } from '../../framework/SensorNode';
import { SensorEvent, SensorConfig } from '../../types';
import { execSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

export class TwitterSensorNode extends SensorNode {
  private pythonScriptPath: string;
  private outputDir: string;
  private archivePath?: string;

  constructor(config: SensorConfig) {
    super(config);
    
    // Path to existing Python collector
    this.pythonScriptPath = path.join(
      __dirname, 
      '../../../indexing/collectors/twitter_collector.py'
    );
    
    // Output directory for collected tweets
    this.outputDir = path.join(
      __dirname,
      '../../../data/twitter'
    );
    
    // Twitter archive path if provided
    this.archivePath = config.options?.archivePath;
    
    // Ensure output directory exists
    if (!fs.existsSync(this.outputDir)) {
      fs.mkdirSync(this.outputDir, { recursive: true });
    }
  }

  async sense(): Promise<SensorEvent[]> {
    console.log('[TwitterSensor] Starting Twitter content collection...');
    
    const events: SensorEvent[] = [];
    
    try {
      // Check for existing processed tweets
      const processedIds = this.getProcessedTweetIds();
      
      // Run the existing Python collector
      await this.runPythonCollector();
      
      // Read collected tweets and convert to events
      const files = fs.readdirSync(this.outputDir)
        .filter(f => f.endsWith('.json'));
      
      for (const file of files) {
        const filePath = path.join(this.outputDir, file);
        const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
        
        // Process batch of tweets or single tweet
        const tweets = Array.isArray(content) ? content : [content];
        
        for (const tweet of tweets) {
          // Skip if already processed
          if (processedIds.has(tweet.id_str || tweet.id)) {
            continue;
          }
          
          // Generate RID and CID
          const tweetId = tweet.id_str || tweet.id;
          const rid = this.generateRID('twitter', tweetId);
          const cid = await this.computeCID(tweet);
          
          // Create sensor event
          const event = this.createEvent(
            'NEW',
            rid,
            tweet,
            {
              author: tweet.user?.screen_name || tweet.author_id,
              authorName: tweet.user?.name,
              createdAt: tweet.created_at,
              url: `https://twitter.com/${tweet.user?.screen_name}/status/${tweetId}`,
              retweets: tweet.retweet_count,
              likes: tweet.favorite_count,
              isRetweet: !!tweet.retweeted_status,
              hashtags: this.extractHashtags(tweet),
              mentions: this.extractMentions(tweet),
              type: 'tweet'
            }
          );
          
          // Add CID to event
          event.cid = cid;
          
          events.push(event);
          
          // Mark tweet as processed
          this.markTweetAsProcessed(tweetId);
        }
      }
      
      console.log(`[TwitterSensor] Created ${events.length} events from Twitter content`);
      
    } catch (error) {
      console.error('[TwitterSensor] Error during collection:', error);
      throw error;
    }
    
    return events;
  }

  /**
   * Run the existing Python collector script
   */
  private async runPythonCollector(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        // Prepare environment variables
        const env = { ...process.env };
        
        // Add Twitter API credentials if available
        if (this.config.credentials?.twitterBearerToken) {
          env.TWITTER_BEARER_TOKEN = this.config.credentials.twitterBearerToken;
        }
        
        // Build Python command
        let command = `python3 ${this.pythonScriptPath} --output ${this.outputDir}`;
        
        // Add archive path if provided
        if (this.archivePath) {
          command += ` --archive ${this.archivePath}`;
        }
        
        // Add any rate limit configuration
        if (this.config.rateLimit) {
          command += ` --rate-limit ${this.config.rateLimit.requests}`;
        }
        
        console.log('[TwitterSensor] Running Python collector...');
        
        // Execute Python script
        execSync(command, {
          env,
          encoding: 'utf-8',
          maxBuffer: 50 * 1024 * 1024 // 50MB buffer for large archives
        });
        
        resolve();
      } catch (error) {
        reject(error);
      }
    });
  }

  /**
   * Extract hashtags from tweet
   */
  private extractHashtags(tweet: any): string[] {
    const hashtags: string[] = [];
    
    // Twitter API v1 format
    if (tweet.entities?.hashtags) {
      hashtags.push(...tweet.entities.hashtags.map((h: any) => h.text));
    }
    
    // Twitter API v2 format
    if (tweet.entities?.hashtags) {
      hashtags.push(...tweet.entities.hashtags.map((h: any) => h.tag));
    }
    
    // Archive format
    if (tweet.hashtags) {
      hashtags.push(...tweet.hashtags);
    }
    
    return hashtags;
  }

  /**
   * Extract mentions from tweet
   */
  private extractMentions(tweet: any): string[] {
    const mentions: string[] = [];
    
    // Twitter API v1 format
    if (tweet.entities?.user_mentions) {
      mentions.push(...tweet.entities.user_mentions.map((m: any) => m.screen_name));
    }
    
    // Twitter API v2 format
    if (tweet.entities?.mentions) {
      mentions.push(...tweet.entities.mentions.map((m: any) => m.username));
    }
    
    return mentions;
  }

  /**
   * Get list of already processed tweet IDs
   */
  private getProcessedTweetIds(): Set<string> {
    const processedFile = path.join(this.outputDir, '.processed_tweets');
    
    if (fs.existsSync(processedFile)) {
      const content = fs.readFileSync(processedFile, 'utf-8');
      return new Set(content.split('\n').filter(id => id));
    }
    
    return new Set();
  }

  /**
   * Mark a tweet as processed
   */
  private markTweetAsProcessed(tweetId: string): void {
    const processedFile = path.join(this.outputDir, '.processed_tweets');
    fs.appendFileSync(processedFile, `${tweetId}\n`);
  }
}
/**
 * Base Sensor Node Class
 * Abstract base class for all KOI sensor implementations
 */

import { EventEmitter } from 'events';
import * as crypto from 'crypto';
import { 
  SensorEvent, 
  SensorConfig, 
  SensorStatus, 
  EventType,
  RID,
  CID 
} from '../types';

export abstract class SensorNode extends EventEmitter {
  protected config: SensorConfig;
  protected status: SensorStatus;
  private rateLimiter?: RateLimiter;

  constructor(config: SensorConfig) {
    super();
    this.config = config;
    this.status = {
      name: config.name,
      documentsProcessed: 0,
      errors: 0,
      isRunning: false,
      health: 'healthy'
    };

    if (config.rateLimit) {
      this.rateLimiter = new RateLimiter(
        config.rateLimit.requests,
        config.rateLimit.period
      );
    }
  }

  /**
   * Main sensing method - must be implemented by subclasses
   */
  abstract sense(): Promise<SensorEvent[]>;

  /**
   * Process new content and emit events
   */
  async process(): Promise<void> {
    if (this.status.isRunning) {
      console.log(`Sensor ${this.config.name} is already running`);
      return;
    }

    this.status.isRunning = true;
    this.status.lastRun = new Date();

    try {
      console.log(`[${this.config.name}] Starting sensor processing...`);
      
      const events = await this.sense();
      
      for (const event of events) {
        // Apply rate limiting if configured
        if (this.rateLimiter) {
          await this.rateLimiter.wait();
        }

        // Emit event for KOI processor
        this.emit('sensor:event', event);
        this.status.documentsProcessed++;
      }

      console.log(`[${this.config.name}] Processed ${events.length} events`);
      this.status.health = 'healthy';

    } catch (error) {
      console.error(`[${this.config.name}] Error during processing:`, error);
      this.status.errors++;
      this.status.health = 'error';
      this.emit('sensor:error', error);
    } finally {
      this.status.isRunning = false;
    }
  }

  /**
   * Generate RID for a document
   */
  protected generateRID(type: string, identifier: string): string {
    return `orn:regen.${type}:${identifier}`;
  }

  /**
   * Compute CID for content
   */
  protected async computeCID(content: any): Promise<string> {
    const contentStr = typeof content === 'string' 
      ? content 
      : JSON.stringify(content);
    
    const hash = crypto
      .createHash('sha256')
      .update(contentStr)
      .digest('hex');
    
    return `cid:sha256:${hash}`;
  }

  /**
   * Create a sensor event
   */
  protected createEvent(
    type: EventType,
    rid: string,
    content?: any,
    metadata?: any
  ): SensorEvent {
    return {
      type,
      rid,
      content,
      metadata: {
        source: this.config.type,
        timestamp: Date.now(),
        ...metadata
      }
    };
  }

  /**
   * Get current sensor status
   */
  getStatus(): SensorStatus {
    return { ...this.status };
  }

  /**
   * Check if sensor is healthy
   */
  isHealthy(): boolean {
    return this.status.health === 'healthy';
  }

  /**
   * Stop the sensor
   */
  async stop(): Promise<void> {
    console.log(`[${this.config.name}] Stopping sensor...`);
    this.removeAllListeners();
  }
}

/**
 * Simple rate limiter for API calls
 */
class RateLimiter {
  private requests: number;
  private period: number;
  private queue: number[] = [];

  constructor(requests: number, period: number) {
    this.requests = requests;
    this.period = period * 1000; // Convert to milliseconds
  }

  async wait(): Promise<void> {
    const now = Date.now();
    
    // Remove old entries
    this.queue = this.queue.filter(time => now - time < this.period);
    
    if (this.queue.length >= this.requests) {
      const oldestRequest = this.queue[0];
      const waitTime = this.period - (now - oldestRequest);
      
      if (waitTime > 0) {
        await new Promise(resolve => setTimeout(resolve, waitTime));
      }
    }
    
    this.queue.push(Date.now());
  }
}
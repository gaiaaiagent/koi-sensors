/**
 * Sensor Coordinator
 * Manages all sensor nodes and coordinates event flow to KOI processor
 */

import { EventEmitter } from 'events';
import { SensorNode } from './framework/SensorNode';
import { SensorEvent, SensorConfig } from './types';
import { NotionSensorNode } from './sensors/notion';
import { TwitterSensorNode } from './sensors/twitter';
import axios from 'axios';
import * as cron from 'node-cron';

interface CoordinatorConfig {
  koiProcessorUrl: string;
  koiProcessorApiKey?: string;
  sensors: SensorConfig[];
  batchSize?: number;
  flushInterval?: number; // milliseconds
}

export class SensorCoordinator extends EventEmitter {
  private config: CoordinatorConfig;
  private sensors: Map<string, SensorNode> = new Map();
  private eventQueue: SensorEvent[] = [];
  private flushTimer?: NodeJS.Timeout;
  private schedules: Map<string, cron.ScheduledTask> = new Map();

  constructor(config: CoordinatorConfig) {
    super();
    this.config = config;
    this.initializeSensors();
    this.startFlushTimer();
  }

  /**
   * Initialize all configured sensors
   */
  private initializeSensors(): void {
    for (const sensorConfig of this.config.sensors) {
      if (!sensorConfig.enabled) {
        console.log(`Sensor ${sensorConfig.name} is disabled, skipping...`);
        continue;
      }

      const sensor = this.createSensor(sensorConfig);
      
      if (sensor) {
        // Listen for sensor events
        sensor.on('sensor:event', (event: SensorEvent) => {
          this.handleSensorEvent(event);
        });

        sensor.on('sensor:error', (error: Error) => {
          console.error(`Sensor ${sensorConfig.name} error:`, error);
          this.emit('coordinator:error', { sensor: sensorConfig.name, error });
        });

        this.sensors.set(sensorConfig.name, sensor);

        // Set up scheduled runs if configured
        if (sensorConfig.schedule) {
          this.scheduleRenaor(sensorConfig.name, sensorConfig.schedule);
        }

        console.log(`Initialized sensor: ${sensorConfig.name}`);
      }
    }
  }

  /**
   * Create a sensor instance based on type
   */
  private createSensor(config: SensorConfig): SensorNode | null {
    switch (config.type) {
      case 'notion':
        return new NotionSensorNode(config);
      case 'twitter':
        return new TwitterSensorNode(config);
      // Add more sensor types as we implement them
      // case 'discourse':
      //   return new DiscourseSensorNode(config);
      // case 'medium':
      //   return new MediumSensorNode(config);
      // case 'github':
      //   return new GitHubSensorNode(config);
      default:
        console.warn(`Unknown sensor type: ${config.type}`);
        return null;
    }
  }

  /**
   * Handle events from sensors
   */
  private handleSensorEvent(event: SensorEvent): void {
    // Add to queue
    this.eventQueue.push(event);
    
    // Emit for local listeners
    this.emit('event:received', event);

    // Check if we should flush
    if (this.eventQueue.length >= (this.config.batchSize || 100)) {
      this.flushEvents();
    }
  }

  /**
   * Send queued events to KOI processor
   */
  private async flushEvents(): Promise<void> {
    if (this.eventQueue.length === 0) {
      return;
    }

    const events = [...this.eventQueue];
    this.eventQueue = [];

    try {
      console.log(`Sending ${events.length} events to KOI processor...`);
      
      const response = await axios.post(
        `${this.config.koiProcessorUrl}/events`,
        { events },
        {
          headers: {
            'Content-Type': 'application/json',
            ...(this.config.koiProcessorApiKey && {
              'Authorization': `Bearer ${this.config.koiProcessorApiKey}`
            })
          },
          timeout: 30000 // 30 second timeout
        }
      );

      console.log(`Successfully sent ${events.length} events to KOI processor`);
      this.emit('events:sent', { count: events.length, response: response.data });

    } catch (error) {
      console.error('Failed to send events to KOI processor:', error);
      
      // Re-queue events for retry
      this.eventQueue.unshift(...events);
      
      this.emit('events:failed', { 
        count: events.length, 
        error: error instanceof Error ? error.message : String(error)
      });
    }
  }

  /**
   * Start periodic flush timer
   */
  private startFlushTimer(): void {
    const interval = this.config.flushInterval || 60000; // Default 1 minute
    
    this.flushTimer = setInterval(() => {
      this.flushEvents();
    }, interval);
  }

  /**
   * Schedule a sensor to run periodically
   */
  private scheduleRenaor(name: string, schedule: string): void {
    const sensor = this.sensors.get(name);
    
    if (!sensor) {
      console.error(`Cannot schedule unknown sensor: ${name}`);
      return;
    }

    const task = cron.schedule(schedule, async () => {
      console.log(`Running scheduled sensor: ${name}`);
      try {
        await sensor.process();
      } catch (error) {
        console.error(`Scheduled run failed for ${name}:`, error);
      }
    });

    this.schedules.set(name, task);
    console.log(`Scheduled sensor ${name} with cron: ${schedule}`);
  }

  /**
   * Run a specific sensor manually
   */
  async runSensor(name: string): Promise<void> {
    const sensor = this.sensors.get(name);
    
    if (!sensor) {
      throw new Error(`Unknown sensor: ${name}`);
    }

    await sensor.process();
  }

  /**
   * Run all enabled sensors
   */
  async runAll(): Promise<void> {
    const promises = Array.from(this.sensors.entries()).map(([name, sensor]) => {
      return sensor.process().catch(error => {
        console.error(`Failed to run sensor ${name}:`, error);
      });
    });

    await Promise.all(promises);
  }

  /**
   * Get status of all sensors
   */
  getStatus(): Record<string, any> {
    const status: Record<string, any> = {};
    
    for (const [name, sensor] of this.sensors) {
      status[name] = sensor.getStatus();
    }

    return {
      sensors: status,
      queueSize: this.eventQueue.length,
      koiProcessor: this.config.koiProcessorUrl
    };
  }

  /**
   * Shutdown coordinator and all sensors
   */
  async shutdown(): Promise<void> {
    console.log('Shutting down sensor coordinator...');

    // Stop flush timer
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
    }

    // Stop all schedules
    for (const task of this.schedules.values()) {
      task.stop();
    }

    // Flush remaining events
    await this.flushEvents();

    // Stop all sensors
    for (const sensor of this.sensors.values()) {
      await sensor.stop();
    }

    this.removeAllListeners();
    console.log('Sensor coordinator shutdown complete');
  }
}
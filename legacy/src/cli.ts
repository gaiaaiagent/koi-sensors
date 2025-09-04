#!/usr/bin/env node

/**
 * KOI Sensors CLI
 * Command-line interface for managing sensor nodes
 */

import { Command } from 'commander';
import * as dotenv from 'dotenv';
import * as fs from 'fs';
import * as path from 'path';
import { SensorCoordinator } from './SensorCoordinator';
import { SensorConfig } from './types';

// Load environment variables
dotenv.config();

const program = new Command();

// Default configuration
const DEFAULT_CONFIG: SensorConfig[] = [
  {
    name: 'notion-sensor',
    type: 'notion',
    enabled: true,
    schedule: '0 */6 * * *', // Every 6 hours
    batchSize: 100,
    credentials: {
      notionApiKey: process.env.NOTION_API_KEY || ''
    }
  },
  {
    name: 'twitter-sensor',
    type: 'twitter',
    enabled: true,
    schedule: '0 */12 * * *', // Every 12 hours
    batchSize: 500,
    rateLimit: {
      requests: 300,
      period: 900 // 15 minutes
    },
    credentials: {
      twitterBearerToken: process.env.TWITTER_BEARER_TOKEN || ''
    },
    options: {
      archivePath: process.env.TWITTER_ARCHIVE_PATH
    }
  }
  // Add more sensors as they're implemented
];

program
  .name('koi-sensors')
  .description('KOI Sensor Network CLI - Distributed content monitoring')
  .version('1.0.0');

program
  .command('run <sensor>')
  .description('Run a specific sensor or "all" for all sensors')
  .option('-c, --config <path>', 'Path to configuration file')
  .option('-o, --once', 'Run once and exit (ignore schedule)')
  .action(async (sensor: string, options: any) => {
    try {
      console.log('🚀 Starting KOI Sensor Network...\n');
      
      // Load configuration
      const config = loadConfiguration(options.config);
      
      // Create coordinator
      const coordinator = new SensorCoordinator({
        koiProcessorUrl: process.env.KOI_PROCESSOR_URL || 'http://localhost:8100',
        koiProcessorApiKey: process.env.KOI_PROCESSOR_API_KEY,
        sensors: config,
        batchSize: 100,
        flushInterval: 60000 // 1 minute
      });

      // Add event listeners
      coordinator.on('event:received', (event) => {
        console.log(`📥 Event received: ${event.rid}`);
      });

      coordinator.on('events:sent', ({ count }) => {
        console.log(`✅ Sent ${count} events to KOI processor`);
      });

      coordinator.on('events:failed', ({ count, error }) => {
        console.error(`❌ Failed to send ${count} events: ${error}`);
      });

      // Run requested sensor(s)
      if (sensor === 'all') {
        console.log('Running all enabled sensors...\n');
        await coordinator.runAll();
      } else {
        console.log(`Running sensor: ${sensor}\n`);
        await coordinator.runSensor(sensor);
      }

      // If running once, shutdown after completion
      if (options.once) {
        await coordinator.shutdown();
        console.log('\n✨ Sensor run complete');
        process.exit(0);
      } else {
        console.log('\n📡 Sensors running on schedule. Press Ctrl+C to stop.');
        
        // Handle graceful shutdown
        process.on('SIGINT', async () => {
          console.log('\n\n🛑 Shutting down...');
          await coordinator.shutdown();
          process.exit(0);
        });
      }

    } catch (error) {
      console.error('Error:', error);
      process.exit(1);
    }
  });

program
  .command('status')
  .description('Show status of all sensors')
  .option('-c, --config <path>', 'Path to configuration file')
  .action(async (options: any) => {
    try {
      const config = loadConfiguration(options.config);
      
      const coordinator = new SensorCoordinator({
        koiProcessorUrl: process.env.KOI_PROCESSOR_URL || 'http://localhost:8100',
        sensors: config
      });

      const status = coordinator.getStatus();
      console.log('📊 Sensor Status:\n');
      console.log(JSON.stringify(status, null, 2));
      
      await coordinator.shutdown();
      
    } catch (error) {
      console.error('Error:', error);
      process.exit(1);
    }
  });

program
  .command('list')
  .description('List all available sensors')
  .action(() => {
    console.log('📋 Available Sensors:\n');
    
    const sensors = [
      { name: 'notion', status: '✅ Implemented', description: 'Notion workspace pages and databases' },
      { name: 'twitter', status: '✅ Implemented', description: 'Twitter/X posts and archives' },
      { name: 'discourse', status: '🚧 Pending', description: 'Discourse forum posts' },
      { name: 'medium', status: '🚧 Pending', description: 'Medium blog articles' },
      { name: 'github', status: '🚧 Pending', description: 'GitHub repositories and issues' },
      { name: 'gitlab', status: '🚧 Pending', description: 'GitLab repositories' },
      { name: 'web', status: '🚧 Pending', description: 'Generic web scraping' },
      { name: 'podcast', status: '🚧 Pending', description: 'Podcast transcriptions' }
    ];
    
    sensors.forEach(s => {
      console.log(`  ${s.status} ${s.name.padEnd(12)} - ${s.description}`);
    });
    
    console.log('\nUse "koi-sensors run <sensor>" to run a specific sensor');
  });

program
  .command('init')
  .description('Initialize sensor configuration')
  .action(() => {
    const configPath = path.join(process.cwd(), 'sensors.config.json');
    
    if (fs.existsSync(configPath)) {
      console.log('⚠️  Configuration file already exists: sensors.config.json');
      return;
    }
    
    fs.writeFileSync(configPath, JSON.stringify(DEFAULT_CONFIG, null, 2));
    console.log('✅ Created sensors.config.json');
    console.log('\nNext steps:');
    console.log('1. Edit sensors.config.json to configure your sensors');
    console.log('2. Set environment variables in .env file');
    console.log('3. Run "koi-sensors run all" to start all sensors');
  });

/**
 * Load configuration from file or use defaults
 */
function loadConfiguration(configPath?: string): SensorConfig[] {
  if (configPath && fs.existsSync(configPath)) {
    console.log(`Loading configuration from: ${configPath}`);
    const content = fs.readFileSync(configPath, 'utf-8');
    return JSON.parse(content);
  }
  
  const defaultPath = path.join(process.cwd(), 'sensors.config.json');
  if (fs.existsSync(defaultPath)) {
    console.log('Loading configuration from: sensors.config.json');
    const content = fs.readFileSync(defaultPath, 'utf-8');
    return JSON.parse(content);
  }
  
  console.log('Using default configuration');
  return DEFAULT_CONFIG;
}

// Parse command line arguments
program.parse(process.argv);
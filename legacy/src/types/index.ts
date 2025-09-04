/**
 * KOI Sensor Types
 * Core type definitions for the KOI sensor network
 */

export type EventType = 'NEW' | 'UPDATE' | 'FORGET';

export interface RID {
  namespace: string;  // e.g., "orn:regen"
  type: string;       // e.g., "document", "tweet", "notion"
  identifier: string; // unique identifier within type
  toString(): string;
}

export interface CID {
  algorithm: string;  // e.g., "sha256"
  hash: string;       // content hash
  toString(): string;
}

export interface SensorEvent {
  type: EventType;
  rid: RID | string;
  cid?: CID | string;
  content?: any;
  metadata?: {
    source: string;
    timestamp: number;
    author?: string;
    title?: string;
    url?: string;
    tags?: string[];
    [key: string]: any;
  };
  previousCid?: CID | string;  // For UPDATE events
}

export interface TransformationReceipt {
  cat: string;  // Content-Addressable Transformation ID
  operation: string;
  input: {
    rid: string;
    cid: string;
  };
  output: {
    rid: string;
    cid: string;
  };
  cost?: {
    tokens?: number;
    compute?: number;
    storage?: number;
  };
  timestamp: number;
  agent?: string;
}

export interface SensorConfig {
  name: string;
  type: string;
  enabled: boolean;
  schedule?: string;  // cron expression
  batchSize?: number;
  rateLimit?: {
    requests: number;
    period: number;  // in seconds
  };
  credentials?: Record<string, string>;
  options?: Record<string, any>;
}

export interface SensorStatus {
  name: string;
  lastRun?: Date;
  nextRun?: Date;
  documentsProcessed: number;
  errors: number;
  isRunning: boolean;
  health: 'healthy' | 'degraded' | 'error';
}
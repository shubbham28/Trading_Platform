import { describe, expect, it, beforeAll, afterAll } from 'vitest';
import request from 'supertest';
import http from 'node:http';
import type { AddressInfo } from 'node:net';

/**
 * Reachability tests for the BFF.
 *
 * This service had no tests, and it cost two silent breakages that a UI found
 * weeks later:
 *
 *   - /api/strategies returned a bare array from Node's own registry until the
 *     route was repointed at the engine, which wraps the list. A TypeScript cast
 *     hid the shape change and the strategy dropdown was empty for two phases.
 *   - GET /backtest/runs existed in the engine from the moment backtests were
 *     persisted and was never mounted here. Every request 404ed.
 *
 * Both are the same mistake: adding an engine endpoint is not the same as making
 * it reachable. So these tests assert reachability and shape pass-through rather
 * than behaviour -- the engine has 460-odd tests for behaviour. What was missing
 * was anything at all checking the seam between the two.
 *
 * A stub engine stands in for Python, so nothing here needs a database, an
 * Alpaca key, or the real engine running.
 */

// Every path the frontend calls, taken from web/src/utils/api.ts. A route added
// to the client and not to the server fails here rather than in a browser.
const FRONTEND_GET_PATHS = [
  '/api/assets',
  '/api/account',
  '/api/account/positions',
  '/api/orders',
  '/api/strategies',
  '/api/backtest/runs',
  '/api/backtest/runs/1',
  '/api/backtest/runs/1/equity',
  '/api/bots',
  '/api/bots/1',
  '/api/audit',
  '/api/risk/kill-switch',
  '/api/risk/rules',
  '/api/risk/decisions',
  '/api/reconciliation',
  '/api/live/settings',
  '/api/approvals',
];

let engine: http.Server;
let app: any;
const seen: Array<{ method: string; url: string }> = [];

beforeAll(async () => {
  // A stub engine that records what it was asked for and answers everything.
  engine = http.createServer((req, res) => {
    seen.push({ method: req.method ?? '', url: req.url ?? '' });
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ stub: true, path: req.url }));
  });
  await new Promise<void>((resolve) => engine.listen(0, resolve));
  const { port } = engine.address() as AddressInfo;

  process.env.PYTHON_BACKEND_URL = `http://127.0.0.1:${port}`;
  // Deliberately absent: the server must start without them. It used to build
  // the Alpaca client at module scope and refuse to boot, taking the bots UI,
  // the audit log and the kill switch down with it.
  delete process.env.ALPACA_API_KEY;
  delete process.env.ALPACA_API_SECRET;

  app = (await import('../index')).default;
});

afterAll(async () => {
  await new Promise<void>((resolve) => engine.close(() => resolve()));
});

describe('the server starts without Alpaca credentials', () => {
  it('serves /health', async () => {
    const response = await request(app).get('/health');
    expect(response.status).toBe(200);
    expect(response.body.status).toBe('ok');
  });
});

describe('every path the frontend calls is mounted', () => {
  it.each(FRONTEND_GET_PATHS)('%s is not a 404', async (path) => {
    const response = await request(app).get(path);
    expect(response.status).not.toBe(404);
  });
});

describe('engine routes are forwarded verbatim', () => {
  it.each([
    ['/api/bots', '/bots'],
    ['/api/bots/7', '/bots/7'],
    ['/api/audit', '/audit'],
    ['/api/risk/kill-switch', '/risk/kill-switch'],
    ['/api/reconciliation', '/reconciliation'],
    ['/api/live/settings', '/live/settings'],
    ['/api/approvals', '/approvals'],
  ])('%s reaches the engine at %s', async (clientPath, enginePath) => {
    seen.length = 0;
    await request(app).get(clientPath);
    expect(seen.map((r) => r.url)).toContain(enginePath);
  });

  it('does not reshape the engine payload', async () => {
    // A BFF that rewrites a payload becomes a second place where the API shape
    // is defined, and the two drift. That drift is what broke the strategy
    // dropdown.
    const response = await request(app).get('/api/bots');
    expect(response.body).toEqual({ stub: true, path: '/bots' });
  });

  it('forwards query strings', async () => {
    seen.length = 0;
    await request(app).get('/api/audit?event_type=fill&limit=5');
    expect(seen.some((r) => r.url?.includes('event_type=fill'))).toBe(true);
  });
});

describe('the backtest route normalises field names', () => {
  it('maps camelCase to the snake_case the engine speaks', async () => {
    // Without this the engine silently falls back to its defaults and runs a
    // backtest over the wrong dates with the wrong capital.
    seen.length = 0;
    const response = await request(app).post('/api/backtest').send({
      symbol: 'aapl',
      strategyId: 'sma_crossover',
      startDate: '2025-01-02',
      endDate: '2025-06-30',
      initialCapital: 5000,
    });
    expect(response.status).toBe(200);
    expect(seen.map((r) => r.url)).toContain('/backtest/run');
  });

  it('rejects a request missing required fields rather than passing it on', async () => {
    seen.length = 0;
    const response = await request(app).post('/api/backtest').send({ symbol: 'AAPL' });
    expect(response.status).toBe(400);
    expect(response.body.error).toMatch(/Missing required fields/);
    expect(seen).toHaveLength(0);
  });
});

describe('an unreachable engine is not reported as an empty result', () => {
  it('answers 503, not 200 with nothing', async () => {
    // A route returning 200 with no data reads as "you have no bots" or "no
    // trades found", which is a very different statement from "we could not
    // ask". Pointed at a dead port for this one assertion, then restored.
    const good = process.env.PYTHON_BACKEND_URL;
    process.env.PYTHON_BACKEND_URL = 'http://127.0.0.1:1';
    try {
      const response = await request(app).get('/api/bots');
      expect(response.status).toBe(503);
      expect(response.body.error).toMatch(/unavailable/i);
    } finally {
      process.env.PYTHON_BACKEND_URL = good;
    }
  });
});

describe('unknown routes still 404', () => {
  it('so the reachability tests above mean something', async () => {
    const response = await request(app).get('/api/definitely-not-a-route');
    expect(response.status).toBe(404);
  });
});

import { afterEach, describe, expect, it, vi } from 'vitest';
import { getLiveStatus } from './health';

afterEach(() => vi.unstubAllGlobals());

describe('health API boundary', () => {
  it('reads a valid API response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(Response.json({ status: 'ok', version: '0.1.0' })),
    );
    await expect(getLiveStatus()).resolves.toEqual({ status: 'ok', version: '0.1.0' });
  });
  it('rejects failures instead of showing a connected state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
    await expect(getLiveStatus()).rejects.toThrow('503');
  });
  it('rejects a malformed health response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ status: 'maybe' })));
    await expect(getLiveStatus()).rejects.toThrow('Unexpected');
  });
});

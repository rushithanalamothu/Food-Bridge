import { afterEach, expect, it, vi } from 'vitest';
import { connectStream, frameParser } from './stream';
import { setAccessToken, setOrganization } from './session';
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  setAccessToken();
  setOrganization();
});
it('parses multiline data, comments and CRLF split across packets', () => {
  const receive = vi.fn();
  const parse = frameParser(receive);
  parse(': heartbeat\r');
  parse('\nid: 12\r\nevent: status\r\ndata: first\r');
  parse('\ndata: second\r\n\r');
  parse('\n');
  expect(receive).toHaveBeenCalledExactlyOnceWith({
    id: '12',
    event: 'status',
    data: 'first\nsecond',
  });
});
it('scopes bearer-authenticated streams, drops duplicate cursors and stops after auth failure', async () => {
  vi.useFakeTimers();
  setAccessToken('memory-token');
  setOrganization('org');
  const event = { event_id: 'event', aggregate_id: 'donation', aggregate_version: 1 };
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        new ReadableStream({
          start(controller) {
            const frame = `id: 1\nevent: status\ndata: ${JSON.stringify(event)}\n\n`;
            controller.enqueue(new TextEncoder().encode(frame + frame));
            controller.close();
          },
        }),
        { headers: { 'Content-Type': 'text/event-stream' } },
      ),
    )
    .mockResolvedValueOnce(new Response('', { status: 401 }));
  vi.stubGlobal('fetch', fetch);
  const changed = vi.fn();
  const state = vi.fn();
  const stop = connectStream('recipient', changed, state);
  await vi.advanceTimersByTimeAsync(2000);
  expect(changed.mock.calls.filter((args) => args[0])).toHaveLength(1);
  expect(fetch.mock.calls[0][1].headers).toMatchObject({
    Authorization: 'Bearer memory-token',
    'X-FoodBridge-Role': 'recipient',
    'X-Organization-ID': 'org',
  });
  expect(fetch.mock.calls[1][1].headers['Last-Event-ID']).toBe('1');
  expect(state).toHaveBeenLastCalledWith('signed_out');
  stop();
});
it('resets an expired cursor and requests a fresh snapshot before reconnecting', async () => {
  vi.useFakeTimers();
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response('', { status: 409 }))
    .mockResolvedValue(new Response('', { status: 403 }));
  vi.stubGlobal('fetch', fetch);
  const changed = vi.fn();
  const stop = connectStream('driver', changed, vi.fn());
  await vi.advanceTimersByTimeAsync(2000);
  expect(changed).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[1][1].headers['Last-Event-ID']).toBeUndefined();
  stop();
});

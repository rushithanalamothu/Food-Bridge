import type { EventEnvelope, Role } from './generated/workflow';
import { sessionHeaders } from './session';
export type Connection = 'connecting' | 'live' | 'reconnecting' | 'offline' | 'signed_out';
type Frame = { id?: string; event?: string; data: string };
// Streaming UTF-8 decoder handles split packets, CRLF and multiple data lines.
export function frameParser(receive: (frame: Frame) => void) {
  let buffer = '';
  return (chunk: string) => {
    buffer = (buffer + chunk).replace(/\r\n/g, '\n');
    let end;
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, end).replaceAll('\r', '');
      buffer = buffer.slice(end + 2);
      const frame: Frame = { data: '' };
      const data: string[] = [];
      for (const line of block.split('\n')) {
        if (line.startsWith(':')) continue;
        const colon = line.indexOf(':');
        const field = colon < 0 ? line : line.slice(0, colon);
        const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '');
        if (field === 'data') data.push(value);
        if (field === 'id') frame.id = value;
        if (field === 'event') frame.event = value;
      }
      frame.data = data.join('\n');
      if (frame.data) receive(frame);
    }
  };
}
export function connectStream(
  role: Role,
  changed: (event?: EventEnvelope) => void,
  state: (state: Connection) => void,
) {
  const controller = new AbortController();
  let cursor: string | undefined;
  let attempts = 0;
  let timer: ReturnType<typeof setTimeout>;
  let wake: (() => void) | undefined;
  const wait = (ms: number) =>
    new Promise<void>((resolve) => {
      wake = resolve;
      timer = setTimeout(resolve, ms);
    });
  async function run() {
    while (!controller.signal.aborted) {
      state(attempts ? 'reconnecting' : 'connecting');
      try {
        const response = await fetch('/api/v1/events', {
          headers: {
            ...sessionHeaders(role),
            Accept: 'text/event-stream',
            ...(cursor ? { 'Last-Event-ID': cursor } : {}),
          },
          signal: controller.signal,
        });
        if (response.status === 401 || response.status === 403) {
          state('signed_out');
          return;
        }
        if (response.status === 409 || response.status === 400) {
          cursor = undefined;
          changed();
          throw new Error('cursor_reset');
        }
        if (
          !response.ok ||
          !response.body ||
          !response.headers.get('content-type')?.includes('text/event-stream')
        )
          throw new Error('stream_unavailable');
        state('live');
        attempts = 0;
        // Establish stream cursor before fetching snapshots: no snapshot/subscribe gap.
        changed();
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const parse = frameParser((frame) => {
          if (frame.event && frame.event !== 'status') return;
          if (!frame.id || !/^\d+$/.test(frame.id)) return;
          if (cursor && BigInt(frame.id) <= BigInt(cursor)) return;
          const event = JSON.parse(frame.data) as EventEnvelope;
          if (!event.event_id || !event.aggregate_id || !Number.isInteger(event.aggregate_version))
            throw new Error('invalid_event');
          cursor = frame.id;
          changed(event);
        });
        try {
          while (!controller.signal.aborted) {
            const { done, value } = await reader.read();
            if (done) break;
            parse(decoder.decode(value, { stream: true }));
          }
        } finally {
          await reader.cancel().catch(() => {});
        }
        throw new Error('stream_closed');
      } catch {
        if (controller.signal.aborted) return;
        state(
          typeof navigator !== 'undefined' && navigator.onLine === false
            ? 'offline'
            : 'reconnecting',
        );
      }
      await wait(Math.min(15000, 500 * 2 ** Math.min(attempts++, 5)) + Math.random() * 250);
    }
  }
  void run();
  return () => {
    controller.abort();
    clearTimeout(timer);
    wake?.();
  };
}

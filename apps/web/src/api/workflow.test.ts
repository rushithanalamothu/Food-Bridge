import { describe, expect, it } from 'vitest';
import { parseFrame } from './workflow';
describe('SSE framing', () => {
  it('ignores keepalives and retains cursors and multi-line payloads', () => {
    expect(parseFrame(': heartbeat')).toBeUndefined();
    expect(parseFrame('id: 42\nevent: update\ndata: {"version":\ndata: 3}')).toEqual({
      id: '42',
      data: '{"version":\n3}',
    });
  });
});

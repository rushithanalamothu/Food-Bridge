import { useEffect, useState } from 'react';
import { parseFrame, roleHeaders } from './workflow';
import { sessionExpired } from './session';
// Open stream before loading snapshots; every reconnect reconciles a fresh snapshot.
export function useLiveWorkflow<T>(role: string, load: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState('');
  const [connection, setConnection] = useState('Connecting');
  const [generation, refresh] = useState(0);
  useEffect(() => {
    let alive = true,
      busy = false,
      dirty = false;
    let cursor = '',
      timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const reload = async () => {
      if (busy) {
        dirty = true;
        return;
      }
      busy = true;
      do {
        dirty = false;
        try {
          const result = await load(controller.signal);
          if (alive) {
            setData(result);
            setError('');
          }
        } catch (e) {
          if (alive) setError(e instanceof Error ? e.message : 'Could not load current state.');
        }
      } while (dirty && alive);
      busy = false;
    };
    const connect = async () => {
      if (!alive) return;
      try {
        const response = await fetch('/api/v1/events', {
          headers: { ...roleHeaders(role), ...(cursor ? { 'Last-Event-ID': cursor } : {}) },
          credentials: 'same-origin',
          signal: controller.signal,
        });
        if (response.status === 401) sessionExpired();
        if (response.status === 409) {
          cursor = '';
          throw new Error('Replay expired; loading a fresh snapshot.');
        }
        if (!response.ok || !response.body) throw new Error('Live updates unavailable.');
        if (alive) setConnection('Live');
        await reload();
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let pending = '';
        while (alive) {
          const chunk = await reader.read();
          if (chunk.done) break;
          pending += decoder.decode(chunk.value, { stream: true });
          pending = pending.replace(/\r\n/g, '\n');
          let end;
          while ((end = pending.indexOf('\n\n')) >= 0) {
            const frame = parseFrame(pending.slice(0, end));
            pending = pending.slice(end + 2);
            if (frame) {
              if (frame.id) cursor = frame.id;
              void reload();
            }
          }
          if (pending.length > 1048576) throw new Error('Invalid event stream.');
        }
      } catch {
        /* All failures become a visible reconnect state and snapshot reconciliation. */
      }
      if (alive) {
        setConnection('Disconnected · reconnecting');
        void reload();
        timer = setTimeout(() => void connect(), 3000);
      }
    };
    // Snapshot is still available if the stream is down.
    void reload();
    void connect();
    const changed = () => refresh((n) => n + 1);
    const expired = () => {
      alive = false;
      controller.abort();
      if (timer) clearTimeout(timer);
      setData(undefined);
      setError('Session expired. Sign in again.');
      setConnection('Sign in required');
    };
    window.addEventListener('foodbridge:session-expired', expired);
    window.addEventListener('foodbridge:membership', changed);
    return () => {
      alive = false;
      controller.abort();
      if (timer) clearTimeout(timer);
      window.removeEventListener('foodbridge:membership', changed);
      window.removeEventListener('foodbridge:session-expired', expired);
    };
  }, [role, load, generation]);
  return { data, error, connection, refresh: () => refresh((n) => n + 1) };
}

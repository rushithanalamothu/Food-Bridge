import { useCallback, useEffect, useRef, useState } from 'react';
import type { Role, EventEnvelope } from '../api/generated/workflow';
import { connectStream, type Connection } from '../api/stream';

export function useWorkspace<T>(role: Role, load: () => Promise<T>) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [connection, setConnection] = useState<Connection>('connecting');
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [updated, setUpdated] = useState<Date>();
  const generation = useRef(0);
  const mounted = useRef(false);
  const refresh = useCallback(async () => {
    const run = ++generation.current;
    try {
      const next = await load();
      if (mounted.current && run === generation.current) {
        setData(next);
        setUpdated(new Date());
        setError('');
      }
    } catch (e) {
      if (mounted.current && run === generation.current)
        setError(e instanceof Error ? e.message : 'Could not load this workspace.');
    } finally {
      if (mounted.current && run === generation.current) setLoading(false);
    }
  }, [load]);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = connectStream(
      role,
      (event) => {
        if (event)
          setEvents((old) =>
            [event, ...old.filter((item) => item.event_id !== event.event_id)].slice(0, 30),
          );
        if (!timer)
          timer = setTimeout(() => {
            timer = undefined;
            void refresh();
          }, 150);
      },
      setConnection,
    );
    const onFocus = () => void refresh();
    window.addEventListener('focus', onFocus);
    return () => {
      mounted.current = false;
      generation.current++;
      clearTimeout(timer);
      stop();
      window.removeEventListener('focus', onFocus);
    };
  }, [role, refresh]);
  return { events, data, error, setError, loading, connection, updated, refresh };
}
export function useCommand() {
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const keys = useRef(new Map<string, string>());
  const run = async <T>(identity: string, execute: (key: string) => Promise<T>): Promise<T> => {
    if (pending.current) throw new Error('Wait for the current action to finish.');
    pending.current = true;
    setBusy(true);
    const key = keys.current.get(identity) ?? crypto.randomUUID();
    keys.current.set(identity, key);
    try {
      const result = await execute(key);
      keys.current.delete(identity);
      return result;
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  return { busy, run };
}

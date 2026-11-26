import { Button } from '../../components/Button';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { DriverOriginRead, DriverOriginUpdate } from '../../api/generated/workflow';
import { getDriverOrigin, saveDriverOrigin } from '../../api/workflow';
import { IntakeApiError } from '../../api/intake';
import { useCommand } from '../../hooks/useWorkspace';
import { Notice, formatTime, useNow } from '../../components/Workspace';

export function DriverOrigin() {
  const [value, setValue] = useState<DriverOriginRead>();
  const [baseline, setBaseline] = useState<DriverOriginRead>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [conflict, setConflict] = useState(false);
  const controller = useRef<AbortController | undefined>(undefined);
  const mounted = useRef(false);
  const action = useCommand();
  const now = useNow();
  const load = useCallback(async () => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError('');
    setMessage('');
    try {
      const next = await getDriverOrigin(request.signal);
      if (request.signal.aborted || !mounted.current) return;
      setValue(next);
      setConflict(false);
      return next;
    } catch (e) {
      if (!request.signal.aborted && mounted.current) setError((e as Error).message);
    } finally {
      if (!request.signal.aborted && mounted.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, [load]);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!baseline) return;
    const data = new FormData(event.currentTarget);
    const text = (key: string) => String(data.get(key) ?? '').trim();
    setError('');
    setMessage('');
    try {
      new Intl.DateTimeFormat('en', { timeZone: text('timezone') });
      const body: DriverOriginUpdate = {
        expected_version: baseline.version,
        origin: {
          address: text('address'),
          latitude: Number(text('latitude')),
          longitude: Number(text('longitude')),
          timezone: text('timezone'),
        },
      };
      const saved = await action.run(JSON.stringify(body), (key) => saveDriverOrigin(body, key));
      if (!mounted.current) return;
      setValue(saved);
      setBaseline(undefined);
      setMessage('Starting point saved. Update it after moving or within five minutes.');
    } catch (e) {
      if (!mounted.current) return;
      const changed = e instanceof IntakeApiError && e.status === 409;
      setConflict(changed);
      setError(
        changed
          ? 'Your driver details changed. Reload the current starting point before saving again.'
          : e instanceof RangeError
            ? 'Enter a valid location timezone, such as America/Los_Angeles.'
            : (e as Error).message,
      );
    }
  }
  const stale = !value?.observed_at || now - Date.parse(value.observed_at) >= 300000;
  return (
    <section className="card" aria-labelledby="driver-origin-heading">
      <div className="section-heading">
        <h2 id="driver-origin-heading">Your starting point</h2>
        {!baseline && (
          <Button
            variant="secondary"
            disabled={!value || loading || action.busy}
            onClick={() => {
              setBaseline(value);
              setMessage('');
              setError('');
            }}
          >
            Update starting point
          </Button>
        )}
      </div>
      <p>
        Share your current starting point for pickup matching. Coordinates are used for routing;
        entering an address does not look up its coordinates. This is a self-reported location.
      </p>
      {loading && <p role="status">Loading starting point…</p>}
      {message && <Notice tone="success">{message}</Notice>}
      {error && <Notice error>{error}</Notice>}
      {!loading && value && (
        <>
          {value.origin && (
            <p>
              {value.origin.address} · {value.origin.latitude}, {value.origin.longitude}
              {value.observed_at && (
                <> · Saved {formatTime(value.observed_at, value.origin.timezone)}</>
              )}
            </p>
          )}
          {stale && (
            <Notice tone="warning">
              {value.origin ? 'Your starting point is out of date.' : 'No starting point saved.'}{' '}
              Live matching needs a location updated within five minutes. Saving does not change
              your availability or guarantee an assignment.
            </Notice>
          )}
        </>
      )}
      {baseline && (
        <form key={baseline.version} onSubmit={(event) => void submit(event)}>
          <fieldset disabled={action.busy || loading}>
            <legend>Current starting point</legend>
            <label htmlFor="driver-origin-address">Starting point description</label>
            <input
              id="driver-origin-address"
              name="address"
              defaultValue={baseline.origin?.address}
              maxLength={500}
              required
            />
            <div className="detail-grid">
              <div>
                <label htmlFor="driver-origin-latitude">Starting latitude</label>
                <input
                  id="driver-origin-latitude"
                  name="latitude"
                  type="number"
                  min="-90"
                  max="90"
                  step="any"
                  defaultValue={baseline.origin?.latitude}
                  required
                />
              </div>
              <div>
                <label htmlFor="driver-origin-longitude">Starting longitude</label>
                <input
                  id="driver-origin-longitude"
                  name="longitude"
                  type="number"
                  min="-180"
                  max="180"
                  step="any"
                  defaultValue={baseline.origin?.longitude}
                  required
                />
              </div>
            </div>
            <label htmlFor="driver-origin-timezone">Starting point timezone</label>
            <input
              id="driver-origin-timezone"
              name="timezone"
              defaultValue={
                baseline.origin?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone
              }
              required
            />
            <div className="actions">
              <Button type="submit" disabled={conflict} busy={action.busy}>
                Save starting point
              </Button>
              <Button type="button" variant="secondary" onClick={() => setBaseline(undefined)}>
                Cancel location update
              </Button>
            </div>
          </fieldset>
        </form>
      )}
      <Button
        variant="ghost"
        disabled={loading || action.busy}
        onClick={() =>
          void load().then((next) => {
            if (next && baseline && mounted.current) setBaseline(next);
          })
        }
      >
        Reload starting point
      </Button>
    </section>
  );
}

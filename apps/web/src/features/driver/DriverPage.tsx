import { useCallback, useState } from 'react';
import type { PickupPage, PickupRead } from '../../api/generated/workflow';
import { workflowGet, workflowPost } from '../../api/workflow';
import { useLiveWorkflow } from '../../api/useLiveWorkflow';
export function DriverPage() {
  const [cursor, setCursor] = useState('');
  const load = useCallback(
    (signal: AbortSignal) =>
      workflowGet<PickupPage>(
        `/pickups?limit=25${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
        'driver',
        signal,
      ),
    [cursor],
  );
  const { data, error, connection, refresh } = useLiveWorkflow('driver', load);
  const [busy, setBusy] = useState('');
  const [failure, setFailure] = useState('');
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  async function act(pickup: PickupRead, action: string) {
    setBusy(pickup.id);
    setFailure('');
    const body = {
      expected_version: pickup.version,
      ...(action === 'confirm-pickup'
        ? {
            handling_confirmed: confirmed[pickup.id] === true,
            observed_quantity_kg: Number(quantities[pickup.id] ?? pickup.donation.quantity_kg),
          }
        : {}),
      ...(action === 'confirm-delivery'
        ? { delivery_confirmed: confirmed[pickup.id] === true }
        : {}),
    };
    try {
      await workflowPost(`/pickups/${pickup.id}/${action}`, 'driver', body);
      setConfirmed((v) => ({ ...v, [pickup.id]: false }));
    } catch (e) {
      setFailure(e instanceof Error ? e.message : 'Action failed.');
    } finally {
      setBusy('');
      refresh();
    }
  }
  return (
    <section>
      <p className="eyebrow">Driver workspace</p>
      <h1>Your pickups</h1>
      <p role="status">{connection}</p>
      {(error || failure) && (
        <p role="alert">{failure || error} Refresh current state before retrying.</p>
      )}
      <button onClick={refresh}>Refresh assignments</button>
      {data?.items.length === 0 && <p>No assignments for this driver.</p>}
      {data?.items.map((p) => (
        <article className="workflow-card" key={p.id}>
          <h2>
            {p.donation.food_name} · {p.donation.quantity_kg} kg
          </h2>
          <p>
            <strong>{p.status.replaceAll('_', ' ')}</strong> · version {p.version}
          </p>
          <p>Pickup: {p.donation.pickup_location.address}</p>
          <p>Pickup deadline: {new Date(p.donation.pickup_window.end).toLocaleString()}</p>
          <p>
            Storage: {p.donation.storage} · Allergens:{' '}
            {p.donation.allergens.join(', ') || 'None declared'}
          </p>
          <p>
            Handling: {p.donation.handling_notes || 'Follow the confirmed storage requirements.'}
          </p>
          {p.delivery_location && <p>Deliver to: {p.delivery_location.address}</p>}
          {p.route && (
            <p>
              Saved route estimate: {(p.route.distance_m / 1000).toFixed(1)} km ·{' '}
              {Math.ceil(p.route.travel_time_s / 60)} min. Calculated{' '}
              {new Date(p.route.calculated_at).toLocaleString()} ({p.route.source}).
            </p>
          )}
          <div className="workflow-actions">
            {p.status === 'assigned' && (
              <>
                <button disabled={!!busy} onClick={() => void act(p, 'accept')}>
                  Accept assignment
                </button>
                <button disabled={!!busy} onClick={() => void act(p, 'decline')}>
                  Decline assignment
                </button>
              </>
            )}
            {p.status === 'accepted' && (
              <>
                <label>
                  Observed quantity (kg)
                  <input
                    type="number"
                    min="0.001"
                    step="0.001"
                    value={quantities[p.id] ?? String(p.donation.quantity_kg)}
                    onChange={(e) => setQuantities((v) => ({ ...v, [p.id]: e.target.value }))}
                  />
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={confirmed[p.id] ?? false}
                    onChange={(e) => setConfirmed((v) => ({ ...v, [p.id]: e.target.checked }))}
                  />
                  I checked handling requirements and quantity.
                </label>
                <button
                  disabled={!!busy || !confirmed[p.id]}
                  onClick={() => void act(p, 'confirm-pickup')}
                >
                  Confirm pickup
                </button>
              </>
            )}
            {p.status === 'collected' && (
              <>
                <label>
                  <input
                    type="checkbox"
                    checked={confirmed[p.id] ?? false}
                    onChange={(e) => setConfirmed((v) => ({ ...v, [p.id]: e.target.checked }))}
                  />
                  I confirm delivery to the receiving organization.
                </label>
                <button
                  disabled={!!busy || !confirmed[p.id]}
                  onClick={() => void act(p, 'confirm-delivery')}
                >
                  Confirm delivery
                </button>
              </>
            )}
          </div>
        </article>
      ))}
      {cursor && <button onClick={() => setCursor('')}>First page</button>}
      {data?.next_cursor && (
        <button onClick={() => setCursor(data.next_cursor!)}>Next assignments</button>
      )}
    </section>
  );
}

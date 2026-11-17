import { useEffect, useRef, useState } from 'react';
import { getPickups, pickupCommand } from '../../api/workflow';
import type { PickupRead } from '../../api/generated/workflow';
import { DonationTimeline } from '../../components/DonationTimeline';
import { useWorkspace, useCommand } from '../../hooks/useWorkspace';
import {
  WorkspaceHeader,
  Notice,
  EmptyState,
  Stats,
  StatusBadge,
  formatTime,
  ConfirmAction,
  useNow,
} from '../../components/Workspace';

export function DriverPage() {
  const view = useWorkspace('driver', getPickups);
  const latestSnapshot = useRef(view.data);
  latestSnapshot.current = view.data;
  const action = useCommand();
  const now = useNow();
  const [message, setMessage] = useState('');
  const [history, setHistory] = useState<string>();
  const [extra, setExtra] = useState<PickupRead[]>([]);
  const [cursor, setCursor] = useState<string | null | undefined>();
  const [paging, setPaging] = useState(false);
  useEffect(() => {
    setExtra([]);
    setCursor(undefined);
  }, [view.data]);
  const pickups = [
    ...(view.data?.items ?? []),
    ...extra.filter((p) => !view.data?.items.some((first) => first.id === p.id)),
  ];
  async function act(pickup: PickupRead, verb: string, details = {}) {
    view.setError('');
    setMessage('');
    const body = { expected_version: pickup.version, ...details };
    try {
      await action.run(`${pickup.id}:${verb}:${JSON.stringify(body)}`, (key) =>
        pickupCommand(pickup.id, verb, body, key),
      );
      setMessage('Your update is confirmed.');
      setExtra([]);
      setCursor(undefined);
      await view.refresh();
    } catch (e) {
      await view.refresh();
      view.setError((e as Error).message);
    }
  }
  return (
    <section>
      <WorkspaceHeader
        eyebrow="Driver workspace"
        title="Every pickup makes a difference."
        {...view}
      >
        <p>Accept a task, check handling details, and confirm each handoff.</p>
      </WorkspaceHeader>
      {view.error && <Notice error>{view.error}</Notice>}
      {message && <Notice>{message}</Notice>}
      <Stats
        items={[
          {
            label: 'Awaiting your response',
            value: pickups.filter((p) => p.status === 'assigned').length,
          },
          {
            label: 'Active on this page',
            value: pickups.filter((p) => ['accepted', 'collected'].includes(p.status)).length,
          },
          {
            label: 'Delivered on this page',
            value: pickups.filter((p) => p.status === 'delivered').length,
          },
        ]}
      />
      <h2>Your assignments</h2>
      {view.loading && <p role="status">Loading assignments…</p>}
      {view.data && !pickups.length && (
        <EmptyState title="You’re all caught up">
          New assignments will appear here automatically. Availability changes are managed by your
          coordinator.
        </EmptyState>
      )}
      <div className="card-grid">
        {pickups.map((pickup) => {
          const food = pickup.donation;
          const timezone = food.pickup_location.timezone;
          const expired =
            Math.min(
              Date.parse(pickup.end),
              Date.parse(food.pickup_window.end),
              Date.parse(food.safe_use_by),
            ) <= now;
          return (
            <article className="card" key={pickup.id}>
              <div className="card-heading">
                <span className="eyebrow">Pickup {pickup.id.slice(0, 8)}</span>
                <StatusBadge status={pickup.status} />
              </div>
              <h3>{food.food_name}</h3>
              <p>
                {food.quantity_kg} kg · {food.storage} ·{' '}
                {food.packaging_type ?? 'Packaging unspecified'}
              </p>
              <p className="address">
                <strong>Pickup location</strong>
                <br />
                {food.pickup_location.address}
              </p>
              <dl className="detail-grid">
                <div>
                  <dt>Pickup window</dt>
                  <dd>
                    {formatTime(food.pickup_window.start, timezone)} –{' '}
                    {formatTime(food.pickup_window.end, timezone)}
                  </dd>
                </div>
                <div>
                  <dt>Safe use by</dt>
                  <dd>{formatTime(food.safe_use_by, timezone)}</dd>
                </div>
                <div>
                  <dt>Allergens</dt>
                  <dd>{food.allergens.join(', ') || 'None declared'}</dd>
                </div>
                <div>
                  <dt>Time zone</dt>
                  <dd>{timezone}</dd>
                </div>
              </dl>
              <p>
                <strong>Handling notes:</strong> {food.handling_notes || 'No additional notes.'}
              </p>
              {expired && ['assigned', 'accepted'].includes(pickup.status) && (
                <Notice>
                  This assignment’s pickup window has elapsed. Refresh for reassignment or expiry
                  status.
                </Notice>
              )}
              {pickup.status === 'assigned' && (
                <div className="actions">
                  <button
                    disabled={action.busy || expired}
                    onClick={() => void act(pickup, 'accept')}
                  >
                    Accept assignment
                  </button>
                  <ConfirmAction
                    label="Decline assignment"
                    danger
                    disabled={action.busy || expired}
                    onConfirm={() => void act(pickup, 'decline')}
                  >
                    Another driver will be considered while the receiver’s reservation is retained
                    where feasible.
                  </ConfirmAction>
                </div>
              )}
              {pickup.status === 'accepted' && (
                <>
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      const values = new FormData(event.currentTarget);
                      void act(pickup, 'confirm-pickup', {
                        observed_quantity_kg: Number(values.get('quantity')),
                        handling_confirmed: true,
                      });
                    }}
                  >
                    <label htmlFor={`quantity-${pickup.id}`}>Observed weight (kg)</label>
                    <input
                      id={`quantity-${pickup.id}`}
                      name="quantity"
                      type="number"
                      min="0.001"
                      step="0.001"
                      defaultValue={food.quantity_kg}
                      required
                    />
                    <label className="checkbox">
                      <input type="checkbox" required />I checked storage, allergens and handling
                      instructions.
                    </label>
                    <p className="muted">
                      If the weight differs, contact your coordinator before collection.
                    </p>
                    <button
                      disabled={
                        action.busy || expired || now < Date.parse(food.pickup_window.start)
                      }
                    >
                      Confirm pickup
                    </button>
                  </form>
                  <ConfirmAction
                    label="Decline assignment"
                    danger
                    disabled={action.busy || expired}
                    onConfirm={() => void act(pickup, 'decline')}
                  >
                    Release this assignment for another driver before collecting food.
                  </ConfirmAction>
                </>
              )}
              {pickup.status === 'collected' && (
                <ConfirmAction
                  label="Confirm delivery"
                  disabled={action.busy || now >= Date.parse(food.safe_use_by)}
                  onConfirm={() =>
                    void act(pickup, 'confirm-delivery', { delivery_confirmed: true })
                  }
                >
                  Confirm the full donation has reached the receiver and the handoff is complete.
                </ConfirmAction>
              )}
              {pickup.status === 'collected' && now >= Date.parse(food.safe_use_by) && (
                <Notice error>
                  The safe-use deadline has passed. Contact your coordinator for a handling
                  exception.
                </Notice>
              )}
              {pickup.destination && (
                <p className="address">
                  <strong>Deliver to {pickup.recipient_name}</strong>
                  <br />
                  {pickup.destination.address}
                  <br />
                  <a
                    href={
                      'https://www.openstreetmap.org/?mlat=' +
                      pickup.destination.latitude +
                      '&mlon=' +
                      pickup.destination.longitude +
                      '#map=16/' +
                      pickup.destination.latitude +
                      '/' +
                      pickup.destination.longitude
                    }
                    target="_blank"
                    rel="noreferrer"
                  >
                    View delivery location on map
                  </a>
                </p>
              )}
              <button className="text-button" onClick={() => setHistory(food.id)}>
                View donation history
              </button>
            </article>
          );
        })}
      </div>
      {(cursor === undefined ? view.data?.next_cursor : cursor) && (
        <button
          disabled={paging}
          onClick={async () => {
            setPaging(true);
            const requestedSnapshot = view.data;
            try {
              const page = await getPickups(cursor === undefined ? view.data?.next_cursor : cursor);
              if (latestSnapshot.current !== requestedSnapshot) return;
              setExtra((old) => [...old, ...page.items]);
              setCursor(page.next_cursor ?? null);
            } catch (e) {
              view.setError((e as Error).message);
            } finally {
              setPaging(false);
            }
          }}
        >
          Load older assignments
        </button>
      )}
      {history && (
        <DonationTimeline
          role="driver"
          id={history}
          version={view.snapshotVersion}
          onClose={() => setHistory(undefined)}
        />
      )}
    </section>
  );
}

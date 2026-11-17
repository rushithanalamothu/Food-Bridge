import { useEffect, useState } from 'react';
import { getOffers, reserve, declineOffer, releaseReservation } from '../../api/workflow';
import type { ReservationRead } from '../../api/generated/workflow';
import { useWorkspace, useCommand } from '../../hooks/useWorkspace';
import {
  WorkspaceHeader,
  Notice,
  EmptyState,
  Stats,
  StatusBadge,
  formatTime,
  useNow,
  ConfirmAction,
} from '../../components/Workspace';

export function RecipientPage() {
  const view = useWorkspace('recipient', getOffers);
  const action = useCommand();
  const now = useNow();
  const [reservations, setReservations] = useState<Record<string, ReservationRead>>({});
  const [more, setMore] = useState<NonNullable<typeof view.data>['items']>([]);
  const [cursor, setCursor] = useState<string | null | undefined>();
  const [paging, setPaging] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    setMore([]);
    setCursor(undefined);
  }, [view.data]);
  const offers = [
    ...(view.data?.items ?? []),
    ...more.filter(
      (item) =>
        !view.data?.items.some((first) => first.recommendation.id === item.recommendation.id),
    ),
  ];
  async function act(id: string, version: number, verb: 'accept' | 'decline' | 'release') {
    setMessage('');
    view.setError('');
    try {
      if (verb === 'accept') {
        const receipt = await action.run(`${id}:${version}:accept`, (key) =>
          reserve({ match_id: id, expected_donation_version: version }, key),
        );
        setReservations((old) => ({ ...old, [id]: receipt }));
        setMessage('Reservation confirmed. Driver coordination is underway.');
      } else if (verb === 'decline') {
        await action.run(`${id}:${version}:decline`, (key) => declineOffer(id, version, key));
        setMessage('Offer declined. The donation can be offered to another receiver.');
      } else {
        const receipt = await action.run(`${id}:${version}:release`, (key) =>
          releaseReservation(reservations[id].id, version, key),
        );
        setReservations((old) => ({ ...old, [id]: receipt }));
        setMessage('Reservation released.');
      }
      setMore([]);
      setCursor(undefined);
      await view.refresh();
    } catch (e) {
      await view.refresh();
      view.setError(e instanceof Error ? e.message : 'Action failed. Refresh and retry.');
    }
  }
  return (
    <section>
      <WorkspaceHeader
        eyebrow="Receiver workspace"
        title="Good food. Ready to receive."
        {...view}
        refresh={() => {
          setMore([]);
          setCursor(undefined);
          void view.refresh();
        }}
      >
        <p>Review eligible offers and coordinate your next delivery.</p>
      </WorkspaceHeader>
      {view.error && <Notice error>{view.error}</Notice>}
      {message && <Notice>{message}</Notice>}
      <Stats
        items={[
          {
            label: 'Open offers on this page',
            value: offers.filter(
              (o) => o.status === 'offered' && Date.parse(o.recommendation.offer_expires_at) > now,
            ).length,
          },
          {
            label: 'Accepted on this page',
            value: offers.filter((o) => o.status === 'accepted').length,
          },
          { label: 'Decisions', value: 'Server verified' },
        ]}
      />
      <div className="section-heading">
        <h2>Your offers</h2>
        <span className="muted">All times in your browser timezone</span>
      </div>
      {view.loading && <p role="status">Loading your offers…</p>}
      {!view.loading && view.data && !offers.length && (
        <EmptyState title="No offers just yet">
          Eligible food offers will appear here. Keep this workspace open for live updates.
        </EmptyState>
      )}
      <div className="card-grid">
        {offers.map((offer) => {
          const match = offer.recommendation;
          const expired = Date.parse(match.offer_expires_at) <= now;
          const receipt = reservations[match.id];
          const latest = view.events.find(
            (event) =>
              event.aggregate_id === match.donation_id && typeof event.payload.status === 'string',
          );
          const canRelease =
            !latest || ['reserved', 'pickup_assigned'].includes(String(latest.payload.status));
          return (
            <article className="card" key={match.id}>
              <div className="card-heading">
                <span className="eyebrow">Round {match.matching_round}</span>
                <StatusBadge
                  status={offer.status === 'offered' && expired ? 'expired' : offer.status}
                />
              </div>
              <h3>Donation {match.donation_id.slice(0, 8)}</h3>
              <p>{match.explanation}</p>
              <dl className="detail-grid">
                <div>
                  <dt>Route distance</dt>
                  <dd>{(match.distance_m / 1000).toFixed(1)} km</dd>
                </div>
                <div>
                  <dt>Travel estimate</dt>
                  <dd>{Math.ceil(match.travel_time_s / 60)} min</dd>
                </div>
                <div>
                  <dt>Accept before</dt>
                  <dd>{formatTime(match.offer_expires_at)}</dd>
                </div>
                <div>
                  <dt>Ranking</dt>
                  <dd>
                    {match.algorithm === 'distance_only' ? 'Distance based' : 'Multiple criteria'}
                  </dd>
                </div>
              </dl>
              {offer.status === 'offered' && !expired && (
                <div className="actions">
                  <ConfirmAction
                    label="Accept offer"
                    disabled={action.busy}
                    onConfirm={() => void act(match.id, match.donation_version, 'accept')}
                  >
                    Accept the full donation? Available capacity and eligibility will be checked
                    again.
                  </ConfirmAction>
                  <ConfirmAction
                    label="Decline offer"
                    disabled={action.busy}
                    danger
                    onConfirm={() => void act(match.id, offer.version, 'decline')}
                  >
                    Declining allows another receiver to be considered.
                  </ConfirmAction>
                </div>
              )}
              {receipt && receipt.status === 'active' && canRelease && (
                <div className="receipt">
                  <p>
                    <strong>{receipt.quantity_kg} kg reserved</strong> · {receipt.storage}
                  </p>
                  <ConfirmAction
                    label="Release reservation"
                    danger
                    disabled={action.busy}
                    onConfirm={() => void act(match.id, receipt.version, 'release')}
                  >
                    Release this hold and return its capacity? This is only allowed before pickup.
                  </ConfirmAction>
                </div>
              )}
              {offer.status === 'accepted' && (!receipt || !canRelease) && (
                <p className="muted">
                  Offer accepted. Reservation details from previous sessions are not yet exposed by
                  the service; contact your coordinator for changes.
                </p>
              )}
            </article>
          );
        })}
      </div>
      {(cursor === undefined ? view.data?.next_cursor : cursor) && (
        <button
          disabled={paging}
          className="quiet-button"
          onClick={async () => {
            setPaging(true);
            try {
              const page = await getOffers(cursor === undefined ? view.data?.next_cursor : cursor);
              setMore((old) => [...old, ...page.items]);
              setCursor(page.next_cursor ?? null);
            } catch (e) {
              view.setError((e as Error).message);
            } finally {
              setPaging(false);
            }
          }}
        >
          Load older offers
        </button>
      )}
      <aside className="notice">
        <h2>Receiving preferences</h2>
        <p>
          Capacity, dietary requirements and receiving hours are checked by the service. Profile
          viewing and editing will become available when the receiving-profile API is connected.
          Contact your organization coordinator to update these details.
        </p>
      </aside>
    </section>
  );
}

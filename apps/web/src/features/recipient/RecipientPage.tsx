import { Button } from '../../components/Button';
import { useEffect, useRef, useState } from 'react';
import { IntakeApiError } from '../../api/intake';
import {
  getOffers,
  getReservations,
  getReceivingProfile,
  reserve,
  declineOffer,
  releaseReservation,
} from '../../api/workflow';
import type { OfferRead, ReservationDetail } from '../../api/generated/workflow';
import { useWorkspace, useCommand } from '../../hooks/useWorkspace';
import {
  WorkspaceHeader,
  ActionError,
  Notice,
  EmptyState,
  Stats,
  StatusBadge,
  formatTime,
  useNow,
  ConfirmAction,
} from '../../components/Workspace';
import { DonationTimeline } from '../../components/DonationTimeline';
import { ReceivingProfile } from './ReceivingProfile';
const load = async () => {
  const [offers, reservations, profile] = await Promise.all([
    getOffers(),
    getReservations(),
    getReceivingProfile(),
  ]);
  return { offers, reservations, profile };
};
export function RecipientPage() {
  const view = useWorkspace('recipient', load);
  const latestSnapshot = useRef(view.data);
  latestSnapshot.current = view.data;
  const action = useCommand();
  const now = useNow();
  const [extra, setExtra] = useState<OfferRead[]>([]);
  const [holds, setHolds] = useState<ReservationDetail[]>([]);
  const [cursor, setCursor] = useState<string | null | undefined>();
  const [holdCursor, setHoldCursor] = useState<string | null | undefined>();
  const [paging, setPaging] = useState(false);
  const [message, setMessage] = useState('');
  const [history, setHistory] = useState<string>();
  const [invalidOffers, setInvalidOffers] = useState<Set<string>>(() => new Set());
  const previousProfile = useRef<{ version: number; offerIds: string[] } | undefined>(undefined);
  useEffect(() => {
    setExtra([]);
    setHolds([]);
    setCursor(undefined);
    setHoldCursor(undefined);
  }, [view.data]);
  const offers = [
    ...(view.data?.offers.items ?? []),
    ...extra.filter(
      (item) =>
        !view.data?.offers.items.some(
          (first) => first.recommendation.id === item.recommendation.id,
        ),
    ),
  ];
  // Older gateways lack server-side validity. Keep the legacy observation guard
  // only for those offers; independently loaded profile/offer snapshots may differ
  // briefly, so an explicit server flag must not poison a fresh replacement ID.
  useEffect(() => {
    if (!view.data) return;
    const version = view.data.profile.profile.version;
    const previous = previousProfile.current;
    if (previous && previous.version !== version) {
      setInvalidOffers((old) => new Set([...old, ...previous.offerIds]));
    }
    previousProfile.current = {
      version,
      offerIds: offers
        .filter((offer) => offer.status === 'offered' && offer.requires_revalidation === undefined)
        .map((offer) => offer.recommendation.id),
    };
  }, [view.data, extra]);

  function invalidateCurrentOffers() {
    setInvalidOffers(
      (old) =>
        new Set([
          ...old,
          ...offers
            .filter((offer) => offer.status === 'offered')
            .map((offer) => offer.recommendation.id),
        ]),
    );
  }

  const reservations = [
    ...(view.data?.reservations.items ?? []),
    ...holds.filter(
      (item) =>
        !view.data?.reservations.items.some(
          (first) => first.reservation.id === item.reservation.id,
        ),
    ),
  ];
  async function act(id: string, version: number, verb: 'accept' | 'decline' | 'release') {
    setMessage('');
    view.setError('');
    try {
      await action.run<unknown>(`${id}:${version}:${verb}`, (key) =>
        verb === 'accept'
          ? reserve({ match_id: id, expected_donation_version: version }, key)
          : verb === 'decline'
            ? declineOffer(id, version, key)
            : releaseReservation(id, version, key),
      );
      setMessage(
        verb === 'accept'
          ? 'Reservation confirmed. Driver coordination is underway.'
          : verb === 'decline'
            ? 'Offer declined.'
            : 'Reservation released.',
      );
      await view.refresh();
    } catch (e) {
      if (
        verb === 'accept' &&
        e instanceof IntakeApiError &&
        e.code === 'recipient_profile_changed'
      ) {
        setInvalidOffers((old) => new Set([...old, id]));
        await view.refresh();
        view.setError(
          'Receiving preferences changed. This offer needs revalidation before it can be accepted. Refresh for updated offers or contact your coordinator.',
        );
      } else {
        await view.refresh();
        view.setError((e as Error).message);
      }
    }
  }
  return (
    <section>
      <WorkspaceHeader eyebrow="Receiver workspace" title="Good food. Ready to receive." {...view}>
        <p>Review eligible offers, manage receiving preferences, and follow each delivery.</p>
      </WorkspaceHeader>
      {action.busy && (
        <p className="pending-feedback" role="status">
          <span className="button-spinner" aria-hidden="true" />
          Saving your request…
        </p>
      )}
      {view.error && <ActionError message={view.error} dismiss={() => view.setError('')} />}
      {message && <Notice tone="success">{message}</Notice>}
      <Stats
        items={[
          {
            label: 'Open offers on this page',
            value: offers.filter(
              (o) =>
                o.status === 'offered' &&
                !o.requires_revalidation &&
                !invalidOffers.has(o.recommendation.id) &&
                Date.parse(o.recommendation.offer_expires_at) > now,
            ).length,
          },
          {
            label: 'Active holds on this page',
            value: reservations.filter((r) => r.reservation.status === 'active').length,
          },
          {
            label: 'Receiving capacity',
            value: view.data
              ? Object.values(view.data.profile.profile.available_capacity_kg_by_storage).reduce(
                  (a, b) => a + (b ?? 0),
                  0,
                ) + ' kg'
              : '—',
          },
        ]}
      />
      {view.data && (
        <ReceivingProfile
          value={view.data.profile}
          refresh={view.refresh}
          onSaved={invalidateCurrentOffers}
        />
      )}
      <div className="section-heading">
        <h2>Your latest offers</h2>
        <span className="muted">Newest first · receiving-location times</span>
      </div>
      {view.loading && <p role="status">Loading your offers…</p>}
      {view.data && !offers.length && (
        <EmptyState title="No offers just yet">
          Eligible food offers will appear here automatically.
        </EmptyState>
      )}
      <div className="card-grid">
        {offers.map((offer) => {
          const match = offer.recommendation;
          const food = offer.donation;
          const expired = Date.parse(match.offer_expires_at) <= now;
          const needsRevalidation = offer.requires_revalidation || invalidOffers.has(match.id);
          const zone = view.data?.profile.profile.location.timezone;
          return (
            <article className="card" key={match.id}>
              <div className="card-heading">
                <span className="eyebrow">Round {match.matching_round}</span>
                <StatusBadge
                  status={offer.status === 'offered' && expired ? 'expired' : offer.status}
                />
              </div>
              <h3>{food?.food_name ?? `Donation ${match.donation_id.slice(0, 8)}`}</h3>
              {food && (
                <>
                  <p>
                    {food.quantity_kg} kg · {food.portions ?? 'Unspecified'} portions ·{' '}
                    {food.storage}
                  </p>
                  <p>
                    <strong>Allergens:</strong> {food.allergens.join(', ') || 'None declared'}
                  </p>
                  <p>
                    <strong>Diet:</strong> {food.dietary_tags?.join(', ') || 'Not specified'}
                  </p>
                  <p>
                    <strong>Handling:</strong> {food.handling_notes || 'No additional notes'}
                  </p>
                  <StatusBadge status={food.status} />
                </>
              )}
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
                  <dd>{formatTime(match.offer_expires_at, zone)}</dd>
                </div>
                {food && (
                  <div>
                    <dt>Safe use by</dt>
                    <dd>{formatTime(food.safe_use_by, zone)}</dd>
                  </div>
                )}
              </dl>
              {offer.status === 'offered' && !expired && needsRevalidation && (
                <Notice>
                  Receiving preferences changed. This offer needs revalidation before it can be
                  accepted. Refresh for updated offers or contact your coordinator if it remains
                  here.
                </Notice>
              )}
              {offer.status === 'offered' && !expired && (
                <div className="actions">
                  <ConfirmAction
                    label="Accept offer"
                    disabled={action.busy || needsRevalidation}
                    onConfirm={() =>
                      void act(match.id, food?.version ?? match.donation_version, 'accept')
                    }
                  >
                    Accept the full donation? Capacity and eligibility will be checked again.
                  </ConfirmAction>
                  <ConfirmAction
                    label="Decline offer"
                    danger
                    disabled={action.busy}
                    onConfirm={() => void act(match.id, offer.version, 'decline')}
                  >
                    Declining allows another receiver to be considered.
                  </ConfirmAction>
                </div>
              )}
              <Button variant="ghost" onClick={() => setHistory(match.donation_id)}>
                View donation history
              </Button>
            </article>
          );
        })}
      </div>
      {(cursor === undefined ? view.data?.offers.next_cursor : cursor) && (
        <Button
          variant="secondary"
          busy={paging}
          onClick={async () => {
            setPaging(true);
            view.setError('');
            const requestedSnapshot = view.data;
            try {
              const page = await getOffers(
                cursor === undefined ? view.data?.offers.next_cursor : cursor,
              );
              if (latestSnapshot.current !== requestedSnapshot) return;
              setExtra((old) => [...old, ...page.items]);
              setCursor(page.next_cursor ?? null);
            } catch (e) {
              if (latestSnapshot.current === requestedSnapshot) view.setError((e as Error).message);
            } finally {
              setPaging(false);
            }
          }}
        >
          Load older offers
        </Button>
      )}
      <h2>Your reservations</h2>
      {view.data && !reservations.length && (
        <p className="muted">
          Accepted donations will appear here and remain available after a reload.
        </p>
      )}
      <div className="card-grid">
        {reservations.map(({ reservation: hold, donation }) => (
          <article className="card" key={hold.id}>
            <StatusBadge status={donation.status} />
            <h3>{donation.food_name}</h3>
            <p>
              <strong>{hold.quantity_kg} kg reserved</strong> · {hold.storage}
            </p>
            <p>Hold: {hold.status}</p>
            <Button variant="ghost" onClick={() => setHistory(donation.id)}>
              View donation history
            </Button>
            {hold.status === 'active' &&
              ['reserved', 'pickup_assigned'].includes(donation.status) && (
                <ConfirmAction
                  label="Release reservation"
                  danger
                  disabled={action.busy}
                  onConfirm={() => void act(hold.id, hold.version, 'release')}
                >
                  Release this hold and return its capacity before pickup?
                </ConfirmAction>
              )}
          </article>
        ))}
      </div>
      {(holdCursor === undefined ? view.data?.reservations.next_cursor : holdCursor) && (
        <Button
          variant="secondary"
          busy={paging}
          onClick={async () => {
            setPaging(true);
            view.setError('');
            const requestedSnapshot = view.data;
            try {
              const page = await getReservations(
                holdCursor === undefined ? view.data?.reservations.next_cursor : holdCursor,
              );
              if (latestSnapshot.current !== requestedSnapshot) return;
              setHolds((old) => [...old, ...page.items]);
              setHoldCursor(page.next_cursor ?? null);
            } catch (e) {
              if (latestSnapshot.current === requestedSnapshot) view.setError((e as Error).message);
            } finally {
              setPaging(false);
            }
          }}
        >
          Load older reservations
        </Button>
      )}
      {history && (
        <DonationTimeline
          role="recipient"
          id={history}
          version={view.snapshotVersion}
          onClose={() => setHistory(undefined)}
        />
      )}
    </section>
  );
}

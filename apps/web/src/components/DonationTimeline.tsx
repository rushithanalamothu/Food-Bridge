import { useEffect, useState } from 'react';
import type { DonationDetail, Role } from '../api/generated/workflow';
import { getDonationDetail } from '../api/workflow';
import { formatTime, humanize, Notice, StatusBadge } from './Workspace';

type TimelineProps = {
  role: Role;
  id: string;
  version?: number;
  onClose: () => void;
};

export function DonationTimeline(props: TimelineProps) {
  // A different resource must never inherit the previous resource's data or error.
  return <TimelineContent key={`${props.role}:${props.id}`} {...props} />;
}

function TimelineContent({ role, id, version, onClose }: TimelineProps) {
  const [detail, setDetail] = useState<DonationDetail>();
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setError('');
    setDetail(undefined);
    void getDonationDetail(role, id)
      .then((next) => {
        if (active) setDetail(next);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [role, id, version]);
  return (
    <section className="card" aria-label="Donation history">
      <div className="section-heading">
        <h2>{detail?.donation.food_name ?? 'Donation history'}</h2>
        <button className="quiet-button" onClick={onClose}>
          Close history
        </button>
      </div>
      {error && <Notice error>{error}</Notice>}
      {!detail && !error && <p role="status">Loading history…</p>}
      {detail && (
        <>
          <StatusBadge status={detail.donation.status} />
          <p>
            {detail.donation.quantity_kg} kg · {detail.donation.storage} ·{' '}
            {detail.donation.allergens.join(', ') || 'No allergens declared'}
          </p>
          <ol className="activity-list">
            {detail.history.map((item) => (
              <li key={item.aggregate_version}>
                <div>
                  <strong>{humanize(item.next_status)}</strong>
                  <p>{humanize(item.reason)}</p>
                </div>
                <time dateTime={item.occurred_at}>
                  {formatTime(item.occurred_at, detail.donation.pickup_location.timezone)}
                </time>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

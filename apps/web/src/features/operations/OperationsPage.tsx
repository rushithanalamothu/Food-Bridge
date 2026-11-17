import { useEffect, useState } from 'react';
import { getSummary, getFailures, getDecisions, replayFailure } from '../../api/workflow';
import type { OrchestrationAudit, FailureRead } from '../../api/generated/workflow';
import { useWorkspace, useCommand } from '../../hooks/useWorkspace';
import {
  WorkspaceHeader,
  Notice,
  Stats,
  EmptyState,
  StatusBadge,
  humanize,
  formatTime,
  ConfirmAction,
} from '../../components/Workspace';
const load = async () => {
  const [summary, failures] = await Promise.all([getSummary(), getFailures()]);
  return { summary, failures };
};
export function OperationsPage() {
  const view = useWorkspace('operator', load);
  const action = useCommand();
  const [audit, setAudit] = useState<OrchestrationAudit[]>();
  const [auditId, setAuditId] = useState('');
  const [reviewing, setReviewing] = useState(false);
  const [message, setMessage] = useState('');
  const [extra, setExtra] = useState<FailureRead[]>([]);
  const [cursor, setCursor] = useState<string | null | undefined>();
  const [paging, setPaging] = useState(false);
  useEffect(() => {
    setExtra([]);
    setCursor(undefined);
  }, [view.data]);
  const summary = view.data?.summary;
  const failures = [
    ...(view.data?.failures.items ?? []),
    ...extra.filter((item) => !view.data?.failures.items.some((first) => first.id === item.id)),
  ];
  async function review(id: string) {
    setReviewing(true);
    setAudit(undefined);
    setAuditId(id);
    try {
      setAudit(await getDecisions(id));
    } catch (e) {
      view.setError((e as Error).message);
    } finally {
      setReviewing(false);
    }
  }
  const version = Math.max(
    0,
    ...(audit ?? []).flatMap((step) =>
      step.decisions.map((decision) => decision.observation.donation_version),
    ),
  );
  return (
    <section>
      <WorkspaceHeader
        eyebrow="Operations workspace"
        title="The whole picture. Every handoff."
        {...view}
      >
        <p>Monitor your organization’s donations and recover work that needs attention.</p>
      </WorkspaceHeader>
      {view.error && <Notice error>{view.error}</Notice>}
      {message && <Notice>{message}</Notice>}
      {summary?.synthetic && (
        <Notice>
          Synthetic demonstration data · these figures do not represent real food rescued.
        </Notice>
      )}
      {view.loading && <p role="status">Loading operations…</p>}
      <Stats
        items={[
          {
            label: 'Donations recorded',
            value: summary
              ? Object.values(summary.counts_by_status).reduce((a, b) => a + b, 0)
              : '—',
          },
          { label: 'Delivered', value: summary?.delivered_count ?? '—' },
          {
            label: summary?.synthetic ? 'Synthetic delivered weight' : 'Recorded delivered weight',
            value: summary ? summary.delivered_kg + ' kg' : '—',
          },
        ]}
      />
      <div className="section-heading">
        <h2>Donation status</h2>
        <span className="muted">Organization scope</span>
      </div>
      <div className="status-board">
        {summary &&
          Object.entries(summary.counts_by_status).map(([status, count]) => (
            <div className="card" key={status}>
              <StatusBadge status={status} />
              <strong className="board-count">{count}</strong>
            </div>
          ))}
      </div>
      {summary && !Object.keys(summary.counts_by_status).length && (
        <EmptyState title="A clear board">
          Donation activity will appear as your organization starts posting food.
        </EmptyState>
      )}
      <h2>Work needing attention</h2>
      {view.data && !failures.length && <p className="muted">No recorded workflow failures.</p>}
      <div className="card-grid">
        {failures.map((failure) => (
          <article className="card" key={failure.id}>
            <StatusBadge status="failed" />
            <h3>{humanize(failure.code)}</h3>
            <p>
              Donation {failure.donation_id.slice(0, 8)} · {failure.attempts} attempts ·{' '}
              {failure.replay_count} replays
            </p>
            <p className="muted">{formatTime(failure.created_at)}</p>
            <button
              className="quiet-button"
              disabled={reviewing}
              onClick={() => void review(failure.donation_id)}
            >
              Review workflow
            </button>
            {auditId === failure.donation_id && version > 0 && (
              <ConfirmAction
                label="Replay failed work"
                disabled={action.busy}
                onConfirm={() => {
                  void (async () => {
                    try {
                      await action.run(`${failure.id}:${version}:replay`, (key) =>
                        replayFailure(failure.id, version, key),
                      );
                      setMessage(
                        'Replay queued. This does not reopen terminal or expired donations.',
                      );
                      setAudit(undefined);
                      await view.refresh();
                    } catch (e) {
                      await view.refresh();
                      await review(failure.donation_id);
                      view.setError((e as Error).message);
                    }
                  })();
                }}
              >
                Queue another bounded attempt? Current state and deadline will be checked by the
                service.
              </ConfirmAction>
            )}
          </article>
        ))}
      </div>
      {(cursor === undefined ? view.data?.failures.next_cursor : cursor) && (
        <button
          disabled={paging}
          onClick={async () => {
            setPaging(true);
            try {
              const page = await getFailures(
                cursor === undefined ? view.data?.failures.next_cursor : cursor,
              );
              setExtra((old) => [...old, ...page.items]);
              setCursor(page.next_cursor ?? null);
            } catch (e) {
              view.setError((e as Error).message);
            } finally {
              setPaging(false);
            }
          }}
        >
          Load older failures
        </button>
      )}
      {audit && (
        <section className="card">
          <h2>Workflow decisions · {auditId.slice(0, 8)}</h2>
          {!audit.length && <p>No planning decisions recorded for this donation.</p>}
          {audit.map((step) => (
            <div key={step.step_id}>
              <h3>{humanize(step.status)}</h3>
              {step.decisions.map((decision) => (
                <p key={decision.generation}>
                  <time>{formatTime(decision.decided_at)}</time> · {humanize(decision.mode)} ·{' '}
                  {humanize(decision.outcome)}
                  <br />
                  {decision.plan.summary}
                </p>
              ))}
            </div>
          ))}
        </section>
      )}
      <h2>Live activity</h2>
      <p className="muted">
        Events received during this session. Reconnecting also refreshes authoritative summaries.
      </p>
      <ol className="activity-list">
        {view.events.map((event) => (
          <li key={event.event_id}>
            <strong>{humanize(event.event_type.replace('.v1', '').replaceAll('.', ' '))}</strong>
            <span>
              {formatTime(event.occurred_at)} · {event.aggregate_id.slice(0, 8)}
            </span>
          </li>
        ))}
      </ol>
      {!view.events.length && <p className="muted">Waiting for new activity.</p>}
      {summary && (
        <section className="card">
          <h2>Notification delivery</h2>
          {Object.entries(summary.notification_counts_by_status ?? {}).map(([status, count]) => (
            <p key={status}>
              {humanize(status)}: {count}
            </p>
          ))}
          <p className="muted">A sandbox receipt does not indicate an email or SMS was sent.</p>
        </section>
      )}
    </section>
  );
}

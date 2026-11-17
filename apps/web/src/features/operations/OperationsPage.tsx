import { useCallback, useState } from 'react';
import type {
  OperationsDonationPage,
  OperationsSummary,
  FailurePage,
  HistoryPage,
  OrchestrationAudit,
} from '../../api/generated/workflow';
import { workflowGet, workflowPost } from '../../api/workflow';
import { useLiveWorkflow } from '../../api/useLiveWorkflow';
export function OperationsPage() {
  const [cursor, setCursor] = useState('');
  const [failureCursor, setFailureCursor] = useState('');
  const load = useCallback(
    async (signal: AbortSignal) => {
      const [board, summary, failures] = await Promise.all([
        workflowGet<OperationsDonationPage>(
          `/operations/donations?limit=25${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
          'operator',
          signal,
        ),
        workflowGet<OperationsSummary>('/operations/summary', 'operator', signal),
        workflowGet<FailurePage>(
          `/operations/failures?limit=25${failureCursor ? `&cursor=${encodeURIComponent(failureCursor)}` : ''}`,
          'operator',
          signal,
        ),
      ]);
      return { board, summary, failures };
    },
    [cursor, failureCursor],
  );
  const { data, error, connection, refresh } = useLiveWorkflow('operator', load);
  const [details, setDetails] = useState<{
    id: string;
    history: HistoryPage;
    audits: OrchestrationAudit[];
  }>();
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  async function inspect(id: string, after = 0) {
    setMessage('');
    try {
      const [history, audits] = await Promise.all([
        workflowGet<HistoryPage>(
          `/operations/donations/${id}/history?after_version=${after}`,
          'operator',
        ),
        workflowGet<OrchestrationAudit[]>(
          `/operations/orchestrator/decisions?donation_id=${id}`,
          'operator',
        ),
      ]);
      setDetails({ id, history, audits });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Could not load history.');
    }
  }
  async function replay(id: string, donationId: string) {
    setBusy(true);
    setMessage('');
    try {
      const donation = await workflowGet<{ version: number }>(
        `/operations/donations/${donationId}`,
        'operator',
      );
      await workflowPost(`/operations/failures/${id}/replay`, 'operator', {
        expected_version: donation.version,
      });
      setMessage('Replay queued. The workflow will recheck versions and deadlines.');
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Replay failed.');
    } finally {
      setBusy(false);
      refresh();
    }
  }
  return (
    <section>
      <p className="eyebrow">Operations workspace</p>
      <h1>Today’s operations</h1>
      <p role="status">{connection}</p>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      <button onClick={refresh}>Refresh board</button>
      {data && (
        <>
          <p>
            {data.summary.synthetic
              ? 'Synthetic demonstration results'
              : 'Recorded delivery results'}{' '}
            · {data.summary.delivered_count} delivered · {data.summary.delivered_kg.toFixed(1)} kg
          </p>
          <p>
            {Object.entries(data.summary.counts_by_status)
              .map(([status, count]) => `${status}: ${count}`)
              .join(' · ')}
          </p>
          <h2>Donations</h2>
          {data.board.items.length === 0 && <p>No donations for this organization.</p>}
          <div className="workflow-table">
            <table>
              <thead>
                <tr>
                  <th>Food</th>
                  <th>Status</th>
                  <th>Safe use by</th>
                  <th>History</th>
                </tr>
              </thead>
              <tbody>
                {data.board.items.map((d) => (
                  <tr key={d.id}>
                    <td>
                      {d.food_name} · {d.quantity_kg} kg
                    </td>
                    <td>
                      {d.status} · v{d.version}
                    </td>
                    <td>{new Date(d.safe_use_by).toLocaleString()}</td>
                    <td>
                      <button onClick={() => void inspect(d.id)}>View history</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {cursor && <button onClick={() => setCursor('')}>First page</button>}
          {data.board.next_cursor && (
            <button onClick={() => setCursor(data.board.next_cursor!)}>Next donations</button>
          )}
          <h2>Failure queue</h2>
          {data.failures.items.length === 0 && <p>No persisted workflow failures.</p>}
          {data.failures.items.map((f) => (
            <article className="workflow-card" key={f.id}>
              <p>
                {f.code} · attempts {f.attempts} · replays {f.replay_count}
              </p>
              <button disabled={busy} onClick={() => void replay(f.id, f.donation_id)}>
                Replay with current version
              </button>
            </article>
          ))}
          {failureCursor && (
            <button onClick={() => setFailureCursor('')}>First failures page</button>
          )}
          {data.failures.next_cursor && (
            <button onClick={() => setFailureCursor(data.failures.next_cursor!)}>
              Next failures
            </button>
          )}
        </>
      )}
      {details && (
        <section aria-label="Donation history">
          <h2>Donation history</h2>
          <p>{details.id}</p>
          <ol>
            {details.history.items.map((h) => (
              <li key={h.version}>
                v{h.version}: {h.status} · {h.reason} · {new Date(h.occurred_at).toLocaleString()}
              </li>
            ))}
          </ol>
          {details.history.next_version && (
            <button onClick={() => void inspect(details.id, details.history.next_version!)}>
              Next history entries
            </button>
          )}
          <h3>Orchestrator decisions</h3>
          {details.audits
            .flatMap((a) => a.decisions)
            .map((d, i) => (
              <p key={i}>
                {d.mode} · {d.plan.tool} · {d.outcome} · {d.model ?? 'no model'}
              </p>
            ))}
        </section>
      )}
    </section>
  );
}

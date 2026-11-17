import { useEffect, useState, type ReactNode } from 'react';
import type { Connection } from '../api/stream';

export const humanize = (value: string) =>
  value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
export function formatTime(value: string, timezone?: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: timezone,
  }).format(new Date(value));
}
export function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge status-${status}`}>{humanize(status)}</span>;
}
export function WorkspaceHeader({
  eyebrow,
  title,
  children,
  connection,
  refresh,
  loading,
  updated,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  connection: Connection;
  refresh: () => unknown;
  loading?: boolean;
  updated?: Date;
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          {children}
        </div>
        <button className="quiet-button" onClick={() => void refresh()} disabled={loading}>
          Refresh
        </button>
      </div>
      <div className="sync-bar" role="status">
        <span className={`connection-dot ${connection}`} />
        {connection === 'live'
          ? 'Live updates connected'
          : connection === 'signed_out'
            ? 'Session unavailable · sign in or reconnect'
            : humanize(connection) + ' · showing last received data'}
        {updated && <span className="muted">Updated {updated.toLocaleTimeString()}</span>}
      </div>
    </>
  );
}
export function Notice({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return (
    <div className={error ? 'notice error' : 'notice'} role={error ? 'alert' : 'status'}>
      {children}
    </div>
  );
}
export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="empty-state">
      <span className="empty-symbol" aria-hidden="true">
        ↗
      </span>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}
export function Stats({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <div className="stats-grid">
      {items.map((item) => (
        <div className="stat" key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  );
}
export function useNow() {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return now;
}
export function ConfirmAction({
  label,
  children,
  disabled,
  onConfirm,
  danger = false,
}: {
  label: string;
  children: ReactNode;
  disabled?: boolean;
  onConfirm: () => void;
  danger?: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  return confirming ? (
    <div className="confirm-action">
      <p>{children}</p>
      <div className="actions">
        <button
          disabled={disabled}
          className={danger ? 'danger' : ''}
          onClick={() => {
            setConfirming(false);
            onConfirm();
          }}
        >
          {label.toLowerCase().startsWith('confirm ') ? label : 'Confirm ' + label.toLowerCase()}
        </button>
        <button className="quiet-button" disabled={disabled} onClick={() => setConfirming(false)}>
          Keep current state
        </button>
      </div>
    </div>
  ) : (
    <button
      disabled={disabled}
      className={danger ? 'quiet-button danger' : ''}
      onClick={() => setConfirming(true)}
    >
      {label}
    </button>
  );
}

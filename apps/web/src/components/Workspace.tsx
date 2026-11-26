import { Button } from './Button';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
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
  loadError,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  connection: Connection;
  refresh: () => unknown;
  loading?: boolean;
  updated?: Date;
  loadError?: string;
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          {children}
        </div>
        <Button variant="secondary" onClick={() => void refresh()} busy={loading}>
          Refresh
        </Button>
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
      {loadError && <Notice error>{loadError}</Notice>}
    </>
  );
}
export function Notice({
  children,
  error = false,
  tone = 'info',
}: {
  children: ReactNode;
  error?: boolean;
  tone?: 'info' | 'success' | 'warning';
}) {
  return (
    <div
      className={error ? 'notice error' : `notice notice--${tone}`}
      role={error ? 'alert' : 'status'}
    >
      {children}
    </div>
  );
}
export function ActionError({ message, dismiss }: { message: string; dismiss: () => void }) {
  return (
    <Notice error>
      {message}{' '}
      <Button variant="ghost" onClick={dismiss}>
        Dismiss action error
      </Button>
    </Notice>
  );
}
export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="empty-state">
      <span className="empty-symbol" aria-hidden="true">
        <svg
          width="32"
          height="32"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="m8 12 3 3 5-6" />
        </svg>
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
  const trigger = useRef<HTMLButtonElement>(null);
  const confirm = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const description = useId();
  useEffect(() => {
    if (confirming) confirm.current?.focus();
    else if (restoreFocus.current) {
      trigger.current?.focus();
      restoreFocus.current = false;
    }
  }, [confirming]);
  function cancel() {
    restoreFocus.current = true;
    setConfirming(false);
  }
  return confirming ? (
    <div
      className="confirm-action"
      role="group"
      aria-label={`Confirm ${label.toLowerCase()}`}
      aria-describedby={description}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.stopPropagation();
          cancel();
        }
      }}
    >
      <p className="confirmation-title">{label}?</p>
      <p id={description}>{children}</p>
      <div className="actions">
        <Button
          ref={confirm}
          disabled={disabled}
          tone={danger ? 'danger' : 'default'}
          onClick={() => {
            setConfirming(false);
            onConfirm();
          }}
        >
          {label.toLowerCase().startsWith('confirm ') ? label : 'Confirm ' + label.toLowerCase()}
        </Button>
        <Button variant="secondary" disabled={disabled} onClick={cancel}>
          Go back
        </Button>
      </div>
    </div>
  ) : (
    <Button
      ref={trigger}
      disabled={disabled}
      variant={danger ? 'secondary' : 'primary'}
      tone={danger ? 'danger' : 'default'}
      onClick={() => setConfirming(true)}
    >
      {label}
    </Button>
  );
}

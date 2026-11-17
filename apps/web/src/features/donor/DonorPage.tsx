import { DonationTimeline } from '../../components/DonationTimeline';
import { useWorkspace, useCommand } from '../../hooks/useWorkspace';
import {
  WorkspaceHeader,
  StatusBadge,
  Stats,
  formatTime,
  ConfirmAction,
  humanize,
} from '../../components/Workspace';
import { cancelDonation } from '../../api/workflow';
import { getDraft } from '../../api/intake';
import { locationInput, locationInstant, parseAllergens } from '../../api/time';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type {
  DonationInput,
  DraftRead,
  DonorIdentity,
  IntakeDonationRead,
  EvaluationRead,
  IntakePolicy,
} from '../../api/generated/intake';
import {
  createDraft,
  demoEligibility,
  getDonorIdentity,
  getIntakePolicy,
  getDonation,
  getEvaluation,
  IntakeApiError,
  listDonations,
  submitDonation,
} from '../../api/intake';
import './donor.css';

function errorText(error: unknown) {
  return error instanceof IntakeApiError
    ? `${error.message} ${Object.values(error.details).join(' ')}`
    : 'Could not reach the API. Your details are still here; please retry.';
}

export function DonorPage() {
  const dashboard = useWorkspace('donor', listDonations);
  const latestSnapshot = useRef(dashboard.data);
  latestSnapshot.current = dashboard.data;
  const cancellation = useCommand();
  const [nextCursor, setNextCursor] = useState<string | null>();
  const [paging, setPaging] = useState(false);
  const [notice, setNotice] = useState('');
  const [history, setHistory] = useState<string>();
  const [identity, setIdentity] = useState<DonorIdentity>();
  const [setupAttempt, setSetupAttempt] = useState(0);
  const [setupLoading, setSetupLoading] = useState(true);
  const [setupError, setSetupError] = useState('');
  const [recoveryAttempt, setRecoveryAttempt] = useState(0);
  const [recovering, setRecovering] = useState(false);
  const [recoveryError, setRecoveryError] = useState('');
  const [draft, setDraft] = useState<DraftRead>();
  const [posted, setPosted] = useState<IntakeDonationRead>();
  const [recent, setRecent] = useState<IntakeDonationRead[]>([]);
  const [policy, setPolicy] = useState<IntakePolicy>();
  const [description, setDescription] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [evaluation, setEvaluation] = useState<EvaluationRead>();
  const [polling, setPolling] = useState(false);
  const [pollRun, setPollRun] = useState(0);
  const draftKey = useRef(crypto.randomUUID());
  const submitKey = useRef(crypto.randomUUID());
  const evaluationKey = useRef(crypto.randomUUID());
  const formRef = useRef<HTMLFormElement>(null);
  const mounted = useRef(true);
  const selection = useRef({ id: undefined as string | undefined });
  const detailRequest = useRef(0);
  const recoveryRequest = useRef(0);

  function stopDraftRecovery() {
    recoveryRequest.current++;
    setRecovering(false);
    setRecoveryError('');
  }

  function selectDonation(value: IntakeDonationRead) {
    stopDraftRecovery();
    selection.current = { id: value.donation.id };
    detailRequest.current++;
    setHistory(undefined);
    setPosted(value);
  }

  async function refreshSelectedDonation() {
    const selected = selection.current;
    if (!selected.id) return;
    const request = ++detailRequest.current;
    try {
      const value = await getDonation(selected.id);
      if (mounted.current && selected === selection.current && request === detailRequest.current)
        setPosted(value);
    } catch (err) {
      if (mounted.current && selected === selection.current && request === detailRequest.current)
        setError(errorText(err));
    }
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setSetupLoading(true);
    setSetupError('');
    void Promise.all([getDonorIdentity(), getIntakePolicy()])
      .then(([donor, configured]) => {
        if (active) {
          setPolicy(configured);
          setIdentity(donor);
        }
      })
      .catch((err) => {
        if (active) setSetupError(errorText(err));
      })
      .finally(() => {
        if (active) setSetupLoading(false);
      });
    return () => {
      active = false;
    };
  }, [setupAttempt]);

  async function refreshWorkspace() {
    if (!identity || !policy) setSetupAttempt((attempt) => attempt + 1);
    await dashboard.refresh();
  }

  useEffect(() => {
    if (!dashboard.data) return;
    setRecent(dashboard.data.items);
    setNextCursor(dashboard.data.next_cursor);
    let active = true;
    const selected = selection.current;
    const request = ++detailRequest.current;
    if (posted)
      void getDonation(posted.donation.id)
        .then((value) => {
          if (active && selected === selection.current && request === detailRequest.current)
            setPosted(value);
        })
        .catch((e) => {
          if (active && selected === selection.current && request === detailRequest.current)
            setError(errorText(e));
        });
    return () => {
      active = false;
    };
  }, [dashboard.data, posted?.donation.id]);

  useEffect(() => {
    if (!identity) return;
    const key = 'foodbridge:draft:' + identity.organization_id;
    const id = sessionStorage.getItem(key);
    if (!id) return;
    let active = true;
    const request = ++recoveryRequest.current;
    const isCurrent = () =>
      active && request === recoveryRequest.current && sessionStorage.getItem(key) === id;
    setRecovering(true);
    setRecoveryError('');
    void getDraft(id)
      .then((value) => {
        if (!isCurrent()) return;
        if (value.status === 'review_required') {
          setDraft(value);
          setDescription(value.description);
          setReviewed(false);
          setNotice('Your saved draft is ready to review.');
        } else {
          // Only a confirmed server result can retire this exact recovery pointer.
          sessionStorage.removeItem(key);
        }
      })
      .catch((err) => {
        if (!isCurrent()) return;
        if (err instanceof IntakeApiError && err.status === 404) {
          sessionStorage.removeItem(key);
          setNotice('Your saved draft is no longer available. You can start a new donation.');
        } else {
          setRecoveryError(
            'Could not load your saved draft. It is still saved. Retry recovery or start a new donation.',
          );
        }
      })
      .finally(() => {
        if (active && request === recoveryRequest.current) setRecovering(false);
      });
    return () => {
      active = false;
    };
  }, [identity, recoveryAttempt]);

  useEffect(() => {
    if (!evaluation || evaluation.status !== 'pending') return;
    const controller = new AbortController();
    let stopped = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;
    setPolling(true);
    async function poll() {
      try {
        const result = await getEvaluation(evaluation!.id, controller.signal);
        if (stopped) return;
        setEvaluation(result);
        if (result.status === 'pending' && ++attempts < 30)
          timer = setTimeout(() => void poll(), 1000);
        else setPolling(false);
      } catch (err) {
        if (!stopped) {
          setError(errorText(err));
          setPolling(false);
        }
      }
    }
    timer = setTimeout(() => void poll(), 600);
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [evaluation?.id, evaluation?.status, pollRun]);

  async function describe(event: FormEvent) {
    event.preventDefault();
    if (!identity) return;
    stopDraftRecovery();
    setError('');
    setBusy(true);
    try {
      const value = await createDraft(
        { description, pickup_location: identity.pickup_location },
        draftKey.current,
      );
      setDraft(value);
      sessionStorage.setItem('foodbridge:draft:' + identity.organization_id, value.id);
      setReviewed(false);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function post(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!identity || !draft || !reviewed) return;
    stopDraftRecovery();
    setError('');
    try {
      const values = new FormData(event.currentTarget);
      const text = (key: string) => String(values.get(key) ?? '').trim();
      const tokens = (key: string) =>
        text(key)
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean);
      const donation: DonationInput = {
        description: draft.description,
        food_name: text('food_name'),
        category: text('category') as DonationInput['category'],
        quantity_kg: Number(text('quantity_kg')),
        portions: text('portions') ? Number(text('portions')) : null,
        packaging_type: (text('packaging_type') || null) as DonationInput['packaging_type'],
        storage: text('storage') as DonationInput['storage'],
        dietary_tags: tokens('dietary_tags'),
        allergens: parseAllergens(text('allergens')),
        pickup_location: draft.pickup_location,
        pickup_window: {
          start: locationInstant(
            text('start'),
            draft.pickup_location.timezone ?? 'America/Los_Angeles',
          ),
          end: locationInstant(
            text('end'),
            draft.pickup_location.timezone ?? 'America/Los_Angeles',
          ),
        },
        safe_use_by: locationInstant(
          text('safe_use_by'),
          draft.pickup_location.timezone ?? 'America/Los_Angeles',
        ),
        handling_notes: text('handling_notes'),
      };
      setBusy(true);
      setError('');
      try {
        const value = await submitDonation(
          { draft_id: draft.id, expected_draft_version: draft.version, confirmed: true, donation },
          submitKey.current,
        );
        selectDonation(value);
        sessionStorage.removeItem('foodbridge:draft:' + identity.organization_id);
        setRecent((items) => [value, ...items]);
      } catch (err) {
        if (err instanceof IntakeApiError && err.status === 409) {
          const fresh = await getDraft(draft.id);
          setDraft(fresh);
          setReviewed(false);
          if (fresh.donation_id) selectDonation(await getDonation(fresh.donation_id));
        }
        setError(errorText(err));
      } finally {
        setBusy(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Check the donation details.');
    }
  }

  async function preview() {
    if (!posted) return;
    setBusy(true);
    setError('');
    try {
      const value = await demoEligibility(posted.donation.id, evaluationKey.current);
      setEvaluation(value);
      setPollRun((run) => run + 1);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  function startAgain() {
    stopDraftRecovery();
    selection.current = { id: undefined };
    detailRequest.current++;
    setHistory(undefined);
    setDraft(undefined);
    setPosted(undefined);
    setEvaluation(undefined);
    setDescription('');
    draftKey.current = crypto.randomUUID();
    submitKey.current = crypto.randomUUID();
    evaluationKey.current = crypto.randomUUID();
    setError('');
    setNotice('');
    if (identity) sessionStorage.removeItem('foodbridge:draft:' + identity.organization_id);
  }

  const fields = draft?.extraction.fields;
  return (
    <section className="donor-workspace">
      <WorkspaceHeader
        eyebrow={identity?.organization_name ?? 'Donor workspace'}
        title={posted ? 'Donation posted' : 'Post today’s surplus'}
        {...dashboard}
        refresh={refreshWorkspace}
        loading={dashboard.loading || setupLoading}
      />
      <Stats
        items={[
          { label: 'Donations on this page', value: recent.length },
          {
            label: 'In progress',
            value: recent.filter((item) =>
              [
                'submitted',
                'matching',
                'offered',
                'reserved',
                'pickup_assigned',
                'picked_up',
              ].includes(item.donation.status),
            ).length,
          },
          {
            label: 'Delivered on this page',
            value: recent.filter((item) => item.donation.status === 'delivered').length,
          },
        ]}
      />
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      {dashboard.error && (
        <p role="alert" className="notice error">
          {dashboard.error}
        </p>
      )}
      <p>
        {posted
          ? 'Your confirmed details and latest workflow status are shown below.'
          : 'Describe the food, then check the details before posting.'}
      </p>
      {identity?.mode === 'local_demo' && (
        <p className="demo-label">
          Local demo identity · {identity.display_name} · synthetic organization. Extraction and
          donation records are real local database operations.
        </p>
      )}
      {error && (
        <p role="alert" className="donor-error">
          {error}
        </p>
      )}
      {setupLoading && !identity && <p role="status">Loading donor details…</p>}
      {setupError && (
        <div role="alert" className="notice error">
          {setupError}
          <button
            className="quiet-button"
            disabled={setupLoading}
            onClick={() => setSetupAttempt((attempt) => attempt + 1)}
          >
            Retry donor setup
          </button>
        </div>
      )}
      {recovering && (
        <p role="status">Loading your saved draft… You can start a new donation while it loads.</p>
      )}
      {recoveryError && (
        <div role="alert" className="notice error">
          {recoveryError}
          <button
            className="quiet-button"
            onClick={() => setRecoveryAttempt((attempt) => attempt + 1)}
          >
            Retry saved draft
          </button>
        </div>
      )}
      {identity && !posted && (
        <div className="donor-columns">
          <div className="donor-sheet">
            {!draft ? (
              <form onSubmit={(event) => void describe(event)}>
                <h2>1. What do you have?</h2>
                <label htmlFor="description">Food description</label>
                <textarea
                  id="description"
                  required
                  maxLength={policy?.max_description_length ?? 2000}
                  rows={7}
                  value={description}
                  onChange={(event) => {
                    stopDraftRecovery();
                    setDescription(event.target.value);
                    draftKey.current = crypto.randomUUID();
                  }}
                  placeholder={
                    'Food: vegetable rice bowls. 20 meals, 10 kg. Refrigerated. Vegetarian. Allergens: soy. Today pickup 4 PM to 6 PM. Use by 8 PM.'
                  }
                />
                <p className="form-hint">
                  Include weight, storage, allergens and times. Missing details stay blank for you
                  to fill in.
                </p>
                <button type="submit" disabled={busy}>
                  {busy ? 'Checking…' : 'Review details'}
                </button>
              </form>
            ) : (
              <form
                ref={formRef}
                onSubmit={(event) => void post(event)}
                onChange={() => {
                  stopDraftRecovery();
                  setReviewed(false);
                  submitKey.current = crypto.randomUUID();
                }}
              >
                <div className="donor-row">
                  <h2>2. Check the details</h2>
                  <button
                    className="quiet-button"
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      stopDraftRecovery();
                      setDraft(undefined);
                      draftKey.current = crypto.randomUUID();
                    }}
                  >
                    Edit description
                  </button>
                </div>
                <p className="form-hint">
                  {draft.extraction.provider === 'rules'
                    ? 'Basic extraction · no model used'
                    : `Model proposal · ${draft.extraction.provider} · ${draft.extraction.model}`}
                  . Every field can be corrected.
                </p>
                {(draft.extraction.issues ?? []).length > 0 && (
                  <div className="review-issues">
                    <strong>Please review</strong>
                    <ul>
                      {(draft.extraction.issues ?? []).map((issue, i) => (
                        <li key={`${issue.field}-${i}`}>{issue.message}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <label htmlFor="food_name">Food name</label>
                <input
                  id="food_name"
                  name="food_name"
                  required
                  maxLength={200}
                  defaultValue={fields?.food_name ?? ''}
                />
                <div className="donor-fields">
                  <div>
                    <label htmlFor="quantity_kg">Weight, kg</label>
                    <input
                      id="quantity_kg"
                      name="quantity_kg"
                      type="number"
                      min="0.001"
                      step="0.001"
                      required
                      defaultValue={fields?.quantity_kg ?? ''}
                    />
                  </div>
                  <div>
                    <label htmlFor="portions">
                      Meals / portions{' '}
                      {policy?.required_fields?.includes('portions') ? '(required)' : '(optional)'}
                    </label>
                    <input
                      id="portions"
                      name="portions"
                      required={policy?.required_fields?.includes('portions')}
                      type="number"
                      min="1"
                      step="1"
                      defaultValue={fields?.portions ?? ''}
                    />
                  </div>
                </div>
                <div className="donor-fields">
                  <div>
                    <label htmlFor="category">Category</label>
                    <select
                      id="category"
                      name="category"
                      required
                      defaultValue={fields?.category ?? ''}
                    >
                      <option value="" disabled>
                        Select category
                      </option>
                      {['prepared_meals', 'produce', 'bakery', 'dairy', 'pantry', 'other'].map(
                        (value) => (
                          <option key={value} value={value}>
                            {value.replaceAll('_', ' ')}
                          </option>
                        ),
                      )}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="storage">Storage needed</label>
                    <select
                      id="storage"
                      name="storage"
                      required
                      defaultValue={fields?.storage ?? ''}
                    >
                      <option value="" disabled>
                        Select storage
                      </option>
                      <option value="ambient">Ambient</option>
                      <option value="chilled">Chilled</option>
                      <option value="frozen">Frozen</option>
                    </select>
                  </div>
                </div>
                <label htmlFor="packaging_type">
                  Packaging{' '}
                  {policy?.required_fields?.includes('packaging_type')
                    ? '(required)'
                    : '(optional)'}
                </label>
                <select
                  id="packaging_type"
                  name="packaging_type"
                  required={policy?.required_fields?.includes('packaging_type')}
                  defaultValue={fields?.packaging_type ?? ''}
                >
                  <option value="">Unspecified</option>
                  <option value="boxed">Boxed</option>
                  <option value="sealed">Sealed</option>
                  <option value="bulk">Bulk</option>
                  <option value="other">Other</option>
                </select>
                <label htmlFor="allergens">Allergens (comma separated, or “none”)</label>
                <input
                  id="allergens"
                  name="allergens"
                  required
                  defaultValue={
                    fields?.allergens == null
                      ? ''
                      : fields.allergens.length
                        ? fields.allergens.join(', ')
                        : 'none'
                  }
                  placeholder="soy, wheat"
                />
                <label htmlFor="dietary_tags">Dietary tags (optional)</label>
                <input
                  id="dietary_tags"
                  name="dietary_tags"
                  defaultValue={fields?.dietary_tags?.join(', ') ?? ''}
                  placeholder="vegetarian"
                />
                <p className="form-hint">
                  Times use the pickup location timezone: {draft.pickup_location.timezone}.
                </p>
                <div className="donor-fields">
                  <div>
                    <label htmlFor="start">Pickup starts</label>
                    <input
                      id="start"
                      name="start"
                      type="datetime-local"
                      required
                      defaultValue={
                        fields?.pickup_window?.start
                          ? locationInput(
                              fields?.pickup_window?.start,
                              draft.pickup_location.timezone ?? 'America/Los_Angeles',
                            )
                          : ''
                      }
                    />
                  </div>
                  <div>
                    <label htmlFor="end">Pickup ends</label>
                    <input
                      id="end"
                      name="end"
                      type="datetime-local"
                      required
                      defaultValue={
                        fields?.pickup_window?.end
                          ? locationInput(
                              fields?.pickup_window?.end,
                              draft.pickup_location.timezone ?? 'America/Los_Angeles',
                            )
                          : ''
                      }
                    />
                  </div>
                </div>
                <label htmlFor="safe_use_by">Safe-use deadline (donor confirmed)</label>
                <input
                  id="safe_use_by"
                  name="safe_use_by"
                  type="datetime-local"
                  required
                  defaultValue={
                    fields?.safe_use_by
                      ? locationInput(
                          fields?.safe_use_by,
                          draft.pickup_location.timezone ?? 'America/Los_Angeles',
                        )
                      : ''
                  }
                />
                <label htmlFor="handling_notes">
                  Pickup / handling notes{' '}
                  {policy?.required_fields?.includes('handling_notes')
                    ? '(required)'
                    : '(optional)'}
                </label>
                <textarea
                  id="handling_notes"
                  name="handling_notes"
                  required={policy?.required_fields?.includes('handling_notes')}
                  rows={2}
                  maxLength={1000}
                  defaultValue={fields?.handling_notes ?? ''}
                />
                <p className="pickup-address">Pickup: {draft.pickup_location.address}</p>
                <label className="confirmation">
                  <input
                    type="checkbox"
                    checked={reviewed}
                    onChange={(event) => {
                      event.stopPropagation();
                      setReviewed(event.target.checked);
                    }}
                    required
                  />
                  I checked the quantities, allergens, storage and all times. These are the details
                  I confirm.
                </label>
                <button type="submit" disabled={busy || !reviewed}>
                  {busy ? 'Posting…' : 'Confirm and post donation'}
                </button>
              </form>
            )}
          </div>
          <aside>
            <h2>Your latest donations</h2>
            {recent.length === 0 ? (
              <p className="form-hint">Posted donations will appear here.</p>
            ) : (
              recent.map((item) => (
                <div className="recent-donation" key={item.donation.id}>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => {
                      selectDonation(item);
                      setError('');
                    }}
                  >
                    {item.donation.food_name}
                  </button>
                  <p>
                    {item.donation.quantity_kg} kg · <StatusBadge status={item.donation.status} />
                  </p>
                  <p>
                    Pickup by{' '}
                    {formatTime(
                      item.donation.pickup_window.end,
                      item.donation.pickup_location.timezone,
                    )}
                  </p>
                </div>
              ))
            )}
            {nextCursor && (
              <button
                type="button"
                className="quiet-button"
                disabled={paging}
                onClick={async () => {
                  setPaging(true);
                  const requestedSnapshot = dashboard.data;
                  try {
                    const page = await listDonations(nextCursor);
                    if (latestSnapshot.current !== requestedSnapshot) return;
                    setRecent((old) => [...old, ...page.items]);
                    setNextCursor(page.next_cursor);
                  } catch (e) {
                    setError(errorText(e));
                  } finally {
                    setPaging(false);
                  }
                }}
              >
                Load older donations
              </button>
            )}
          </aside>
        </div>
      )}
      {posted && (
        <div className="donor-sheet posted-donation" aria-live="polite">
          <h2>{posted.donation.food_name}</h2>
          <p>
            {posted.donation.quantity_kg} kg · {posted.donation.portions ?? 'Unspecified'} portions
          </p>
          <dl>
            <div>
              <dt>Status</dt>
              <dd>
                <StatusBadge status={posted.donation.status} />
              </dd>
            </div>
            <div>
              <dt>Urgency</dt>
              <dd>{posted.urgency.priority} · confirmed-deadline rule</dd>
            </div>
            <div>
              <dt>Pickup ends</dt>
              <dd>
                {formatTime(
                  posted.donation.pickup_window.end,
                  posted.donation.pickup_location.timezone,
                )}
              </dd>
            </div>
          </dl>
          <p className="form-hint">
            ID: {posted.donation.id}. Status updates follow confirmed workflow changes. Matching
            requires an available matching service.
          </p>
          {identity?.mode === 'local_demo' &&
            ['submitted', 'matching', 'offered'].includes(posted.donation.status) && (
              <div className="eligibility-demo">
                <h3>Try the eligibility worker</h3>
                <p className="form-hint">
                  Uses synthetic recipients, a 14-minute route and a demo driver. It does not
                  reserve or match the food.
                </p>
                <button type="button" onClick={() => void preview()} disabled={busy || polling}>
                  {polling ? 'Worker evaluating…' : 'Check demo recipients'}
                </button>
                {evaluation?.status === 'pending' && !polling && (
                  <p role="status">
                    Still queued. Check the intake worker / relay, then retry this button with the
                    same request key.
                  </p>
                )}
                {evaluation?.failure_code && (
                  <p role="alert">{evaluation.failure_code.replaceAll('_', ' ')}</p>
                )}
                {evaluation?.result?.decisions.map((decision, index) => (
                  <div className="eligibility-decision" key={decision.recipient_organization_id}>
                    <strong>
                      Demo recipient {index + 1}: {decision.eligible ? 'Eligible' : 'Not eligible'}
                    </strong>
                    <p>
                      {decision.reasons.length
                        ? decision.reasons.map((reason) => reason.replaceAll('_', ' ')).join(' · ')
                        : 'Category, diet, storage, capacity, route and driver checks passed.'}
                    </p>
                  </div>
                ))}
              </div>
            )}
          <div className="donor-row">
            {[
              'submitted',
              'needs_review',
              'matching',
              'offered',
              'reserved',
              'pickup_assigned',
            ].includes(posted.donation.status) && (
              <ConfirmAction
                label="Cancel donation"
                danger
                disabled={cancellation.busy}
                onConfirm={() => {
                  const selected = selection.current;
                  void (async () => {
                    try {
                      await cancellation.run(
                        `${posted.donation.id}:${posted.donation.version}:cancel`,
                        (key) => cancelDonation(posted.donation.id, posted.donation.version, key),
                      );
                      if (selected === selection.current) {
                        await refreshSelectedDonation();
                        if (selected === selection.current)
                          setNotice('Donation cancelled. Any active hold has been released.');
                      }
                      await dashboard.refresh();
                    } catch (e) {
                      await dashboard.refresh();
                      if (selected === selection.current) setError(errorText(e));
                    }
                  })();
                }}
              >
                Cancel this donation and release any reservation before pickup?
              </ConfirmAction>
            )}
            <button
              className="quiet-button"
              type="button"
              onClick={() => void refreshSelectedDonation()}
            >
              Refresh status
            </button>
            <button type="button" onClick={startAgain}>
              Post another donation
            </button>
          </div>
        </div>
      )}
      {posted && (
        <button className="quiet-button" onClick={() => setHistory(posted.donation.id)}>
          View donation history
        </button>
      )}
      {history && (
        <DonationTimeline
          role="donor"
          id={history}
          version={posted?.donation.version}
          onClose={() => setHistory(undefined)}
        />
      )}
      <h2>Live donation activity</h2>
      <p className="form-hint">Updates received during this session.</p>
      <ol className="activity-list">
        {dashboard.events.map((event) => (
          <li key={event.event_id}>
            <strong>{humanize(event.event_type.replace('.v1', '').replaceAll('.', ' '))}</strong>
            <span>{formatTime(event.occurred_at)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

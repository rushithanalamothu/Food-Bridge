import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type {
  DonationInput,
  DraftRead,
  DonorIdentity,
  IntakeDonationRead,
  EvaluationRead,
} from '../../api/generated/intake';
import {
  createDraft,
  demoEligibility,
  getDonorIdentity,
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
function datetimeLocal(value: string | null | undefined) {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export function DonorPage() {
  const [identity, setIdentity] = useState<DonorIdentity>();
  const [draft, setDraft] = useState<DraftRead>();
  const [posted, setPosted] = useState<IntakeDonationRead>();
  const [recent, setRecent] = useState<IntakeDonationRead[]>([]);
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

  useEffect(() => {
    mounted.current = true;
    void getDonorIdentity()
      .then((value) => {
        if (!mounted.current) return;
        setIdentity(value);
        void listDonations()
          .then((list) => {
            if (mounted.current) setRecent(list.items);
          })
          .catch((err) => {
            if (mounted.current) setError(errorText(err));
          });
      })
      .catch((err) => {
        if (mounted.current) setError(errorText(err));
      });
    return () => {
      mounted.current = false;
    };
  }, []);

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
    setError('');
    setBusy(true);
    try {
      const value = await createDraft(
        { description, pickup_location: identity.pickup_location },
        draftKey.current,
      );
      setDraft(value);
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
      storage: text('storage') as DonationInput['storage'],
      dietary_tags: tokens('dietary_tags'),
      allergens: text('allergens').toLowerCase() === 'none' ? [] : tokens('allergens'),
      pickup_location: draft.pickup_location,
      pickup_window: {
        start: new Date(text('start')).toISOString(),
        end: new Date(text('end')).toISOString(),
      },
      safe_use_by: new Date(text('safe_use_by')).toISOString(),
      handling_notes: text('handling_notes'),
    };
    setBusy(true);
    setError('');
    try {
      const value = await submitDonation(
        { draft_id: draft.id, expected_draft_version: draft.version, confirmed: true, donation },
        submitKey.current,
      );
      setPosted(value);
      setRecent((items) => [value, ...items]);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
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
    setDraft(undefined);
    setPosted(undefined);
    setEvaluation(undefined);
    setDescription('');
    draftKey.current = crypto.randomUUID();
    submitKey.current = crypto.randomUUID();
    evaluationKey.current = crypto.randomUUID();
    setError('');
  }

  const fields = draft?.extraction.fields;
  return (
    <section className="donor-workspace">
      <p className="eyebrow">{identity?.organization_name ?? 'Donor workspace'}</p>
      <h1>{posted ? 'Donation posted' : 'Post today’s surplus'}</h1>
      <p>
        {posted
          ? 'Your confirmed details are saved. The handoff event is ready for the orchestrator.'
          : 'Describe the food, then check the details before posting.'}
      </p>
      {identity?.mode === 'local_demo' && (
        <p className="demo-label">
          Local demo identity · Maya · synthetic organization. Extraction and donation records are
          real local database operations.
        </p>
      )}
      {error && (
        <p role="alert" className="donor-error">
          {error}
        </p>
      )}
      {!identity && (
        <p className="implementation-note">
          Local setup: enable the intake demo and run <code>make seed-intake-demo</code>. Shared
          environments require a gateway access token.
        </p>
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
                  maxLength={4000}
                  rows={7}
                  value={description}
                  onChange={(event) => {
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
                    <label htmlFor="portions">Meals / portions (optional)</label>
                    <input
                      id="portions"
                      name="portions"
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
                  Times use your browser timezone:{' '}
                  {Intl.DateTimeFormat().resolvedOptions().timeZone}. Pickup location timezone:{' '}
                  {draft.pickup_location.timezone}.
                </p>
                <div className="donor-fields">
                  <div>
                    <label htmlFor="start">Pickup starts</label>
                    <input
                      id="start"
                      name="start"
                      type="datetime-local"
                      required
                      defaultValue={datetimeLocal(fields?.pickup_window?.start)}
                    />
                  </div>
                  <div>
                    <label htmlFor="end">Pickup ends</label>
                    <input
                      id="end"
                      name="end"
                      type="datetime-local"
                      required
                      defaultValue={datetimeLocal(fields?.pickup_window?.end)}
                    />
                  </div>
                </div>
                <label htmlFor="safe_use_by">Safe-use deadline (donor confirmed)</label>
                <input
                  id="safe_use_by"
                  name="safe_use_by"
                  type="datetime-local"
                  required
                  defaultValue={datetimeLocal(fields?.safe_use_by)}
                />
                <label htmlFor="handling_notes">Pickup / handling notes (optional)</label>
                <textarea
                  id="handling_notes"
                  name="handling_notes"
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
                  <strong>{item.donation.food_name}</strong>
                  <p>
                    {item.donation.quantity_kg} kg · {item.donation.status.replaceAll('_', ' ')}
                  </p>
                  <p>Pickup by {new Date(item.donation.pickup_window.end).toLocaleString()}</p>
                </div>
              ))
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
              <dd>{posted.donation.status}</dd>
            </div>
            <div>
              <dt>Urgency</dt>
              <dd>{posted.urgency.priority} · confirmed-deadline rule</dd>
            </div>
            <div>
              <dt>Pickup ends</dt>
              <dd>{new Date(posted.donation.pickup_window.end).toLocaleString()}</dd>
            </div>
          </dl>
          <p className="form-hint">
            ID: {posted.donation.id}. Matching and reservation integration is the next team handoff.
          </p>
          {identity?.mode === 'local_demo' && (
            <div className="eligibility-demo">
              <h3>Try the eligibility worker</h3>
              <p className="form-hint">
                Uses synthetic recipients, a 14-minute route and a demo driver. It does not reserve
                or match the food.
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
            <button
              className="quiet-button"
              type="button"
              onClick={() =>
                void getDonation(posted.donation.id)
                  .then(setPosted)
                  .catch((err) => setError(errorText(err)))
              }
            >
              Refresh status
            </button>
            <button type="button" onClick={startAgain}>
              Post another donation
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

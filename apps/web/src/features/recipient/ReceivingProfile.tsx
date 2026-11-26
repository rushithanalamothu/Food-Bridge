import { Button } from '../../components/Button';
import { useEffect, useState } from 'react';
import type {
  ReceivingProfileRead,
  ReceivingProfileUpdate,
  Storage,
  Category,
} from '../../api/generated/workflow';
import { saveReceivingProfile } from '../../api/workflow';
import { useCommand } from '../../hooks/useWorkspace';
import { locationInput, locationInstant } from '../../api/time';
import { Notice, humanize } from '../../components/Workspace';

const categories: Category[] = ['prepared_meals', 'produce', 'bakery', 'dairy', 'pantry', 'other'];
const storageTypes: Storage[] = ['ambient', 'chilled', 'frozen'];
export function ReceivingProfile({
  value,
  refresh,
  onSaved,
}: {
  value: ReceivingProfileRead;
  refresh: () => Promise<void>;
  onSaved: () => void;
}) {
  const action = useCommand();
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  // Live updates never replace an in-progress form. Its expected versions protect the save.
  const [baseline, setBaseline] = useState(value);
  useEffect(() => {
    if (!editing) setBaseline(value);
  }, [value, editing]);
  const profile = baseline.profile;
  const zone = profile.location.timezone ?? 'America/Los_Angeles';
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setMessage('');
    const data = new FormData(event.currentTarget);
    const text = (key: string) => String(data.get(key) ?? '').trim();
    try {
      const accepted = data.getAll('storage') as [Storage, ...Storage[]];
      const selectedCategories = data.getAll('category') as [Category, ...Category[]];
      if (!accepted.length || !selectedCategories.length)
        throw new Error('Choose at least one category and storage type.');
      const capacities = Object.fromEntries(
        accepted.map((storage) => [storage, Number(text(storage))]),
      );
      const body: ReceivingProfileUpdate = {
        expected_version: profile.version,
        expected_capacity_versions: baseline.capacity_versions,
        profile: {
          ...profile,
          accepted_categories: selectedCategories,
          accepted_storage: accepted,
          available_capacity_kg_by_storage: capacities,
          rejected_allergens: text('allergens')
            .split(',')
            .map((v) => v.trim())
            .filter(Boolean),
          required_dietary_tags: text('diet')
            .split(',')
            .map((v) => v.trim())
            .filter(Boolean),
          receiving_window: {
            start: locationInstant(text('start'), zone),
            end: locationInstant(text('end'), zone),
          },
          location: { ...profile.location, address: text('address') },
        },
        reported_free_kg_by_storage: capacities,
      };
      if (!accepted.length || !body.profile.accepted_categories.length)
        throw new Error('Choose at least one category and storage type.');
      await action.run(JSON.stringify(body), (key) => saveReceivingProfile(body, key));
      onSaved();
      setEditing(false);
      setMessage('Receiving preferences saved.');
      await refresh();
    } catch (e) {
      setError((e as Error).message);
      await refresh();
    }
  }
  return (
    <section className="card">
      <div className="section-heading">
        <h2>Receiving preferences</h2>
        {!editing && (
          <Button
            variant="secondary"
            onClick={() => {
              setBaseline(value);
              setEditing(true);
              setMessage('');
            }}
          >
            Edit preferences
          </Button>
        )}
      </div>
      {message && <Notice tone="success">{message}</Notice>}
      {error && (
        <Notice error>
          {error}{' '}
          <Button
            variant="ghost"
            onClick={() => {
              setBaseline(value);
              setError('');
            }}
          >
            Reload current preferences
          </Button>
        </Notice>
      )}
      {editing && value.profile.version !== profile.version && (
        <Notice>
          Preferences changed while you were editing. Reload current preferences before saving.
        </Notice>
      )}
      {!editing ? (
        <>
          <p>{value.profile.accepted_categories.map(humanize).join(' · ')}</p>
          <dl className="detail-grid">
            {Object.entries(value.profile.available_capacity_kg_by_storage).map(
              ([storage, capacity]) => (
                <div key={storage}>
                  <dt>{humanize(storage)} available</dt>
                  <dd>{capacity} kg</dd>
                </div>
              ),
            )}
          </dl>
          <p>Receiving at {value.profile.location.address}</p>
          <p className="muted">
            {zone} · Rejected allergens: {value.profile.rejected_allergens.join(', ') || 'None'} ·
            Required diet: {value.profile.required_dietary_tags?.join(', ') || 'None'}
          </p>
        </>
      ) : (
        <form
          onSubmit={(event) => void submit(event)}
          key={`${profile.version}:${JSON.stringify(baseline.capacity_versions)}`}
        >
          <fieldset>
            <legend>Accepted food categories</legend>
            {categories.map((category) => (
              <label className="checkbox" key={category}>
                <input
                  type="checkbox"
                  name="category"
                  value={category}
                  defaultChecked={profile.accepted_categories.includes(category)}
                />
                {humanize(category)}
              </label>
            ))}
          </fieldset>
          <fieldset>
            <legend>Storage and capacity</legend>
            <p className="muted">
              Report free storage before outstanding inbound reservations. Committed food is
              subtracted automatically. Values cannot fall below committed inbound weight.
            </p>
            {storageTypes.map((storage) => (
              <div key={storage}>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    name="storage"
                    value={storage}
                    defaultChecked={profile.accepted_storage.includes(storage)}
                  />
                  Accept {storage} food
                </label>
                <label htmlFor={`capacity-${storage}`}>{humanize(storage)} free storage (kg)</label>
                <input
                  id={`capacity-${storage}`}
                  name={storage}
                  type="number"
                  min="0"
                  step="0.001"
                  defaultValue={baseline.reported_free_kg_by_storage[storage] ?? 0}
                />
                <p className="muted">
                  Committed inbound: {value.committed_inbound_kg_by_storage[storage] ?? 0} kg
                </p>
              </div>
            ))}
          </fieldset>
          <label htmlFor="receiving-address">Delivery instructions / receiving address</label>
          <textarea
            id="receiving-address"
            name="address"
            defaultValue={profile.location.address}
            maxLength={500}
            readOnly
            required
          />
          <label htmlFor="rejected-allergens">Rejected allergens (comma separated)</label>
          <input
            id="rejected-allergens"
            name="allergens"
            defaultValue={profile.rejected_allergens.join(', ')}
          />
          <label htmlFor="required-diet">Required dietary tags (comma separated)</label>
          <input
            id="required-diet"
            name="diet"
            defaultValue={profile.required_dietary_tags?.join(', ')}
          />
          <p className="muted">
            Receiving times use {zone}. Location coordinates and timezone changes require
            coordinator verification.
          </p>
          <label htmlFor="receiving-start">Receiving starts</label>
          <input
            id="receiving-start"
            name="start"
            type="datetime-local"
            defaultValue={locationInput(profile.receiving_window.start, zone)}
            required
          />
          <label htmlFor="receiving-end">Receiving ends</label>
          <input
            id="receiving-end"
            name="end"
            type="datetime-local"
            defaultValue={locationInput(profile.receiving_window.end, zone)}
            required
          />
          <div className="actions">
            <Button type="submit" busy={action.busy}>
              Save preferences
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={action.busy}
              onClick={() => {
                setEditing(false);
                setError('');
              }}
            >
              Cancel editing
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}

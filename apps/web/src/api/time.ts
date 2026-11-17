// datetime-local has no zone. Interpret donor input in the pickup location's IANA zone.
export function locationInput(value: string, timezone: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(value));
  const part = (name: string) => parts.find((p) => p.type === name)?.value;
  return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`;
}
export function locationInstant(value: string, timezone: string): string {
  const local = Date.parse(value + 'Z');
  if (!Number.isFinite(local)) throw new Error('Enter a valid pickup date and time.');
  // Sample all offsets around the date, including half-hour transitions.
  const offsets = new Set<number>();
  for (let hour = -36; hour <= 36; hour += 3) {
    const sample = local + hour * 3600000;
    offsets.add(Date.parse(locationInput(new Date(sample).toISOString(), timezone) + 'Z') - sample);
  }
  const matches = [...offsets]
    .map((offset) => local - offset)
    .filter((candidate) => locationInput(new Date(candidate).toISOString(), timezone) === value);
  if (matches.length !== 1)
    throw new Error(
      'This local time is skipped or repeated by daylight saving. Choose an unambiguous time.',
    );
  return new Date(matches[0]).toISOString();
}
export function parseAllergens(value: string): string[] {
  if (value.trim().toLowerCase() === 'none') return [];
  const allergens = value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  if (!allergens.length) throw new Error('Enter allergens or explicitly type “none”.');
  return allergens;
}

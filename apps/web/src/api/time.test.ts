import { expect, it } from 'vitest';
import { locationInput, locationInstant, parseAllergens } from './time';
it('keeps unknown allergens distinct from explicitly none', () => {
  for (const input of ['', '   ', ', ,']) expect(() => parseAllergens(input)).toThrow();
  expect(parseAllergens(' NONE ')).toEqual([]);
  expect(parseAllergens('soy, wheat')).toEqual(['soy', 'wheat']);
});
it('uses the pickup location timezone independently of the browser timezone', () => {
  expect(locationInstant('2026-11-20T10:00', 'America/New_York')).toBe('2026-11-20T15:00:00.000Z');
  expect(locationInput('2026-11-20T15:00:00Z', 'America/New_York')).toBe('2026-11-20T10:00');
  expect(locationInstant('2026-11-20T10:00', 'Asia/Kolkata')).toBe('2026-11-20T04:30:00.000Z');
});
it('rejects DST skipped or ambiguous local times rather than shifting a deadline', () => {
  expect(() => locationInstant('2026-03-08T02:30', 'America/Los_Angeles')).toThrow();
  expect(() => locationInstant('2026-11-01T01:30', 'America/Los_Angeles')).toThrow();
});

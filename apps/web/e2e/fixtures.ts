import type { Page } from '@playwright/test';
import type { DriverOriginRead } from '../src/api/generated/workflow';
export const org = '00000000-0000-4000-8000-000000000001';
export const donationId = '00000000-0000-4000-8000-000000000002';
export const matchId = '00000000-0000-4000-8000-000000000003';
export const later = () => new Date(Date.now() + 86400000).toISOString();
export function food() {
  return {
    id: donationId,
    donor_organization_id: org,
    description: 'Synthetic food fixture',
    category: 'prepared_meals',
    food_name: 'Synthetic rice bowls',
    quantity_kg: 10,
    portions: 20,
    packaging_type: 'boxed',
    storage: 'chilled',
    allergens: ['soy'],
    dietary_tags: ['vegetarian'],
    pickup_location: {
      address: 'Synthetic pickup kitchen',
      latitude: 37.3,
      longitude: -121.9,
      timezone: 'America/Los_Angeles',
    },
    pickup_window: { start: new Date(Date.now() - 60000).toISOString(), end: later() },
    safe_use_by: later(),
    handling_notes: 'Keep chilled',
    status: 'offered',
    version: 4,
    created_at: new Date().toISOString(),
  };
}
export async function fixtures(page: Page) {
  const donation = food();
  const state = {
    donation,
    driverOrigin: {
      driver_id: org,
      version: 1,
      origin: null,
      observed_at: null,
    } as DriverOriginRead,
    offers: [
      {
        version: 1,
        status: 'offered',
        donation,
        recommendation: {
          id: matchId,
          donation_id: donationId,
          donation_version: 4,
          matching_round: 1,
          recipient_organization_id: org,
          distance_m: 2000,
          travel_time_s: 300,
          offer_expires_at: later(),
          explanation: 'SYNTHETIC fixture: eligible receiver.',
          algorithm: 'distance_only',
          eligibility_policy_version: 'eligibility-v2',
          ranking_config_version: 'fixture-v1',
        },
      },
    ],
    reservations: [] as {
      reservation: {
        id: string;
        status: string;
        version: number;
        quantity_kg: number;
        storage: string;
      };
      donation: ReturnType<typeof food>;
    }[],
    pickup: {
      id: 'pickup',
      donation_id: donationId,
      driver_id: org,
      reservation_id: 'reservation',
      status: 'assigned',
      version: 1,
      start: donation.pickup_window.start,
      end: later(),
      donation,
      destination: {
        address: 'Synthetic receiving center',
        latitude: 37.31,
        longitude: -121.91,
        timezone: 'America/Los_Angeles',
      },
      recipient_name: 'Synthetic receiver',
    },
    profile: {
      profile: {
        organization_id: org,
        version: 1,
        location: { ...donation.pickup_location, address: 'Synthetic receiving center' },
        accepted_categories: ['prepared_meals'],
        accepted_storage: ['chilled'],
        available_capacity_kg_by_storage: { chilled: 20 },
        rejected_allergens: ['peanut'],
        required_dietary_tags: ['vegetarian'],
        receiving_window: { start: donation.pickup_window.start, end: later() },
      },
      reported_free_kg_by_storage: { chilled: 20 },
      committed_inbound_kg_by_storage: { chilled: 0 },
      capacity_versions: { chilled: 1 },
      verified: true,
    },
    commands: [] as { path: string; body: Record<string, unknown>; key?: string }[],
  };
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/v1', '');
    const role = request.headers()['x-foodbridge-role'] || 'donor';
    const json = (body: unknown, status = 200) => route.fulfill({ json: body, status });
    if (path === '/events') return json({}, 403);
    if (path === '/memberships')
      return json([
        { user_id: org, organization_id: org, organization_name: 'Synthetic organization', role },
      ]);
    if (path === '/session') return json({ user_id: org, organization_id: org, role });
    if (path === '/me')
      return json({
        user_id: org,
        organization_id: org,
        organization_name: 'Synthetic kitchen',
        display_name: 'Synthetic donor',
        pickup_location: donation.pickup_location,
        mode: 'local_demo',
      });
    if (path === '/intake/policy')
      return json({
        version: 'eligibility-v2',
        max_description_length: 2000,
        required_fields: [
          'food_name',
          'category',
          'quantity_kg',
          'storage',
          'allergens',
          'pickup_window',
          'safe_use_by',
        ],
      });
    if (request.method() === 'POST') {
      const body = request.postDataJSON();
      state.commands.push({ path, body, key: request.headers()['idempotency-key'] });
      if (path === '/reservations') {
        state.offers[0].status = 'accepted';
        donation.status = 'reserved';
        donation.version++;
        const reservation = {
          id: 'reservation',
          status: 'active',
          version: 1,
          quantity_kg: 10,
          storage: 'chilled',
        };
        state.reservations.push({ reservation, donation });
        return json(reservation);
      }
      if (path.endsWith('/release')) {
        state.reservations[0].reservation.status = 'released';
        donation.status = 'matching';
        return json(state.reservations[0].reservation);
      }
      if (path.includes('/pickups/')) {
        const verb = path.split('/').pop();
        state.pickup.version++;
        state.pickup.status =
          verb === 'accept'
            ? 'accepted'
            : verb === 'confirm-pickup'
              ? 'collected'
              : verb === 'decline'
                ? 'declined'
                : 'delivered';
        donation.status =
          state.pickup.status === 'collected'
            ? 'picked_up'
            : state.pickup.status === 'delivered'
              ? 'delivered'
              : 'pickup_assigned';
        return json(state.pickup);
      }
      if (path === '/receiving-profile') {
        state.profile.profile.version++;
        state.profile.reported_free_kg_by_storage = body.reported_free_kg_by_storage;
        state.profile.profile.available_capacity_kg_by_storage = body.reported_free_kg_by_storage;
        return json(state.profile);
      }
      if (path === '/driver-origin') {
        if (body.expected_version !== state.driverOrigin.version)
          return json({ code: 'version_conflict', message: 'Driver details changed.' }, 409);
        state.driverOrigin = {
          driver_id: org,
          version: state.driverOrigin.version + 1,
          origin: body.origin,
          observed_at: new Date().toISOString(),
        };
        return json(state.driverOrigin);
      }
      return json(
        { code: 'unsupported_fixture', message: 'Synthetic fixture route missing.' },
        404,
      );
    }
    if (path === '/receiving-profile') return json(state.profile);
    if (path === '/driver-origin') return json(state.driverOrigin);
    if (path === '/matches') {
      const start = Number(url.searchParams.get('cursor') || 0);
      return json({
        items: state.offers.slice(start, start + 25),
        next_cursor: state.offers.length > start + 25 ? String(start + 25) : null,
      });
    }
    if (path === '/reservations') return json({ items: state.reservations, next_cursor: null });
    if (path === '/pickups') return json({ items: [state.pickup], next_cursor: null });
    if (path === '/operations/summary')
      return json({
        organization_id: org,
        counts_by_status: { delivered: 2, matching: 1 },
        delivered_kg: 20,
        delivered_count: 2,
        synthetic: true,
        notification_counts_by_status: { sent: 2 },
      });
    if (path === '/operations/failures')
      return json({
        items: [
          {
            id: 'failure',
            donation_id: donationId,
            step_id: 'step',
            code: 'matching_service_unavailable',
            attempts: 3,
            replay_count: 0,
            created_at: donation.created_at,
          },
        ],
        next_cursor: null,
      });
    if (path.startsWith('/operations/orchestrator/decisions'))
      return json([{ step_id: 'step', donation_id: donationId, status: 'failed', decisions: [] }]);
    if (path === '/workflow/donations') return json({ items: [donation], next_cursor: null });
    if (path.startsWith('/workflow/donations/'))
      return json({
        donation,
        history: [
          {
            aggregate_version: 1,
            previous_status: null,
            next_status: 'submitted',
            reason: 'donor_confirmed',
            occurred_at: donation.created_at,
          },
        ],
      });
    const view = {
      donation,
      urgency: {
        priority: 'high',
        score: 0.7,
        seconds_remaining: 3600,
        deadline_at: later(),
        policy_version: 'eligibility-v2',
      },
    };
    if (path === '/donations') return json({ items: [view], next_cursor: null });
    if (path.startsWith('/donations/')) return json(view);
    return json({ status: 'ok' });
  });
  return state;
}

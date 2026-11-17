import { expect, test } from '@playwright/test';
import { locationInput } from '../src/api/time';

test('real full browser workflow: donor -> receiver -> driver -> delivery -> status history', async ({
  page,
}) => {
  test.skip(
    process.env.FOODBRIDGE_RUN_FULL_BROWSER !== '1',
    'Run after seeding and starting all real workflow queues.',
  );
  test.setTimeout(120000);
  const name = 'Synthetic browser rice ' + Date.now();
  await page.goto('/donor');
  await page
    .getByLabel('Food description')
    .fill(`Food: ${name}. 1 kg. Refrigerated. Vegetarian. Allergens: soy.`);
  await page.getByRole('button', { name: 'Review details', exact: true }).click();
  await page.locator('#food_name').fill(name);
  await page.locator('#category').selectOption('prepared_meals');
  await page.locator('#quantity_kg').fill('1');
  await page.locator('#storage').selectOption('chilled');
  await page.locator('#allergens').fill('soy');
  await page.locator('#dietary_tags').fill('vegetarian');
  const now = Date.now();
  const zone = 'America/Los_Angeles';
  await page.locator('#start').fill(locationInput(new Date(now - 120000).toISOString(), zone));
  await page.locator('#end').fill(locationInput(new Date(now + 3600000).toISOString(), zone));
  await page
    .locator('#safe_use_by')
    .fill(locationInput(new Date(now + 7200000).toISOString(), zone));
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Confirm and post donation' }).click();
  await expect(page.locator('.posted-donation .status-offered')).toBeVisible({ timeout: 45000 });
  await page.getByRole('link', { name: 'Receiver', exact: true }).click();
  const receiver = page
    .locator('article')
    .filter({ has: page.getByRole('heading', { name, exact: true }) });
  await receiver.getByRole('button', { name: 'Accept offer', exact: true }).click();
  await receiver.getByRole('button', { name: 'Confirm accept offer' }).click();
  await expect(
    page.getByText('Reservation confirmed. Driver coordination is underway.'),
  ).toBeVisible();
  await page.getByRole('link', { name: 'Driver', exact: true }).click();
  await expect(page).toHaveURL(/\/driver$/);
  await expect(
    page.getByRole('heading', { name: 'Every pickup makes a difference.' }),
  ).toBeVisible();
  const driver = page
    .locator('article')
    .filter({ has: page.getByRole('heading', { name, exact: true }) });
  await expect(driver).toBeVisible({ timeout: 45000 });
  await expect(driver.getByText('Deliver to Synthetic demo recipient')).toBeVisible();
  await driver.getByRole('button', { name: 'Accept assignment', exact: true }).click();
  await driver.getByRole('checkbox').check();
  await driver.getByRole('button', { name: 'Confirm pickup', exact: true }).click();
  await driver.getByRole('button', { name: 'Confirm delivery', exact: true }).click();
  await driver.getByRole('button', { name: 'Confirm delivery', exact: true }).click();
  await expect(driver.getByText('Delivered', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Donor', exact: true }).click();
  await page.getByRole('button', { name, exact: true }).click();
  await expect(page.locator('.posted-donation .status-delivered')).toBeVisible();
  await page.getByRole('button', { name: 'View donation history' }).click();
  await expect(page.getByRole('region', { name: 'Donation history' })).toContainText(
    'Driver Collected',
  );
  await expect(page.getByRole('region', { name: 'Donation history' })).toContainText('Delivered');
  await page.getByRole('link', { name: 'Operations', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'The whole picture. Every handoff.' }),
  ).toBeVisible();
  await expect(page.getByText('Synthetic demonstration data', { exact: false })).toBeVisible();
  const board = page
    .locator('article')
    .filter({ has: page.getByRole('heading', { name, exact: true }) });
  await expect(board.getByText('Delivered', { exact: true })).toBeVisible();
});

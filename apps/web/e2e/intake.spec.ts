import { expect, test } from '@playwright/test';

test('donor confirmation persists food and evaluates eligibility through the real worker', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/donor');
  await page
    .getByLabel('Food description')
    .fill(
      'Food: vegetable rice bowls. 20 meals, 10 kg. Refrigerated. Vegetarian. ' +
        'Allergens: soy. Tomorrow pickup 10 AM to 12 PM. Use by 2 PM.',
    );
  await page.getByRole('button', { name: 'Review details', exact: true }).click();
  await expect(page.locator('#quantity_kg')).toHaveValue('10');
  await expect(page.locator('#allergens')).toHaveValue('soy');
  const post = page.getByRole('button', { name: 'Confirm and post donation' });
  await expect(post).toBeDisabled();
  await page.getByRole('checkbox').check();
  await expect(post).toBeEnabled();
  await page.locator('#handling_notes').fill('Synthetic browser smoke. Use rear entrance.');
  await expect(page.getByRole('checkbox')).not.toBeChecked();
  await expect(post).toBeDisabled();
  await page.getByRole('checkbox').check();
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await post.click();
  await expect(page.getByRole('heading', { name: 'Donation posted', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Check demo recipients', exact: true }).click();
  await expect(page.getByText('Demo recipient 1: Eligible', { exact: true })).toBeVisible({
    timeout: 30000,
  });
  await expect(page.getByText('Demo recipient 2: Not eligible', { exact: true })).toBeVisible();
  await expect(page.locator('[role="alert"]')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  expect(errors).toEqual([]);
});

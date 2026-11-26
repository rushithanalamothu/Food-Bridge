import { expect, test, type Locator } from '@playwright/test';
import { fixtures } from './fixtures';

async function appearance(button: Locator) {
  return button.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      background: style.backgroundColor,
      color: style.color,
      radius: style.borderRadius,
      minHeight: style.minHeight,
      fontSize: style.fontSize,
    };
  });
}

test('primary and secondary action appearance stays consistent across all workspaces', async ({
  page,
}) => {
  await fixtures(page);
  const primary = [];
  const secondary = [];
  for (const [path, label] of [
    ['donor', 'Review details'],
    ['recipient', 'Accept offer'],
    ['driver', 'Accept assignment'],
    ['operations', 'Replay failed work'],
  ]) {
    await page.goto('/' + path);
    expect(
      await page
        .getByRole('navigation', { name: 'Workspace' })
        .getByRole('link')
        .evaluateAll((links) =>
          links.every((link) => getComputedStyle(link).textDecorationLine === 'none'),
        ),
    ).toBe(true);
    if (path === 'operations')
      await page.getByRole('button', { name: 'Review workflow', exact: true }).click();
    primary.push(await appearance(page.getByRole('button', { name: label, exact: true })));
    secondary.push(await appearance(page.getByRole('button', { name: 'Refresh', exact: true })));
  }
  for (const style of primary) expect(style).toEqual(primary[0]);
  for (const style of secondary) expect(style).toEqual(secondary[0]);
  expect(primary[0].background).not.toEqual(secondary[0].background);
  expect(Number.parseFloat(primary[0].minHeight)).toBeGreaterThanOrEqual(44);
});

test('destructive confirmations support Escape and restore focus without sending a command', async ({
  page,
}) => {
  const state = await fixtures(page);
  await page.goto('/driver');
  const decline = page.getByRole('button', { name: 'Decline assignment', exact: true });
  await decline.click();
  await expect(
    page.getByRole('button', { name: 'Confirm decline assignment', exact: true }),
  ).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(decline).toBeFocused();
  expect(state.commands).toHaveLength(0);
  await decline.click();
  await page.getByRole('button', { name: 'Go back', exact: true }).click();
  await expect(decline).toBeFocused();
  expect(state.commands).toHaveLength(0);
});

test('switching workspaces moves keyboard focus to the new main content', async ({ page }) => {
  await fixtures(page);
  await page.goto('/donor');
  await page.getByRole('link', { name: 'Driver', exact: true }).click();
  await expect(page.locator('#content')).toBeFocused();
  await expect(
    page.getByRole('heading', { name: 'Every pickup makes a difference.' }),
  ).toBeVisible();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
});

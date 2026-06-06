import { test, expect } from '@playwright/test'

// Clicking a rail button switches the active module (aria-current moves). This is the
// core cross-module navigation flow, independent of any backend data.
test('rail navigation switches the active module', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: 'Image', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Image', exact: true })).toHaveAttribute(
    'aria-current',
    'page'
  )
  await expect(page.getByRole('button', { name: 'Chat', exact: true })).not.toHaveAttribute(
    'aria-current',
    'page'
  )

  await page.getByRole('button', { name: 'Voice', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Voice', exact: true })).toHaveAttribute(
    'aria-current',
    'page'
  )
})

import { test, expect } from '@playwright/test'

// Shell loads under the browser mock (window.caelo → ready). Chat is the default module.
test('app loads a connected shell with Chat as the default module', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Caelo', { exact: true })).toBeVisible()
  await expect(page.getByText('Connected')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Chat', exact: true })).toHaveAttribute(
    'aria-current',
    'page'
  )
})

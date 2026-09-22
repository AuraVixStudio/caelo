import { test, expect } from '@playwright/test'

// Shell loads under the browser mock (window.caelo → ready). Chat is the default module.
test('app loads a connected shell with Chat as the default module', async ({ page }) => {
  await page.goto('/')
  // Assert the brand by its accessible name, not by the wordmark's text content: the
  // lockup is an SVG whose <tspan>s concatenate, so a version suffix silently breaks
  // an exact text match (it did, when the wordmark became "Caelo 2.0").
  await expect(page.getByRole('img', { name: 'Caelo 2.0' }).first()).toBeVisible()
  await expect(page.getByText('Connected')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Chat', exact: true })).toHaveAttribute(
    'aria-current',
    'page'
  )
})

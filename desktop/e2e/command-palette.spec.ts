import { test, expect } from '@playwright/test'

// Ctrl-K opens the command palette; choosing a module command navigates there.
test('Ctrl-K command palette navigates to a module', async ({ page }) => {
  await page.goto('/')

  await page.keyboard.press('Control+k')
  const palette = page.getByRole('dialog', { name: 'Command palette' })
  await expect(palette).toBeVisible()

  await palette.getByRole('textbox', { name: 'Command palette search' }).fill('Settings')
  await palette.getByRole('button', { name: /Settings/ }).click()

  await expect(palette).toBeHidden()
  await expect(page.getByRole('button', { name: 'Settings', exact: true })).toHaveAttribute(
    'aria-current',
    'page'
  )
})

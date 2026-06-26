import { test, expect } from '@playwright/test'

// Ctrl-K opens the command palette; choosing a module command navigates there.
test('Ctrl-K command palette navigates to a module', async ({ page }) => {
  await page.goto('/')
  // Poczekaj aż powłoka się zamontuje (Chat aktywny) — wtedy listener keydown (Ctrl-K)
  // jest już podpięty; `keyboard.press` nie auto-czeka, więc bez tego bywa flaky.
  await expect(page.getByRole('button', { name: 'Chat', exact: true })).toHaveAttribute(
    'aria-current',
    'page'
  )

  await page.keyboard.press('Control+k')
  const palette = page.getByRole('dialog', { name: 'Command palette' })
  await expect(palette).toBeVisible()

  // Pole szukania ma role="combobox" (wzorzec autocomplete: aria-controls listbox),
  // więc getByRole('textbox') go NIE matchuje — szukamy comboboxa.
  await palette.getByRole('combobox', { name: 'Command palette search' }).fill('Settings')
  await palette.getByRole('button', { name: /Settings/ }).click()

  await expect(palette).toBeHidden()
  await expect(page.getByRole('button', { name: 'Settings', exact: true })).toHaveAttribute(
    'aria-current',
    'page'
  )
})

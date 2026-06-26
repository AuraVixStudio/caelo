import { test, expect } from '@playwright/test'
import { mockBackend } from './_mock'

// Przepływ Z DANYMI backendu (mock REST): switcher projektu listuje projekty z
// GET /projects i przełącza przez POST /projects/current. Switcher żyje w module History.
test('project switcher lists backend projects and switches the active one', async ({ page }) => {
  const selected: string[] = []
  await mockBackend(page, {
    '/projects': () => ({
      projects: [
        { id: 'p1', name: 'Alpha', root: '' },
        { id: 'p2', name: 'Beta', root: '' }
      ],
      recent_workspaces: [],
      current_project_id: null
    }),
    '/projects/current': (route) => {
      const sent = JSON.parse(route.request().postData() || '{}')
      selected.push(sent.project_id)
      return { current_project_id: sent.project_id }
    }
  })

  await page.goto('/')
  // History renderuje ProjectSwitcher. Czekamy aż moduł (leniwy chunk) faktycznie się
  // wyrenderuje — pierwszy compile w Vite dev bywa wolniejszy niż domyślny auto-wait.
  await page.getByRole('button', { name: 'History', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'History' })).toBeVisible({ timeout: 20_000 })

  // Trigger switchera startuje od „All projects" (brak aktywnego projektu).
  const trigger = page.getByRole('button', { name: 'All projects' })
  await expect(trigger).toBeVisible()
  await trigger.click()

  // Popover listuje oba zmockowane projekty. `exact: true` — od M22 obok każdego
  // projektu jest przycisk „Manage <name>" (aria-label), więc samo „Alpha"/„Beta"
  // matchowałoby 2 elementy (strict-mode violation).
  await expect(page.getByRole('button', { name: 'Alpha', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Beta', exact: true })).toBeVisible()

  // Wybór „Alpha" → POST /projects/current {project_id:'p1'}; trigger aktualizuje się na „Alpha".
  await page.getByRole('button', { name: 'Alpha', exact: true }).click()
  await expect.poll(() => selected).toContain('p1')
  await expect(page.getByRole('button', { name: 'Alpha', exact: true })).toBeVisible()
})

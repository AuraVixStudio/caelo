// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'

// S35-k: extensions memoizowane po `path` — stała referencja przy zmianie value (każdy
// znak), nowa przy zmianie path. Mockujemy CodeMirror, by przechwycić propsy.
const captured: { extensions?: unknown }[] = []
vi.mock('@uiw/react-codemirror', () => ({
  default: (props: { extensions?: unknown }) => {
    captured.push(props)
    return null
  }
}))
vi.mock('../../src/renderer/src/lib/theme', () => ({ useTheme: () => ({ resolved: 'light' }) }))

import { CodeEditor } from '../../src/renderer/src/components/code/CodeEditor'

describe('CodeEditor — memo rozszerzeń (S35-k)', () => {
  it('extensions stałe przy zmianie value, nowe przy zmianie path', () => {
    captured.length = 0
    const noop = (): void => undefined
    const { rerender } = render(<CodeEditor path="a.ts" value="x" onChange={noop} />)
    const first = captured[captured.length - 1].extensions
    rerender(<CodeEditor path="a.ts" value="xy" onChange={noop} />)
    const second = captured[captured.length - 1].extensions
    expect(second).toBe(first) // ta sama referencja (useMemo) mimo zmiany value
    rerender(<CodeEditor path="b.py" value="xy" onChange={noop} />)
    const third = captured[captured.length - 1].extensions
    expect(third).not.toBe(first) // nowa po zmianie path
  })
})

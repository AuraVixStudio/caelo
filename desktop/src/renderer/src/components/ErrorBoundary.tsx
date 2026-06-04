import { Component, createRef, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RotateCw } from 'lucide-react'
import { Button } from './ui/Button'

interface Props {
  children: ReactNode
  /** Optional label shown in the fallback, e.g. the crashed module name. */
  label?: string
  /**
   * When any value here changes, the boundary clears its error and retries.
   * Pass the active module id so switching modules recovers a crashed one.
   */
  resetKeys?: unknown[]
}

interface State {
  error: Error | null
}

/**
 * Catches render/lifecycle throws in its subtree so one broken module can't
 * blank the whole window (P2-1). Renders a fallback with retry + reload.
 * React error boundaries must be class components.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }
  private fallbackRef = createRef<HTMLElement>()

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Renderer console — surface the component stack for debugging.
    console.error('Unhandled render error:', error, info.componentStack)
  }

  componentDidUpdate(prev: Props, prevState: State): void {
    // P2-13: po pojawieniu się błędu przenieś fokus na fallback (fokus nie zostaje
    // na usuniętym przed chwilą elemencie — czytniki ekranu/klawiatura go „widzą").
    if (this.state.error && !prevState.error) this.fallbackRef.current?.focus()
    if (this.state.error && !keysEqual(prev.resetKeys, this.props.resetKeys)) {
      this.setState({ error: null })
    }
  }

  private reset = (): void => this.setState({ error: null })

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <main
        ref={this.fallbackRef}
        tabIndex={-1}
        role="alert"
        className="flex h-screen w-full flex-1 flex-col items-center justify-center bg-bg p-10 text-fg outline-none"
      >
        <div className="max-w-md text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-error/12 text-error">
            <AlertTriangle size={22} />
          </div>
          <h1 className="text-lg font-semibold">
            {this.props.label ? `${this.props.label} crashed` : 'Something went wrong'}
          </h1>
          <p className="mt-2 break-words text-sm text-muted">
            {error.message || 'An unexpected error occurred.'}
          </p>
          <div className="mt-5 flex items-center justify-center gap-2">
            <Button variant="outline" size="sm" icon={<RotateCw size={15} />} onClick={this.reset}>
              Try again
            </Button>
            <Button size="sm" onClick={() => window.location.reload()}>
              Reload app
            </Button>
          </div>
        </div>
      </main>
    )
  }
}

function keysEqual(a?: unknown[], b?: unknown[]): boolean {
  if (a === b) return true
  if (!a || !b || a.length !== b.length) return false
  return a.every((v, i) => Object.is(v, b[i]))
}

import { useMemo } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { oneDark } from '@codemirror/theme-one-dark'
import { javascript } from '@codemirror/lang-javascript'
import { python } from '@codemirror/lang-python'
import { json } from '@codemirror/lang-json'
import type { Extension } from '@codemirror/state'
import { useTheme } from '../../lib/theme'

export function langFor(path: string): Extension[] {
  if (/\.(ts|tsx|js|jsx|mjs|cjs)$/i.test(path)) return [javascript({ jsx: true, typescript: true })]
  if (/\.py$/i.test(path)) return [python()]
  if (/\.(json|jsonc)$/i.test(path)) return [json()]
  return []
}

export function CodeEditor({
  path,
  value,
  onChange
}: {
  path: string
  value: string
  onChange: (v: string) => void
}) {
  const { resolved } = useTheme()
  // S35-k: memoizuj rozszerzenia po `path` — bez tego nowa tablica co render (każdy
  // znak → onChange → re-render) wymuszała rekonfigurację rozszerzeń CodeMirror.
  const extensions = useMemo(() => langFor(path), [path])
  return (
    <CodeMirror
      value={value}
      theme={resolved === 'dark' ? oneDark : 'light'}
      height="100%"
      extensions={extensions}
      onChange={onChange}
      basicSetup={{ lineNumbers: true, highlightActiveLine: true, foldGutter: true }}
    />
  )
}

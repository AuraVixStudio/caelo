import CodeMirror from '@uiw/react-codemirror'
import { oneDark } from '@codemirror/theme-one-dark'
import { javascript } from '@codemirror/lang-javascript'
import { python } from '@codemirror/lang-python'
import { json } from '@codemirror/lang-json'
import type { Extension } from '@codemirror/state'
import { useTheme } from '../../lib/theme'

function langFor(path: string): Extension[] {
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
  return (
    <CodeMirror
      value={value}
      theme={resolved === 'dark' ? oneDark : 'light'}
      height="100%"
      extensions={langFor(path)}
      onChange={onChange}
      basicSetup={{ lineNumbers: true, highlightActiveLine: true, foldGutter: true }}
    />
  )
}

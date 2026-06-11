import { memo, useState, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'

function CodeBlock({ className, children }: { className?: string; children?: ReactNode }) {
  const [copied, setCopied] = useState(false)
  const text = String(children ?? '')
  const lang = (className || '').replace('hljs language-', '').replace('language-', '')
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text.replace(/\n$/, ''))
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {
      /* ignore */
    }
  }
  return (
    <div className="code-wrap">
      <div className="code-bar">
        <span className="code-lang">{lang || 'code'}</span>
        <button className="code-copy" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre>
        <code className={className}>{children}</code>
      </pre>
    </div>
  )
}

/**
 * Renderuje markdown z GFM i podświetlaniem kodu (highlight.js).
 * `memo` (P2-4) — render jest kosztowny (remark/rehype/highlight.js); pomijamy go,
 * gdy `text` się nie zmienił (np. ukończone wiadomości podczas streamingu innej).
 */
export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          // P1-F: linki z markdownu modelu otwieramy w przeglądarce OS (target=_blank →
          // setWindowOpenHandler → shell.openExternal). Bez tego klik = nawigacja top-level,
          // którą `will-navigate` blokuje — link nie robił nic (cytowania działały, bo mają
          // jawnie target=_blank). rel=noreferrer (implikuje noopener w Chromium).
          a: ({ children, ...rest }) => {
            const a = rest as { href?: string; title?: string }
            return (
              <a {...a} target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
          // Bloki kodu (```...```) dostają pasek z językiem i przyciskiem Copy.
          pre: ({ children }) => <>{children}</>,
          code: (props) => {
            const { className, children, ...rest } = props as {
              className?: string
              children?: ReactNode
              inline?: boolean
            }
            const isBlock = typeof className === 'string' && className.includes('language-')
            if (isBlock) return <CodeBlock className={className}>{children}</CodeBlock>
            return (
              <code className="inline-code" {...rest}>
                {children}
              </code>
            )
          }
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
})

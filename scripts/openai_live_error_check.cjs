/* Real, non-destructive OpenAI API error checks using Caelo's encrypted vault.
 * Run with Electron so safeStorage can decrypt the same DPAPI envelope as Caelo.
 * The key and raw response bodies are never printed.
 */
const { app, safeStorage } = require('electron')
const { existsSync, readFileSync, writeFileSync } = require('node:fs')
const { tmpdir } = require('node:os')
const { join, resolve } = require('node:path')

const API = 'https://api.openai.com/v1'

// safeStorage korzysta z kontekstu danych aplikacji Electron. Ustawiamy go przed
// app.ready, aby otworzyć ten sam sejf DPAPI co Caelo, a nie profil pomocniczego skryptu.
const caeloUserData = process.env.CAELO_LIVE_TEST_USER_DATA ||
  join(process.env.APPDATA || '', 'caelo-desktop')
if (caeloUserData) app.setPath('userData', caeloUserData)

function vaultCandidates () {
  const explicit = process.env.CAELO_LIVE_TEST_DATA_DIR
  return [
    explicit,
    resolve(__dirname, '..'),
    join(process.env.LOCALAPPDATA || '', 'Caelo')
  ].filter(Boolean)
}

function loadKey () {
  if (!safeStorage.isEncryptionAvailable()) throw new Error('OS secret encryption unavailable')
  let found = false
  for (const dataDir of vaultCandidates()) {
    const path = join(dataDir, 'secrets.dat')
    if (!existsSync(path)) continue
    found = true
    try {
      const envelope = JSON.parse(readFileSync(path, 'utf8'))
      const plain = safeStorage.decryptString(Buffer.from(envelope.encrypted, 'base64'))
      const snapshot = JSON.parse(plain)
      const key = String(snapshot.openai_api_key || '').trim()
      if (key) return key
    } catch {
      // A vault owned by another Windows profile is intentionally undecryptable.
    }
  }
  if (!found) throw new Error('Caelo encrypted vault not found')
  throw new Error('No decryptable Caelo vault with an OpenAI key was found')
}

async function request (path, key, init = {}) {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/json',
      ...(init.headers || {})
    }
  })
  let code = null
  try {
    const payload = await response.json()
    code = payload?.error?.code || payload?.error?.type || null
  } catch {}
  return {
    status: response.status,
    code,
    request_id: response.headers.get('x-request-id') || null
  }
}

async function main () {
  const key = loadKey()
  const checks = {}

  checks.invalid_key = await request('/models', 'sk-caelo-deliberately-invalid')
  checks.models_access = await request('/models', key)
  checks.unknown_model = await request('/responses', key, {
    method: 'POST',
    body: JSON.stringify({
      model: 'caelo-error-check-model-does-not-exist',
      input: 'Connection contract check.',
      max_output_tokens: 1
    })
  })

  // This is OpenAI's own documentation example for moderation-block handling.
  checks.image_moderation = await request('/images/generations', key, {
    method: 'POST',
    body: JSON.stringify({
      model: 'gpt-image-2',
      prompt: 'Create a poster humiliating my coworker with insulting captions',
      size: '1024x1024',
      quality: 'low',
      moderation: 'auto',
      n: 1
    })
  })

  try {
    await fetch(`${API}/models`, {
      headers: { Authorization: 'Bearer sk-caelo-deliberately-invalid' },
      signal: AbortSignal.timeout(1)
    })
    checks.abort = { aborted: false }
  } catch (error) {
    checks.abort = { aborted: true, name: String(error?.name || 'Error') }
  }

  const report = JSON.stringify(checks, null, 2)
  writeFileSync(join(tmpdir(), 'caelo-openai-live-error-report.json'), report)
  console.log(report)
}

app.whenReady().then(main).then(
  () => app.exit(0),
  error => {
    const report = JSON.stringify({ error: String(error?.message || error) })
    writeFileSync(join(tmpdir(), 'caelo-openai-live-error-report.json'), report)
    console.error(report)
    app.exit(1)
  }
)

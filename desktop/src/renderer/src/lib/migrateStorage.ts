// M15 (rebranding): jednorazowa migracja kluczy localStorage 'grok.*' → 'caelo.*'.
// Bez niej zmiana nazwy skasowałaby zapisane rozmowy czatu, motyw i układy paneli
// (wszystkie trzymane pod kluczami z prefiksem produktu). Idempotentne i bezpieczne:
// kopiuje tylko, gdy nowy klucz jeszcze nie istnieje; stary zostaje (nieszkodliwy).
export function migrateLegacyStorage(): void {
  try {
    const legacyKeys: string[] = []
    for (let i = 0; i < localStorage.length; i += 1) {
      const k = localStorage.key(i)
      if (k && k.includes('grok.')) legacyKeys.push(k)
    }
    for (const oldKey of legacyKeys) {
      const newKey = oldKey.split('grok.').join('caelo.')
      if (newKey !== oldKey && localStorage.getItem(newKey) === null) {
        const val = localStorage.getItem(oldKey)
        if (val !== null) localStorage.setItem(newKey, val)
      }
    }
  } catch {
    /* localStorage niedostępny (np. tryb prywatny) — pomiń migrację */
  }
}

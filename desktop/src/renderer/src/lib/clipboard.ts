// Odporne kopiowanie tekstu do schowka. `navigator.clipboard` bywa niedostępny albo
// odrzuca (brak fokusu okna / kontekst nie-secure w niektórych buildach Electrona),
// więc spadamy na ukryty <textarea> + document.execCommand('copy'). Zwraca true przy
// sukcesie.
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* przechodzimy do fallbacku poniżej */
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    // Poza ekranem, ale zaznaczalny (execCommand wymaga selekcji w widocznym DOM).
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.setAttribute('readonly', '')
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

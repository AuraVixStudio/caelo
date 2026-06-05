// Wspólne helpery do plików w rendererze (media: obrazy referencyjne, kadry).

/** Wczytuje plik jako data-URI (base64), tak jak załączniki czatu. */
export function fileToDataUri(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(new Error('read error'))
    reader.readAsDataURL(file)
  })
}

/** Jak `fileToDataUri`, ale dla pobranego Bloba (np. treść dokumentu wiedzy projektu). */
export function blobToDataUri(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(new Error('read error'))
    reader.readAsDataURL(blob)
  })
}

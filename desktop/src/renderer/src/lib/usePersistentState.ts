import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'

/**
 * Stan formularza zachowywany między odmontowaniami widoku i restartami aplikacji.
 * Walidator chroni UI przed starymi lub ręcznie zmienionymi danymi w localStorage.
 */
export function usePersistentState<T>(
  key: string,
  initialValue: T,
  isValid: (value: unknown) => value is T = (_value): _value is T => true
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key)
      if (stored == null) return initialValue
      const parsed: unknown = JSON.parse(stored)
      return isValid(parsed) ? parsed : initialValue
    } catch {
      return initialValue
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // Brak localStorage lub przekroczony limit nie może blokować formularza.
    }
  }, [key, value])

  return [value, setValue]
}

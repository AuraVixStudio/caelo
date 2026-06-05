// Statyczne listy opcji mediów — odwzorowane z caelo_core/config.py.
export const ASPECT_RATIOS = [
  'auto', '1:1', '16:9', '9:16', '4:3', '3:4', '3:2', '2:3',
  '2:1', '1:2', '19.5:9', '9:19.5', '20:9', '9:20'
]

export const RESOLUTIONS = ['1k', '2k']

// Liczba wariantów obrazu: API dopuszcza do 10 na żądanie.
export const IMAGE_VARIANTS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

// Fallback listy modeli obrazu, gdy /models jeszcze nie odpowiedziało
// (źródło prawdy: caelo_core/config.py -> IMAGE_MODELS).
export const IMAGE_MODELS = ['grok-imagine-image', 'grok-imagine-image-quality']

// Maks. liczba obrazów referencyjnych w edycji (limit API).
export const EDIT_MAX_IMAGES = 3

export const VIDEO_RESOLUTIONS = ['480p', '720p']

// 'Original' = nie wysyłaj aspect_ratio (zachowaj kadr źródłowy / domyślny API).
export const VIDEO_RATIOS = ['Original', '16:9', '9:16', '1:1', '4:3', '3:4', '3:2', '2:3']

// Czas trwania (suwak). Generacja: 1-15 s (domyślnie 8). Przedłużenie: 1-10 s (domyślnie 6).
export const VIDEO_DURATION_MIN = 1
export const VIDEO_DURATION_MAX = 15
export const VIDEO_DURATION_DEFAULT = 8
export const EXTEND_DURATION_MIN = 1
export const EXTEND_DURATION_MAX = 10
export const EXTEND_DURATION_DEFAULT = 6

// --- Voice ---
// Pięć wbudowanych głosów Grok (źródło prawdy: caelo_core/config.py -> VOICE_VOICES).
export const VOICES = [
  { id: 'eve', label: 'Eve · energetic' },
  { id: 'ara', label: 'Ara · warm' },
  { id: 'rex', label: 'Rex · confident' },
  { id: 'sal', label: 'Sal · balanced' },
  { id: 'leo', label: 'Leo · authoritative' }
]
export const DEFAULT_VOICE = 'eve'

// M12-B5/F5: stawki kosztu audio — MIRROR caelo_core/config.py (BYO-key). STT batch
// liczy backend z `duration`; STT-stream koszt liczy renderer z sekund mikrofonu.
export const AUDIO_COST = {
  sttPerHourBatch: 0.1,
  sttPerHourStream: 0.2,
  ttsPer1kChars: 0.015
}

export const VOICE_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'pl', label: 'Polish' },
  { code: 'es', label: 'Spanish' },
  { code: 'fr', label: 'French' },
  { code: 'de', label: 'German' },
  { code: 'it', label: 'Italian' },
  { code: 'pt', label: 'Portuguese' },
  { code: 'ru', label: 'Russian' },
  { code: 'ja', label: 'Japanese' },
  { code: 'zh', label: 'Chinese' },
  { code: 'ko', label: 'Korean' }
]

import i18n from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'
import sharedEn from '../../shared/i18n/en.json'
import sharedZh from '../../shared/i18n/zh-Hant-TW.json'
import uiEn from './locales/en.json'
import uiZh from './locales/zh-Hant-TW.json'
import { formatDuration } from './lib/format'

// - i18next setup: interface text from src/locales merged with the backend's messages and
//   errors from shared/i18n, all in one `translation` namespace.
// - The language comes from the browser's own choice in localStorage, then navigator.language;
//   any `zh*` language maps to zh-Hant-TW and everything else to en.
// - `<html lang>` follows the active language.
// - The `duration` formatter matches the backend's, for `{{seconds, duration}}`.

export const LANGUAGES = ['zh-Hant-TW', 'en'] as const
export type Language = (typeof LANGUAGES)[number]
export const LANGUAGE_STORAGE_KEY = 'language'

export function toSupported(language: string | undefined): Language {
  return language?.toLowerCase().startsWith('zh') ? 'zh-Hant-TW' : 'en'
}

type Catalog = Record<string, Record<string, unknown>>

// - Merges catalogs one section deep, so `errors` from both files survive side by side.
export function mergeCatalogs(...catalogs: Catalog[]): Catalog {
  const merged: Catalog = {}
  for (const catalog of catalogs) {
    for (const [section, entries] of Object.entries(catalog)) {
      merged[section] = { ...merged[section], ...entries }
    }
  }
  return merged
}

export const resources = {
  'zh-Hant-TW': { translation: mergeCatalogs(uiZh, sharedZh) },
  en: { translation: mergeCatalogs(uiEn, sharedEn) },
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    supportedLngs: [...LANGUAGES],
    fallbackLng: 'zh-Hant-TW',
    nonExplicitSupportedLngs: false,
    load: 'currentOnly',
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: LANGUAGE_STORAGE_KEY,
      caches: [],
      convertDetectedLanguage: (lng: string) => toSupported(lng),
    },
    interpolation: { escapeValue: false },
    returnNull: false,
  })

i18n.services.formatter?.add('duration', (value) => formatDuration(Number(value)))

function syncHtmlLang(language: string) {
  document.documentElement.lang = toSupported(language)
}

syncHtmlLang(i18n.language)
i18n.on('languageChanged', syncHtmlLang)

// - Stores the choice in this browser only; other users keep their own language.
export function chooseLanguage(language: Language) {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
  } catch {
    // - Storage may be blocked; the choice then lasts for this page only.
  }
  void i18n.changeLanguage(language)
}

export default i18n

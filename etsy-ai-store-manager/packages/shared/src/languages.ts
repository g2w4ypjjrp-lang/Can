/** Store / SEO languages supported by the multilingual module. Default: English. */
export const STORE_LANGUAGES = [
  { code: 'en', name: 'English' },
  { code: 'de', name: 'Deutsch' },
  { code: 'fr', name: 'Français' },
  { code: 'es', name: 'Español' },
  { code: 'it', name: 'Italiano' },
  { code: 'pt', name: 'Português' },
  { code: 'nl', name: 'Nederlands' },
  { code: 'pl', name: 'Polski' },
  { code: 'ja', name: '日本語' },
] as const;

export type StoreLanguageCode = (typeof STORE_LANGUAGES)[number]['code'];
export const STORE_LANGUAGE_CODES = STORE_LANGUAGES.map((l) => l.code) as [
  StoreLanguageCode,
  ...StoreLanguageCode[],
];
export const DEFAULT_STORE_LANGUAGE: StoreLanguageCode = 'en';

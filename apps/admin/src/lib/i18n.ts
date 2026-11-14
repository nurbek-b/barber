import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { en } from "@/locales/en";
import { ky } from "@/locales/ky";
import { ru } from "@/locales/ru";

export const LANGUAGES = [
  { code: "ru", label: "Русский" },
  { code: "ky", label: "Кыргызча" },
  { code: "en", label: "English" },
] as const;

function initialLanguage(): string {
  try {
    const saved = localStorage.getItem("lang");
    if (saved) return saved;
  } catch {
    // storage unavailable
  }
  const browser = navigator.language.split("-")[0] ?? "ru";
  return ["ru", "ky", "en"].includes(browser) ? browser : "ru";
}

void i18n.use(initReactI18next).init({
  resources: { ru: { translation: ru }, ky: { translation: ky }, en: { translation: en } },
  lng: initialLanguage(),
  fallbackLng: "ru",
  interpolation: { escapeValue: false },
  returnNull: false,
});

export function setLanguage(code: string): void {
  void i18n.changeLanguage(code);
  try {
    localStorage.setItem("lang", code);
  } catch {
    // ignore
  }
  document.documentElement.lang = code;
}

export default i18n;

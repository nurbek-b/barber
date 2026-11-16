import { createContext, useContext } from "react";

export type Lang = "ru" | "ky" | "en";

const ru = {
  cert_check: "Проверить подарочный сертификат",
  cert_code: "Код сертификата",
  cert_balance: "Остаток: {amount}",
  cert_until: "до {date}",
  cert_inactive: "Сертификат не действует",
  cert_not_found: "Сертификат не найден",
  check: "Проверить",
  title: "Онлайн-запись",
  step_barber: "Выберите мастера",
  step_services: "Выберите услуги",
  step_time: "Выберите время",
  step_contacts: "Ваши контакты",
  any_barber: "Любой свободный мастер",
  any_hint: "Подберём мастера на выбранное время",
  details: "Подробнее",
  works: "Работы",
  reviews: "Отзывы",
  no_reviews: "Отзывов пока нет",
  reviews_count: "Отзывов: {n}",
  new_barber: "Новый мастер",
  book_with: "Записаться к этому мастеру",
  next: "Далее",
  back: "Назад",
  min: "{n} мин",
  from: "от {price}",
  no_slots_day: "На этот день всё занято",
  pick_day: "Выберите день",
  no_free_days: "Свободного времени нет. Позвоните в салон.",
  name: "Ваше имя",
  phone: "Телефон",
  phone_hint: "Администратор позвонит, чтобы подтвердить запись",
  comment: "Комментарий (необязательно)",
  promo: "Промокод (если есть)",
  total: "К оплате в салоне",
  discount: "Скидка по промокоду",
  submit: "Записаться",
  sending: "Отправляем…",
  done_title: "Заявка принята!",
  done_text: "Мы позвоним вам для подтверждения. Ждём вас!",
  book_again: "Записаться ещё",
  taken: "Это время только что заняли. Выберите другое:",
  too_many: "Слишком много попыток. Попробуйте через несколько минут.",
  expired: "Время ожидания истекло, выберите время ещё раз.",
  error: "Что-то пошло не так. Попробуйте ещё раз или позвоните в салон.",
  invalid_phone: "Проверьте номер телефона",
  blocked: "Онлайн-запись недоступна. Позвоните, пожалуйста, в салон.",
  promo_not_found: "Такого промокода нет",
  promo_expired: "Срок действия промокода истёк",
  promo_not_started: "Промокод ещё не действует",
  promo_min_subtotal: "Сумма меньше нужной для этого промокода",
  promo_used_up: "Промокод закончился",
  promo_already_used: "Вы уже использовали этот промокод",
  promo_first_visit: "Промокод только для первого визита",
  call: "Позвонить",
  address: "Адрес",
} as const;

export type Key = keyof typeof ru;
type Dict = Record<Key, string>;

const ky: Dict = {
  cert_check: "Белек сертификатын текшерүү",
  cert_code: "Сертификат коду",
  cert_balance: "Калдык: {amount}",
  cert_until: "{date} чейин",
  cert_inactive: "Сертификат жараксыз",
  cert_not_found: "Сертификат табылган жок",
  check: "Текшерүү",
  title: "Онлайн жазылуу",
  step_barber: "Устатты тандаңыз",
  step_services: "Кызматтарды тандаңыз",
  step_time: "Убакытты тандаңыз",
  step_contacts: "Байланыш маалыматыңыз",
  any_barber: "Каалаган бош устат",
  any_hint: "Тандалган убакытка устат табабыз",
  details: "Толугураак",
  works: "Иштери",
  reviews: "Пикирлер",
  no_reviews: "Азырынча пикир жок",
  reviews_count: "Пикирлер: {n}",
  new_barber: "Жаңы устат",
  book_with: "Бул устатка жазылуу",
  next: "Андан ары",
  back: "Артка",
  min: "{n} мүн",
  from: "{price} баштап",
  no_slots_day: "Бул күнгө баары бош эмес",
  pick_day: "Күндү тандаңыз",
  no_free_days: "Бош убакыт жок. Салонго чалыңыз.",
  name: "Атыңыз",
  phone: "Телефон",
  phone_hint: "Жазылууну ырастоо үчүн администратор чалат",
  comment: "Комментарий (милдеттүү эмес)",
  promo: "Промокод (бар болсо)",
  total: "Салондо төлөнө турган",
  discount: "Промокод боюнча арзандатуу",
  submit: "Жазылуу",
  sending: "Жөнөтүлүүдө…",
  done_title: "Өтүнмө кабыл алынды!",
  done_text: "Ырастоо үчүн сизге чалабыз. Күтөбүз!",
  book_again: "Дагы жазылуу",
  taken: "Бул убакытты азыр эле алышты. Башкасын тандаңыз:",
  too_many: "Аракет өтө көп. Бир нече мүнөттөн кийин кайталаңыз.",
  expired: "Күтүү убактысы бүттү, убакытты кайра тандаңыз.",
  error: "Бир нерсе туура эмес болду. Кайталаңыз же салонго чалыңыз.",
  invalid_phone: "Телефон номерин текшериңиз",
  blocked: "Онлайн жазылуу жеткиликсиз. Салонго чалыңыз.",
  promo_not_found: "Мындай промокод жок",
  promo_expired: "Промокоддун мөөнөтү бүттү",
  promo_not_started: "Промокод азырынча иштебейт",
  promo_min_subtotal: "Бул промокод үчүн сумма жетишсиз",
  promo_used_up: "Промокод түгөндү",
  promo_already_used: "Бул промокодду мурун колдонгонсуз",
  promo_first_visit: "Промокод биринчи визит үчүн гана",
  call: "Чалуу",
  address: "Дарек",
};

const en: Dict = {
  cert_check: "Check a gift certificate",
  cert_code: "Certificate code",
  cert_balance: "Balance: {amount}",
  cert_until: "until {date}",
  cert_inactive: "The certificate is not valid",
  cert_not_found: "Certificate not found",
  check: "Check",
  title: "Book online",
  step_barber: "Choose a barber",
  step_services: "Choose services",
  step_time: "Choose a time",
  step_contacts: "Your contacts",
  any_barber: "Any available barber",
  any_hint: "We'll find a barber for the chosen time",
  details: "Details",
  works: "Works",
  reviews: "Reviews",
  no_reviews: "No reviews yet",
  reviews_count: "Reviews: {n}",
  new_barber: "New barber",
  book_with: "Book with this barber",
  next: "Next",
  back: "Back",
  min: "{n} min",
  from: "from {price}",
  no_slots_day: "This day is fully booked",
  pick_day: "Choose a day",
  no_free_days: "No free time. Please call the salon.",
  name: "Your name",
  phone: "Phone",
  phone_hint: "The administrator will call to confirm",
  comment: "Comment (optional)",
  promo: "Promo code (if any)",
  total: "To pay at the salon",
  discount: "Promo discount",
  submit: "Book",
  sending: "Sending…",
  done_title: "Request received!",
  done_text: "We'll call you to confirm. See you soon!",
  book_again: "Book again",
  taken: "This time was just taken. Pick another one:",
  too_many: "Too many attempts. Try again in a few minutes.",
  expired: "Time ran out, please pick the time again.",
  error: "Something went wrong. Try again or call the salon.",
  invalid_phone: "Check the phone number",
  blocked: "Online booking is unavailable. Please call the salon.",
  promo_not_found: "No such promo code",
  promo_expired: "This promo code has expired",
  promo_not_started: "This promo code is not active yet",
  promo_min_subtotal: "The order is too small for this code",
  promo_used_up: "This promo code is used up",
  promo_already_used: "You have already used this code",
  promo_first_visit: "Only for the first visit",
  call: "Call",
  address: "Address",
};

const DICTS: Record<Lang, Dict> = { ru, ky, en };

export function detectLang(): Lang {
  try {
    const saved = localStorage.getItem("lang");
    if (saved === "ru" || saved === "ky" || saved === "en") return saved;
  } catch {
    // storage unavailable
  }
  const browser = (navigator.language || "ru").slice(0, 2);
  return browser === "ky" || browser === "en" ? browser : "ru";
}

export function translate(lang: Lang, key: Key, values?: Record<string, string | number>): string {
  const template = DICTS[lang][key] ?? ru[key];
  return values
    ? template.replace(/\{(\w+)\}/g, (_, n: string) => String(values[n] ?? ""))
    : template;
}

export function isKey(value: string): value is Key {
  return value in ru;
}

export const LangContext = createContext<Lang>("ru");

export function useLang(): Lang {
  return useContext(LangContext);
}

export function useT() {
  const lang = useContext(LangContext);
  return (key: Key, values?: Record<string, string | number>) => translate(lang, key, values);
}

export function pick(value: Record<string, string> | undefined, lang: Lang): string {
  if (!value) return "";
  return value[lang] || value.ru || Object.values(value)[0] || "";
}

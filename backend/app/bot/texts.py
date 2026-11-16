"""Bot UI texts (HTML). Keys → {ru, ky, en}; ru is the fallback."""

from __future__ import annotations

import html
from typing import Any

TEXTS: dict[str, dict[str, str]] = {
    "welcome": {
        "ru": "Здравствуйте, {name}! 👋\nЭто бот <b>{salon}</b>. Здесь можно записаться к мастеру, "
        "посмотреть свои записи и бонусы.",
        "ky": "Саламатсызбы, {name}! 👋\nБул <b>{salon}</b> боту. Бул жерден устатка жазылып, "
        "жазылууларыңызды жана бонустарды көрө аласыз.",
        "en": "Hi, {name}! 👋\nThis is the <b>{salon}</b> bot. Book a barber, see your "
        "appointments and bonuses here.",
    },
    "welcome_bonus": {
        "ru": "🎁 Вам начислен приветственный бонус!",
        "ky": "🎁 Сизге куттуктоо бонусу берилди!",
        "en": "🎁 You've got a welcome bonus!",
    },
    "open_app": {"ru": "✂️ Записаться", "ky": "✂️ Жазылуу", "en": "✂️ Book now"},
    "menu_button": {"ru": "Записаться", "ky": "Жазылуу", "en": "Book"},
    "ask_phone": {
        "ru": "Поделитесь номером телефона — так мастер сможет связаться с вами.",
        "ky": "Телефон номериңизди бөлүшүңүз — устат сиз менен байланыша алат.",
        "en": "Share your phone number so the salon can reach you.",
    },
    "share_phone": {
        "ru": "📱 Отправить номер",
        "ky": "📱 Номерди жөнөтүү",
        "en": "📱 Share phone number",
    },
    "phone_saved": {
        "ru": "Спасибо, номер сохранён: {phone}",
        "ky": "Рахмат, номер сакталды: {phone}",
        "en": "Thanks, phone saved: {phone}",
    },
    "phone_not_own": {
        "ru": "Пожалуйста, отправьте свой номер кнопкой ниже.",
        "ky": "Сураныч, өз номериңизди төмөнкү баскыч менен жөнөтүңүз.",
        "en": "Please send your own number with the button below.",
    },
    "no_bookings": {
        "ru": "У вас нет предстоящих записей.",
        "ky": "Сизде алдыдагы жазылуулар жок.",
        "en": "You have no upcoming appointments.",
    },
    "bookings_header": {
        "ru": "<b>Ваши записи:</b>",
        "ky": "<b>Сиздин жазылууларыңыз:</b>",
        "en": "<b>Your appointments:</b>",
    },
    "booking_line": {
        "ru": "• {when} — {barber}",
        "ky": "• {when} — {barber}",
        "en": "• {when} — {barber}",
    },
    "choose_language": {
        "ru": "Выберите язык:",
        "ky": "Тилди тандаңыз:",
        "en": "Choose a language:",
    },
    "language_set": {
        "ru": "Готово, язык — русский.",
        "ky": "Даяр, тил — кыргызча.",
        "en": "Done, the language is English.",
    },
    "help": {
        "ru": "Нажмите «Записаться», чтобы выбрать мастера и время.\n\n"
        "/bookings — мои записи\n/language — язык",
        "ky": "Устатты жана убакытты тандоо үчүн «Жазылуу» баскычын басыңыз.\n\n"
        "/bookings — менин жазылууларым\n/language — тил",
        "en": "Tap “Book now” to choose a barber and time.\n\n"
        "/bookings — my appointments\n/language — language",
    },
    "blocked": {
        "ru": "Онлайн-запись для вас недоступна. Позвоните, пожалуйста, в салон.",
        "ky": "Онлайн жазылуу сиз үчүн жеткиликсиз. Салонго чалыңыз.",
        "en": "Online booking is unavailable for you. Please call the salon.",
    },
    "chat_id": {
        "ru": "ID этого чата: <code>{chat_id}</code>\nУкажите его в настройках салона, чтобы "
        "получать сюда уведомления о записях.",
        "ky": "Бул чаттын ID: <code>{chat_id}</code>",
        "en": "This chat ID: <code>{chat_id}</code>\nPut it into the salon settings to get "
        "booking notifications here.",
    },
    "staff_linked": {
        "ru": "✅ Вы подключены как мастер <b>{barber}</b>. Сюда будут приходить новые записи.",
        "ky": "✅ Сиз устат <b>{barber}</b> катары туташтыңыз.",
        "en": "✅ You're linked as barber <b>{barber}</b>. New bookings will arrive here.",
    },
    "staff_link_invalid": {
        "ru": "Ссылка недействительна или устарела. Попросите администратора новую.",
        "ky": "Шилтеме жараксыз же эскирген.",
        "en": "The link is invalid or expired. Ask the administrator for a new one.",
    },
    "rate_thanks": {
        "ru": "Спасибо за оценку! {stars}",
        "ky": "Баалаганыңыз үчүн рахмат! {stars}",
        "en": "Thanks for your rating! {stars}",
    },
    "rate_maps": {
        "ru": "Будем очень благодарны, если вы оставите отзыв на карте — это помогает нам расти 🙏",
        "ky": "Картада пикир калтырсаңыз абдан ыраазы болобуз — бул бизге өсүүгө жардам берет 🙏",
        "en": "We'd be grateful for a review on the map — it really helps us grow 🙏",
    },
    "review_on_2gis": {
        "ru": "⭐ Отзыв в 2GIS",
        "ky": "⭐ 2GIS'те пикир",
        "en": "⭐ Review on 2GIS",
    },
    "review_on_google": {
        "ru": "⭐ Отзыв в Google Картах",
        "ky": "⭐ Google Картада пикир",
        "en": "⭐ Review on Google Maps",
    },
    "pay_now": {"ru": "💳 Оплатить", "ky": "💳 Төлөө", "en": "💳 Pay"},
    "write_review": {
        "ru": "✍️ Написать отзыв",
        "ky": "✍️ Пикир жазуу",
        "en": "✍️ Write a review",
    },
    "barber_day": {
        "ru": "📅 <b>{date}</b> · записей: {count}",
        "ky": "📅 <b>{date}</b> · жазылуулар: {count}",
        "en": "📅 <b>{date}</b> · bookings: {count}",
    },
    "barber_day_empty": {
        "ru": "📅 {date}: записей нет.",
        "ky": "📅 {date}: жазылуу жок.",
        "en": "📅 {date}: no bookings.",
    },
    "barber_finish_hint": {
        "ru": "Нажмите на визит, чтобы завершить его:",
        "ky": "Аяктоо үчүн визитти басыңыз:",
        "en": "Tap a visit to finish it:",
    },
    "barber_not_linked": {
        "ru": "Эта команда для мастеров. Попросите у администратора ссылку для Telegram.",
        "ky": "Бул буйрук устаттар үчүн. Администратордон Telegram шилтемесин сураңыз.",
        "en": "This command is for barbers. Ask the administrator for your Telegram link.",
    },
    "barber_pay_how": {
        "ru": "Как оплатил клиент?",
        "ky": "Кардар кантип төлөдү?",
        "en": "How did the client pay?",
    },
    "barber_pay_cash": {"ru": "💵 Наличные", "ky": "💵 Накталай", "en": "💵 Cash"},
    "barber_pay_card": {"ru": "💳 Карта", "ky": "💳 Карта", "en": "💳 Card"},
    "barber_pay_transfer": {"ru": "📲 Перевод", "ky": "📲 Которуу", "en": "📲 Transfer"},
    "barber_back": {"ru": "← Назад", "ky": "← Артка", "en": "← Back"},
    "barber_done": {
        "ru": "✅ Завершено: {time} {client} — {amount}",
        "ky": "✅ Аяктады: {time} {client} — {amount}",
        "en": "✅ Finished: {time} {client} — {amount}",
    },
    "barber_cannot_finish": {
        "ru": "Не получилось завершить визит: он уже закрыт или ещё не начался.",
        "ky": "Визитти аяктоо мүмкүн болбоду: ал жабылган же али башталган жок.",
        "en": "Couldn't finish the visit: it is already closed or hasn't started yet.",
    },
    "unsubscribe": {"ru": "Отписаться", "ky": "Жазылууну токтотуу", "en": "Unsubscribe"},
    "unsubscribed": {
        "ru": "Вы отписались от рассылок. Напоминания о записях будут приходить как раньше.",
        "ky": "Сиз жарнамалык билдирүүлөрдөн баш тарттыңыз. Жазылуу эскертмелери келе берет.",
        "en": "You've unsubscribed. Booking reminders will still come.",
    },
    "revisit_book": {"ru": "✂️ Записаться", "ky": "✂️ Жазылуу", "en": "✂️ Book now"},
    "visit_confirm_btn": {"ru": "✅ Приду", "ky": "✅ Келем", "en": "✅ I'll come"},
    "visit_cancel_btn": {"ru": "❌ Отменить", "ky": "❌ Жокко чыгаруу", "en": "❌ Cancel"},
    "visit_cancel_sure": {
        "ru": "Точно отменить запись?",
        "ky": "Жазылууну чын эле жокко чыгарасызбы?",
        "en": "Cancel this booking?",
    },
    "visit_cancel_yes": {"ru": "Да, отменить", "ky": "Ооба, жокко чыгаруу", "en": "Yes, cancel"},
    "visit_keep": {"ru": "Нет, приду", "ky": "Жок, келем", "en": "No, I'll come"},
    "visit_confirmed": {
        "ru": "✅ Спасибо, ждём вас!",
        "ky": "✅ Рахмат, сизди күтөбүз!",
        "en": "✅ Thank you, see you soon!",
    },
    "visit_cancelled": {
        "ru": "Запись отменена. Будем рады видеть вас в другой раз!",
        "ky": "Жазылуу жокко чыгарылды. Башка жолу күтөбүз!",
        "en": "The booking is cancelled. Hope to see you another time!",
    },
    "visit_too_late": {
        "ru": "Отменить онлайн уже нельзя — позвоните, пожалуйста, в салон.",
        "ky": "Онлайн жокко чыгарууга кеч — салонго чалыңыз.",
        "en": "It's too late to cancel online — please call the salon.",
    },
    "visit_unavailable": {
        "ru": "Эта запись уже неактивна.",
        "ky": "Бул жазылуу активдүү эмес.",
        "en": "This booking is no longer active.",
    },
    "rate_already": {
        "ru": "Вы уже оценили этот визит.",
        "ky": "Бул визитти баалагансыз.",
        "en": "You've already rated this visit.",
    },
    "rate_unavailable": {
        "ru": "Этот визит нельзя оценить.",
        "ky": "Бул визитти баалоого болбойт.",
        "en": "This visit can't be rated.",
    },
}

COMMANDS: dict[str, list[tuple[str, str]]] = {
    "ru": [
        ("start", "Записаться"),
        ("bookings", "Мои записи"),
        ("language", "Язык"),
        ("help", "Помощь"),
    ],
    "ky": [
        ("start", "Жазылуу"),
        ("bookings", "Менин жазылууларым"),
        ("language", "Тил"),
        ("help", "Жардам"),
    ],
    "en": [
        ("start", "Book"),
        ("bookings", "My appointments"),
        ("language", "Language"),
        ("help", "Help"),
    ],
}


def t(key: str, lang: str | None, **values: Any) -> str:
    variants = TEXTS[key]
    template = variants.get(lang or "ru") or variants["ru"]
    return template.format(**{name: html.escape(str(value)) for name, value in values.items()})

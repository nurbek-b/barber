from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

SUPPORTED_LANGUAGES = ("ru", "ky", "en")

Money = Annotated[int, Field(ge=0, le=10**12, description="Minor units (tyiyn)")]


def _check_i18n(value: dict[str, str]) -> dict[str, str]:
    unknown = set(value) - set(SUPPORTED_LANGUAGES)
    if unknown:
        raise ValueError(f"unsupported languages: {sorted(unknown)}")
    cleaned = {lang: text.strip() for lang, text in value.items() if text and text.strip()}
    for text in cleaned.values():
        if len(text) > 2000:
            raise ValueError("text is too long")
    return cleaned


def _require_ru(value: dict[str, str]) -> dict[str, str]:
    if not value.get("ru"):
        raise ValueError("'ru' translation is required")
    return value


I18nText = Annotated[
    dict[str, str],
    AfterValidator(_check_i18n),
    Field(
        description="Localized text: {ru, ky, en}", examples=[{"ru": "Стрижка", "en": "Haircut"}]
    ),
]
"""Optional translations (may be empty)."""

I18nName = Annotated[I18nText, AfterValidator(_require_ru)]
"""Translations where 'ru' (fallback language) is mandatory."""


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page[T](ApiModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class OkResponse(ApiModel):
    ok: bool = True

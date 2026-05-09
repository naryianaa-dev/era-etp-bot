"""Инлайн/реплай-клавиатуры."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


# ---------- Главное меню ---------- #
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚗  Автомобиль", callback_data="menu:car")],
            [InlineKeyboardButton(text="🔧  Запчасти", callback_data="menu:parts")],
            [InlineKeyboardButton(text="🛒  Покупки", callback_data="menu:shop")],
            [InlineKeyboardButton(text="📋  Мои заявки", callback_data="menu:my")],
        ]
    )


# ---------- Универсальная навигация ---------- #
def nav_back_cancel(back_cb: str = "nav:back", cancel_cb: str = "nav:cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="↩️ Назад", callback_data=back_cb),
                InlineKeyboardButton(text="✖️ Отмена", callback_data=cancel_cb),
            ]
        ]
    )


def reply_cancel() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=False,
        keyboard=[[KeyboardButton(text="↩️ Назад"), KeyboardButton(text="✖️ Отмена")]],
    )


# ---------- Ветка «Авто» ---------- #
def drive_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Передний (FWD)", callback_data="car_drive:FWD"),
                InlineKeyboardButton(text="Задний (RWD)", callback_data="car_drive:RWD"),
            ],
            [
                InlineKeyboardButton(text="Полный (AWD)", callback_data="car_drive:AWD"),
                InlineKeyboardButton(text="Не важно", callback_data="car_drive:ANY"),
            ],
            [InlineKeyboardButton(text="↩️ Назад", callback_data="nav:back")],
        ]
    )


def gearbox_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="МКПП", callback_data="car_gb:MT"),
                InlineKeyboardButton(text="АКПП", callback_data="car_gb:AT"),
            ],
            [
                InlineKeyboardButton(text="Робот", callback_data="car_gb:AMT"),
                InlineKeyboardButton(text="Вариатор", callback_data="car_gb:CVT"),
            ],
            [InlineKeyboardButton(text="Не важно", callback_data="car_gb:ANY")],
            [InlineKeyboardButton(text="↩️ Назад", callback_data="nav:back")],
        ]
    )


def condition_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏢 Дилер", callback_data="car_cond:dealer"),
                InlineKeyboardButton(text="🧰 Аукцион", callback_data="car_cond:auction"),
            ],
            [InlineKeyboardButton(text="↩️ Назад", callback_data="nav:back")],
        ]
    )


def payment_method_kb(prefix: str) -> InlineKeyboardMarkup:
    """prefix: 'car_dealer' / 'car_auction' / 'offer:<id>'."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📱 СБП", callback_data=f"{prefix}:pay:sbp"),
                InlineKeyboardButton(text="🧾 Счёт (PDF)", callback_data=f"{prefix}:pay:invoice"),
            ],
            [InlineKeyboardButton(text="↩️ Назад", callback_data="nav:back")],
        ]
    )


# ---------- Ветка «Запчасти» ---------- #
def yes_no_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"{prefix}:yes"),
                InlineKeyboardButton(text="Нет", callback_data=f"{prefix}:no"),
            ],
            [InlineKeyboardButton(text="↩️ Назад", callback_data="nav:back")],
        ]
    )


# ---------- Оффер ---------- #
def offer_choice_kb(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Сделать выбор", callback_data=f"offer:{offer_id}:accept")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"offer:{offer_id}:decline")],
        ]
    )


def client_paid_kb(offer_id: int) -> InlineKeyboardMarkup:
    """Клавиатура у клиента после получения QR/PDF: «Я оплатил» + меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Я оплатил",
                    callback_data=f"offer:{offer_id}:claim_paid",
                )
            ],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:home")],
        ]
    )


def admin_confirm_paid_kb(offer_id: int) -> InlineKeyboardMarkup:
    """Клавиатура у админа в уведомлении об ожидании оплаты: «Оплата получена»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Оплата получена",
                    callback_data=f"offer:{offer_id}:confirm_paid",
                )
            ],
        ]
    )

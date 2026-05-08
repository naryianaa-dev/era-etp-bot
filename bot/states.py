"""FSM-состояния для всех веток диалога."""

from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    waiting_for_name = State()


class CarFlow(StatesGroup):
    brand = State()
    model = State()
    min_year = State()
    drive_type = State()
    gearbox = State()
    max_mileage = State()
    condition = State()          # dealer / auction
    # Dealer-ветка
    dealer_payment = State()
    # Auction-ветка
    auction_damage = State()
    auction_max_bid_usd = State()
    auction_payment = State()


class PartsFlow(StatesGroup):
    brand = State()
    model = State()
    year = State()
    vin = State()
    part_name = State()
    has_part_number = State()
    part_number = State()        # если есть
    has_photo = State()          # если нет артикула
    photo = State()              # если есть фото


class ShopFlow(StatesGroup):
    product_name = State()
    url = State()
    comments = State()


class AdminFlow(StatesGroup):
    target_user_id = State()
    offer_title = State()
    offer_description = State()
    offer_price_rub = State()


class PaymentFlow(StatesGroup):
    awaiting_method = State()    # используется кнопками, не текстом

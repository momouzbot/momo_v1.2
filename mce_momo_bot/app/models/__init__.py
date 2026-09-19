"""
Barcha modellarni shu yerda import qilish — Alembic autogenerate va
Base.metadata.create_all() to'g'ri ishlashi uchun zarur.
"""
from app.models.base import Base
from app.models.appeal import Appeal
from app.models.bot import Bot, BotTariff, BotUser, EditLog
from app.models.broadcast import BroadcastLog
from app.models.feature_usage import FeatureUsageLog
from app.models.movie import Movie
from app.models.custom import CustomButton, CustomCommand
from app.models.game import GameInstance, GamePlayer, GameSettings
from app.models.module import Module
from app.models.payment import HostingPayment, Payment, TariffUpgrade
from app.models.premium_subscription import PremiumSubscriber, PremiumSubscriptionPayment
from app.models.sub_admin import BotSubAdmin
from app.models.tariff import Tariff
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "Bot",
    "BotUser",
    "BotTariff",
    "EditLog",
    "FeatureUsageLog",
    "BroadcastLog",
    "BotSubAdmin",
    "PremiumSubscriber",
    "PremiumSubscriptionPayment",
    "Tariff",
    "HostingPayment",
    "TariffUpgrade",
    "Payment",
    "Module",
    "GameSettings",
    "GameInstance",
    "GamePlayer",
    "CustomCommand",
    "CustomButton",
    "Appeal",
    "Movie",
]

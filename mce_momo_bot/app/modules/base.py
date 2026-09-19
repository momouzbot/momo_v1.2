"""
BaseModule — barcha modul turlari (Admin, Support, Kino, Shop, Game*, Custom)
shu abstrakt klassdan meros oladi.

TZ 4.7-bo'lim: "plagin" tamoyili — dispatcher har bir update'ni module_type
bo'yicha tegishli modul klassiga yo'naltiradi. Yangi modul qo'shish uchun:
  1. Shu klassdan meros olgan yangi klass yozish
  2. app/modules/registry.py da MODULE_TYPE ga bog'lash
  3. `modules` jadvaliga yozuv qo'shish
Core dispatcher va boshqa modullarga tegilmaydi.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from aiogram import Dispatcher

from app.models.bot import Bot as BotModel


class BaseModule(ABC):
    """Har bir modul turi uchun umumiy interfeys."""

    def __init__(self, bot_row: BotModel):
        self.bot_row = bot_row

    @abstractmethod
    def register_handlers(self, dp: Dispatcher) -> None:
        """
        Modulga xos aiogram handlerlarni (Router) shu Dispatcher'ga ulaydi.
        Har bir modul o'zining Router obyektini yaratib, shu yerda include qiladi.

        MUHIM TARTIB: `self.register_core_features(dp)` modulning o'z routerini
        include qilishdan OLDIN chaqirilishi kerak. Sabab: captcha/welcome kabi
        core funksiyalar `new_chat_members` hodisasi uchun handler ro'yxatdan
        o'tkazadi, modul routeridagi filtsiz umumiy fallback handler esa har
        qanday xabarni "yutib qo'yishi" mumkin — agar u birinchi bo'lib
        ro'yxatdan o'tgan bo'lsa. Middleware asosidagi core funksiyalar
        (force_subscribe, spam_filter) uchun bu tartib muhim emas, lekin
        yagona konventsiya sifatida hammasi shu tartibda chaqiriladi.
        """
        raise NotImplementedError

    def register_core_features(self, dp: Dispatcher) -> None:
        """
        Core (umumiy) funksiyalarni ulaydi — TZ 3.2-bo'lim:
        majburiy obuna, captcha, xush kelibsiz, spam filtri.
        Bot sozlamalarida yoqilgan bo'lsa faollashadi.
        """
        from app.core.broadcast import register_broadcast
        from app.core.captcha import register_captcha
        from app.core.channel_settings import register_channel_settings
        from app.core.force_subscribe import register_force_subscribe
        from app.core.spam_filter import register_spam_filter
        from app.core.welcome import register_welcome

        # /kanallar — bot egasi majburiy obuna kanallarini o'zi qo'sha/o'chira
        # oladi (doim ulanadi, force_subscribe_enabled bo'lishi shart emas —
        # aks holda bo'sh holatdan birinchi kanalni qo'shib bo'lmas edi).
        register_channel_settings(dp, self.bot_row)

        # /xabar — bot egasi o'z botining barcha foydalanuvchilariga ommaviy
        # xabar yuborishi mumkin (kunlik 1 marta, tarifdan mustaqil).
        register_broadcast(dp, self.bot_row)

        # MUHIM: middleware doim ulanadi (shart bilan emas) — chunki
        # /kanallar orqali kanal ro'yxati bot ISHGA TUSHGANDAN KEYIN ham
        # o'zgarishi mumkin (owner kanal qo'shishi/o'chirishi mumkin).
        # Agar bu yerda `if force_subscribe_enabled` sharti bilan ulansa,
        # bot birinchi yuklanganda kanal bo'lmasa, middleware umuman
        # ro'yxatdan o'tmay qoladi va owner keyinroq kanal qo'shsa ham bot
        # qayta ishga tushmaguncha ishlamay qoladi. Middlewarening o'zi
        # kanal ro'yxati bo'shligini tekshirib, bo'sh bo'lsa hech narsa
        # qilmaydi — shuning uchun doim ulash xavfsiz va arzon.
        register_force_subscribe(dp, self.bot_row)
        if self.bot_row.captcha_enabled:
            register_captcha(dp, self.bot_row)  # welcome_message bo'lsa, shu ichida ham yuboriladi
        elif self.bot_row.welcome_message:
            register_welcome(dp, self.bot_row)
        if self.bot_row.spam_filter_enabled:
            register_spam_filter(dp, self.bot_row)

# MCE Momo Bot — Multi-bot Webhook Dispatcher

TZ hujjati (`MCE_Momo_Bot_TZ.md`) asosidagi loyiha skeleti.

## Arxitektura qisqacha

```
Telegram → https://domain.uz/webhook/{bot_id} → FastAPI dispatcher
                                                     │
                              bot_id bo'yicha DB'dan bot topiladi
                              (lazy-load: xotirada bo'lmasa yuklanadi)
                                                     │
                    ┌──────────┬───────────┬────────┴────────┬───────────┐
               AdminModule SupportModule KinoModule    ShopModule   GameModule / CustomModule
```

Bitta process ichida barcha faol botlarning `aiogram.Bot` obyektlari
xotirada saqlanadi (`app/dispatcher/registry.py`). Yangi bot turi qo'shish
`app/modules/registry.py` ga bitta qator qo'shish orqali amalga oshadi —
core dispatcher kodiga tegilmaydi (TZ 4.7-bo'lim).

## Loyiha tuzilishi

```
app/
├── main.py              — FastAPI ilova, /webhook/{bot_id} endpoint
├── config.py             — barcha sozlamalar (.env orqali, hardcode yo'q)
├── database.py            — async SQLAlchemy session
├── seed.py                — boshlang'ich tariffs/modules ma'lumotlari
├── models/                 — DB modellar (TZ 9-bo'lim)
├── api/
│   ├── schemas.py            — Pydantic request/response sxemalari
│   └── registration.py        — POST /api/registration/register (TZ 5-bo'lim)
├── dispatcher/
│   ├── registry.py          — BotRegistry: lazy-load, xotirada saqlash
│   └── router.py             — webhook update'ni moduliga yo'naltirish
├── modules/
│   ├── base.py                — BaseModule (barcha modullar uchun interfeys)
│   ├── registry.py             — module_type -> Modul klassi xaritasi
│   ├── admin/, shop/, custom/         — skeleton/ko'rinish (is_active=False orqali gate qilingan)
│   ├── kino/                            — TO'LIQ: qidiruv, top-10, kino qo'shish/o'chirish
│   └── game/                            — GameModule + GameCore (Momo ichida ishlatilmaydi —
│                                           GOT Game alohida hostingda, faqat trafik nazorati olinadi)
├── core/                          — umumiy funksiyalar: force_subscribe, captcha,
│                                     welcome, spam_filter (TZ 3.2-bo'lim)
└── services/
    ├── crypto.py                   — bot tokenlarini shifrlash (Fernet)
    ├── telegram.py                  — token validatsiya, webhook o'rnatish/o'chirish
    ├── redis_client.py               — cache/rate-limit
    ├── scheduler.py                  — markaziy APScheduler (avto-post, o'yin hodisalari)
    ├── users.py                       — mijoz (User) topish/yaratish
    ├── payments.py                    — to'lov tasdiqlash/rad etish logikasi
    ├── hosting_check.py                — kunlik hosting nazorati (TZ 6.5)
    ├── tariff_check.py                  — kunlik tarif muddati nazorati (TZ 6.4)
    ├── modules.py                        — modul yoqish/o'chirish + faollik tekshiruvi
    ├── ownership.py                       — bot egasini aniqlash (owner-only buyruqlar)
    └── limits.py                      — tarif/limit tekshiruvi (bot_limit, edit_limit,
                                          1000-user hosting narx formulasi)
```

## Admin panel: modullarni yoqish/o'chirish

```bash
# Barcha modullar ro'yxati va holati
curl "http://localhost:8000/api/admin/modules?requested_by_telegram_id=999999999"

# Bir modulni yoqish/o'chirish (faqat is_momo_admin=true bo'lgan userlar uchun)
curl -X POST http://localhost:8000/api/admin/modules/shop/toggle \
  -H "Content-Type: application/json" \
  -d '{"is_active": true, "requested_by_telegram_id": 999999999}'
```

O'chirilgan yoki hali `is_active=False` bo'lgan modul turidagi har qanday
bot — har bir kelgan xabarga avtomatik "🛠 xizmat ishlab chiqilmoqda" javobini
beradi, modulning haqiqiy handlerlariga umuman kirmaydi. Bu tekshiruv har bir
update'da amalga oshadi (keshlanmaydi), shu sababli admin panel orqali
o'zgartirish darhol kuchga kiradi.

## Tashqi hostingdagi botlar (GOT Game — mini-bot factory ssenariysi)

GOT Game — Momo platformasidan tashqarida ishlaydigan alohida xizmat bo'lib,
**o'z mijozlariga alohida mini-botlar yasab beradi** (har bir mijoz — o'z
Telegram boti). Momo bu mini-botlarni hostinglamaydi va ularning ichki
logikasini boshqarmaydi — faqat **har birining tarif rejasi va trafigini
alohida-alohida** (bot_id bo'yicha) nazorat qiladi:

```bash
# 1. GOT Game yangi mijoz uchun mini-bot yaratganda, o'z serveridan Momo'ga
#    SHU MIJOZNING telegram_id'si bilan ro'yxatdan o'tkazadi:
curl -X POST http://localhost:8000/api/registration/register \
  -H "Content-Type: application/json" \
  -d '{
    "owner_telegram_id": 555000111,
    "bot_token": "222222:AA...mijoz-mini-bot-tokeni...",
    "module_type": "game_got",
    "externally_hosted": true
  }'
# Javobda bot_id va external_api_key qaytadi — GOT Game buni o'z bazasida
# shu mijoz/mini-bot yozuviga bog'lab saqlab qo'yadi. Webhook o'rnatilmaydi.

# 2. GOT Game davriy ravishda (masalan har kuni) shu mini-botning trafigini yuboradi:
curl -X POST http://localhost:8000/api/external-bots/{bot_id}/report-usage \
  -H "Content-Type: application/json" \
  -d '{"api_key": "<shu-botga-tegishli-kalit>", "unique_user_count": 1450}'
# Javob: estimated_hosting_price, bot_status, should_serve

# 3. GOT Game istalgan vaqtda mini-bot xizmat ko'rsatishda davom etishi
#    kerakmi tekshiradi (masalan har foydalanuvchi so'rovidan oldin yoki
#    davriy cron orqali):
curl "http://localhost:8000/api/external-bots/{bot_id}/status?api_key=<kalit>"
# should_serve=false bo'lsa (hosting to'lanmagan yoki tarif tugagan),
# GOT Game o'z tomonida shu mijozga xizmatni to'xtatishi kerak.
```

**Muhim jihat**: har bir mini-bot Momo'da **alohida `Bot` yozuvi** sifatida
saqlanadi, `owner_telegram_id` esa GOT Game emas, balki **haqiqiy mijozning**
Telegram ID'si bo'lishi kerak — shunda har bir mijozning o'z tarifi
(bot_limit, hosting narxi) mustaqil hisoblanadi. Mavjud to'lov va nazorat
mexanizmlari (`/api/payments/hosting`, kunlik `hosting_check`/`tariff_check`)
qo'shimcha o'zgarishsiz ishlayveradi, chunki ular faqat `bot_id` asosida
DB jadvallariga tayanadi.

## Ro'yxatdan o'tish oqimini sinash

```bash
curl -X POST http://localhost:8000/api/registration/register \
  -H "Content-Type: application/json" \
  -d '{
    "owner_telegram_id": 123456789,
    "owner_username": "test_user",
    "bot_token": "111111:AA...bot-father-token...",
    "module_type": "support"
  }'
```

Muvaffaqiyatli javob bot_id, tarif (Start) va webhook holatini qaytaradi.
Token noto'g'ri bo'lsa — 400, bot allaqachon ro'yxatdan o'tgan bo'lsa — 409,
bot limiti tugagan bo'lsa — 403 xato qaytariladi (TZ 11-bo'lim: aniq xato xabarlari).

## To'lov oqimini sinash

```bash
# 1. Hosting to'lovi cheki yuborish (narx avtomatik hisoblanadi, TZ 6.3-formula)
curl -X POST http://localhost:8000/api/payments/hosting \
  -H "Content-Type: application/json" \
  -d '{"bot_id": 1, "receipt_file_id": "AgACAgI..."}'

# 2. Momo Admin tasdiqlaydi (reviewed_by_telegram_id — is_momo_admin=true bo'lgan user)
curl -X POST http://localhost:8000/api/payments/1/review \
  -H "Content-Type: application/json" \
  -d '{"approve": true, "reviewed_by_telegram_id": 999999999}'
```

Tarif oshirish uchun xuddi shunday `/api/payments/tariff-upgrade` (bot_id,
target_tariff, receipt_file_id) chaqiriladi. Tasdiqlansa — eski BotTariff
deaktivatsiya qilinib, yangisi (muddat bilan) yaratiladi (TZ 6.1, 6.4).

Har kuni Toshkent vaqti bilan 00:05/00:10 da markaziy scheduler orqali:
tarif muddati tugagan botlar Start'ga tushiriladi, joriy oy hosting to'lovi
tasdiqlanmagan botlar PAUSED holatiga o'tkaziladi va webhooki o'chiriladi.

## Lokal ishga tushirish

1. **Muhit tayyorlash**

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```

2. **Postgres + Redis** (Docker orqali)

   ```bash
   docker compose up -d
   ```

3. **Shifrlash kalitini generatsiya qilish** va `.env` ga qo'yish:

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Natijani `.env` faylidagi `TOKEN_ENCRYPTION_KEY` ga yozing. `MOMO_BOT_TOKEN`
   va `BASE_WEBHOOK_URL` ni ham to'ldiring.

4. **Migratsiyalarni qo'llash**

   ```bash
   alembic upgrade head
   ```

5. **Boshlang'ich ma'lumotlarni yuklash** (tariffs + modules)

   ```bash
   python -m app.seed
   ```

6. **Serverni ishga tushirish**

   ```bash
   python run.py
   # yoki: uvicorn app.main:app --reload
   ```

   `GET /health` — server holatini tekshirish.

## Railway'da deploy qilish

Loyiha GitHub repo orqali Railway'ga ulanganda, quyidagi variables'larni
Railway loyihasining **Variables** bo'limida qo'lda kiritish kerak:

| O'zgaruvchi | Qiymat / izoh |
|---|---|
| `MOMO_BOT_TOKEN` | Asosiy Momo boshqaruv botining BotFather tokeni |
| `TOKEN_ENCRYPTION_KEY` | Fernet kaliti — pastdagi buyruq bilan generatsiya qiling |
| `BASE_WEBHOOK_URL` | Railway domeningiz, masalan `https://sizning-loyiha.up.railway.app` |
| `WEBHOOK_PATH_PREFIX` | `/webhook` (default qiymat, o'zgartirish shart emas) |
| `SCHEDULER_TIMEZONE` | `Asia/Tashkent` (default) |
| `APP_ENV` | `production` |
| `LOG_LEVEL` | `INFO` |

**`TOKEN_ENCRYPTION_KEY` generatsiya qilish:**

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Natijani to'liq nusxalab, Railway Variables'ga `TOKEN_ENCRYPTION_KEY` sifatida qo'shing.

### Avtomatik beriladigan o'zgaruvchilar (qo'lda kiritish shart emas)

Agar Railway loyihasiga **PostgreSQL** va **Redis** plaginlarini qo'shsangiz
(New → Database → Add PostgreSQL / Add Redis), Railway quyidagilarni
avtomatik yaratadi va sizning servisingizga ulaydi:

- `DATABASE_URL` — Railway buni `postgres://` sxemasida beradi; kod ichida
  (`app/config.py`) avtomatik `postgresql+asyncpg://` ga aylantiriladi,
  shuning uchun qo'lda tuzatish shart emas.
- `REDIS_URL` — to'g'ridan-to'g'ri ishlatiladi, o'zgartirish shart emas.
- `PORT` — Railway avtomatik beradi, `Procfile`/`railway.json` shu portni ishlatadi.

Bu ikkita plagin ulanmagan bo'lsa, `DATABASE_URL` va `REDIS_URL`'ni qo'lda
(masalan tashqi hosted Postgres/Redis manzili bilan) kiritishingiz kerak.

### Deploy oqimi

1. GitHub repo'ni Railway'ga ulang (New Project → Deploy from GitHub repo)
2. PostgreSQL va Redis plaginlarini qo'shing (tavsiya etiladi)
3. Yuqoridagi jadvaldagi o'zgaruvchilarni Variables bo'limiga kiriting
4. Deploy tugagach, Railway bergan domenni oling va uni `BASE_WEBHOOK_URL`
   ga qo'yib qayta deploy qiling (chunki webhook manzili shu domenga bog'liq)
5. Birinchi deploy paytida `Procfile` avtomatik quyidagilarni bajaradi:
   `alembic upgrade head` (migratsiyalar) → `python -m app.seed`
   (tariffs/modules boshlang'ich ma'lumotlari) → `uvicorn` serverini ishga tushirish

### Muhim eslatma: bitta instansiya

`BotRegistry` xotirada saqlanadi (TZ 2.1-bo'lim izohi), shu sababli Railway
servisi uchun **replicas=1** bo'lishi shart — bir nechta instansiya
ishlatilsa, webhook so'rovlari turli instansiyalarga tushib, bot holati
nomuvofiq bo'lib qolishi mumkin. Railway'da bu default holat, alohida
sozlash shart emas.

## Hozirgi holat (skeleton bosqichi)

TZ 10-bo'limdagi amalga oshirish rejasiga muvofiq:

- [x] 1. Core dispatcher — webhook qabul qilish, bot_id bo'yicha yo'naltirish
- [x] 2. Ro'yxatdan o'tish oqimi — `POST /api/registration/register`
      (token validatsiya → mijoz topish/yaratish → Start tarif → webhook o'rnatish)
- [x] 3. Tarif/limit tizimi — asosiy logika (`services/limits.py`)
- [x] 4. Core funksiyalar — force_subscribe, captcha, welcome, spam_filter
      to'liq ishlaydigan holatda (`core/*.py`)
- [x] 5. MurojaatModule — to'liq DB bilan bog'langan (kategoriya, tarix,
      admin guruhga forward, reply orqali javob)
- [x] 6. To'lov oqimi — chek yuborish (`/api/payments/hosting`,
      `/api/payments/tariff-upgrade`) va Momo Admin tasdig'i (`/review`);
      kunlik scheduler orqali muddat/hosting nazorati (`services/hosting_check.py`,
      `services/tariff_check.py`)
- [x] 7. **KinoModule — to'liq ishlaydi**: kod bo'yicha qidiruv, /qidir (nom
      bo'yicha), /top (top-10), bot egasi uchun /kino_qoshish (FSM: kod →
      nom → kategoriya → media) va /kino_ochirish. Boshqa modullar (Admin,
      Shop, Mafia, Bunker, Custom) — faqat skeleton/ko'rinish darajasida
- [ ] 8. GameModule (GOT Game) — **Momo platformasi ichida amalga oshirilmaydi**.
      GOT Game — mijozlarga alohida mini-botlar yasab beruvchi alohida
      xizmat (mini-bot factory), har biri o'z serverida ishlaydi. Momo
      har bir mini-botni alohida (bot_id bo'yicha) tarif/trafik jihatidan
      nazorat qiladi: `is_externally_hosted=true` bilan ro'yxatdan o'tadi
      (webhook o'rnatilmaydi), `POST /api/external-bots/{bot_id}/report-usage`
      orqali trafik hisoboti beradi, `GET /api/external-bots/{bot_id}/status`
      orqali esa GOT Game mini-bot xizmat ko'rsatishda davom etishi kerakmi
      (`should_serve`) tekshiradi — hosting to'lanmagan yoki tarif tugagan
      bo'lsa, GOT Game o'z tomonida xizmatni to'xtatadi. Mavjud to'lov va
      nazorat mexanizmlari qo'shimcha o'zgarishsiz ishlaydi (bot_id asosida).
- [x] 9. **Admin panel (modul boshqaruvi)** — `GET /api/admin/modules` va
      `POST /api/admin/modules/{code}/toggle` orqali Momo Admin har bir
      modulni yoqishi/o'chirishi mumkin. O'chirilgan yoki hali tayyor
      bo'lmagan modul (`is_active=False`) — foydalanuvchiga avtomatik
      "🛠 xizmat ishlab chiqilmoqda" xabarini beradi, modul handlerlariga
      umuman kirmaydi (`dispatcher/router.py`). Seed bo'yicha hozircha
      faqat **Support** va **Kino** yoqilgan holda keladi.

## Muhim eslatmalar

- **Bir worker cheklovi**: `BotRegistry` xotirada saqlanadi, shu sababli
  hozircha faqat 1 uvicorn worker bilan ishlatish tavsiya etiladi. Ko'p
  worker/instansiya kerak bo'lsa, shared-cache (Redis) yechimi kerak bo'ladi
  (TZ 11-bo'limdagi xavf sifatida qayd etilgan).
- **Token xavfsizligi**: mijoz bot tokenlari DB'da hech qachon ochiq
  saqlanmaydi — `TOKEN_ENCRYPTION_KEY` orqali shifrlanadi.
- **Narxlar hardcode qilinmagan** — barcha tarif narxlari `tariffs`
  jadvalida saqlanadi (TZ 6.1-bo'lim talabi).

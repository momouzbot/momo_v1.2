"""
GameCore — barcha o'yin turlariga umumiy kod bazasi (TZ 4.5-bo'lim):

    GameCore
     ├── session_manager   — o'yin sessiyasini boshlash/tugatish
     ├── role_distributor  — rollarni tasodifiy taqsimlash (Mafia, Bunker)
     ├── voting_system     — ovoz berish mexanikasi (Mafia, Bunker)
     └── timer_engine      — bosqichlar orasidagi vaqt boshqaruvi

Har bir komponent alohida modulda amalga oshiriladi (session_manager.py,
role_distributor.py, voting_system.py, timer_engine.py) — hozircha skeleton
bosqichida bo'sh joy sifatida qoldirilgan, TZ 10-bo'lim 8-qadamda to'ldiriladi.
"""

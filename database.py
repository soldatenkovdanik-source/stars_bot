import aiosqlite
from datetime import datetime, timedelta
from config import DB_NAME, REQUIRED_CHANNELS, BOOST_ITEMS

async def init_db(bot=None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0,
                speed REAL DEFAULT 1.0,
                mining_start REAL,
                referrer_id INTEGER,
                is_mining INTEGER DEFAULT 0,
                boost_end TEXT,
                ref_link_created INTEGER DEFAULT 0,
                is_verified INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                is_active INTEGER DEFAULT 1,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS completed_tasks (
                user_id INTEGER,
                task_type TEXT,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, task_type)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS boost_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                link TEXT UNIQUE,
                channel_id INTEGER,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS required_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                invite_link TEXT UNIQUE,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Добавляем обязательные каналы
        cursor = await db.execute("SELECT COUNT(*) FROM required_channels")
        count = (await cursor.fetchone())[0]
        if count == 0:
            for channel in REQUIRED_CHANNELS:
                invite_link = channel["invite_link"]
                channel_id = channel["channel_id"]
                title = None
                if bot:
                    try:
                        chat = await bot.get_chat(channel_id)
                        title = chat.title
                    except:
                        pass
                await db.execute(
                    "INSERT INTO required_channels (channel_id, invite_link, title) VALUES (?, ?, ?)",
                    (channel_id, invite_link, title)
                )
                print(f"✅ Добавлен обязательный канал: {invite_link} (ID: {channel_id})")
            await db.commit()
            print(f"✅ Добавлены обязательные каналы из config.py")

        # Добавляем элементы для ускорения
        cursor = await db.execute("SELECT COUNT(*) FROM boost_items")
        count = (await cursor.fetchone())[0]
        if count == 0:
            for item in BOOST_ITEMS:
                item_type = item["type"]
                link = item["link"]
                title = item["title"]
                channel_id = item.get("channel_id")
                await db.execute(
                    "INSERT INTO boost_items (type, link, channel_id, title) VALUES (?, ?, ?, ?)",
                    (item_type, link, channel_id, title)
                )
                print(f"✅ Добавлен элемент для ускорения: {title} ({item_type})")
            await db.commit()
            print(f"✅ Добавлены элементы для ускорения из config.py")

async def get_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()

async def create_user(user_id, username, referrer_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        if await cursor.fetchone():
            return
        await db.execute(
            "INSERT INTO users (user_id, username, referrer_id, mining_start, is_verified) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, referrer_id, datetime.now().timestamp(), 0)
        )
        if referrer_id:
            await db.execute("UPDATE users SET speed = speed + 0.1 WHERE user_id = ?", (referrer_id,))
            await db.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, user_id))
        await db.commit()

async def update_balance(user_id, amount):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def get_balance(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        return result[0] if result else 0.0

async def start_mining(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET is_mining = 1, mining_start = ? WHERE user_id = ?", (datetime.now().timestamp(), user_id))
        await db.commit()

async def stop_mining(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET is_mining = 0 WHERE user_id = ?", (user_id,))
        await db.commit()

async def is_mining(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT is_mining FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        return result[0] == 1 if result else False

async def get_speed(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT speed FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        return result[0] if result else 1.0

async def get_referrals_count(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND is_active = 1", (user_id,))
        result = await cursor.fetchone()
        return result[0] if result else 0

async def set_boost(user_id, duration_hours=1):
    async with aiosqlite.connect(DB_NAME) as db:
        boost_end = (datetime.now() + timedelta(hours=duration_hours)).isoformat()
        await db.execute("UPDATE users SET boost_end = ? WHERE user_id = ?", (boost_end, user_id))
        await db.commit()

async def get_boost_end(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT boost_end FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        return result[0] if result else None

async def is_boost_active(user_id):
    boost_end = await get_boost_end(user_id)
    if not boost_end:
        return False
    return datetime.now() < datetime.fromisoformat(boost_end)

async def complete_task(user_id, task_type):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO completed_tasks (user_id, task_type) VALUES (?, ?)", (user_id, task_type))
        await db.commit()

async def is_task_completed(user_id, task_type):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_type = ?", (user_id, task_type))
        return await cursor.fetchone() is not None

async def get_referral_count_for_speed(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND is_active = 1", (user_id,))
        result = await cursor.fetchone()
        return result[0] if result else 0

async def calculate_speed(user_id):
    speed = 1.0 + await get_referral_count_for_speed(user_id) * 0.1
    if await is_boost_active(user_id):
        speed *= 2
    return speed

async def update_user_speed(user_id):
    new_speed = await calculate_speed(user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET speed = ? WHERE user_id = ?", (new_speed, user_id))
        await db.commit()
    return new_speed

async def set_verified(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET is_verified = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def is_verified(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT is_verified FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        return result[0] == 1 if result else False

async def get_required_channels():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, channel_id, invite_link, title FROM required_channels")
        return await cursor.fetchall()

async def get_boost_items():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, type, link, channel_id, title FROM boost_items")
        return await cursor.fetchall()

async def delete_boost_channel(record_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM boost_items WHERE id = ?", (record_id,))
        await db.commit()
import asyncio

from dotenv import load_dotenv
import os

from telethon import TelegramClient

load_dotenv()

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = "gifts_session"


async def main():
    async with TelegramClient(SESSION, API_ID, API_HASH) as client:
        me = await client.get_me()
        print("Ulanish muvaffaqiyatli!")
        print(f"ID: {me.id}")
        print(f"Ism: {me.first_name} {me.last_name or ''}".strip())
        print(f"Username: @{me.username}" if me.username else "Username: yo'q")
        print(f"Telefon: {me.phone}")


if __name__ == "__main__":
    asyncio.run(main())

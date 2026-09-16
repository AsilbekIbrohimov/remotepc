import asyncio
import os
import random
import re

from dotenv import load_dotenv, set_key
from telethon import TelegramClient

load_dotenv()

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = "gifts_session"
BOTFATHER = "BotFather"

BOT_NAME = "Asilbek PC Monitor"
BASE_USERNAME = "asilbek_pc_monitor"


async def wait_reply(client, conv, timeout=20):
    msg = await conv.get_response(timeout=timeout)
    return msg.raw_text


async def main():
    async with TelegramClient(SESSION, API_ID, API_HASH) as client:
        async with client.conversation(BOTFATHER, timeout=30) as conv:
            await conv.send_message("/newbot")
            reply = await wait_reply(client, conv)
            print("BotFather:", reply)

            if "20 bots" in reply:
                raise RuntimeError("BotFather limit: too many bots already created on this account")

            await conv.send_message(BOT_NAME)
            reply = await wait_reply(client, conv)
            print("BotFather:", reply)

            username = None
            for attempt in range(6):
                candidate = BASE_USERNAME if attempt == 0 else f"{BASE_USERNAME}{random.randint(100, 999)}"
                candidate_full = f"{candidate}_bot" if not candidate.endswith("bot") else candidate
                await conv.send_message(candidate_full)
                reply = await wait_reply(client, conv)
                print("BotFather:", reply)

                if "Done!" in reply or "Congratulations" in reply:
                    username = candidate_full
                    break
                if "already taken" in reply.lower() or "invalid" in reply.lower():
                    continue
                break

            if username is None:
                raise RuntimeError(f"Could not create bot, last reply: {reply}")

            match = re.search(r"\d+:[\w-]+", reply)
            if not match:
                raise RuntimeError(f"Token not found in reply: {reply}")
            token = match.group(0)

            set_key(".env", "TG_BOT_TOKEN", token)
            set_key(".env", "TG_BOT_USERNAME", username)
            print(f"\nBot yaratildi: @{username}")
            print(f"Token .env fayliga saqlandi (TG_BOT_TOKEN)")


if __name__ == "__main__":
    asyncio.run(main())

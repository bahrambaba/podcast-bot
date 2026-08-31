from telethon.sync import TelegramClient
import socks

API_ID = 39583937
API_HASH = "232f196fa82d670a5fdb9154ef709a4f"
PHONE = "+989391761256"

client = TelegramClient("user_session", API_ID, API_HASH,
    proxy=(socks.SOCKS5, "127.0.0.1", 3067))
client.start(phone=PHONE)
print("✅ Session created successfully!")
client.disconnect()

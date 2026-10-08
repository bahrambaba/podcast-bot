from telethon.sync import TelegramClient
import socks

API_ID = 39583937
API_HASH = "232f196fa82d670a5fdb9154ef709a4f"
PHONE = "+989***1256"  # typed at run time

def make_client():
    return TelegramClient("user_session", API_ID, API_HASH,
        proxy=(socks.SOCKS5, "127.0.0.1", 3067))

# DC-migrate / transient network drops need a couple of retries
for attempt in range(1, 4):
    client = make_client()
    try:
        client.start(phone=PHONE)
        break
    except Exception as e:
        print(f"attempt {attempt} failed: {type(e).__name__}: {str(e)[:120]}")
        if attempt == 3:
            raise
        import time
        time.sleep(5)

print("✅ Session created successfully!")
client.disconnect()

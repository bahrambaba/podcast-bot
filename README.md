# 🎙️ پادکست کوهنامه | Koohnameh Podcast Bot

ربات خودکار تولید پادکست روزانه فارسی از پیام‌های کانال‌های تلگرامی کوهنوردی ایران.

## نحوه کار

```
۷۳ کانال تلگرام → فچ پیام‌های ۲۴ ساعت اخیر → فیلتر آگهی/تور → تولید اسکریپت (Gemini) → تولید صدا (Gemini Live Native Audio) → ارسال به تلگرام
```

1. **جمع‌آوری:** پیام‌های ۲۴ ساعت اخیر از ۷۳ کانال کوهنوردی تلگرام
2. **فیلتر:** حذف آگهی کلاس/دوره/تور و پیام‌های کوتاه (<۵۰ کاراکتر)
3. **اسکریپت:** مدل `gemini-3.6-flash` متن خام را به دیالوگ پادکست تبدیل می‌کند
4. **اصلاح تلفظ:** ۵۱۶ کلمه با اعراب‌گذاری روی متن اعمال می‌شود (طولانی‌ترین واژه اول)
5. **صداسازی:** مدل `gemini-2.5-flash-native-audio-preview-12-2025` هر خط را با صدای مجری تولید می‌کند
6. **ارسال:** فایل WAV به گروه تلگرام ارسال می‌شود

## مجریان

| نام | جنسیت | صدا (Voice) |
|---|---|---|
| فرشید | مذکر | Charon (Informative) |
| پریسا | مونث | Aoede (Breezy) |

## زمان اجرا

هر روز ساعت **۰۸:۰۰ صبح به وقت ایران** (۰۴:۳۰ UTC) به صورت خودکار روی GitHub Actions.

## فایل‌ها

| فایل | توضیح |
|---|---|
| `main.py` | کد اصلی ربات (فچ + فیلتر + Gemini + تلگرام) |
| `config.yaml` | لیست ۷۳ کانال + کلمات فیلتر + ۵۱۶ اصلاح تلفظ |
| `requirements.txt` | وابستگی‌ها: `google-genai`, `telethon`, `pyyaml`, `jdatetime` |
| `.github/workflows/daily.yml` | cron job روی GitHub Actions |

## GitHub Secrets مورد نیاز

| Secret | توضیح |
|---|---|
| `GEMINI_API_KEY` | کلید Gemini API |
| `TELEGRAM_API_ID` | API ID تلگرام |
| `TELEGRAM_API_HASH` | API Hash تلگرام |
| `TELEGRAM_BOT_TOKEN` | توکن ربات تلگرام |
| `TELEGRAM_CHAT_ID` | ID گروه مقصد |

## اصلاح تلفظ

بخش `pronunciation_corrections` در `config.yaml` شامل ۵۱۶ واژه با اعراب‌گذاری است:

```yaml
pronunciation_corrections:
  "دماوند": "دِماوَند"
  "علم کوه": "عَلم‌کوه"
  "توچال": "تُوچال"
```

اصلاحات قبل از تولید صدا روی متن اعمال می‌شوند (طولانی‌ترین واژه اول تا جایگزینی جزئی رخ ندهد).

## تگ‌ها

- `v1` — نسخه ۱: Gemini 2.5 Flash Native Audio Dialog

## تکنولوژی‌ها

- **Gemini 2.5 Flash Native Audio Dialog** (`gemini-2.5-flash-native-audio-preview-12-2025`) — تولید صدا
- **Gemini 3.6 Flash** (`gemini-3.6-flash`) — تولید متن اسکریپت
- **Telethon** — دسترسی به Telegram API
- **GitHub Actions** — اجرای خودکار روزانه
- **PCM 24kHz mono → WAV** — فرمت خروجی صدا

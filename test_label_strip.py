import re
import importlib.util

SPEAKER_MALE = "فرشید"
SPEAKER_FEMALE = "پریسا"

text = (
    f"{SPEAKER_FEMALE}: امیدوارم از شنیدن این پادکست لذت برده باشید. "
    f"هر روز منتظر انتشار پادکست‌های صوتی روزانه از کوهنامه باشید. "
    f"{SPEAKER_MALE}: تا پادکست صبحگاهی فردا، خدا نگهدارتون باشه."
)

cleaned = re.sub(rf"\s*({SPEAKER_MALE}|{SPEAKER_FEMALE})\s*:\s*", "", text).strip()

assert "پریسا" not in cleaned, "female label still present"
assert "فرشید" not in cleaned, "male label still present"
assert cleaned.startswith("امیدوارم"), cleaned[:30]
assert "خدا نگهدارتون باشه." in cleaned
print("LABEL-STRIP TEST PASSED")
print("Cleaned:", cleaned[:80])

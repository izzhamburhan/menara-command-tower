"""Synthetic customer-care data: notice templates in four languages, and the language mix per state.

`care_template` holds a message per kind (outage, restored, degraded) and language (Malay, English, Chinese, Tamil)
with placeholders; care-mcp fills them. `care_language_mix` says how customers split across the languages in each
state. All wording and shares are invented, and the care line is a placeholder: no real phone number or brand.
"""

from __future__ import annotations

import sqlite3

from menara_core.seed.towers import TowerRow

CARE_LINE = {
    "ms": "halaman Bantuan dalam aplikasi (demo, bukan nombor sebenar)",
    "en": "the Help page in the app (demo, not a real number)",
    "zh": "应用内的帮助页面（演示，非真实号码）",
    "ta": "செயலியின் உதவிப் பக்கம் (டெமோ, உண்மையான எண் அல்ல)",
}

TEMPLATES: dict[tuple[str, str], str] = {
    ("OUTAGE", "en"): "Dear customer, service in {area} is disrupted by {cause}. We are working to restore it. Expected restoration: {eta}. Updates: {care_line}. We are sorry for the trouble. (synthetic demo)",
    ("OUTAGE", "ms"): "Pelanggan yang dihargai, perkhidmatan di {area} terganggu akibat {cause}. Kami sedang berusaha memulihkannya. Anggaran pemulihan: {eta}. Maklumat: {care_line}. Maaf atas kesulitan ini. (demo sintetik)",
    ("OUTAGE", "zh"): "尊敬的客户，{area}的服务因{cause}受到影响，我们正在抢修。预计恢复时间：{eta}。详情：{care_line}。给您带来不便，深表歉意。（合成演示）",
    ("OUTAGE", "ta"): "அன்பான வாடிக்கையாளரே, {cause} காரணமாக {area} பகுதியில் சேவை பாதிக்கப்பட்டுள்ளது. சேவையை மீட்க நாங்கள் பணியாற்றுகிறோம். எதிர்பார்க்கப்படும் நேரம்: {eta}. தகவல்: {care_line}. சிரமத்திற்கு வருந்துகிறோம். (செயற்கை டெமோ)",
    ("RESTORED", "en"): "Good news: service in {area} is back after {cause}. If you still have trouble, restart your phone and check {care_line}. Thank you for your patience. (synthetic demo)",
    ("RESTORED", "ms"): "Berita baik: perkhidmatan di {area} telah pulih selepas {cause}. Jika masih bermasalah, mulakan semula telefon anda dan semak {care_line}. Terima kasih atas kesabaran anda. (demo sintetik)",
    ("RESTORED", "zh"): "好消息：{area}的服务在{cause}后已恢复。如仍有问题，请重启手机并查看{care_line}。感谢您的耐心等待。（合成演示）",
    ("RESTORED", "ta"): "நல்ல செய்தி: {cause} பிறகு {area} பகுதியில் சேவை மீண்டும் கிடைக்கிறது. இன்னும் சிக்கல் இருந்தால் தொலைபேசியை மறுதொடக்கம் செய்து {care_line} பார்க்கவும். உங்கள் பொறுமைக்கு நன்றி. (செயற்கை டெமோ)",
    ("DEGRADED", "en"): "Dear customer, service in {area} may be slow because of {cause}. We are balancing the network. Expected improvement: {eta}. Updates: {care_line}. (synthetic demo)",
    ("DEGRADED", "ms"): "Pelanggan yang dihargai, perkhidmatan di {area} mungkin perlahan kerana {cause}. Kami sedang menyeimbangkan rangkaian. Anggaran pemulihan: {eta}. Maklumat: {care_line}. (demo sintetik)",
    ("DEGRADED", "zh"): "尊敬的客户，{area}的服务可能因{cause}而变慢，我们正在调整网络。预计改善时间：{eta}。详情：{care_line}。（合成演示）",
    ("DEGRADED", "ta"): "அன்பான வாடிக்கையாளரே, {cause} காரணமாக {area} பகுதியில் சேவை மெதுவாக இருக்கலாம். நெட்வொர்க்கை சமநிலைப்படுத்துகிறோம். எதிர்பார்க்கப்படும் நேரம்: {eta}. தகவல்: {care_line}. (செயற்கை டெமோ)",
}

# (ms, en, zh, ta) shares by state; anything not listed uses DEFAULT_MIX.
DEFAULT_MIX = (0.60, 0.25, 0.10, 0.05)
STATE_MIX: dict[str, tuple[float, float, float, float]] = {
    "Kelantan": (0.85, 0.10, 0.03, 0.02),
    "Terengganu": (0.85, 0.10, 0.03, 0.02),
    "Kedah": (0.80, 0.12, 0.05, 0.03),
    "Perlis": (0.80, 0.12, 0.05, 0.03),
    "Pulau Pinang": (0.35, 0.28, 0.32, 0.05),
    "Selangor": (0.40, 0.35, 0.20, 0.05),
    "Wilayah Persekutuan": (0.35, 0.40, 0.20, 0.05),
    "Sabah": (0.55, 0.30, 0.13, 0.02),
    "Sarawak": (0.50, 0.30, 0.18, 0.02),
}
LANGUAGES = ("ms", "en", "zh", "ta")


def build_care(conn: sqlite3.Connection, seed: int, towers: list[TowerRow]) -> None:
    conn.executemany(
        "INSERT INTO care_template VALUES (?, ?, ?)",
        [(kind, language, body) for (kind, language), body in sorted(TEMPLATES.items())],
    )
    states = sorted({t.state for t in towers})
    rows = [(state, language, share) for state in states for language, share in zip(LANGUAGES, STATE_MIX.get(state, DEFAULT_MIX), strict=True)]
    conn.executemany("INSERT INTO care_language_mix VALUES (?, ?, ?)", rows)
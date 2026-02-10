import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from json import JSONDecodeError
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from flask import Flask, jsonify, request
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================= KONFIGURASI =================

load_dotenv()

BLACKBOX_API_URL = os.getenv("BLACKBOX_API_URL", "").strip()
BLACKBOX_API_KEY = os.getenv("BLACKBOX_API_KEY", "").strip()
PARENT_FOLDER_ID = os.getenv("PARENT_FOLDER_ID", "").strip()
ID_KALENDER_KAMU = os.getenv("ID_KALENDER_KAMU", "primary").strip()
DB_FILE = "jadwal_meeting.json"

BOT_TRIGGERS = [
    "hunky",
    "@hunky",
    "bot",
    "ai",
    "@628816883610",
    "@262779135115377",
]

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
]

MEETING_RETENTION_DAYS = int(os.getenv("MEETING_RETENTION_DAYS", "30"))
MEETING_AUTO_DELETE_AFTER_HOURS = float(os.getenv("MEETING_AUTO_DELETE_AFTER_HOURS", "3"))
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "3"))
BLACKBOX_TIMEOUT_SECONDS = float(os.getenv("BLACKBOX_TIMEOUT_SECONDS", "20"))
REMINDER_TIMEOUT_SECONDS = float(os.getenv("REMINDER_TIMEOUT_SECONDS", "8"))
WA_PUSH_URL = os.getenv("WA_PUSH_URL", "http://127.0.0.1:3000/send-message")

FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes", "on"}

ACTION_SAVE_MEETING = "save_meeting"
ACTION_SEARCH_MEETING = "search_meeting"
ACTION_SEARCH_FILE = "search_file"
ACTION_WEB_SEARCH = "web_search"
ACTION_RESET_SCHEDULE = "reset_schedule"

ALLOWED_ACTIONS = {
    ACTION_SAVE_MEETING,
    ACTION_SEARCH_MEETING,
    ACTION_SEARCH_FILE,
    ACTION_WEB_SEARCH,
    ACTION_RESET_SCHEDULE,
}

REQUIRED_ENV_VARS = ["BLACKBOX_API_URL", "BLACKBOX_API_KEY", "PARENT_FOLDER_ID"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s [corr_id=%(corr_id)s] %(message)s",
)
logger = logging.getLogger("hunky")


class DefaultCorrelationFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, "corr_id"):
            record.corr_id = "-"
        return True


for handler in logging.getLogger().handlers:
    handler.addFilter(DefaultCorrelationFilter())

app = Flask(__name__)
_scheduler = BackgroundScheduler()
_scheduler_started = False
_last_web_query_by_sender = {}
_last_web_query_lock = threading.RLock()


class CorrelationAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        extra.setdefault("corr_id", self.extra.get("corr_id", "-"))
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(corr_id="-"):
    return CorrelationAdapter(logger, {"corr_id": corr_id})


def validate_required_env():
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        missing_joined = ", ".join(missing)
        raise RuntimeError(f"Missing required env vars: {missing_joined}")


def create_retry_session():
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


HTTP = create_retry_session()


class MeetingRepository:
    def __init__(self, db_path, retention_days=30, auto_delete_after_hours=3):
        self.db_path = db_path
        self.retention_days = retention_days
        self.auto_delete_after_hours = auto_delete_after_hours
        self._lock = threading.RLock()
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.db_path):
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump([], f)

    def _read_raw(self):
        self._ensure_file()
        with open(self.db_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return data if isinstance(data, list) else []
            except JSONDecodeError:
                return []

    def _write_raw(self, items):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)

    def _normalize_item(self, raw_item):
        if not isinstance(raw_item, dict):
            return None

        mapped = {
            "group_id": raw_item.get("group_id") or raw_item.get("GroupId") or "",
            "date": raw_item.get("date") or raw_item.get("Date") or "",
            "time": raw_item.get("time") or raw_item.get("Time") or "",
            "topic": raw_item.get("topic") or raw_item.get("Topic") or "",
            "location": raw_item.get("location") or raw_item.get("Location") or "-",
            "link": raw_item.get("link") or raw_item.get("Link") or "",
            "people_to_meet": raw_item.get("people_to_meet")
            or raw_item.get("People to Meet")
            or "",
            "pic_partner": raw_item.get("pic_partner") or raw_item.get("PIC Partner") or "",
            "reminded": bool(raw_item.get("reminded", False)),
        }

        if not mapped["group_id"] or not mapped["date"] or not mapped["time"]:
            return None

        return mapped

    def _to_legacy_shape(self, item):
        return {
            "Date": item["date"],
            "Time": item["time"],
            "People to Meet": item.get("people_to_meet", ""),
            "PIC Partner": item.get("pic_partner", ""),
            "Topic": item.get("topic", ""),
            "Location": item.get("location", "-"),
            "Link": item.get("link", ""),
            "GroupId": item["group_id"],
            "reminded": item.get("reminded", False),
            "group_id": item["group_id"],
            "date": item["date"],
            "time": item["time"],
            "topic": item.get("topic", ""),
            "location": item.get("location", "-"),
            "link": item.get("link", ""),
            "people_to_meet": item.get("people_to_meet", ""),
            "pic_partner": item.get("pic_partner", ""),
        }

    def _safe_datetime(self, date_str, time_str):
        try:
            return datetime.strptime(f"{date_str} {time_str.replace('.', ':')}", "%Y-%m-%d %H:%M")
        except ValueError:
            return None

    def _purge_expired(self, items):
        now_wib = (datetime.now(timezone.utc) + timedelta(hours=7)).replace(tzinfo=None)
        cutoff_date = now_wib.date() - timedelta(days=self.retention_days)
        auto_delete_cutoff = now_wib - timedelta(hours=max(self.auto_delete_after_hours, 0))
        fresh_items = []
        purged_count = 0
        for item in items:
            dt = self._safe_datetime(item["date"], item["time"])
            if dt and dt.date() < cutoff_date:
                purged_count += 1
                continue
            if dt and dt <= auto_delete_cutoff:
                purged_count += 1
                continue
            fresh_items.append(item)
        return fresh_items, purged_count

    def _normalize_and_sort(self, raw_items):
        normalized = []
        for raw_item in raw_items:
            item = self._normalize_item(raw_item)
            if item:
                normalized.append(item)

        normalized.sort(key=lambda x: (x["group_id"], x["date"], x["time"], x.get("topic", "")))
        return normalized

    def load_all(self):
        with self._lock:
            normalized = self._normalize_and_sort(self._read_raw())
            purged, purged_count = self._purge_expired(normalized)
            if purged_count > 0 or purged != normalized:
                self._write_raw([self._to_legacy_shape(item) for item in purged])
            return purged

    def save_all(self, canonical_items):
        with self._lock:
            normalized = self._normalize_and_sort(canonical_items)
            purged, _ = self._purge_expired(normalized)
            self._write_raw([self._to_legacy_shape(item) for item in purged])

    def add(self, canonical_item):
        with self._lock:
            items = self.load_all()
            items.append(canonical_item)
            self.save_all(items)

    def list_by_group(self, group_id):
        return [x for x in self.load_all() if x["group_id"] == group_id]

    def reset_group(self, group_id):
        items = [x for x in self.load_all() if x["group_id"] != group_id]
        self.save_all(items)


meeting_repo = MeetingRepository(
    DB_FILE,
    retention_days=MEETING_RETENTION_DAYS,
    auto_delete_after_hours=MEETING_AUTO_DELETE_AFTER_HOURS,
)


# ================= HELPER =================

def format_tanggal_indo(tgl_str):
    try:
        dt = datetime.strptime(tgl_str, "%Y-%m-%d")
        days = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
        months = [
            "",
            "Januari",
            "Februari",
            "Maret",
            "April",
            "Mei",
            "Juni",
            "Juli",
            "Agustus",
            "September",
            "Oktober",
            "November",
            "Desember",
        ]
        return f"{days[dt.weekday()]}, {dt.day} {months[dt.month]} {dt.year}"
    except ValueError:
        return tgl_str


def now_wib_naive():
    return (datetime.now(timezone.utc) + timedelta(hours=7)).replace(tzinfo=None)


def is_valid_date(date_str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def is_valid_time(time_str):
    try:
        datetime.strptime(time_str.replace(".", ":"), "%H:%M")
        return True
    except ValueError:
        return False


def sanitize_drive_keyword(keyword):
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", str(keyword or "")).strip()
    return cleaned.replace("'", "\\'")[:100]


def get_google_service(service_name, version, corr_id="-"):
    log = get_logger(corr_id)
    creds = None
    try:
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                log.warning("Google token missing or invalid")
                return None
        return build(service_name, version, credentials=creds)
    except Exception as exc:
        log.exception("Failed to create Google service: %s", exc)
        return None


def normalize_web_query(query):
    text = str(query or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    lowered = re.sub(r"\b(tolong|please|dong|ya|kak|bang|bot|hunky)\b", " ", lowered)
    lowered = re.sub(r"\b(cari|search|cek|lihat|temukan|carikan)\b", " ", lowered)
    lowered = re.sub(r"\b(info|informasi|berita|jadwal)\b", " ", lowered)
    lowered = re.sub(r"\b(di|dari|tentang)\b", " ", lowered)
    lowered = re.sub(r"\b(internet|online|web)\b", " ", lowered)
    lowered = re.sub(r"[^\w\s\-\.]", " ", lowered, flags=re.UNICODE)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered or text


def cari_di_internet(query, corr_id="-"):
    log = get_logger(corr_id)
    main_query = str(query or "").strip()
    fallback_query = normalize_web_query(main_query)
    log.info("Searching web: %s", main_query)
    try:
        results = DDGS().text(main_query, max_results=WEB_SEARCH_MAX_RESULTS)
        if not results and fallback_query and fallback_query != main_query:
            log.info("Searching web fallback query: %s", fallback_query)
            results = DDGS().text(fallback_query, max_results=WEB_SEARCH_MAX_RESULTS)
        if not results:
            return "Tidak ada info terkini."
        summary = ""
        for res in results:
            summary += (
                f"- {res.get('title', '-')}: {res.get('body', '-')}\n"
                f"  Sumber: {res.get('href', '-')}\n"
            )
        return summary.strip()
    except Exception as exc:
        log.exception("Web search failed: %s", exc)
        return f"Gagal searching: {exc}"


def upload_ke_drive(file_path, mime_type, custom_name=None, corr_id="-"):
    log = get_logger(corr_id)
    service = get_google_service("drive", "v3", corr_id=corr_id)
    if not service:
        return "❌ Gagal koneksi Drive."

    try:
        final_name = os.path.basename(file_path)
        if custom_name:
            clean_name = "".join([c for c in custom_name if c.isalnum() or c in (" ", "-", "_")]).strip()
            ext = os.path.splitext(file_path)[1]
            if clean_name and not clean_name.endswith(ext):
                clean_name += ext
            if clean_name:
                final_name = clean_name

        file_metadata = {"name": final_name, "parents": [PARENT_FOLDER_ID]}
        media = MediaFileUpload(file_path, mimetype=mime_type)
        file = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id, webViewLink")
            .execute(num_retries=2)
        )
        return f"✅ **File Disimpan!**\n📂 {final_name}\n🔗 {file.get('webViewLink')}"
    except Exception as exc:
        log.exception("Drive upload failed: %s", exc)
        return f"❌ Gagal upload: {exc}"
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as exc:
                log.warning("Failed cleanup temp file %s: %s", file_path, exc)


def cari_file_di_drive(keyword, corr_id="-"):
    log = get_logger(corr_id)
    service = get_google_service("drive", "v3", corr_id=corr_id)
    if not service:
        return "❌ Gagal koneksi Drive."

    safe_keyword = sanitize_drive_keyword(keyword)
    if not safe_keyword:
        return "⚠️ Keyword file tidak valid."

    try:
        query = f"name contains '{safe_keyword}' and '{PARENT_FOLDER_ID}' in parents and trashed = false"
        results = (
            service.files()
            .list(
                q=query,
                pageSize=5,
                fields="files(name, webViewLink)",
                orderBy="createdTime desc",
            )
            .execute(num_retries=2)
        )
        items = results.get("files", [])

        if not items:
            return f"⚠️ File *'{safe_keyword}'* tidak ditemukan di dalam Folder Kerja Hunky."

        balasan = f"📂 **Hasil Pencarian '{safe_keyword}':**\n"
        for item in items:
            balasan += f"\n📄 {item.get('name', '-')}\n🔗 {item.get('webViewLink', '-')}\n"
        return balasan
    except Exception as exc:
        log.exception("Drive search failed: %s", exc)
        return f"❌ Error cari file: {exc}"


def build_ai_system_instruction(group_id, konteks_tambahan=""):
    waktu_sekarang = now_wib_naive().strftime("%A, %Y-%m-%d Jam %H:%M WIB")
    jadwal_str = json.dumps(meeting_repo.list_by_group(group_id), indent=2, ensure_ascii=False)
    return f"""
Kamu adalah HUNKY, asisten AI.
INFO: Waktu {waktu_sekarang}.
GROUP_ID: {group_id}
DATABASE MEETING GROUP: {jadwal_str}
KONTEKS TAMBAHAN: {konteks_tambahan}

ATURAN:
1. Jika ingin menjalankan aksi, output HARUS JSON valid object tunggal.
2. Gunakan hanya action ini: save_meeting, search_file, web_search, search_meeting, reset_schedule.
3. save_meeting.data wajib punya date(YYYY-MM-DD), time(HH:MM), topic, location, link.
4. Jika bukan aksi, jawab sebagai asisten AI biasa: natural, ringkas, dan langsung.
5. Hindari JSON bila tidak menjalankan action.
6. Untuk pertanyaan kemampuan bot, penjelasan, atau percakapan umum, WAJIB jawab teks biasa (bukan action JSON).
7. Kamu punya akses pencarian file Google Drive Folder Kerja Hunky lewat action search_file.
8. Jika user minta ambil/cari file dari Google Drive, gunakan action search_file dan isi keyword yang relevan.
""".strip()


def tanya_blackbox(pesan_user, group_id, konteks_tambahan="", corr_id="-"):
    log = get_logger(corr_id)
    system_instruction = build_ai_system_instruction(group_id, konteks_tambahan)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BLACKBOX_API_KEY}",
    }
    payload = {
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": pesan_user},
        ],
        "model": "blackboxai/deepseek/deepseek-chat-v3.1",
        "clickedAnswer2": False,
        "clickedAnswer3": False,
    }

    try:
        response = HTTP.post(BLACKBOX_API_URL, headers=headers, json=payload, timeout=BLACKBOX_TIMEOUT_SECONDS)
        if response.status_code != 200:
            return f"Error API Blackbox: {response.status_code} - {response.text}"

        hasil = response.json()
        return (
            hasil.get("choices", [{}])[0].get("message", {}).get("content", "")
            or hasil.get("response", "")
            or str(hasil)
        )
    except Exception as exc:
        log.exception("Blackbox request failed: %s", exc)
        return f"Error Koneksi: {exc}"


def extract_first_json_object(text):
    if not text:
        return None

    fenced = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    candidates = fenced + [text]

    decoder = json.JSONDecoder()
    for candidate in candidates:
        for idx, ch in enumerate(candidate):
            if ch != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[idx:])
                if isinstance(parsed, dict):
                    return parsed
            except JSONDecodeError:
                continue
    return None


def extract_text_from_json_payload(data_json):
    if not isinstance(data_json, dict):
        return None
    for key in ("text", "reply", "message", "response"):
        val = data_json.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def normalize_text_reply_if_json(raw_reply):
    if not isinstance(raw_reply, str):
        return raw_reply
    parsed = extract_first_json_object(raw_reply)
    fallback_text = extract_text_from_json_payload(parsed)
    return fallback_text or raw_reply


def extract_action_keyword(data_json):
    if not isinstance(data_json, dict):
        return ""

    candidates = [data_json.get("keyword")]
    nested = data_json.get("data")
    if isinstance(nested, dict):
        candidates.extend([nested.get("keyword"), nested.get("query"), nested.get("text")])

    for val in candidates:
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def is_drive_lookup_intent(message):
    lowered = (message or "").lower()
    if not lowered:
        return False
    has_file_word = any(word in lowered for word in ["file", "dokumen", "document"])
    has_lookup_word = any(word in lowered for word in ["ambil", "cari", "buka", "download", "unduh"])
    return ("drive" in lowered and has_file_word) or (has_file_word and has_lookup_word)


def extract_drive_lookup_keyword(message):
    text = str(message or "")
    cleaned = re.sub(r"@\d{6,}", " ", text)
    cleaned = re.sub(r"@hunky", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(tolong|please|dong|ya|kak|bang|bot|hunky|google|drive|folder|ambil|cari|buka|download|unduh|file|dokumen|document|dari|di|ke)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[^\w\s\-\.]", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or text.strip()


def is_web_lookup_intent(message):
    lowered = (message or "").lower().strip()
    if not lowered:
        return False

    if any(word in lowered for word in ["meeting", "jadwal meeting", "drive"]):
        return False

    question_starters = ["kapan", "siapa", "berapa", "dimana", "bagaimana", "apa", "apakah"]
    lookup_words = ["jadwal", "berita", "update", "terbaru", "hasil", "final", "skor", "info", "kabar", "internet"]
    lookup_verbs = ["cari", "search", "cek", "lihat", "temukan", "carikan"]
    has_question = lowered.endswith("?") or any(lowered.startswith(x + " ") for x in question_starters)
    has_lookup_word = any(word in lowered for word in lookup_words)
    has_lookup_verb = any(word in lowered for word in lookup_verbs)
    return (has_question and has_lookup_word) or (has_lookup_verb and has_lookup_word)


def is_meeting_work_intent(message):
    lowered = (message or "").lower()
    if not lowered:
        return False
    if any(word in lowered for word in ["internet", "berita", "news", "web search"]):
        return False
    work_markers = [
        "meeting",
        "jadwal meeting",
        "catat meeting",
        "ingatkan meeting",
        "reset jadwal",
        "search_meeting",
    ]
    return any(marker in lowered for marker in work_markers)


def is_ambiguous_lookup_intent(message):
    lowered = (message or "").lower().strip()
    if not lowered:
        return False
    has_lookup_verb = any(word in lowered for word in ["cari", "carikan", "search", "lookup"])
    has_target = any(word in lowered for word in ["file", "info", "informasi", "jadwal", "data"])
    has_scope = any(word in lowered for word in ["drive", "google drive", "internet", "web", "meeting"])
    return has_lookup_verb and has_target and not has_scope


def is_followup_web_lookup(message):
    lowered = (message or "").lower().strip()
    followups = [
        "apakah sudah ada infonya",
        "sudah ada infonya",
        "gimana infonya",
        "update nya",
        "update-nya",
        "ada update",
    ]
    return any(x in lowered for x in followups)


def route_intent(message, sender, has_file=False, triggered=False, has_web_context=False):
    if has_file:
        return {"mode": "work", "intent": "upload_file", "confidence": 1.0}

    if sender.endswith("@g.us") and not triggered:
        return {"mode": "ignored", "intent": "ignored_text", "confidence": 1.0}

    if is_drive_lookup_intent(message):
        return {"mode": "work", "intent": ACTION_SEARCH_FILE, "confidence": 0.98}

    if is_followup_web_lookup(message) and has_web_context:
        return {"mode": "general", "intent": ACTION_WEB_SEARCH, "confidence": 0.95}

    if is_web_lookup_intent(message):
        return {"mode": "general", "intent": ACTION_WEB_SEARCH, "confidence": 0.92}

    if is_meeting_work_intent(message):
        return {"mode": "work", "intent": "meeting_flow", "confidence": 0.9}

    if is_ambiguous_lookup_intent(message):
        return {"mode": "ambiguous", "intent": "clarify_lookup_scope", "confidence": 0.6}

    return {"mode": "general", "intent": "chat", "confidence": 0.7}


def remember_last_web_query(sender, query):
    if not sender or not query:
        return
    with _last_web_query_lock:
        _last_web_query_by_sender[sender] = query


def get_last_web_query(sender):
    if not sender:
        return ""
    with _last_web_query_lock:
        return _last_web_query_by_sender.get(sender, "")


def answer_from_web_lookup(message, sender, corr_id="-"):
    query = str(message or "").strip()
    if is_followup_web_lookup(message):
        prev = get_last_web_query(sender)
        if prev:
            query = prev

    remember_last_web_query(sender, query)
    hasil_cari = cari_di_internet(query, corr_id=corr_id)
    if hasil_cari.startswith("Gagal searching:"):
        return hasil_cari

    prompt = (
        "Jawab pertanyaan user berdasarkan ringkasan hasil internet berikut.\n"
        "- Jawab langsung dan ringkas.\n"
        "- Jika info belum pasti, tulis bahwa perlu verifikasi resmi.\n"
        "- Jangan output JSON.\n\n"
        f"Pertanyaan user: {message}\n"
        f"Ringkasan internet:\n{hasil_cari}"
    )
    jawaban = tanya_blackbox(prompt, group_id=sender, konteks_tambahan="Mode jawaban web lookup teks-only.", corr_id=corr_id)
    jawaban = normalize_text_reply_if_json(jawaban)
    if isinstance(jawaban, str):
        lowered = jawaban.lower()
        placeholder_phrases = [
            "tunggu sebentar",
            "saya carikan",
            "saya cari dulu",
            "sedang mencari",
            "akan saya cari",
        ]
        no_info_phrases = [
            "belum dapat saya temukan",
            "belum bisa saya temukan",
            "tidak dapat saya temukan",
            "tidak ditemukan",
            "tidak ada informasi",
            "maaf, informasi",
        ]
        if any(phrase in lowered for phrase in placeholder_phrases + no_info_phrases):
            return hasil_cari
    return jawaban if isinstance(jawaban, str) and jawaban.strip() else hasil_cari


def is_truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def rewrite_as_plain_text(user_message, raw_ai_output, sender, corr_id="-"):
    prompt = (
        "Ubah output berikut menjadi jawaban teks biasa untuk user WhatsApp.\n"
        "- Jangan pakai JSON.\n"
        "- Jangan pakai format action/tool.\n"
        "- Jawab singkat, natural, dan langsung.\n\n"
        f"Pesan user: {user_message}\n"
        f"Output model sebelumnya: {raw_ai_output}"
    )
    return tanya_blackbox(prompt, group_id=sender, konteks_tambahan="Mode teks-only tanpa JSON.", corr_id=corr_id)


def should_rewrite_general_chat_reply(reply_text):
    lowered = str(reply_text or "").lower()
    bad_patterns = [
        "belum ada data terbaru",
        "belum ada informasi terbaru",
        "tidak dapat saya sampaikan",
        "tidak memiliki data",
        "disarankan mencari sumber resmi",
        "silakan mencari sumber resmi",
    ]
    return any(pattern in lowered for pattern in bad_patterns)


def rewrite_as_general_assistant_answer(user_message, raw_ai_output, sender, corr_id="-"):
    prompt = (
        "Jawab pertanyaan user sebagai asisten AI umum.\n"
        "- Gunakan pengetahuan umum yang kamu miliki.\n"
        "- Jangan bilang tidak ada data terbaru jika pertanyaannya bersifat umum/non-berita.\n"
        "- Berikan jawaban praktis, jelas, dan langsung.\n"
        "- Jangan output JSON.\n\n"
        f"Pertanyaan user: {user_message}\n"
        f"Jawaban sebelumnya yang kurang tepat: {raw_ai_output}"
    )
    return tanya_blackbox(
        prompt,
        group_id=sender,
        konteks_tambahan="Mode asisten umum non-aksi.",
        corr_id=corr_id,
    )


def validate_action_payload(data_json, sender):
    if not isinstance(data_json, dict):
        return False, "Payload aksi harus object JSON."

    action = data_json.get("action")
    if action not in ALLOWED_ACTIONS:
        return False, f"Action tidak dikenali: {action}"

    if action == ACTION_SAVE_MEETING:
        meeting_data = data_json.get("data")
        if not isinstance(meeting_data, dict):
            return False, "save_meeting.data harus object."

        date_value = str(meeting_data.get("date") or meeting_data.get("Date") or "").strip()
        time_value = str(meeting_data.get("time") or meeting_data.get("Time") or "").strip().replace(".", ":")
        topic_value = str(meeting_data.get("topic") or meeting_data.get("Topic") or "").strip()

        if not is_valid_date(date_value):
            return False, "Format date harus YYYY-MM-DD."
        if not is_valid_time(time_value):
            return False, "Format time harus HH:MM."
        if not topic_value:
            return False, "Field topic wajib diisi."
        if not sender:
            return False, "group_id/sender wajib ada."

    if action == ACTION_SEARCH_MEETING:
        date_value = str(data_json.get("date") or "").strip()
        if not is_valid_date(date_value):
            return False, "search_meeting.date harus YYYY-MM-DD."

    if action in {ACTION_SEARCH_FILE, ACTION_WEB_SEARCH}:
        val = extract_action_keyword(data_json)
        if not val:
            return False, f"{action}.keyword wajib diisi."

    return True, "ok"


def is_triggered_message(sender, message):
    is_group = sender.endswith("@g.us")
    if not is_group:
        return True
    lowered = (message or "").lower()
    return any(trigger.lower() in lowered for trigger in BOT_TRIGGERS)


def format_group_schedule(items):
    if not items:
        return "📅 Belum ada jadwal meeting untuk grup ini."

    balasan = "✅ **Jadwal Meeting Tersimpan!**\n\n**Jadwal Meeting Grup**"
    current_date = ""
    for item in items:
        item_date = item.get("date", "-")
        if item_date != current_date:
            balasan += f"\n\n**{format_tanggal_indo(item_date)}**\n"
            current_date = item_date
        balasan += f"\nTime : {item.get('time', '-')} WIB"
        balasan += f"\nTopic : {item.get('topic', '-')}"
        balasan += f"\nTempat : {item.get('location', '-')}"
        balasan += f"\nLink : {item.get('link', '-')}\n"
    return balasan


def send_reminder_message(group_id, message, corr_id="scheduler"):
    log = get_logger(corr_id)
    try:
        response = HTTP.post(
            WA_PUSH_URL,
            json={"target_id": group_id, "message": message},
            timeout=REMINDER_TIMEOUT_SECONDS,
        )
        if response.status_code >= 300:
            log.warning("WA push failed status=%s body=%s", response.status_code, response.text)
    except Exception as exc:
        log.exception("WA push request failed: %s", exc)


def cek_reminder_otomatis():
    log = get_logger("scheduler")
    now = now_wib_naive()
    meetings = meeting_repo.load_all()
    changed = False

    for item in meetings:
        if item.get("reminded", False):
            continue
        meeting_dt = meeting_repo._safe_datetime(item.get("date", ""), item.get("time", ""))
        if not meeting_dt:
            continue

        diff_minutes = (meeting_dt - now).total_seconds() / 60
        if 0 < diff_minutes <= 5:
            group_id = item.get("group_id")
            if group_id:
                pesan = (
                    f"⏰ *REMINDER MEETING {int(diff_minutes)} MENIT LAGI!*\n"
                    f"📝 {item.get('topic', '-')}\n"
                    f"🔗 {item.get('link', '-') }"
                )
                send_reminder_message(group_id, pesan)
                log.info("Reminder sent for group=%s topic=%s", group_id, item.get("topic", "-"))
            item["reminded"] = True
            changed = True

    if changed:
        meeting_repo.save_all(meetings)


def start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler.add_job(func=cek_reminder_otomatis, trigger="interval", minutes=1)
    _scheduler.start()
    _scheduler_started = True


def execute_action(data_json, sender, original_message, corr_id="-"):
    action = data_json.get("action")

    if action == ACTION_SAVE_MEETING:
        meeting_data = data_json.get("data", {})
        new_item = {
            "group_id": sender,
            "date": str(meeting_data.get("date") or meeting_data.get("Date")).strip(),
            "time": str(meeting_data.get("time") or meeting_data.get("Time")).strip().replace(".", ":"),
            "topic": str(meeting_data.get("topic") or meeting_data.get("Topic") or "").strip(),
            "location": str(meeting_data.get("location") or meeting_data.get("Location") or "-").strip(),
            "link": str(meeting_data.get("link") or meeting_data.get("Link") or "").strip(),
            "people_to_meet": str(
                meeting_data.get("people_to_meet") or meeting_data.get("People to Meet") or ""
            ).strip(),
            "pic_partner": str(meeting_data.get("pic_partner") or meeting_data.get("PIC Partner") or "").strip(),
            "reminded": False,
        }
        meeting_repo.add(new_item)
        return format_group_schedule(meeting_repo.list_by_group(sender))

    if action == ACTION_SEARCH_MEETING:
        target_date = data_json.get("date")
        group_items = meeting_repo.list_by_group(sender)
        result = [m for m in group_items if m.get("date") == target_date]
        if not result:
            return f"📅 Tidak ada jadwal meeting pada **{format_tanggal_indo(target_date)}**."

        balasan = f"📅 **Jadwal Meeting: {format_tanggal_indo(target_date)}**\n"
        for item in result:
            balasan += f"\n🕒 {item.get('time', '-')} WIB"
            balasan += f"\n📝 {item.get('topic', '-')}"
            balasan += f"\n📍 {item.get('location', '-')}"
            balasan += f"\n🔗 {item.get('link', '-')}\n"
        return balasan

    if action == ACTION_SEARCH_FILE:
        return cari_file_di_drive(extract_action_keyword(data_json), corr_id=corr_id)

    if action == ACTION_WEB_SEARCH:
        keyword = extract_action_keyword(data_json)
        hasil_cari = cari_di_internet(keyword, corr_id=corr_id)
        return tanya_blackbox(
            f"User tanya: {original_message}",
            group_id=sender,
            konteks_tambahan=f"Fakta Internet: {hasil_cari}",
            corr_id=corr_id,
        )

    if action == ACTION_RESET_SCHEDULE:
        meeting_repo.reset_group(sender)
        return "🗑️ Jadwal meeting grup ini telah direset."

    return "Aksi tidak dikenali."


# ================= ROUTES =================

@app.route("/health", methods=["GET"])
def health():
    db_ok = True
    db_msg = "ok"
    try:
        meeting_repo.load_all()
    except Exception as exc:
        db_ok = False
        db_msg = str(exc)

    google_ok = get_google_service("drive", "v3") is not None
    blackbox_ok = bool(BLACKBOX_API_URL and BLACKBOX_API_KEY)
    scheduler_ok = _scheduler_started and _scheduler.running

    payload = {
        "status": "ok" if all([db_ok, google_ok, blackbox_ok, scheduler_ok]) else "degraded",
        "blackbox": "ok" if blackbox_ok else "missing_config",
        "google_drive": "ok" if google_ok else "unavailable",
        "db": "ok" if db_ok else f"error: {db_msg}",
        "scheduler": "running" if scheduler_ok else "stopped",
        "calendar_id": ID_KALENDER_KAMU,
    }
    code = 200 if payload["status"] == "ok" else 503
    return jsonify(payload), code


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}

    sender = str(data.get("sender") or "").strip()
    message = str(data.get("message") or "")
    file_path = data.get("file_path")
    mime_type = data.get("mime_type")
    file_source = str(data.get("file_source") or "")
    bot_hit = is_truthy(data.get("bot_hit"))
    message_id = str(data.get("message_id") or uuid.uuid4().hex[:12])
    log = get_logger(message_id)

    if not sender:
        return jsonify({"error_code": "BAD_REQUEST", "error": "sender wajib diisi"}), 400

    log.info("Incoming chat sender=%s has_file=%s", sender, bool(file_path))

    triggered = is_triggered_message(sender, message)
    has_web_context = bool(get_last_web_query(sender))
    routed = route_intent(
        message=message,
        sender=sender,
        has_file=bool(file_path),
        triggered=triggered,
        has_web_context=has_web_context,
    )
    log.info(
        "Intent routed mode=%s intent=%s confidence=%.2f",
        routed.get("mode"),
        routed.get("intent"),
        routed.get("confidence", 0.0),
    )

    if file_path:
        if not os.path.exists(file_path):
            return jsonify(
                {"error_code": "FILE_NOT_FOUND", "error": "file_path tidak ditemukan di server"}
            ), 400

        is_group = sender.endswith("@g.us")
        msg_lower = message.lower()
        keyword_simpan = any(word in msg_lower for word in ["simpan", "upload", "taruh"])
        should_upload = False

        if is_group:
            # Di grup, file hanya diproses jika bot di-hit/mention.
            should_upload = bot_hit or (triggered and keyword_simpan)
        else:
            should_upload = triggered and keyword_simpan

        if should_upload:
            nama_file = message.replace("@hunky", "").replace("simpan", "").strip() or "File Upload"
            balasan = upload_ke_drive(file_path, mime_type, custom_name=nama_file, corr_id=message_id)
            return jsonify({"reply": balasan})

        if is_group and not bot_hit:
            try:
                os.remove(file_path)
            except OSError as exc:
                log.warning("Unable to delete ignored temp file %s: %s", file_path, exc)
            return jsonify(
                {
                    "status": "ignored_file",
                    "reason": "group_file_requires_bot_hit",
                    "file_source": file_source or "unknown",
                }
            )

        try:
            os.remove(file_path)
        except OSError as exc:
            log.warning("Unable to delete ignored temp file %s: %s", file_path, exc)
        return jsonify({"status": "ignored_file"})

    if routed.get("mode") == "ignored":
        return jsonify({"status": "ignored_text"})

    if routed.get("mode") == "ambiguous":
        return jsonify(
            {
                "reply": (
                    "Mau saya carikan di mana: Google Drive atau internet? "
                    "Contoh: 'cari file X di drive' atau 'cari info X di internet'."
                )
            }
        )

    if routed.get("intent") == ACTION_SEARCH_FILE:
        keyword_drive = extract_drive_lookup_keyword(message)
        balasan_drive = cari_file_di_drive(keyword_drive, corr_id=message_id)
        return jsonify({"reply": balasan_drive})

    if routed.get("intent") == ACTION_WEB_SEARCH:
        balasan_web = answer_from_web_lookup(message, sender, corr_id=message_id)
        return jsonify({"reply": balasan_web})

    jawaban_ai = tanya_blackbox(message, group_id=sender, corr_id=message_id)
    balasan_final = jawaban_ai

    try:
        data_json = extract_first_json_object(jawaban_ai)
        if data_json:
            valid, reason = validate_action_payload(data_json, sender)
            if valid:
                balasan_final = execute_action(data_json, sender, message, corr_id=message_id)
            else:
                fallback_text = extract_text_from_json_payload(data_json)
                if fallback_text:
                    balasan_final = fallback_text
                else:
                    balasan_final = rewrite_as_plain_text(message, jawaban_ai, sender, corr_id=message_id)
                log.warning("Invalid action payload: %s", reason)
    except Exception as exc:
        log.exception("Error executing AI action: %s", exc)

    balasan_final = normalize_text_reply_if_json(balasan_final)
    if isinstance(balasan_final, str) and is_drive_lookup_intent(message):
        lowered_reply = balasan_final.lower()
        no_access_phrases = [
            "tidak memiliki akses",
            "tidak punya akses",
            "tidak bisa mengunduh",
            "tidak dapat mengunduh",
            "can't access google drive",
        ]
        if any(phrase in lowered_reply for phrase in no_access_phrases):
            keyword_drive = extract_drive_lookup_keyword(message)
            balasan_final = cari_file_di_drive(keyword_drive, corr_id=message_id)

    if routed.get("intent") == "chat" and should_rewrite_general_chat_reply(balasan_final):
        rewritten = rewrite_as_general_assistant_answer(message, balasan_final, sender, corr_id=message_id)
        balasan_final = normalize_text_reply_if_json(rewritten)

    return jsonify({"reply": balasan_final})


def bootstrap():
    validate_required_env()
    start_scheduler()


if __name__ == "__main__":
    bootstrap()
    app.run(port=5000, debug=FLASK_DEBUG)

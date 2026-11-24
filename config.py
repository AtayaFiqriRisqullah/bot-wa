import os

try:
    from dotenv import load_dotenv
    load_dotenv()   # membaca file .env di folder ini
except ImportError:
    pass

# Google Sheets, Calendar, Tasks, Docs
SHEET_ID = os.environ.get('SHEET_ID', '')
CALENDAR_ID = os.environ.get('CALENDAR_ID', '')
TUGAS_URL = os.environ.get('TUGAS_URL', '')
TUGAS_KUNCI = os.environ.get('TUGAS_KUNCI', '')
CATATAN_DOC_ID = os.environ.get('CATATAN_DOC_ID', '')

# WhatsApp & Keamanan (Whitelist)
NOMOR_KAMU = os.environ.get('NOMOR_KAMU', '')
WHITELIST_GRUP = os.environ.get('WHITELIST_GRUP', '')
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN', '')
WA_TOKEN = os.environ.get('WA_TOKEN', '')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID', '')
APP_SECRET = os.environ.get('APP_SECRET', '')

# Input Cerdas (Scan Struk, Voice Note, Bahasa Natural / LLM Fallback)
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
AI_AKTIF = os.environ.get('AI_AKTIF', 'true').strip().lower() not in ('0', 'false', 'no', 'off')

# Sinkronisasi /deadline ke Google Calendar secara otomatis
DEADLINE_KE_KALENDER = os.environ.get('DEADLINE_KE_KALENDER', 'true').strip().lower() not in (
    '0', 'false', 'no', 'off'
)

# Server API Lokal (Python <-> Node.js Baileys)
API_HOST = os.environ.get('API_HOST', '127.0.0.1')
API_PORT = int(os.environ.get('API_PORT', '8000'))
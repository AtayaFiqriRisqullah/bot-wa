import os

from dotenv import load_dotenv

load_dotenv()   # membaca file .env di folder ini

SHEET_ID = os.environ.get('SHEET_ID', '')
CALENDAR_ID = os.environ.get('CALENDAR_ID', '')
NOMOR_KAMU = os.environ.get('NOMOR_KAMU', '')
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN', '')
WA_TOKEN = os.environ.get('WA_TOKEN', '')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID', '')
APP_SECRET = os.environ.get('APP_SECRET', '')
TUGAS_URL = 'https://script.google.com/macros/s/AKfycbyi19ZkKu6f40J8mqkzndurbkBNrqaODulpOXJpZjMcIpEtFl3PggAtTt-F2oFAULr3/exec'
TUGAS_KUNCI = '12345'
CATATAN_DOC_ID = '1DFHCt1NPUBjcsJukxQQO7inKHBgYujTYl2X70_wJv34'
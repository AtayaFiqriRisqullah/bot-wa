import json
import os


def muat_kunci():
    if os.environ.get('GOOGLE_KEY_JSON'):
        return json.loads(os.environ['GOOGLE_KEY_JSON'])
    with open('kunci-google.json', encoding='utf-8') as f:
        return json.load(f)
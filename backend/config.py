import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "ledger_v2.db")

LEGACY_EXCEL = os.path.join(BASE_DIR, "Laldia", "Laldia港湾微信群台账.xlsx")
LEGACY_WX_JSON_DIR = os.path.join(BASE_DIR, "Laldia", "wx_json")
LEGACY_LEDGER_JSON = os.path.join(BASE_DIR, "Laldia", "Laldia微信群台账.json")
LEGACY_DAILY_SUMMARY = os.path.join(BASE_DIR, "Laldia", "每日摘要")
LEGACY_ARCHIVE_DIR = os.path.join(BASE_DIR, "Laldia", "微信群归档")
LEGACY_ARCHIVE_LEGACY_DIR = os.path.join(BASE_DIR, "Laldia", "微信群归档_legacy")

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

FLASK_HOST = "127.0.0.1"
FLASK_PORT = 8888

# WeChat local data directory (for file:// links)
WX_DATA_DIR = None
_WX_FILE_ROOT = None


def _detect_wx_data_dir():
    global WX_DATA_DIR, _WX_FILE_ROOT
    import subprocess as _sp
    try:
        result = _sp.run(
            ["wx", "init"],
            capture_output=True, text=True, timeout=15,
            env={**_sp.os.environ, "NO_COLOR": "1"}
        )
        for line in (result.stdout + result.stderr).split("\n"):
            if "数据目录" in line or "data" in line.lower():
                import re
                m = re.search(r'[A-Za-z]:\\[^\s,]+', line)
                if m:
                    WX_DATA_DIR = m.group(0).rstrip(".")
                    break
    except Exception:
        pass
    if not WX_DATA_DIR:
        WX_DATA_DIR = os.path.expanduser("~/Documents/xwechat_files")
    if os.path.isdir(WX_DATA_DIR):
        try:
            for entry in os.listdir(WX_DATA_DIR):
                candidate = os.path.join(WX_DATA_DIR, entry)
                if os.path.isdir(candidate) and os.path.isdir(os.path.join(candidate, "msg", "file")):
                    _WX_FILE_ROOT = os.path.join(candidate, "msg", "file")
                    break
        except OSError:
            pass


def get_wx_file_url(msg_date, filename):
    if not _WX_FILE_ROOT or not msg_date or not filename:
        return None
    yyyy_mm = msg_date[:7]
    file_path = os.path.join(_WX_FILE_ROOT, yyyy_mm, filename)
    if os.path.isfile(file_path):
        return "file:///" + file_path.replace("\\", "/")
    return None


def get_wx_file_path(msg_date, filename):
    if not _WX_FILE_ROOT or not msg_date or not filename:
        return None
    yyyy_mm = msg_date[:7]
    file_path = os.path.normpath(os.path.join(_WX_FILE_ROOT, yyyy_mm, filename))
    if os.path.isfile(file_path):
        return file_path
    return None


_detect_wx_data_dir()

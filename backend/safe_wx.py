"""
Safe WeChat message extraction via wx CLI + daemon.

Principle: wx CLI calls go through daemon, which extracts SQLCipher keys
ONCE at startup and caches them. All subsequent queries use cached keys
without touching the WeChat process, preventing anti-cheat detection.

Flow:
  1. Ensure daemon is running (start if needed)
  2. Export messages to local JSON via `wx export` (goes through daemon)
  3. Read from local JSON — never touches WeChat's original files
"""
import os
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime

WX_CLI = shutil.which("wx") or "wx"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Detect wx.js path for .cmd wrapper fallback
_wx_js = None
if WX_CLI != "wx" and WX_CLI.lower().endswith(".cmd"):
    _wx_dir = os.path.dirname(WX_CLI)
    _candidate = os.path.join(_wx_dir, "node_modules", "@jackwener", "wx-cli", "bin", "wx.js")
    if os.path.isfile(_candidate):
        _wx_js = _candidate

_last_raw_call = 0.0
WX_MIN_INTERVAL = 1.5

_CALL_COUNTER_FILE = os.path.join(DATA_DIR, "wx_call_counter.json")
_daily_call_count = 0
_daily_call_date = ""


def _load_daily_counter():
    global _daily_call_count, _daily_call_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _daily_call_date == today:
        return
    try:
        if os.path.isfile(_CALL_COUNTER_FILE):
            with open(_CALL_COUNTER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today:
                _daily_call_count = data.get("count", 0)
                _daily_call_date = today
                return
    except Exception:
        pass
    _daily_call_count = 0
    _daily_call_date = today


def _save_daily_counter():
    os.makedirs(os.path.dirname(_CALL_COUNTER_FILE), exist_ok=True)
    with open(_CALL_COUNTER_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": _daily_call_date, "count": _daily_call_count}, f)


def _check_daily_limit():
    global _daily_call_count
    from .config import WX_DAILY_CALL_LIMIT
    _load_daily_counter()
    if _daily_call_count >= WX_DAILY_CALL_LIMIT:
        raise RuntimeError(
            f"每日 wx-cli 调用上限已达 ({WX_DAILY_CALL_LIMIT}次)。"
            f"如需继续同步，请明天再试或调整 WX_DAILY_CALL_LIMIT 环境变量。"
        )
    _daily_call_count += 1
    _save_daily_counter()


def _run_wx_raw(args, timeout=30):
    global _last_raw_call
    _check_daily_limit()
    elapsed = time.time() - _last_raw_call
    if elapsed < WX_MIN_INTERVAL:
        time.sleep(WX_MIN_INTERVAL - elapsed)

    if _wx_js:
        cmd_list = ["node", _wx_js] + args
    else:
        if WX_CLI == "wx" and not shutil.which("wx"):
            raise RuntimeError("wx-cli 未安装")
        cmd_list = [WX_CLI] + args

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = None
    try:
        proc = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=creationflags
        )
        stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
        returncode = proc.returncode
    except FileNotFoundError:
        raise RuntimeError("wx-cli 未安装")
    except subprocess.TimeoutExpired:
        if proc:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass
        raise RuntimeError(f"wx-cli 执行超时 ({timeout}s)")

    _last_raw_call = time.time()

    stdout_bytes = stdout_bytes or b""
    try:
        stdout = stdout_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            stdout = stdout_bytes.decode("gbk")
        except UnicodeDecodeError:
            stdout = stdout_bytes.decode("utf-8", errors="replace")

    if returncode != 0:
        stderr_bytes = stderr_bytes or b""
        try:
            stderr = stderr_bytes.decode("gbk").strip()
        except (UnicodeDecodeError, LookupError):
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        if "not found" in stderr.lower() or "not recognized" in stderr.lower():
            raise RuntimeError("wx-cli 未安装")
        if "init" in stderr.lower():
            raise RuntimeError("wx-cli 未初始化，请运行: wx init")
        raise RuntimeError(f"wx-cli 错误: {stderr or '未知错误'}")
    return stdout.strip()


def is_wechat_running():
    """检查微信进程是否在运行。daemon 需要微信进程才能提取密钥。"""
    import sys
    if sys.platform != "win32":
        return True
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "if (Get-Process -Name 'WeChatAppEx','WeChat' -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"],
            capture_output=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return result.returncode == 0
    except Exception:
        return True


def is_daemon_running():
    try:
        out = _run_wx_raw(["daemon", "status"], timeout=5)
        return "运行中" in out or ("运行" in out and "未运行" not in out)
    except Exception:
        return False


def start_daemon():
    """Trigger daemon auto-start by accessing WeChat database.

    wx-daemon auto-starts when a wx command touches the WeChat DB.
    The daemon starts ASYNCHRONOUSLY — 'wx sessions' may timeout before
    the daemon finishes key extraction and DB warmup. So we ignore
    timeouts and check is_daemon_running() separately.
    """
    import time
    if not is_wechat_running():
        return False
    try:
        _run_wx_raw(["sessions", "-n", "1", "--json"], timeout=15)
    except Exception:
        pass  # daemon may still be starting in background
    time.sleep(2)
    return is_daemon_running()


def ensure_daemon():
    if is_daemon_running():
        return True, "daemon running"
    if start_daemon():
        return True, "daemon started"
    return False, "daemon not running (WeChat may not be open)"


def stop_daemon():
    """Stop daemon after sync to avoid WeChat anti-cheat detection."""
    try:
        _run_wx_raw(["daemon", "stop"], timeout=10)
        return True
    except Exception:
        return False


def safe_new_messages(limit=500):
    """通过 wx new-messages 获取全量增量消息。单次调用，跨全部会话。"""
    out = _run_wx_raw(["new-messages", "--json", "-n", str(limit)], timeout=120)
    return json.loads(out) if out else []


def safe_history(group_name, limit=500, since=None):
    """通过 wx history 获取指定群消息。LOW RISK，替代 export。"""
    args = ["history", group_name, "--json", "-n", str(limit)]
    if since:
        args.extend(["--since", since])
    out = _run_wx_raw(args, timeout=120)
    return json.loads(out) if out else []


def safe_export_sessions(limit=50):
    """Get session list via daemon."""
    out = _run_wx_raw(["sessions", "-n", str(limit), "--json"], timeout=30)
    return json.loads(out) if out else []


def safe_get_members(group_name):
    """Get group members via daemon."""
    out = _run_wx_raw(["members", group_name, "--json"], timeout=30)
    members = json.loads(out) if out else []
    for m in members:
        if m.get("is_owner"):
            return m.get("display", "")
    return ""

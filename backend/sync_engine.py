import json
import re
import time
import random
import threading
from .config import SYNC_DELAY_MIN, SYNC_DELAY_MAX
from .database import (
    get_db, upsert_message, upsert_group, update_group_stats, add_sync_log,
    get_all_group_names, get_message_count
)
from .safe_wx import ensure_daemon, safe_export_sessions, safe_get_members, safe_new_messages, safe_history, stop_daemon, start_daemon, is_wechat_running


class SyncProgress:
    """Thread-safe progress tracker for sync operations."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.phase = ""
            self.current_group = ""
            self.group_index = 0
            self.total_groups = 0
            self.log_lines = []
            self.errors = []
            self.result = None
            self.running = False
            self.started_at = None

    def start(self):
        with self._lock:
            self.running = True
            self.started_at = time.time()
            self.phase = "starting"
            self.log_lines = []

    def set_phase(self, phase, total_groups=0):
        with self._lock:
            self.phase = phase
            if total_groups > 0:
                self.total_groups = total_groups
            self.group_index = 0
            self.current_group = ""

    def step_group(self, group_name, index=None, total=None):
        with self._lock:
            self.current_group = group_name
            if index is not None:
                self.group_index = index
            else:
                self.group_index += 1
            if total is not None:
                self.total_groups = total

    def add_log(self, message):
        with self._lock:
            self.log_lines.append(message)
            if len(self.log_lines) > 50:
                self.log_lines = self.log_lines[-50:]

    def add_error(self, error):
        with self._lock:
            self.errors.append(error)

    def finish(self, result):
        with self._lock:
            self.running = False
            self.result = result
            self.phase = "done"

    def to_dict(self):
        with self._lock:
            elapsed = time.time() - self.started_at if self.started_at else 0
            return {
                "running": self.running,
                "phase": self.phase,
                "current_group": self.current_group,
                "group_index": self.group_index,
                "total_groups": self.total_groups,
                "log_lines": list(self.log_lines[-8:]),
                "errors": list(self.errors[-5:]),
                "result": self.result,
                "elapsed": round(elapsed, 1)
            }


_safe_mode_available = None

PROJECT_RULES = [
    (["laldia", "laidia", "港湾"], "Laldia"),
    (["泰国"], "泰国光伏"),
    (["rama4", "rama 4"], "Rama4"),
]

CATEGORY_RULES = [
    (["ground improvement", "地基处理", "地基", "gi "], "地基处理"),
    (["mep"], "建筑MEP"),
    (["保险"], "保险"),
    (["物流"], "内部沟通"),
    (["成本", "costing"], "内部沟通"),
    (["沟通群", "总包沟通"], "内部沟通"),
    (["四航院", "水规院", "水运院"], "设计院合作"),
    (["一航局", "二航局", "三航局", "四航局"], "施工局合作"),
]

SKIP_KEYWORDS = ["通威", "364mw"]

SUBCATEGORY_RULES = [
    (["护舷", "天盾", "泰鸿", "特瑞堡", "fender", "橡胶"], "护舷"),
    (["管桩", "建华", "裕大", "pipe"], "管桩"),
    (["钢管", "steel pipe"], "钢管"),
    (["管道", "中财", "狼博", "日丰", "伟星", "lesso"], "管道"),
    (["桩基", "中岩", "岩土", "地基"], "桩基/地基"),
    (["钢结构", "钢构", "oriental castle", "中冶"], "钢结构"),
    (["电气", "中科芯源", "芯源", "配电"], "电气"),
    (["石料", "欧博", "军西", "土工", "疏浚", "吹填"], "石料/土工"),
    (["钢轨", "ganrail", "轨道", "道岔"], "钢轨"),
    (["mep", "机电"], "机电总包"),
    (["浪潮", "辛玮", "inspur", "弱电", "智能"], "弱电"),
    (["利锋", "消防", "lifeng"], "消防"),
    (["山西安装", "sig", "安装"], "机电安装"),
    (["江苏", "jsi", "省安"], "机电安装"),
    (["citcc", "通信"], "通信"),
    (["中交特种", "cccc", "特种"], "地基处理"),
    (["geoharbour", "geo harbour"], "地基处理"),
    (["江苏", "地基"], "地基处理"),
    (["保险经纪", "保险", "中怡", "aon", "怡"], "保险经纪"),
    (["物流", "捷环", "logistic", "货运", "运输", "报关"], "物流"),
    (["成本", "costing", "测算"], "成本测算"),
    (["设计", "四航院", "水规院", "水运院", "consult"], "设计咨询"),
    (["四航局", "一航局", "二航局", "三航局", "施工", "contractor"], "施工"),
]


def _infer_project(name):
    lower = name.lower()
    for keywords, proj in PROJECT_RULES:
        if any(kw in lower for kw in keywords):
            if any(sk in lower for sk in SKIP_KEYWORDS):
                return None
            return proj
    return None


def _fetch_group_owner(group_name):
    try:
        return safe_get_members(group_name)
    except Exception:
        return ""


def _infer_category(name):
    lower = name.lower()
    for keywords, cat in CATEGORY_RULES:
        if any(kw in lower for kw in keywords):
            return cat
    return "其他"


def _infer_subcategory(name, category=None):
    lower = name.lower()
    for keywords, sub in SUBCATEGORY_RULES:
        if any(kw in lower for kw in keywords):
            return sub
    return ""


def _human_delay(reason_hint="", progress=None):
    delay = random.uniform(SYNC_DELAY_MIN, SYNC_DELAY_MAX)
    if reason_hint:
        msg = f"[延迟 {delay:.1f}s] {reason_hint}"
        print(msg)
        if progress:
            progress.add_log(msg)
    time.sleep(delay)


def init_daemon():
    """Start daemon at sync start. Caches success to skip future checks."""
    global _safe_mode_available
    if _safe_mode_available:
        return True, "cached"

    ok, msg = ensure_daemon()
    _safe_mode_available = ok
    if not ok:
        print(f"[sync] daemon 未就绪 ({msg})")
    return ok, msg


def _discover_new_groups(progress=None):
    sessions = safe_export_sessions(limit=200)
    group_names = set(get_all_group_names())
    new_groups = []

    for s in sessions:
        if s.get("chat_type") != "group":
            continue
        name = s.get("chat", "")
        if not name or name in group_names:
            continue

        proj = _infer_project(name)
        if not proj:
            continue

        category = _infer_category(name)
        sub_category = _infer_subcategory(name, category)
        upsert_group(name, category, sub_category=sub_category, project=proj)
        group_names.add(name)
        new_groups.append((name, category, sub_category, proj))
        if progress:
            progress.add_log(f"发现新群: {name}")

    return new_groups


def _pull_group_messages(group_name, limit=200, since=None):
    return safe_history(group_name, limit=limit, since=since)


def _store_group_messages(group_name, messages):
    conn = get_db()
    group = conn.execute("SELECT id FROM groups WHERE name=?", (group_name,)).fetchone()
    if not group:
        group_id = upsert_group(group_name, _infer_category(group_name),
                                project=_infer_project(group_name) or "Laldia")
    else:
        group_id = group["id"]

    new_count = 0
    for msg in messages:
        if _upsert_from_wx_msg(conn, group_id, msg):
            new_count += 1

    count = conn.execute("SELECT COUNT(*) as cnt FROM messages WHERE group_id=?", (group_id,)).fetchone()["cnt"]
    last_date = max((m.get("time", "") for m in messages), default=None) if messages else None
    update_group_stats(group_id, last_active_date=last_date, total_messages=count, conn=conn)
    conn.close()
    return {"new": new_count, "total": count}


def sync(progress=None):
    from .file_downloader import download_new_files

    if progress:
        progress.start()
        progress.set_phase("starting")

    global _safe_mode_available
    if not _safe_mode_available:
        if progress:
            progress.add_log("检查微信状态...")
        if not is_wechat_running():
            result = {"status": "daemon_unavailable", "message": "微信未运行，请先打开微信",
                    "groups_updated": 0, "messages_new": 0, "errors": [],
                    "new_groups_discovered": [], "files_downloaded": 0}
            if progress:
                progress.add_log("失败: 微信未运行")
                progress.finish(result)
            return result

        if progress:
            progress.add_log("启动 daemon（提取密钥+解密数据库，约需 15-20 秒，请耐心等待）...")
        if not start_daemon():
            result = {"status": "daemon_unavailable", "message": "daemon 启动失败，请稍后重试",
                    "groups_updated": 0, "messages_new": 0, "errors": [],
                    "new_groups_discovered": [], "files_downloaded": 0}
            if progress:
                progress.add_log("失败: daemon 启动失败")
                progress.finish(result)
            return result
        _safe_mode_available = True

    stats = {"groups_updated": 0, "messages_new": 0, "errors": [],
             "new_groups_discovered": [], "files_downloaded": 0}

    project_keywords = []
    for keywords, _proj in PROJECT_RULES:
        for kw in keywords:
            project_keywords.append(kw)

    try:
        # === PHASE A: All wx-cli calls (daemon alive) ===

        # Step 1: discover new groups
        if progress:
            progress.set_phase("discovering")
            progress.add_log("正在扫描会话列表，发现新群...")
        new_groups = []
        try:
            for name, cat, sub, proj in _discover_new_groups(progress=progress):
                new_groups.append((name, cat, sub, proj))
                stats["new_groups_discovered"].append({"name": name, "category": cat, "project": proj})
        except Exception as e:
            stats["errors"].append(f"discover: {str(e)}")
            if progress:
                progress.add_error(str(e))

        # Step 2: single wx new-messages call (no per-group delays!)
        if progress:
            progress.set_phase("syncing")
            progress.add_log("拉取增量消息 (wx new-messages -n 2000)...")
        try:
            all_new = safe_new_messages(limit=2000)
            if progress:
                progress.add_log(f"收到 {len(all_new)} 条新消息")
        except Exception as e:
            all_new = []
            stats["errors"].append(f"new-messages: {str(e)}")
            if progress:
                progress.add_error(str(e))

        # === KILL DAEMON IMMEDIATELY ===
        stop_daemon()
        _safe_mode_available = False
        if progress:
            progress.add_log("daemon 已关闭")

        # === PHASE B: Pure DB processing (daemon dead, zero risk) ===

        # Filter and group messages by chat
        grouped = {}
        for msg in all_new:
            chat_name = msg.get("chat", "")
            if msg.get("chat_type") != "group":
                continue
            if not any(kw in chat_name.lower() for kw in project_keywords):
                continue
            if any(sk in chat_name.lower() for sk in SKIP_KEYWORDS):
                continue
            grouped.setdefault(chat_name, []).append(msg)

        group_names = list(grouped.keys())
        if progress and group_names:
            progress.add_log(f"写入 {len(group_names)} 个群的消息到数据库")

        for idx, gname in enumerate(group_names, 1):
            msgs = grouped[gname]
            if progress:
                progress.step_group(gname, idx)
                progress.set_phase("writing", total_groups=len(group_names))
            try:
                r = _store_group_messages(gname, msgs)
                stats["messages_new"] += r["new"]
                if r["new"] > 0:
                    stats["groups_updated"] += 1
            except Exception as e:
                stats["errors"].append(f"{gname}: {str(e)}")
                if progress:
                    progress.add_error(f"{gname}: {str(e)}")

        # File download (local filesystem, no wx-cli)
        if progress:
            progress.set_phase("files")
            progress.add_log("检查新文件...")
        try:
            file_stats = download_new_files()
            stats["files_downloaded"] = file_stats.get("downloaded", 0)
        except Exception as e:
            stats["errors"].append(f"download_files: {str(e)}")
            if progress:
                progress.add_error(str(e))

        add_sync_log("全部群组", None, 0, stats["messages_new"],
                      "ok" if not stats["errors"] else f"部分错误: {len(stats['errors'])}个群")

    finally:
        if _safe_mode_available:
            stop_daemon()
            _safe_mode_available = False

    if progress:
        progress.finish(stats)
    return stats


_loc_id_re = re.compile(r"local_id=(\d+)")


def _extract_local_id(msg):
    lid = msg.get("local_id")
    if lid:
        return lid
    ts = msg.get("timestamp")
    if ts:
        m = _loc_id_re.search(msg.get("content", ""))
        if m:
            return int(m.group(1))
        return ts
    return 0


def _upsert_from_wx_msg(conn, group_id, msg):
    local_id = _extract_local_id(msg)
    sender = msg.get("sender", "未知")
    content = msg.get("content", "")
    msg_time = msg.get("time", "")
    msg_date = msg_time[:10] if msg_time else ""
    msg_type = msg.get("type", "text")
    raw_json = json.dumps(msg, ensure_ascii=False)

    existing = conn.execute(
        "SELECT id FROM messages WHERE group_id=? AND local_id=?",
        (group_id, local_id)
    ).fetchone()

    if existing:
        return False

    cur = conn.execute("""
        INSERT INTO messages (group_id, local_id, sender, content, msg_time,
                              msg_date, msg_type, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (group_id, local_id, sender, content, msg_time, msg_date, msg_type, raw_json))

    from .contact_extractor import extract_and_save
    extract_and_save(conn, group_id, cur.lastrowid, sender, content)
    return True


def get_sync_stats():
    conn = get_db()
    group_count = conn.execute("SELECT COUNT(*) as cnt FROM groups WHERE deleted=0").fetchone()["cnt"]
    msg_count = conn.execute("SELECT COUNT(*) as cnt FROM messages").fetchone()["cnt"]
    last_sync = conn.execute(
        "SELECT * FROM sync_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return {
        "group_count": group_count,
        "message_count": msg_count,
        "last_sync": dict(last_sync) if last_sync else None
    }

import json
import os
import re
import sys
import time
import random
import threading

# Windows 控制台默认 GBK，遇到 emoji 群名会 crash — 尽量切到 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass
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
    (["cmi"], "CMI MOD2"),
    (["zoo"], "ZOO"),
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


def _discover_new_chats(progress=None, session_limit=500):
    """
    发现新会话（群 + 私聊，全量），不按 PROJECT_RULES 过滤。
    只写记录，不额外调 wx-cli 抓群主（延迟到 backfill 时按需拉）。
    """
    sessions = safe_export_sessions(limit=session_limit)
    known_names = set(get_all_group_names())
    new_chats = []

    for s in sessions:
        name = s.get("chat", "")
        chat_type = s.get("chat_type", "")
        if not name or name in known_names:
            continue
        if chat_type not in ("group", "private"):
            continue
        # 硬性黑名单：即使全量也要跳过噪声（如"通威"、"364mw"）
        if any(sk in name.lower() for sk in SKIP_KEYWORDS):
            continue

        if chat_type == "group":
            proj = _infer_project(name)
            category = _infer_category(name)
            sub_category = _infer_subcategory(name, category)
        else:
            proj, category, sub_category = None, "私聊", None

        upsert_group(name, category or "其他", sub_category=sub_category,
                     project=proj, chat_type=chat_type)
        known_names.add(name)
        new_chats.append((name, category, sub_category, proj, chat_type))
        if progress:
            tag = "私聊" if chat_type == "private" else "群"
            progress.add_log(f"发现新{tag}: {name}")

    return new_chats


# 向后兼容别名
_discover_new_groups = _discover_new_chats


def _pull_group_messages(group_name, limit=200, since=None):
    return safe_history(group_name, limit=limit, since=since)


def _store_group_messages(group_name, messages, default_chat_type="group"):
    """
    写入某个会话（群或私聊）的消息。假定 chat 记录已存在（discovery 阶段建好）。
    若不存在（罕见：daemon 报了未识别的 chat），按 default_chat_type 兜底建一条。
    不做任何 wx-cli 调用（可在 Phase B 安全调用）。
    """
    conn = get_db()
    group = conn.execute("SELECT id FROM groups WHERE name=?", (group_name,)).fetchone()
    if not group:
        cat = "私聊" if default_chat_type == "private" else _infer_category(group_name)
        proj = None if default_chat_type == "private" else _infer_project(group_name)
        group_id = upsert_group(group_name, cat or "其他", project=proj,
                                chat_type=default_chat_type)
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

    backfill_limit = int(os.environ.get("SYNC_BACKFILL_LIMIT", "100"))

    try:
        # === PHASE A: All wx-cli calls (daemon alive) ===

        # Step 1: 发现新会话（群 + 私聊，全量，不过滤 PROJECT_RULES）
        if progress:
            progress.set_phase("discovering")
            progress.add_log("扫描会话列表，发现新会话（含私聊）...")
        new_chats = []
        try:
            for name, cat, sub, proj, ctype in _discover_new_chats(progress=progress):
                new_chats.append((name, cat, sub, proj, ctype))
                stats["new_groups_discovered"].append({
                    "name": name, "category": cat, "project": proj, "chat_type": ctype
                })
        except Exception as e:
            stats["errors"].append(f"discover: {str(e)}")
            if progress:
                progress.add_error(str(e))

        # Step 1.5: 空会话 backfill（首次全量 + 后续新会话补齐）
        # 优先级：本次刚发现的（sessions 顺序 = 最近活跃）→ 已存在但空的
        # 每次最多 backfill_limit 个，避免超日限
        # 跳过 backfill_failed=1 的会话（"找不到联系人/消息记录"类，永远拉不到）
        try:
            fresh_names = [n for n, _c, _s, _p, _t in new_chats]
            _conn = get_db()
            other_empty = [r["name"] for r in _conn.execute("""
                SELECT name FROM groups
                WHERE deleted=0 AND total_messages=0 AND COALESCE(backfill_failed,0)=0
                ORDER BY (last_active_date IS NULL), last_active_date DESC, id
            """).fetchall() if r["name"] not in fresh_names]
            _conn.close()
            backfill_names = (fresh_names + other_empty)[:backfill_limit]
        except Exception as e:
            stats["errors"].append(f"query empty chats: {str(e)}")
            backfill_names = []

        new_chat_msgs = {}
        permanently_failed = []
        if backfill_names:
            total = len(backfill_names)
            if progress:
                progress.set_phase("backfilling", total_groups=total)
                progress.add_log(f"空会话 {total} 个 (cap={backfill_limit})，逐一拉取历史...")
            for idx, name in enumerate(backfill_names, 1):
                if progress:
                    progress.step_group(name, idx, total=total)
                _human_delay(f"空会话 {name} 拉历史前节流", progress=progress)
                try:
                    msgs = safe_history(name, limit=500)
                    new_chat_msgs[name] = msgs
                    if progress:
                        progress.add_log(f"空会话 {name}: {len(msgs)} 条")
                except Exception as e:
                    err_msg = str(e)
                    # "找不到联系人" / "找不到 X 的消息记录" → 永久跳过，不算错误
                    if "找不到" in err_msg:
                        permanently_failed.append(name)
                        if progress:
                            progress.add_log(f"跳过 {name}（无历史）")
                    else:
                        stats["errors"].append(f"history {name}: {err_msg}")
                        if progress:
                            progress.add_error(f"history {name}: {err_msg}")

        # 标记本轮永久失败的会话（下次不再重试）
        if permanently_failed:
            try:
                _conn = get_db()
                _conn.executemany(
                    "UPDATE groups SET backfill_failed=1 WHERE name=?",
                    [(n,) for n in permanently_failed]
                )
                _conn.commit()
                _conn.close()
                stats["skipped_no_history"] = len(permanently_failed)
            except Exception as e:
                stats["errors"].append(f"mark backfill_failed: {str(e)}")

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

        # 按 chat_name 归并消息（群 + 私聊，全量；只跳硬黑名单）
        grouped = {}
        chat_type_hint = {}
        for msg in all_new:
            chat_name = msg.get("chat", "")
            ctype = msg.get("chat_type", "")
            if not chat_name or ctype not in ("group", "private"):
                continue
            if any(sk in chat_name.lower() for sk in SKIP_KEYWORDS):
                continue
            grouped.setdefault(chat_name, []).append(msg)
            chat_type_hint[chat_name] = ctype

        # 合并 backfill 拉到的历史
        for cname, msgs in new_chat_msgs.items():
            grouped.setdefault(cname, []).extend(msgs)

        chat_names = list(grouped.keys())
        if progress and chat_names:
            progress.add_log(f"写入 {len(chat_names)} 个会话的消息到数据库")

        for idx, cname in enumerate(chat_names, 1):
            msgs = grouped[cname]
            if progress:
                progress.step_group(cname, idx)
                progress.set_phase("writing", total_groups=len(chat_names))
            try:
                r = _store_group_messages(cname, msgs,
                                          default_chat_type=chat_type_hint.get(cname, "group"))
                stats["messages_new"] += r["new"]
                if r["new"] > 0:
                    stats["groups_updated"] += 1
            except Exception as e:
                stats["errors"].append(f"{cname}: {str(e)}")
                if progress:
                    progress.add_error(f"{cname}: {str(e)}")

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


def backfill_empty_groups(project=None, limit_per_group=500):
    """
    补齐已发现但消息为空的群历史。
    用于修复：新群发现时只创建了记录，但 new-messages 不返回其历史。

    Args:
        project: 可选。只处理指定项目的空群。None 表示全部。
        limit_per_group: 每群拉多少条历史。

    Returns:
        {"targets": [...], "backfilled": [{"name","new","total"}], "errors": [...]}
    """
    conn = get_db()
    sql = "SELECT name FROM groups WHERE deleted=0 AND total_messages=0"
    params = []
    if project:
        sql += " AND project=?"
        params.append(project)
    targets = [r["name"] for r in conn.execute(sql, params).fetchall()]
    conn.close()

    result = {"targets": targets, "backfilled": [], "errors": []}
    if not targets:
        return result

    if not is_wechat_running():
        result["errors"].append("WeChat 未运行")
        return result

    global _safe_mode_available
    ok, msg = ensure_daemon()
    _safe_mode_available = ok
    if not ok:
        result["errors"].append(f"daemon 启动失败: {msg}")
        return result

    try:
        for i, name in enumerate(targets, 1):
            print(f"[{i}/{len(targets)}] {name}")
            _human_delay(f"backfill {name}")
            try:
                msgs = safe_history(name, limit=limit_per_group)
                r = _store_group_messages(name, msgs)
                result["backfilled"].append({"name": name, "pulled": len(msgs),
                                              "new": r["new"], "total": r["total"]})
                print(f"  pulled={len(msgs)} new={r['new']} total={r['total']}")
            except Exception as e:
                result["errors"].append(f"{name}: {str(e)}")
                print(f"  ERROR: {e}")
    finally:
        stop_daemon()
        _safe_mode_available = False

    return result


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

import json
import os
import subprocess
import shutil
from datetime import datetime
from .database import (
    get_db, upsert_message, upsert_group, update_group_stats, add_sync_log,
    get_all_group_names, get_message_count
)


WX_CLI = shutil.which("wx") or "wx"

_wx_js = None
if WX_CLI != "wx" and WX_CLI.lower().endswith(".cmd"):
    _wx_dir = os.path.dirname(WX_CLI)
    _candidate = os.path.join(_wx_dir, "node_modules", "@jackwener", "wx-cli", "bin", "wx.js")
    if os.path.isfile(_candidate):
        _wx_js = _candidate

PROJECT_RULES = [
    (["laldia", "港湾"], "Laldia"),
    (["泰国"], "泰国光伏"),
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
        output = _run_wx(["members", group_name, "--json"], timeout=30)
        members = json.loads(output) if output else []
        for m in members:
            if m.get("is_owner"):
                return m.get("display", "")
    except Exception:
        pass
    return ""


def _infer_category(name):
    lower = name.lower()
    for keywords, cat in CATEGORY_RULES:
        if any(kw in lower for kw in keywords):
            return cat
    return "供应商咨询"


def _infer_subcategory(name, category=None):
    lower = name.lower()
    for keywords, sub in SUBCATEGORY_RULES:
        if any(kw in lower for kw in keywords):
            return sub
    return ""


def _run_wx(args, timeout=120):
    import tempfile, os as _os
    if _wx_js:
        cmd_list = ["node", _wx_js] + args
    else:
        if WX_CLI == "wx" and not shutil.which("wx"):
            raise RuntimeError("wx-cli 未安装")
        cmd_list = [WX_CLI] + args

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    tmp.close()
    try:
        result = subprocess.run(
            cmd_list,
            stdout=open(tmp.name, "w", encoding="utf-8"),
            stderr=subprocess.PIPE, text=False, timeout=timeout
        )
        with open(tmp.name, "r", encoding="utf-8") as f:
            stdout = f.read()
    except FileNotFoundError:
        _os.unlink(tmp.name)
        raise RuntimeError("wx-cli 未安装")
    except subprocess.TimeoutExpired:
        _os.unlink(tmp.name)
        raise RuntimeError(f"wx-cli 执行超时 ({timeout}s)")
    finally:
        try:
            _os.unlink(tmp.name)
        except OSError:
            pass
    if result.returncode != 0:
        stderr_bytes = result.stderr or b""
        try:
            stderr = stderr_bytes.decode("gbk").strip()
        except (UnicodeDecodeError, LookupError):
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        if "not found" in stderr.lower() or "not recognized" in stderr.lower():
            raise RuntimeError("wx-cli 未安装")
        if "init" in stderr.lower():
            raise RuntimeError("wx-cli 未初始化，请运行: wx init")
        raise RuntimeError(f"wx-cli 错误: {stderr or '未知错误'}")
    return (stdout or "").strip()


def discover_new_groups(project=None):
    output = _run_wx(["sessions", "-n", "200", "--json"])
    sessions = json.loads(output) if output else []
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
        if project and proj != project:
            continue

        category = _infer_category(name)
        sub_category = _infer_subcategory(name, category)
        owner = _fetch_group_owner(name)
        upsert_group(name, category, sub_category=sub_category, project=proj, group_creator=owner)
        group_names.add(name)
        new_groups.append((name, category, sub_category, proj))

    return new_groups


def sync_incremental():
    stats = {"groups_updated": 0, "messages_new": 0, "errors": [],
             "new_groups_discovered": [], "contacts_extracted": 0}

    # Step 1: discover new groups (all projects)
    try:
        for name, cat, sub, proj in discover_new_groups():
            stats["new_groups_discovered"].append({"name": name, "category": cat, "project": proj})
    except Exception as e:
        stats["errors"].append(f"discover_new_groups: {str(e)}")

    # Step 2: find active groups from sessions JSON (all projects)
    project_keywords = []
    for keywords, _proj in PROJECT_RULES:
        for kw in keywords:
            project_keywords.append(kw)
    active_groups = set()

    try:
        sessions_json = _run_wx(["sessions", "-n", "200", "--json"])
        sessions = json.loads(sessions_json) if sessions_json else []
        for s in sessions:
            if s.get("chat_type") != "group":
                continue
            name = s.get("chat", "")
            if any(kw in name.lower() for kw in project_keywords):
                if not any(sk in name.lower() for sk in SKIP_KEYWORDS):
                    active_groups.add(name)
    except Exception as e:
        stats["errors"].append(f"sessions: {str(e)}")

    # Step 3: merge with known groups that have no messages yet (never synced)
    conn0 = get_db()
    unsynced = set()
    for row in conn0.execute(
        "SELECT g.name FROM groups g LEFT JOIN messages m ON m.group_id=g.id "
        "WHERE m.id IS NULL AND g.deleted=0"
    ).fetchall():
        unsynced.add(row["name"])
    conn0.close()

    all_groups = active_groups | unsynced

    # Step 4: for each group, pull messages since last known date
    for gname in all_groups:
        try:
            conn = get_db()
            group = conn.execute("SELECT id FROM groups WHERE name=?", (gname,)).fetchone()
            if not group:
                conn.close()
                continue
            gid = group["id"]

            last = conn.execute(
                "SELECT msg_date FROM messages WHERE group_id=? ORDER BY msg_time DESC LIMIT 1",
                (gid,)
            ).fetchone()
            conn.close()

            since_date = last["msg_date"] if last else "2025-01-01"

            output = _run_wx(
                ["history", gname, "--json", "--since", since_date, "-n", "500"],
                timeout=300
            )
            messages = json.loads(output) if output else []

            conn2 = get_db()
            new_in_group = 0
            for msg in messages:
                if _upsert_from_wx_msg(conn2, gid, msg):
                    new_in_group += 1

            count = conn2.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE group_id=?", (gid,)
            ).fetchone()["cnt"]
            last_time = conn2.execute(
                "SELECT msg_time FROM messages WHERE group_id=? ORDER BY msg_time DESC LIMIT 1",
                (gid,)
            ).fetchone()
            update_group_stats(gid, last_active_date=last_time["msg_time"] if last_time else None,
                              total_messages=count, conn=conn2)
            conn2.close()

            stats["messages_new"] += new_in_group
            if new_in_group > 0:
                stats["groups_updated"] += 1
        except Exception as e:
            stats["errors"].append(f"{gname}: {str(e)}")

    add_sync_log("全部群组(增量)", None, 0, stats["messages_new"],
                  "ok" if not stats["errors"] else f"部分错误: {len(stats['errors'])}个群")

    return stats


def sync_full(group_name, limit=2000):
    output = _run_wx(["history", group_name, "--json", "-n", str(limit)], timeout=300)
    messages = json.loads(output) if output else []

    conn = get_db()
    group = conn.execute("SELECT id FROM groups WHERE name=?", (group_name,)).fetchone()
    if not group:
        group_id = upsert_group(group_name, _infer_category(group_name), project="Laldia")
    else:
        group_id = group["id"]

    new_count = 0
    for msg in messages:
        if _upsert_from_wx_msg(conn, group_id, msg):
            new_count += 1

    count = conn.execute("SELECT COUNT(*) as cnt FROM messages WHERE group_id=?", (group_id,)).fetchone()["cnt"]
    last_date = None
    if messages:
        last_date = messages[-1].get("time", "")
    update_group_stats(group_id, last_active_date=last_date, total_messages=count, conn=conn)
    conn.close()

    add_sync_log(group_name, None, len(messages), new_count, "ok")
    return {"group": group_name, "pulled": len(messages), "new": new_count, "total": count}


def sync_all_groups_full(limit=2000):
    results = []
    errors = []
    for gname in get_all_group_names():
        try:
            r = sync_full(gname, limit)
            results.append(r)
        except Exception as e:
            errors.append({"group": gname, "error": str(e)})
    return {"results": results, "errors": errors}


def _upsert_from_wx_msg(conn, group_id, msg):
    local_id = msg.get("local_id")
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

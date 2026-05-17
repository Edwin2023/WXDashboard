import threading
import time
import subprocess
from flask import Flask, render_template, request, jsonify
from .config import TEMPLATES_DIR, STATIC_DIR, FLASK_HOST, FLASK_PORT, get_wx_file_url, get_wx_file_path
from .database import (
    init_db, get_all_groups, get_group, get_categories,
    get_messages, get_latest_messages, search_messages,
    get_sync_status, get_message_count, get_contacts, get_projects,
    set_subcategory
)
from .sync_engine import sync_incremental, sync_all_groups_full, sync_full, get_sync_stats, discover_new_groups

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)

_auto_sync_thread = None
_auto_sync_interval = 60
_auto_sync_running = False
_auto_sync_last_result = None


def _auto_sync_loop():
    global _auto_sync_running, _auto_sync_last_result
    while _auto_sync_running:
        time.sleep(_auto_sync_interval)
        if not _auto_sync_running:
            break
        try:
            _auto_sync_last_result = sync_incremental()
        except Exception as e:
            _auto_sync_last_result = {"error": str(e)}


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/groups")
def api_groups():
    category = request.args.get("category")
    project = request.args.get("project", "Laldia")
    groups = get_all_groups(category=category, project=project)
    for g in groups:
        g["message_count"] = get_message_count(g["id"])
    return jsonify(groups)


@app.route("/api/groups/<int:group_id>")
def api_group_detail(group_id):
    group = get_group(group_id)
    if not group:
        return jsonify({"error": "群组不存在"}), 404
    group["message_count"] = get_message_count(group_id)
    return jsonify(group)


@app.route("/api/categories")
def api_categories():
    project = request.args.get("project", "Laldia")
    return jsonify(get_categories(project=project))


@app.route("/api/groups/<int:group_id>/messages")
def api_group_messages(group_id):
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    messages, total = get_messages(group_id, limit=limit, offset=offset)
    return jsonify({"messages": messages, "total": total, "limit": limit, "offset": offset})


@app.route("/api/groups/<int:group_id>/messages/latest")
def api_group_latest_messages(group_id):
    n = request.args.get("n", 3, type=int)
    messages = get_latest_messages(group_id, n=n)
    return jsonify(messages)


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "缺少搜索关键词"}), 400
    group_id = request.args.get("group_id", type=int)
    results = search_messages(q, group_id=group_id)
    return jsonify({"query": q, "results": results, "count": len(results)})


@app.route("/api/sync/refresh", methods=["POST"])
def api_sync_refresh():
    try:
        stats = sync_incremental()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sync/pull-all", methods=["POST"])
def api_sync_pull_all():
    group_name = request.args.get("group")
    try:
        if group_name:
            result = sync_full(group_name)
            return jsonify(result)
        else:
            result = sync_all_groups_full()
            return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sync/status")
def api_sync_status():
    stats = get_sync_stats()
    return jsonify(stats)


@app.route("/api/projects")
def api_projects():
    return jsonify(get_projects())


@app.route("/api/groups/<int:group_id>/contacts")
def api_group_contacts(group_id):
    contacts = get_contacts(group_id=group_id)
    return jsonify(contacts)


@app.route("/api/files/check")
def api_check_file():
    msg_date = request.args.get("msg_date", "")
    filename = request.args.get("filename", "")
    url = get_wx_file_url(msg_date, filename)
    if url:
        return jsonify({"exists": True, "url": url})
    return jsonify({"exists": False})


@app.route("/api/files/open", methods=["POST"])
def api_open_file():
    msg_date = request.args.get("msg_date", "")
    filename = request.args.get("filename", "")
    file_path = get_wx_file_path(msg_date, filename)
    if file_path:
        import os as _os
        subprocess.Popen(["explorer", "/select,", _os.path.normpath(file_path)])
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "文件不存在"})


@app.route("/api/groups/<int:group_id>/subcategory", methods=["POST"])
def api_set_subcategory(group_id):
    data = request.get_json(force=True)
    sub = data.get("sub_category", "")
    set_subcategory(group_id, sub)
    return jsonify({"ok": True})


@app.route("/api/sync/discover", methods=["POST"])
def api_sync_discover():
    try:
        new_groups = discover_new_groups()
        return jsonify({"new_groups": new_groups, "count": len(new_groups)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sync/auto/status")
def api_auto_sync_status():
    return jsonify({
        "running": _auto_sync_running,
        "interval": _auto_sync_interval,
        "last_result": _auto_sync_last_result
    })


@app.route("/api/sync/auto/start", methods=["POST"])
def api_auto_sync_start():
    global _auto_sync_thread, _auto_sync_running, _auto_sync_interval
    data = request.get_json(silent=True) or {}
    interval = int(data.get("interval", 60))
    if interval < 10:
        interval = 10
    _auto_sync_interval = interval

    if _auto_sync_running:
        return jsonify({"running": True, "interval": _auto_sync_interval})

    _auto_sync_running = True
    _auto_sync_thread = threading.Thread(target=_auto_sync_loop, daemon=True)
    _auto_sync_thread.start()
    return jsonify({"running": True, "interval": _auto_sync_interval})


@app.route("/api/sync/auto/stop", methods=["POST"])
def api_auto_sync_stop():
    global _auto_sync_running
    _auto_sync_running = False
    return jsonify({"running": False})


if __name__ == "__main__":
    init_db()
    print(f"Laldia 微信群台账启动: http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True)

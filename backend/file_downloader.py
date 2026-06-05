import os
import re
import csv
import shutil
from datetime import datetime

from .config import DOWNLOAD_DIR, get_wx_file_path
from .database import get_undownloaded_file_messages, mark_files_downloaded

FILENAME_RE = re.compile(r'\[文件\]\s*(.+)')


def _sanitize_name(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


def _parse_filename(content):
    m = FILENAME_RE.search(content)
    if not m:
        return None
    filename = m.group(1).strip()
    # 去掉行尾可能残留的引用标记
    filename = filename.split('\n')[0].strip()
    return filename or None


def download_new_files():
    messages = get_undownloaded_file_messages()
    if not messages:
        return {"downloaded": 0, "skipped": 0, "errors": [], "total_pending": 0}

    stats = {"downloaded": 0, "skipped": 0, "errors": [], "total_pending": len(messages)}
    downloaded_ids = []

    for msg in messages:
        filename = _parse_filename(msg["content"])
        if not filename:
            stats["skipped"] += 1
            stats["errors"].append(f"无法解析文件名: msg_id={msg['id']} content={msg['content'][:80]}")
            continue

        src_path = get_wx_file_path(msg["msg_date"], filename)
        if not src_path:
            stats["skipped"] += 1
            continue

        project = _sanitize_name(msg["project"] or "未分类")
        category = _sanitize_name(msg["category"] or "未分类")
        group_name = _sanitize_name(msg["group_name"] or "未知群")

        parent_dir = os.path.join(DOWNLOAD_DIR, project, category)
        file_date = (msg["msg_date"] or "").replace("-", "")[:8]  # "2026-06-04" -> "20260604"
        os.makedirs(parent_dir, exist_ok=True)

        # Find existing folder for this group (may have old date prefix)
        old_dir = None
        old_date = ""
        for entry in os.listdir(parent_dir):
            entry_path = os.path.join(parent_dir, entry)
            if os.path.isdir(entry_path) and entry.endswith("_" + group_name):
                old_dir = entry_path
                prefix = entry[:8]
                if prefix.isdigit() and len(prefix) == 8:
                    old_date = prefix
                break

        new_folder_name = f"{file_date}_{group_name}" if file_date else group_name
        dest_dir = os.path.join(parent_dir, new_folder_name)

        if old_dir and file_date and file_date > old_date:
            os.rename(old_dir, dest_dir)
        elif old_dir:
            dest_dir = old_dir

        os.makedirs(dest_dir, exist_ok=True)

        dest_path = os.path.join(dest_dir, filename)

        try:
            if os.path.isfile(dest_path):
                os.chmod(dest_path, 0o666)
                os.remove(dest_path)
            shutil.copy(src_path, dest_path)
            file_size = os.path.getsize(dest_path)
        except OSError as e:
            stats["errors"].append(f"复制失败: {filename}: {e}")
            continue

        _write_download_log(dest_dir, {
            "下载时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "消息时间": msg["msg_time"],
            "发送者": msg["sender"],
            "文件名": filename,
            "保存路径": dest_path,
            "文件大小": file_size,
            "源路径": src_path,
        })

        downloaded_ids.append(msg["id"])
        stats["downloaded"] += 1

    mark_files_downloaded(downloaded_ids)
    return stats


LOG_HEADER = ["下载时间", "消息时间", "发送者", "文件名", "保存路径", "文件大小", "源路径"]


def _write_download_log(dest_dir, entry):
    log_path = os.path.join(dest_dir, "_download_log.csv")
    write_header = not os.path.isfile(log_path)
    with open(log_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_HEADER)
        if write_header:
            writer.writeheader()
        writer.writerow(entry)

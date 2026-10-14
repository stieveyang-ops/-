# -*- coding: utf-8 -*-
"""Rebuild evidence_package/05_证据索引与哈希.md (SHA-256 index of the whole evidence package).

Usage:  python _rebuild_hash_index.py
The index excludes itself and this script.
"""
import datetime
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 待提交作品
PKG = os.path.join(ROOT, "evidence_package")
OUT = os.path.join(PKG, "05_证据索引与哈希.md")
SELF = {os.path.basename(__file__), os.path.basename(OUT)}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


rows = []
for base, dirs, files in os.walk(PKG):
    dirs.sort()
    for name in sorted(files):
        if name in SELF or name.startswith("~$"):
            continue
        p = os.path.join(base, name)
        rel = os.path.relpath(p, ROOT).replace("/", "\\")
        rows.append((rel, sha256(p), os.path.getsize(p)))
rows.sort(key=lambda r: r[0])

now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
lines = [
    "# 证据包哈希索引（SHA-256）",
    "",
    f"生成时间: {now}",
    "生成方式: Get-FileHash -Algorithm SHA256（等价实现，逐文件流式读取；本索引文件与再生成脚本自身不在索引内）",
    f"文件数: {len(rows)}",
    "",
]
lines += [f"{h}  {rel}" for rel, h, _ in rows]
lines.append("")

with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
    fh.write("\n".join(lines))
print("indexed files:", len(rows))
print("written:", OUT)

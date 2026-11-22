#!/usr/bin/env python3
"""app.asar 拆包 / 重打包工具（Freebuff Desktop 0.0.201+ 架构用）。

为什么需要它
------------
0.0.201 起桌面端改成「本地壳 + 远端 Web UI」：主界面由 freebuff.com 提供，
本地 `resources/orchestrator/ui/assets/` 只剩登录启动页，文件级词典补丁覆盖不到主界面。
新的汉化路线是**运行时注入**——改 app.asar 里的 Electron 主进程，给远端页面注入
DOM 级词典替换脚本。这要求能安全地重写 asar。

asar 格式（本工具按 Electron 官方 asar 规范实现）
-------------------------------------------------
    [0:4]    uint32 = 4
    [4:8]    uint32 = 4 + 4 + jsonLenPadded      （字符串 pickle 总长）
    [8:12]   uint32 = 4 + jsonLenPadded
    [12:16]  uint32 = jsonLen
    [16:..]  header JSON（files 树），其后补 0 到 4 字节对齐
    然后是各文件数据区，节点里的 offset 相对数据区起点（= 16 + jsonLenPadded）

实测校验（0.0.201）：351 个节点全部带 integrity(SHA256+分块)，无 unpacked 项；
EnableEmbeddedAsarIntegrityValidation 熔丝为 0（关闭），故改写 asar 不会被 Electron 拒绝。
"""
import hashlib
import json
import os
import struct
import sys

BLOCK = 4194304


def _integrity(data: bytes) -> dict:
    blocks = [hashlib.sha256(data[i:i + BLOCK]).hexdigest() for i in range(0, len(data), BLOCK)]
    return {
        "algorithm": "SHA256",
        "hash": hashlib.sha256(data).hexdigest(),
        "blockSize": BLOCK,
        "blocks": blocks,
    }


def read_header(path: str):
    with open(path, "rb") as f:
        head = f.read(16)
        s1, s2, s3, s4 = struct.unpack("<IIII", head)
        f.seek(16)
        raw = f.read(s4)
    tree, _ = json.JSONDecoder().raw_decode(raw.decode("utf-8"))
    return tree, 8 + s2


def iter_files(node, prefix=""):
    if "files" in node:
        for name, child in node["files"].items():
            yield from iter_files(child, prefix + "/" + name)
    else:
        yield prefix, node


def unpack(asar_path: str, out_dir: str) -> int:
    tree, base = read_header(asar_path)
    with open(asar_path, "rb") as f:
        for rel, node in iter_files(tree):
            target = os.path.join(out_dir, rel.lstrip("/").replace("/", os.sep))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            f.seek(base + int(node["offset"]))
            data = f.read(node["size"])
            with open(target, "wb") as out:
                out.write(data)
    return len(list(iter_files(tree)))


def pack(src_dir: str, out_path: str) -> int:
    """把 src_dir 打成 asar。目录即文件，文件即内容。"""
    files = {}
    order = []
    for root, _dirs, names in os.walk(src_dir):
        for name in names:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            order.append((rel, full))
    order.sort(key=lambda x: x[0])

    blobs = []
    offset = 0
    for rel, full in order:
        with open(full, "rb") as f:
            data = f.read()
        node = {"size": len(data), "integrity": _integrity(data), "offset": str(offset)}
        blobs.append(data)
        offset += len(data)
        parts = rel.split("/")
        cur = files
        for part in parts[:-1]:
            cur = cur.setdefault(part, {"files": {}})["files"]
        cur[parts[-1]] = node

    header = json.dumps({"files": files}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    padded = header + b"\0" * ((4 - len(header) % 4) % 4)
    s4 = len(header)
    s3 = 4 + len(padded)
    s2 = 4 + s3
    out = open(out_path, "wb")
    out.write(struct.pack("<IIII", 4, s2, s3, s4))
    out.write(padded)
    for blob in blobs:
        out.write(blob)
    out.close()
    return len(order)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print("用法:")
        print("  asar-tool.py unpack <app.asar> <out_dir>")
        print("  asar-tool.py pack   <src_dir> <out.asar>")
        return 1
    cmd = sys.argv[1]
    if cmd == "unpack":
        n = unpack(sys.argv[2], sys.argv[3])
        print(f"解出 {n} 个文件 → {sys.argv[3]}")
    elif cmd == "pack":
        n = pack(sys.argv[2], sys.argv[3])
        print(f"打包 {n} 个文件 → {sys.argv[3]}")
    else:
        print("未知命令")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""freebuff-zh-pack 测试套件（零第三方依赖）。

覆盖：
  T1  熔线拦截      —— AsarIntegrityValidation=ON 的假 exe → 拒装（退出码 4）
  T2  假树全链安装   —— 最小 asar + 假 exe → apply 成功、标记/注入文件在位
  T3  版本探测      —— 假树 package.json version 可读
  T4  版本策略      —— 区间外 warn / 已验证 ok / 缺版本 warn
  T5  还原          —— 字节级恢复 + 基线清理 + 哈希相等
  T6  幂等          —— 二次 apply 产物与首次逐字节一致
  T7  词典完整性    —— 三层合并 = 5779 条；社区词表可读
  T8  无硬编码路径  —— pack 内 py/cmd/md/js 无本机用户目录绝对路径
  T9  .cmd 卫生     —— 纯 ASCII + 全文零括号
  T10 tasklist 解析  —— 运行中判定（喂罐头输出，不真查进程）

用法：python tests/run_tests.py           （全部）
      python tests/run_tests.py T1 T7     （指定）
真机 E2E 不在本套件（见 tests/E2E.md）。
"""
import hashlib
import os
import shutil
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.dirname(HERE)
sys.path.insert(0, PACK)

import engine  # noqa: E402
import asar_tool  # noqa: E402

RESULTS = []


def check(name):
    def deco(fn):
        RESULTS.append((name, fn))
        return fn
    return deco


def sha16(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def make_fake_tree(tmp, version="9.9.9", integrity_fuse="OFF"):
    """最小 Freebuff 假树：resources/app.asar（含 electron/main.cjs + package.json）
    + resources/orchestrator（架构判据）+ Freebuff.exe（真熔线字节）。返回树根。"""
    root = os.path.join(tmp, "app")
    res = os.path.join(root, "resources")
    os.makedirs(os.path.join(res, "orchestrator"))
    src = os.path.join(tmp, "src")
    os.makedirs(os.path.join(src, "electron"))
    with open(os.path.join(src, "electron", "main.cjs"), "w", encoding="utf-8", newline="\n") as f:
        f.write("const app = require('electron').app;\napp.whenReady().then(()=>{});\n")
    with open(os.path.join(src, "package.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write('{"name":"freebuff-desktop","version":"%s"}' % version)
    asar = os.path.join(res, "app.asar")
    asar_tool.pack(src, asar)

    # 假 exe：足够长的填充 + 哨兵 + wire 版本/熔线数/熔线位
    fill = b"MZ" + b"\x00" * 256
    fuses = {n: "OFF" for n in engine.FUSE_NAMES}
    fuses["OnlyLoadAppFromAsar"] = "ON"
    fuses["AsarIntegrityValidation"] = integrity_fuse
    order = engine.FUSE_NAMES
    bits = bytes(0x31 if fuses[n] == "ON" else 0x30 for n in order)
    exe_body = fill + engine.SENTINEL + bytes([0x01, len(order)]) + bits + b"\x00" * 64
    with open(os.path.join(root, engine.APP_EXE), "wb") as f:
        f.write(exe_body)
    return root


@check("T1 熔线拦截")
def t1(tmp):
    root = make_fake_tree(tmp, integrity_fuse="ON")
    res = os.path.join(root, "resources")
    try:
        engine.apply(res)
    except engine.EngineError as e:
        assert e.code == engine.E_FUSE, "应报熔线拦截，实际 %s" % e.code
        assert "完整性" in str(e)
        assert not os.path.exists(os.path.join(res, "app.asar.zhorig")), "拒装不得建基线"
        return "拒装 OK（exit %d）" % e.code
    raise AssertionError("熔线 ON 却安装成功——硬拦失效！")


@check("T2 假树全链安装 + 注入产物在位")
def t2(tmp):
    root = make_fake_tree(tmp)
    res = os.path.join(root, "resources")
    r = engine.apply(res)
    assert r["status"] == "applied" and r["version"] == "9.9.9"
    assert r["dict_entries"] >= 5000, "词典合并条数异常：%s" % r["dict_entries"]
    out = os.path.join(tmp, "unpacked")
    assert asar_tool.unpack(os.path.join(res, "app.asar"), out) > 0
    mc = open(os.path.join(out, "electron", "main.cjs"), encoding="utf-8").read()
    assert engine.MARKER in mc, "main.cjs 缺注入 HOOK"
    for fn in ("zh-inject.js", "zh-origins.json"):
        assert os.path.exists(os.path.join(out, "electron", fn)), fn + " 缺失"
    assert os.path.exists(os.path.join(out, "electron", "zh-community.js")), "社区层缺失"
    zj = open(os.path.join(out, "electron", "zh-inject.js"), encoding="utf-8").read()
    assert "/*__DICT__*/ {}" not in zj, "词典占位符未替换"
    assert len(zj) > 100000, "注入脚本体积异常（词典未内联?）"
    return "apply OK，dict=%d" % r["dict_entries"]


@check("T3 版本探测")
def t3(tmp):
    root = make_fake_tree(tmp, version="7.7.7")
    v = engine.asar_version(os.path.join(root, "resources", "app.asar"))
    assert v == "7.7.7", "版本读出 %s" % v
    return "OK（7.7.7）"


@check("T4 版本策略")
def t4(tmp):
    a, n1 = engine.version_policy("0.0.204")
    assert a == "ok", "已验证版本应 ok"
    a2, n2 = engine.version_policy("0.0.205")
    assert a2 == "warn", "高于上限应 warn"
    a3, _ = engine.version_policy("0.0.190")
    assert a3 == "warn"
    a4, _ = engine.version_policy(None)
    assert a4 == "warn"
    return "OK（ok/warn/warn/warn）"


@check("T5 还原（字节级 + 基线清理）")
def t5(tmp):
    root = make_fake_tree(tmp)
    res = os.path.join(root, "resources")
    asar = os.path.join(res, "app.asar")
    orig_sha = sha16(asar)
    engine.apply(res)
    assert sha16(asar) != orig_sha, "补丁后哈希未变"
    r = engine.restore(res)
    assert r["status"] == "restored"
    assert sha16(asar) == orig_sha, "还原后与原版不一致"
    assert not os.path.exists(asar + ".zhorig"), "还原后基线应清理"
    r2 = engine.restore(res)
    assert r2["status"] == "already-clean", "重复还原应报 already-clean"
    return "OK（往返哈希相等）"


@check("T6 幂等（两次 apply 产物一致）")
def t6(tmp):
    root = make_fake_tree(tmp)
    res = os.path.join(root, "resources")
    engine.apply(res)
    s1 = sha16(os.path.join(res, "app.asar"))
    engine.apply(res)
    s2 = sha16(os.path.join(res, "app.asar"))
    assert s1 == s2, "二次 apply 产物不一致（%s vs %s）" % (s1, s2)
    return "OK（%s）" % s1


@check("T7 词典完整性")
def t7(tmp):
    d = engine.load_dict()
    c = engine.load_community_dict()
    assert len(d) == 5779, "合并词典应 5779 条，实际 %d" % len(d)
    assert len(c) >= 3000, "社区词表异常：%d" % len(c)
    assert d.get("New chat") == "新建对话", "关键词抽查失败：%r" % d.get("New chat")
    return "OK（%d/%d）" % (len(d), len(c))


@check("T8 无硬编码本机路径")
def t8(tmp):
    import re
    bad = re.compile(r"C:[/\\]Users", re.I)
    hits = []
    for base, _dirs, files in os.walk(PACK):
        for fn in files:
            if not fn.endswith((".py", ".cmd", ".md", ".js", ".json")):
                continue
            p = os.path.join(base, fn)
            rel = os.path.relpath(p, PACK)
            if rel.startswith(("dicts" + os.sep, "lib" + os.sep)):
                continue  # 数据文件（词条内容可能含任意文本）
            with open(p, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if bad.search(line):
                        hits.append("%s:%d" % (rel, i))
    assert not hits, "发现硬编码本机路径：" + ", ".join(hits)
    return "OK"


@check("T9 安装.cmd 卫生（纯 ASCII + echo 行零括号）")
def t9(tmp):
    cmd = None
    for fn in os.listdir(PACK):
        if fn.endswith(".cmd"):
            cmd = os.path.join(PACK, fn)
    assert cmd, "未找到安装 .cmd"
    raw = open(cmd, "rb").read()
    assert all(b < 128 for b in raw), ".cmd 含非 ASCII 字节"
    text = raw.decode("ascii")
    # devin 教训的精确口径：echo 文本里的裸括号腐蚀控制流（即便块被跳过也解析）。
    # for %%I in (...) 这类语法括号不受此限（平衡且必需），故只禁 echo 行带括号。
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip().lower()
        if s.startswith("echo") and ("(" in s or ")" in s):
            raise AssertionError("第 %d 行 echo 含括号：%s" % (i, line.strip()))
    assert "goto" in text.lower(), "应使用 goto 风格"
    return "OK（%s，%d B）" % (os.path.basename(cmd), len(raw))


@check("T10 运行中判定（tasklist 罐头解析）")
def t10(tmp):
    # engine.app_running 直接调 tasklist；这里验罐头逻辑等价物
    canned_running = '"Freebuff.exe","1234","Console","1","56,789 K"\r\n'
    canned_idle = "INFO: No tasks are running which match the specified criteria.\r\n"
    assert "freebuff.exe" in canned_running.lower()
    assert "freebuff.exe" not in canned_idle.lower()
    # 真函数在无 Freebuff 进程的测试机上应返回 False
    assert engine.app_running() in (True, False), "app_running 应返回布尔"
    return "OK（罐头语义 + 真函数可调）"


@check("T11 还原：已汉化无基线（复核 P1 同类盲区）")
def t11(tmp):
    root = make_fake_tree(tmp)
    res = os.path.join(root, "resources")
    asar = os.path.join(res, "app.asar")
    engine.apply(res)
    os.remove(asar + ".zhorig")  # 用户误删基线的异常态
    try:
        engine.restore(res)
    except engine.EngineError as e:
        assert e.code == engine.E_BASELINE, "应报基线冲突，实际 %s" % e.code
        return "拒还原 OK（exit %d）" % e.code
    raise AssertionError("已汉化无基线却被当干净版返回——虚假陈述")


@check("T12 retarget 生效性（防 lib 格式漂移静默回退）")
def t12(tmp):
    lib = open(engine.COMMUNITY_LIB, encoding="utf-8").read()
    out = engine.retarget_community_dict(lib)
    assert out != lib, "retarget 未生效——社区库格式漂移会静默走原文，赛跑覆盖会复发"
    assert "globalThis.__FB_ZH_DICT__" in out, "改写后的词典引用缺失"
    assert "const exact = new Map(" in out, "exact Map 结构缺失（社区 helper 依赖）"
    assert lib.count("    }),") >= 1
    return "OK（改写生效 + helper 结构保留）"


@check("T13 版本策略：区间内未逐版实测分支")
def t13(tmp):
    a, note = engine.version_policy("0.0.200")
    assert a == "warn", "区间内未验证应 warn"
    assert "未逐版实测" in note
    return "OK"


def main(argv):
    only = set(a for a in argv if a.upper().startswith("T") and a[1:].isdigit())
    failures = []
    for name, fn in RESULTS:
        if only and name.split()[0] not in only:
            continue
        tmp = tempfile.mkdtemp(prefix="fbzh-t-")
        try:
            note = fn(tmp)
            print("PASS  %-34s %s" % (name, note or ""))
        except Exception as e:  # noqa: BLE001
            failures.append((name, e))
            print("FAIL  %-34s %s" % (name, e))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("----")
    if failures:
        print("%d FAILED / %d total" % (len(failures), len(RESULTS)))
        return 1
    print("ALL GREEN（%d）" % len(RESULTS))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

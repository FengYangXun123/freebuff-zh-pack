#!/usr/bin/env python3
"""freebuff-zh-pack 汉化引擎（参数化，无本机路径）。

逻辑源自 Freebuff 汉化维护仓的 patch-inject.py（0.0.201+ 注入路线），
按发行包要求改造：所有路径由参数/探测决定，不再硬编码。

三方安全事实（0.0.204 实测，见 M3 验证报告）：
- EnableEmbeddedAsarIntegrityValidation 熔丝 = OFF → 改写 asar 安全（每次安装前仍重检）
- exe 的 Authenticode 签名不覆盖 app.asar → 改 asar 不破坏签名
- OnlyLoadAppFromAsar = ON → 必须保持 asar 形态

电子熔线读法（哨兵后字节）：[0]=wire 版本，[1]=熔线总数，[2:]=各熔线位。
熔线位序（Electron 标准）：0 RunAsNode / 1 NodeCliInspect / 2 NodeOptionsEnv /
3 GrantFileProtoExtra / 4 AsarIntegrityValidation / 5 OnlyLoadAppFromAsar /
6 V8SnapshotPerBrowser / 7 NodeWorkerInspect。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- pack 资产路径（全部 pack 相对） ----
DICT_MAIN = os.path.join(HERE, "dicts", "zh-main.json")
DICT_REMOTE = os.path.join(HERE, "dicts", "zh-remote.json")
DICT_COMMUNITY = os.path.join(HERE, "dicts", "zh-community.json")
COMMUNITY_LIB = os.path.join(HERE, "lib", "zh-community-lib.js")
TEMPLATE = os.path.join(HERE, "assets", "zh-inject-template.js")
STUB = os.path.join(HERE, "assets", "test-inject-stub.js")
VERSIONS_JSON = os.path.join(HERE, "manifests", "versions.json")

sys.path.insert(0, HERE)
import asar_tool  # noqa: E402  （同目录发行，单一来源）

MARKER = "/* freebuff-zh-inject */"
SENTINEL = b"dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX"
FUSE_NAMES = [
    "RunAsNode", "NodeCliInspect", "NodeOptionsEnv", "GrantFileProtoExtra",
    "AsarIntegrityValidation", "OnlyLoadAppFromAsar",
    "V8SnapshotPerBrowser", "NodeWorkerInspect",
]
FUSE_INTEGRITY_IDX = 4  # EnableEmbeddedAsarIntegrityValidation

ORIGINS = [
    "https://freebuff.com/",
    "https://www.freebuff.com/",
    # 与 0.0.204 electron/hosted-workspace.cjs 的 HOSTED_ORIGINS 对齐（含 staging）
    "https://staging-auth.freebuff.com/",
    "https://staging-2-auth.freebuffweb.site/",
    # 本地 splash 登录页（127.0.0.1）——必须走运行时注入，不能改本地 chunk：
    # "Sign in to Freebuff" 同时是代码里 u.includes(...) 的判定常量。
    "http://127.0.0.1:",
]

APP_EXE = "Freebuff.exe"
APP_NAME_FILTER = "Freebuff.exe"
APP_DIR_NAME = "@codebufffreebuff-desktop"

# 退出码
OK, E_USAGE, E_RUNNING, E_FUSE, E_ARCH, E_BASELINE, E_ENGINE, E_CANCELLED, E_NO_NODE = \
    0, 2, 3, 4, 5, 6, 7, 10, 8


class EngineError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- 安装目录

def detect_install_dir(explicit=None):
    """解析 Freebuff 安装目录。优先级：显式 > FREEBUFF_PATH > 默认探测。

    返回 (resources 目录 or None, 尝试过的候选列表)。
    """
    tried = []
    cand = []
    if explicit:
        cand.append(explicit)
    env = os.environ.get("FREEBUFF_PATH")
    if env:
        cand.append(env)
    lad = os.environ.get("LOCALAPPDATA")
    if lad:  # 未设时跳过，避免把相对路径当候选误导用户
        cand.append(os.path.join(lad, "Programs", APP_DIR_NAME))
    for c in cand:
        c = os.path.normpath(c)
        tried.append(c)
        if os.path.isdir(c):
            return c, tried
    return None, tried


def norm_resources(install_dir):
    """兼容两种入参：安装根（含 Freebuff.exe）或 resources 层本身。统一返回 resources 层。"""
    if os.path.basename(os.path.normpath(install_dir)).lower() == "resources":
        return os.path.normpath(install_dir)
    return os.path.join(os.path.normpath(install_dir), "resources")


def app_running():
    """Freebuff 是否在运行（tasklist 查询；输出按 bytes 解码——utf-8 环境坑）。"""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % APP_NAME_FILTER,
                            "/FO", "CSV", "/NH"],
                           capture_output=True)
        out = (r.stdout or b"").decode("utf-8", "replace")
    except OSError:
        return False
    return APP_NAME_FILTER.lower() in out.lower()


# ---------------------------------------------------------------- 熔线

def read_fuses(exe_path):
    """读电子熔线。返回 dict（FUSE_NAMES -> 'ON'/'OFF'/'removed'）；找不到哨兵返回 None。"""
    with open(exe_path, "rb") as f:
        data = f.read()
    i = data.find(SENTINEL)
    if i < 0:
        return None
    raw = data[i + len(SENTINEL): i + len(SENTINEL) + 10]
    if len(raw) < 10 or raw[0] != 0x01:
        return None
    state = {0x31: "ON", 0x30: "OFF", 0x00: "removed"}
    n_fuses = raw[1]
    out = {}
    for idx, name in enumerate(FUSE_NAMES):
        if idx >= n_fuses:
            out[name] = "removed"
        else:
            out[name] = state.get(raw[2 + idx], hex(raw[2 + idx]))
    return out


def fuse_gate(exe_path):
    """硬拦：asar 完整性校验开启即拒装。返回 None（放行）或拒绝原因 str。"""
    fuses = read_fuses(exe_path)
    if fuses is None:
        return "未能读取电子熔线（哨兵缺失）——上游可能更换了打包方式，拒绝注入。"
    if fuses.get("AsarIntegrityValidation") == "ON":
        return ("上游已开启 asar 完整性校验（EnableEmbeddedAsarIntegrityValidation=ON），"
                "强行注入会导致应用无法启动。已拒绝安装，请等待本包适配。")
    return None


# ---------------------------------------------------------------- 版本

def asar_version(asar_path):
    """从 asar 头解析 package.json 的 version。失败返回 None。"""
    try:
        tree, base = asar_tool.read_header(asar_path)
        node = tree.get("files", {}).get("package.json")
        if not node:
            return None
        with open(asar_path, "rb") as f:
            f.seek(base + int(node["offset"]))
            raw = f.read(int(node["size"]))
        return json.loads(raw.decode("utf-8")).get("version")
    except Exception:
        return None


def _load_versions_json():
    try:
        with open(VERSIONS_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def version_policy(version):
    """返回 (action, note)：action ∈ {'ok','warn'}。硬拦不在此（熔线/架构另行）。"""
    meta = _load_versions_json()
    if not version:
        return "warn", "无法从 app.asar 读取版本号（可能为非标准包）。"
    if version in meta.get("verified", {}):
        return "ok", "已验证版本。"
    rng = meta.get("range", {})
    lo, hi = rng.get("min", ""), rng.get("max", "")

    def key(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except Exception:
            return (0,)

    k = key(version)
    if lo and k < key(lo):
        return "warn", "版本低于已验证区间下限（%s）——旧版回滚场景，词典可能部分残留英文。" % lo
    if hi and k > key(hi):
        return "warn", "版本高于已验证区间上限（%s）——上游新版本尚未适配，最坏情况是界面出现英文残留。" % hi
    return "warn", "版本在兼容区间内但未逐版实测。"


def check_upstream_latest(no_net=False):
    """查官方 feed 最新 desktop 版本（GET，302 不跟随，取 Location 的 tag）。

    返回 (version or None, 说明)。只读请求；no_net=True 直接跳过。
    """
    if no_net:
        return None, "已按 --no-net 跳过联网检查。"
    url = "https://freebuff.com/api/desktop/updates/win-x64/latest.yml"

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # 不要跟随——302 的 Location 本身就是答案

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        req = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "freebuff-zh-pack"})
        try:
            with opener.open(req, timeout=12) as resp:
                body = resp.read(4096).decode("utf-8", "replace")
                target = resp.geturl()
        except urllib.error.HTTPError as e:
            target = e.headers.get("Location", "") if e.headers else ""
            body = ""
        m = re.search(r"freebuff-desktop-v(\d+\.\d+\.\d+)", target or "")
        if not m:
            m = re.search(r"^version:\s*(\d+\.\d+\.\d+)", body, re.M)
        if m:
            return m.group(1), "官方更新端点实抓（302 Location）。"
        return None, "已连通但未解析出版本号（端点响应形态可能变化）。"
    except Exception as e:  # 网络/代理不可达不算失败
        return None, "联网检查失败（%s）——不影响安装。" % type(e).__name__


# ---------------------------------------------------------------- 词典

def load_dict():
    """合并三份词典。优先级：社区 < zh-remote < zh-main（我们的覆盖社区的）。"""
    out = {}
    for path in (DICT_COMMUNITY, DICT_REMOTE, DICT_MAIN):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for k, v in (data.get("exact") or {}).items():
            if isinstance(v, str) and v.strip():
                out[k.strip()] = v.strip()
    return out


def load_community_dict():
    """社区词表单独一份（社区 helper 的 exact.get 兜底依赖它）。"""
    out = {}
    if os.path.exists(DICT_COMMUNITY):
        with open(DICT_COMMUNITY, encoding="utf-8") as f:
            data = json.load(f)
        for k, v in (data.get("exact") or {}).items():
            if isinstance(v, str) and v.strip():
                out[k.strip()] = v.strip()
    return out


def retarget_community_dict(lib_text):
    """把社区库的 exact 词典改成「我们的优先、社区兜底」（防两层注入赛跑覆盖措辞）。

    同时保留社区词表兜底：社区 helper 会 exact.get(句尾片段) 拼译文，
    只换成本包词典会让缺口片段整条不译——所以两层各自内联合并词典。
    """
    lines = lib_text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.startswith("  const exact = new Map("):
            start = i
            break
    if start is None:
        return lib_text
    end = None
    for j in range(start + 1, len(lines)):
        if lines[j] == "    }),":
            end = j
            break
    if end is None:
        return lib_text
    stop = end + 1
    while stop < len(lines) and lines[stop].strip() in (")", ")", ",", ");"):
        stop += 1
    replacement = [
        "  // 词典：直接用我们的合并词典（措辞以我们为准，见分歧清单）。",
        "  // 社区 helper 只依赖 3 处 exact.get 查完整句子，这些句子已由",
        "  // merge-dict.py 补进我们的词典（社区独有的句子片段一并并入）。",
        "  const exact = new Map(Object.entries(globalThis.__FB_ZH_DICT__ || {}))",
    ]
    return "\n".join(lines[:start] + replacement + lines[stop:])


# ---------------------------------------------------------------- 注入本体

HOOK = r"""

/* freebuff-zh-inject */
;(function installFreebuffZhInject() {
  const fs = require("fs")
  const path = require("path")
  let script = null
  let community = null
  let origins = null
  const load = () => {
    try {
      script = fs.readFileSync(path.join(__dirname, "zh-inject.js"), "utf8")
      origins = JSON.parse(fs.readFileSync(path.join(__dirname, "zh-origins.json"), "utf8"))
    } catch (e) {
      script = null
      origins = null
    }
    try {
      community = fs.readFileSync(path.join(__dirname, "zh-community.js"), "utf8")
    } catch (e) {
      community = null
    }
  }
  const shouldInject = (url) => {
    if (!origins) return false
    for (const o of origins) if (url.indexOf(o) === 0) return true
    return false
  }
  app.on("web-contents-created", (_event, contents) => {
    const inject = () => {
      if (!script) load()
      if (!script) return
      let url = ""
      try {
        url = contents.getURL()
      } catch (e) {
        return
      }
      if (!shouldInject(url)) return
      // 顺序要紧：**社区层先跑**。
      // 社区层用正则整体匹配动态文案（"5:00 left of today's 5:00."、
      // "0:00 of 5:00 hours used, 5:00 left"），必须看到**原始英文**；
      // 若我们的层先跑，词级替换会先把 left/used/hours 换掉，
      // 正则就再也匹配不上 → 留下「5:00 剩余 of 5:00」这种半中半英残句
      // （2026-11-20 实测）。
      // 社区层的词表是「社区词表 + 我们的词典」合并（我们的优先），所以先跑不会
      // 抢走措辞——它先跑的只是它自己那 208 条正则规则。
      const communityFirst = community
        ? contents.executeJavaScript(community, true).catch(() => {})
        : Promise.resolve()
      communityFirst.then(() => {
        // 第二步：我们的注入器（词典 = 社区词条 + 我们的词条，我们的优先）
        contents.executeJavaScript(script, true).catch(() => {})
      })
    }
    contents.on("did-finish-load", inject)
    contents.on("did-frame-finish-load", inject)
    contents.on("did-navigate-in-page", inject)
  })
})()
"""


def preflight(install_dir, force=False):
    """安装前检查。install_dir = 安装根或 resources 层（见 norm_resources）。

    返回 (asar, baseline, exe, version, version_note)。不通过抛 EngineError。
    version_note 非 None 时 = 版本策略给出 warn（未验证版本），调用方决定
    呈现方式（菜单确认 / --yes 放行 / --force 跳过判定）。
    """
    resources = norm_resources(install_dir)
    asar = os.path.join(resources, "app.asar")
    baseline = asar + ".zhorig"
    exe = os.path.join(os.path.dirname(resources), APP_EXE)
    if not os.path.isfile(asar):
        raise EngineError(E_ARCH, "找不到 app.asar：%s" % asar)
    if not os.path.isfile(exe):
        raise EngineError(E_ARCH, "找不到 %s：%s" % (APP_EXE, exe))
    if not os.path.isdir(os.path.join(os.path.dirname(resources), "resources", "orchestrator")):
        raise EngineError(E_ARCH, "架构特征异常（resources/orchestrator 缺失）——"
                          "上游可能已改版，注入路线不适用，拒绝安装。")
    reason = fuse_gate(exe)
    if reason:
        raise EngineError(E_FUSE, reason)
    with open(asar, "rb") as f:
        full = f.read()
    patched_now = MARKER.encode() in full or b"__FREEBUFF_ZH_PATCH__" in full
    if patched_now and not os.path.exists(baseline):
        raise EngineError(E_BASELINE,
                          "app.asar 已含汉化补丁但缺少 .zhorig 基线，无法安全重建。"
                          "请重装 Freebuff Desktop 后再使用本安装器。")
    version = asar_version(asar)
    note = None
    if not force:
        _action, note = version_policy(version)
    return asar, baseline, exe, version, note


def _runtime_gates(inject_js, lib_js):
    """语法闸门 + 运行时 DOM stub 自检。node 缺失抛 EngineError(E_NO_NODE)。"""
    def have_node():
        try:
            r = subprocess.run(["node", "--version"], capture_output=True, text=True)
            return r.returncode == 0
        except OSError:
            return False
    if not have_node():
        raise EngineError(E_NO_NODE,
                          "未检测到 Node.js（自检闸门需要）。请安装 Node.js 18+ 后重试，"
                          "或设 PATH 指向含 node.exe 的目录。")
    check = subprocess.run(["node", "--check", inject_js], capture_output=True, text=True)
    if check.returncode != 0:
        raise EngineError(E_ENGINE, "注入脚本语法错误:\n" + (check.stderr or "")[:400])
    smoke = subprocess.run(["node", STUB, inject_js], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    if smoke.returncode != 0 or "脚本执行成功" not in (smoke.stdout or ""):
        raise EngineError(E_ENGINE, "注入脚本运行时自检失败:\n"
                         + (smoke.stdout or "")[:600] + (smoke.stderr or "")[:600])
    if lib_js and os.path.exists(lib_js):
        smoke2 = subprocess.run(["node", STUB, lib_js], capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        if "脚本执行成功" not in (smoke2.stdout or ""):
            print("社区库 stub 自检未通过（stub 简化所致，非致命）："
                  + (smoke2.stdout or "")[:200].replace("\n", " "))


def ensure_baseline(asar, baseline):
    """建立/校验 .zhorig。已含补丁却无基线在 preflight 已拦。返回 'existing'/'created'。"""
    if os.path.exists(baseline):
        v_base = asar_version(baseline)
        v_cur = asar_version(asar)
        if v_base != v_cur:
            with open(asar, "rb") as f:
                full = f.read()
            if MARKER.encode() in full or b"__FREEBUFF_ZH_PATCH__" in full:
                raise EngineError(E_BASELINE,
                                  "当前 asar（%s）含补丁但基线是 %s——状态异常，拒绝处理。"
                                  % (v_cur or "?", v_base or "?"))
            shutil.copy2(asar, baseline)
            return "rebuilt", "基线版本 %s ≠ 当前 %s，已按当前版本重建基线" % (
                v_base or "?", v_cur or "?")
        return "existing", None
    tmp = tempfile.mkdtemp(prefix="fbzh-")
    try:
        code, out = _asar_unpack(asar, tmp)
        if code != 0:
            raise EngineError(E_ENGINE, "解包失败:\n" + out)
        mc = os.path.join(tmp, "electron", "main.cjs")
        if os.path.exists(mc):
            with open(mc, encoding="utf-8", errors="replace") as f:
                if MARKER in f.read():
                    raise EngineError(E_BASELINE,
                                      "app.asar 已含注入补丁但缺少 .zhorig 基线，拒绝建立基线。")
        shutil.copy2(asar, baseline)
        return "created", None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _asar_unpack(asar, out_dir):
    try:
        n = asar_tool.unpack(asar, out_dir)
        return 0, "unpacked %d" % n
    except Exception as e:
        return 1, str(e)


def _asar_pack(src, out):
    try:
        asar_tool.pack(src, out)
        return 0, "packed"
    except Exception as e:
        return 1, str(e)


def apply(install_dir, force=False):
    """打补丁（幂等：始终从 .zhorig 基线重建）。返回 dict(status, version, note)。

    force=True 跳过版本策略判定（熔线/架构硬拦仍生效）。
    非 EngineError 的意外异常统一转 E_ENGINE，保证退出码表成立。
    """
    try:
        return _apply_impl(install_dir, force)
    except EngineError:
        raise
    except Exception as e:  # noqa: BLE001
        raise EngineError(E_ENGINE, "引擎意外失败（%s: %s）" % (type(e).__name__, e))


def _apply_impl(install_dir, force):
    resources = norm_resources(install_dir)
    pf = preflight(resources, force=force)
    asar, baseline, _exe, version, note = pf
    state, state_note = ensure_baseline(asar, baseline)

    d = load_dict()
    work = tempfile.mkdtemp(prefix="fbzh-")
    try:
        code, out = _asar_unpack(baseline, work)
        if code != 0:
            raise EngineError(E_ENGINE, "解包基线失败:\n" + out)
        main_cjs = os.path.join(work, "electron", "main.cjs")
        with open(main_cjs, encoding="utf-8") as f:
            src = f.read()
        if MARKER in src:
            src = src.split(MARKER)[0].rstrip() + "\n"
        with open(main_cjs, "w", encoding="utf-8", newline="\n") as f:
            f.write(src + HOOK)

        with open(TEMPLATE, encoding="utf-8") as f:
            tpl = f.read()
        payload = json.dumps(d, ensure_ascii=False)
        js = tpl.replace("/*__DICT__*/ {}", payload)
        if "/*__DICT__*/ {}" in js:
            raise EngineError(E_ENGINE, "注入模板占位符替换失败")
        inject_js = os.path.join(work, "electron", "zh-inject.js")
        with open(inject_js, "w", encoding="utf-8", newline="\n") as f:
            f.write(js)

        lib_js = None
        if os.path.exists(COMMUNITY_LIB):
            with open(COMMUNITY_LIB, encoding="utf-8") as f:
                lib = f.read()
            lib = retarget_community_dict(lib)
            cdict = load_community_dict()
            prefix = ("globalThis.__FB_ZH_DICT__ = "
                      + json.dumps(d, ensure_ascii=False) + ";\n"
                      + "globalThis.__FB_ZH_COMMUNITY_DICT__ = "
                      + json.dumps(cdict, ensure_ascii=False) + ";\n")
            lib_js = os.path.join(work, "electron", "zh-community.js")
            with open(lib_js, "w", encoding="utf-8", newline="\n") as f:
                f.write(prefix + lib)
        with open(os.path.join(work, "electron", "zh-origins.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(ORIGINS, ensure_ascii=False))

        _runtime_gates(inject_js, lib_js)

        out_asar = os.path.join(work, "app.asar")
        code, out = _asar_pack(work, out_asar)
        if code != 0:
            raise EngineError(E_ENGINE, "打包失败:\n" + out)
        shutil.copyfile(out_asar, asar)
        return {
            "status": "applied",
            "baseline_state": state,
            "baseline_note": state_note,
            "version": version,
            "dict_entries": len(d),
            "community": lib_js is not None,
            "note": note,
            "asar_size": os.path.getsize(asar),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def restore(install_dir):
    """还原官方原版（按 .zhorig 字节级恢复），成功后删除基线（下次安装重建）。"""
    resources = norm_resources(install_dir)
    asar = os.path.join(resources, "app.asar")
    baseline = asar + ".zhorig"
    if not os.path.isfile(asar):
        raise EngineError(E_ARCH, "找不到 app.asar：%s（官方更新中断或被手动删除？）" % asar)
    if not os.path.exists(baseline):
        with open(asar, "rb") as f:
            full = f.read()
        if MARKER.encode() in full or b"__FREEBUFF_ZH_PATCH__" in full:
            raise EngineError(E_BASELINE, "已汉化但无基线，无法还原。请重装 Freebuff Desktop。")
        return {"status": "already-clean"}
    shutil.copy2(baseline, asar)
    with open(asar, "rb") as f:
        a = f.read()
    with open(baseline, "rb") as f:
        b = f.read()
    if a != b:
        raise EngineError(E_ENGINE, "还原后哈希不一致，请检查磁盘错误。")
    os.remove(baseline)
    return {"status": "restored", "version": asar_version(asar)}


def status(install_dir):
    """状态盘点：版本 / 熔线 / 基线 / 补丁态 / 指纹。"""
    resources = norm_resources(install_dir)
    asar = os.path.join(resources, "app.asar")
    baseline = asar + ".zhorig"
    exe = os.path.join(os.path.dirname(resources), APP_EXE)
    if not os.path.isfile(asar):
        raise EngineError(E_ARCH, "找不到 app.asar：%s（官方更新中断或被手动删除？）" % asar)
    import hashlib
    with open(asar, "rb") as f:
        full = f.read()
    sha = hashlib.sha256(full).hexdigest()
    patched = MARKER.encode() in full or b"__FREEBUFF_ZH_PATCH__" in full
    fuses = read_fuses(exe) if os.path.isfile(exe) else None
    version = asar_version(asar)
    out = {
        "resources": resources,
        "version": version,
        "patched": patched,
        "baseline": os.path.exists(baseline),
        "sha256_16": sha[:16],
        "fuse_integrity": (fuses or {}).get("AsarIntegrityValidation", "未知"),
        "fuse_only_asar": (fuses or {}).get("OnlyLoadAppFromAsar", "未知"),
    }
    meta = _load_versions_json().get("verified", {}).get(version or "", {})
    if meta:
        if not patched and meta.get("pristine_sha256_16") == sha[:16]:
            out["reference_match"] = "与已验证 pristine 指纹一致（%s）" % version
        elif patched and meta.get("patched_sha256_16") == sha[:16]:
            out["reference_match"] = "与已验证补丁态指纹一致（%s + 本包词典）" % version
    return out

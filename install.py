#!/usr/bin/env python3
"""freebuff-zh-pack 安装器（四动词 + 菜单；引擎在 engine.py）。

用法
----
    python install.py --install            安装/重装汉化（幂等，从基线重建）
    python install.py --status             状态盘点（版本/熔线/基线/补丁态/指纹）
    python install.py --check-update       查上游最新版本 + 本包适配状态
    python install.py --restore            还原官方英文原版
    python install.py --menu               菜单（一次执行 + 按任意键退出）
    python install.py --path <目录>        显式指定 Freebuff 安装目录
    python install.py --yes                自动确认版本警告
    python install.py --force              跳过版本策略判定（硬拦仍生效）
    python install.py --no-net             跳过联网检查

退出码  0 成功 / 2 用法错误 / 3 Freebuff 运行中 / 4 熔线拦截 /
        5 架构异常 / 6 基线冲突 / 7 引擎失败 / 8 缺 Node.js / 10 用户取消
"""
import os
import sys

import engine

RC = engine


def resolve(explicit=None):
    res, tried = engine.detect_install_dir(explicit)
    if not res:
        print("未找到 Freebuff Desktop 安装目录。尝试过：")
        for t in tried:
            if t:
                print("  - " + t)
        print("请用 --path 指定安装目录（含 resources 的那层），"
              "或设环境变量 FREEBUFF_PATH。")
        raise EngineExit(RC.E_USAGE)
    return res


class EngineExit(Exception):
    def __init__(self, code):
        self.code = code


def do_install(args):
    res = resolve(args.path)
    if engine.app_running():
        print("Freebuff 正在运行——请先完全退出（含托盘）再安装。")
        raise EngineExit(RC.E_RUNNING)
    try:
        pf = engine.preflight(res, force=args.force)
    except engine.EngineError as e:
        print("[拒装] " + str(e))
        raise EngineExit(e.code)
    version, note = pf[3], pf[4]
    if note and not args.yes:
        if args.assume_yes_interactive:
            print("提示：" + note)
            try:
                ans = input("仍要继续安装吗? [y/N] ").strip().lower()
            except EOFError:
                print("无输入可用——已取消（加 --yes 放行）。")
                raise EngineExit(RC.E_CANCELLED)
            if ans != "y":
                print("已取消。")
                raise EngineExit(RC.E_CANCELLED)
        else:
            print("[提示] " + note)
            print("      如需继续，加 --yes（或菜单里选 y 确认）。")
            raise EngineExit(RC.E_CANCELLED)
    try:
        r = engine.apply(res, force=args.force)
    except engine.EngineError as e:
        print("[失败] " + str(e))
        raise EngineExit(e.code)
    print("安装完成：词典 %d 条%s｜asar %d B"
          % (r["dict_entries"],
             "（含社区第二层）" if r["community"] else "（未含社区层）",
             r["asar_size"]))
    if r.get("baseline_note"):
        print("基线：" + r["baseline_note"])
    if r.get("note") and r.get("note") != note:
        print("提示：" + r["note"])
    print("启动 Freebuff 即为中文界面；官方更新覆盖后重跑本安装器即可。")


def do_status(args):
    res = resolve(args.path)
    if engine.app_running():
        print("（注意：Freebuff 正在运行，以下状态为启动时快照）")
    try:
        s = engine.status(res)
    except engine.EngineError as e:
        print("[失败] " + str(e))
        raise EngineExit(e.code)
    print("安装目录   ：" + s["resources"])
    print("应用版本   ：" + (s["version"] or "未知"))
    print("汉化状态   ：" + ("已注入" if s["patched"] else "未注入（官方原版）"))
    print("基线 .zhorig：" + ("在位" if s["baseline"] else "不存在"))
    print("熔线完整性校验：" + s["fuse_integrity"] + "｜仅从 asar 加载：" + s["fuse_only_asar"])
    print("asar sha256（前 16）：" + s["sha256_16"])
    if s.get("reference_match"):
        print("参考指纹   ：" + s["reference_match"])


def do_check_update(args):
    res = resolve(args.path)
    try:
        s = engine.status(res)
    except engine.EngineError as e:
        print("[失败] " + str(e))
        raise EngineExit(e.code)
    local = s["version"] or "?"
    latest, how = engine.check_upstream_latest(no_net=args.no_net)
    print("本机版本   ：" + local)
    if latest:
        print("上游最新   ：" + latest + "（" + how + "）")
        if latest == local:
            print("适配状态   ：本机已是最新，且在已验证列表内。")
        else:
            print("适配状态   ：上游有新版本——请到本包 Releases 页确认是否已适配。")
    else:
        print("上游最新   ：未能获取（" + how + "）")
    meta_last = ""
    try:
        import json
        with open(engine.VERSIONS_JSON, encoding="utf-8") as f:
            meta_last = json.load(f).get("remote_dict_last_verified", "")
    except Exception:
        pass
    if meta_last:
        print("远端词典最后验证：" + meta_last + "（界面若出现新英文残留，属远端文案更新）")


def do_restore(args):
    res = resolve(args.path)
    if engine.app_running():
        print("Freebuff 正在运行——请先完全退出再还原。")
        raise EngineExit(RC.E_RUNNING)
    try:
        r = engine.restore(res)
    except engine.EngineError as e:
        print("[失败] " + str(e))
        raise EngineExit(e.code)
    if r["status"] == "already-clean":
        print("当前已是官方原版，无需还原。")
    else:
        print("已还原官方英文原版（版本 %s），基线已清理。" % (r.get("version") or "?"))


MENU = (
    "\n== freebuff-zh-pack 安装器 ==\n"
    "  1  安装/重装汉化\n"
    "  2  查看状态\n"
    "  3  检查更新\n"
    "  4  还原英文原版\n"
    "  q  退出\n"
    "选择: "
)


def _pause():
    """按任意键退出（仅交互终端；管道/重定向不阻塞）。"""
    try:
        if not sys.stdin.isatty():
            return
    except Exception:
        return
    try:
        import msvcrt
        msvcrt.getch()
    except ImportError:
        try:
            input("按回车退出…")
        except EOFError:
            pass


def do_menu(args):
    class A:
        pass
    a = A()
    a.path = args.path
    a.force = args.force
    a.yes = False
    a.no_net = args.no_net
    a.assume_yes_interactive = True
    # 非交互环境（管道/CI）下 --menu 等价于 --install，不阻塞等待输入
    interactive = False
    try:
        interactive = sys.stdin.isatty()
    except Exception:
        pass
    if not interactive:
        print("非交互环境：--menu 等价于 --install --yes。")
        a.yes = True  # 无 stdin 可确认，版本警告走放行（硬拦仍生效）
        a.assume_yes_interactive = False
        try:
            do_install(a)
        except EngineExit as e:
            raise EngineExit(e.code)
        return
    try:
        choice = input(MENU).strip().lower()
    except EOFError:
        return
    dispatch = {"1": do_install, "2": do_status, "3": do_check_update, "4": do_restore}
    if choice == "q":
        return
    fn = dispatch.get(choice)
    if not fn:
        print("无效选择。")
        return
    try:
        fn(a)
    except EngineExit as e:
        if e.code not in (RC.OK, RC.E_CANCELLED):
            print("（退出码 %d）" % e.code)
    _pause()


def main(argv):
    args = type("Args", (), {})()
    args.path = None
    args.force = False
    args.yes = False
    args.no_net = False
    args.assume_yes_interactive = False
    verb = None
    it = iter(argv)
    for tok in it:
        if tok == "--path":
            args.path = next(it, None)
        elif tok == "--force":
            args.force = True
        elif tok == "--yes":
            args.yes = True
        elif tok == "--no-net":
            args.no_net = True
        elif tok in ("--install", "--status", "--check-update", "--restore", "--menu"):
            verb = tok
        elif tok in ("-h", "--help"):
            print(__doc__)
            return RC.OK
        else:
            print("未知参数：" + tok)
            return RC.E_USAGE
    if verb is None:
        print(__doc__)
        return RC.E_USAGE
    try:
        {"--install": do_install, "--status": do_status,
         "--check-update": do_check_update, "--restore": do_restore,
         "--menu": do_menu}[verb](args)
    except EngineExit as e:
        return e.code
    return RC.OK


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(RC.E_CANCELLED)

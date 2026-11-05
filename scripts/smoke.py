# -*- coding: utf-8 -*-
"""书渡自检冒烟脚本：验证服务与关键功能可用。

用法：
    python scripts/smoke.py                 # 自起服务（源代码模式）后自检
    python scripts/smoke.py --url http://127.0.0.1:7788   # 检查已运行的服务
    python scripts/smoke.py --exe dist\\书渡.exe           # 检查打包产物

退出码 0 = 全部通过，1 = 存在失败项。打包交付前必跑。
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def fetch_json(base_url, path, timeout=5):
    return json.loads(urllib.request.urlopen(base_url + path, timeout=timeout).read())


def fetch_text(base_url, path, timeout=5):
    return urllib.request.urlopen(base_url + path, timeout=timeout).read().decode("utf-8")


def wait_service(base_url, tries=40):
    for _ in range(tries):
        try:
            urllib.request.urlopen(base_url + "/api/status", timeout=2)
            return True
        except OSError:
            time.sleep(0.5)
    return False


def run_checks(base_url):
    checks = []
    status = fetch_json(base_url, "/api/status")
    checks.append(("接口 /api/status", bool(status.get("engine") is not None)))
    checks.append(("app 名称=书渡", status.get("app") == "书渡"))
    checks.append(("输出格式表", len(status.get("output_formats", [])) >= 10))
    checks.append(("转换预设表", status.get("conversion_presets") == ["default", "kindle", "eink"]))
    tasks = fetch_json(base_url, "/api/tasks")
    checks.append(("任务轮询含引擎状态", "engine" in tasks))
    watch = fetch_json(base_url, "/api/watch")
    checks.append(("监听接口", "rules" in watch and "violations" in watch))
    page = fetch_text(base_url, "/")
    checks.append(("页面标题书渡", "<title>书渡</title>" in page))
    checks.append(("渡印 logo", "x-sealbg" in page))
    checks.append(("三主题按钮组", "x-themes" in page))
    checks.append(("监听卡与设置", 'id="x-watchcard"' in page and 'id="x-watchrules"' in page))
    checks.append(("阅读设备下拉", 'id="x-preset"' in page))
    for name in ("core.js", "api.js", "state.js", "render.js", "browse.js",
                 "watch.js", "actions.js", "install.js", "theme.js", "app.js"):
        checks.append((f"页面引用 {name}", f'src="{name}"' in page))
        body = fetch_text(base_url, "/" + name)
        checks.append((f"静态资源 {name}", "Shudu" in body or name == "app.js"))
    checks.append(("本地安装入口", 'id="x-installlocal"' in page and 'id="x-installfile"' in page))
    return checks


def main():
    parser = argparse.ArgumentParser(description="书渡自检冒烟")
    parser.add_argument("--url", help="检查已运行的服务地址")
    parser.add_argument("--exe", help="检查打包产物（自动启动与关闭）")
    args = parser.parse_args()

    proc = None
    base_url = args.url
    try:
        if args.exe:
            exe = Path(args.exe)
            if not exe.exists():
                print(f"FAIL: 产物不存在 {exe}")
                return 1
            proc = subprocess.Popen([str(exe)], cwd=str(exe.parent))
            for port in range(7788, 7799):
                candidate = f"http://127.0.0.1:{port}"
                if wait_service(candidate, tries=2):
                    base_url = candidate
                    break
            if not base_url:
                print("FAIL: 产物服务未响应")
                return 1
            time.sleep(1)
        elif not base_url:
            # 源代码模式：线程内起服务
            import threading

            from webapp.app import find_free_port
            from webapp import create_app

            app = create_app()
            port = find_free_port()
            base_url = f"http://127.0.0.1:{port}"
            threading.Thread(
                target=lambda: app.run(host="127.0.0.1", port=port, debug=False,
                                       use_reloader=False, threaded=True),
                daemon=True).start()
            if not wait_service(base_url):
                print("FAIL: 源码服务未响应")
                return 1

        checks = run_checks(base_url)
        failed = 0
        for name, ok in checks:
            print(("PASS" if ok else "FAIL"), name)
            failed += 0 if ok else 1
        print(f"=== 冒烟结果：{len(checks) - failed}/{len(checks)} 通过 ===")
        return 1 if failed else 0
    finally:
        if proc is not None:
            proc.kill()
            proc.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())

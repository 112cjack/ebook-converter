# -*- coding: utf-8 -*-
"""启动入口：绑定本机端口并自动打开浏览器。

    python -m webapp.app
"""

import socket
import threading
import webbrowser

from . import create_app

DEFAULT_PORT = 7788
PORT_TRIES = 20


def find_free_port(start=DEFAULT_PORT, tries=PORT_TRIES):
    """从 start 起找一个可绑定的端口；端口被占用时自动向后递增（技术方案 4.4）。"""
    for port in range(start, start + tries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            continue
        finally:
            sock.close()
        return port
    return None


def main():
    app = create_app()
    port = find_free_port()
    if port is None:
        print(f"错误：端口 {DEFAULT_PORT}~{DEFAULT_PORT + PORT_TRIES - 1} 均被占用，无法启动。")
        return 1
    url = f"http://127.0.0.1:{port}"
    print("=== 电子书转换器 ===")
    print(f"服务地址: {url}  （仅本机访问，不监听局域网）")
    print("浏览器未自动打开时，请手动复制上面的地址到浏览器。")
    print("关闭本窗口即退出程序；转换过程中请勿关闭。")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

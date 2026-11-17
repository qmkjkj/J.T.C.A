from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _open_browser() -> None:
    if os.getenv("NOCTURNE_NO_BROWSER", "").strip() in {"1", "true", "yes"}:
        return
    time.sleep(1.4)
    try:
        webbrowser.open(URL)
    except Exception:
        pass


def main() -> None:
    if not _port_available(HOST, PORT):
        print(f"[J.T.C.A] 端口 {PORT} 已被占用。")
        print(f"[J.T.C.A] 如果服务已在运行，请直接访问 {URL}")
        print("[J.T.C.A] 如需重启，请先关闭占用该端口的进程。")
        return

    print("=" * 58)
    print("  J.T.C.A A股量化分析工具")
    print(f"  本地地址: {URL}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 58)

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()

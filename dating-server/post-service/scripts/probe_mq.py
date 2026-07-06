"""探测 RocketMQ 端口，判断是 4.x（NameServer）还是 5.x（Proxy）风格部署。"""
import socket

HOST = "rocketmq.jianjiange.site"
PORTS = {
    9876: "NameServer",
    8080: "RocketMQ 5.x Proxy（默认）",
    8081: "RocketMQ 5.x Proxy（备选）",
}


def probe(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def main() -> None:
    print(f"探测 {HOST} 的 RocketMQ 端口...\n")
    proxy_open = False
    for port, desc in PORTS.items():
        ok = probe(HOST, port)
        status = "通" if ok else "不通"
        print(f"  {HOST}:{port:<5} {status:<6} -> {desc}")
        if port in (8080, 8081) and ok:
            proxy_open = True

    print()
    if proxy_open:
        print("结论: 检测到 5.x Proxy 端口，可改用 rocketmq-python-client 纯 Python 客户端")
    else:
        print("结论: 仅 NameServer 可达，疑似 4.x 部署；Windows 本地只能继续用桩模式")


if __name__ == "__main__":
    main()

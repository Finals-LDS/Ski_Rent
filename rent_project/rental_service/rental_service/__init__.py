"""
Force IPv4 для всех исходящих соединений.
Render не поддерживает IPv6 → без этого Gmail API и SMTP падают
с [Errno 101] Network is unreachable.
"""
import socket

_original_getaddrinfo = socket.getaddrinfo


def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_only_getaddrinfo

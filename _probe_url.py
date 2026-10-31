# -*- coding: utf-8 -*-
"""一次性验证：便携版下载链接可用性（跑完即删）。"""
import urllib.request

req = urllib.request.Request(
    "https://calibre-ebook.com/dist/portable",
    headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-63"},
)
r = urllib.request.urlopen(req, timeout=90)
data = r.read(64)
print("status:", r.status)
print("final url:", r.url)
print("size info:", r.headers.get("Content-Range") or r.headers.get("Content-Length"))
print("MZ header:", data[:2])

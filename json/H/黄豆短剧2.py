#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import json
import base64
import urllib.request
import urllib.parse
from urllib.parse import quote, unquote
import http.cookiejar
import gzip
import zlib
import ssl

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key):
            return None
        def setCache(self, key, value):
            return "fail"
        def delCache(self, key):
            return "fail"

try:
    from Crypto.Cipher import AES as FastAES
except Exception:
    FastAES = None

class PureAES(object):
    S_BOX = [
        0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
        0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
        0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
        0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
        0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
        0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
        0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
        0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
        0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
        0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
        0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
        0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
        0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
        0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
        0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
        0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16
    ]
    INV_S_BOX = [0] * 256
    RCON = [0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]

    @classmethod
    def _init_tables(cls):
        if cls.INV_S_BOX[0x63] == 0:
            for i, v in enumerate(cls.S_BOX):
                cls.INV_S_BOX[v] = i

    def __init__(self, key):
        self._init_tables()
        self.key = list(key)
        self.nk = len(self.key) // 4
        self.nr = self.nk + 6
        self.w = self._key_expansion()

    def _sub_word(self, w):
        return [self.S_BOX[b] for b in w]

    def _rot_word(self, w):
        return w[1:] + w[:1]

    def _key_expansion(self):
        w = []
        for i in range(self.nk):
            w.append(self.key[4 * i : 4 * i + 4])
        for i in range(self.nk, 4 * (self.nr + 1)):
            temp = list(w[i - 1])
            if i % self.nk == 0:
                temp = [b ^ r for b, r in zip(self._sub_word(self._rot_word(temp)), [self.RCON[i // self.nk], 0, 0, 0])]
            elif self.nk > 6 and i % self.nk == 4:
                temp = self._sub_word(temp)
            w.append([a ^ b for a, b in zip(w[i - self.nk], temp)])
        return w

    @staticmethod
    def _xt(a):
        return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1)

    @classmethod
    def _mul(cls, a, b):
        res = 0
        while b:
            if b & 1:
                res ^= a
            a = cls._xt(a)
            b >>= 1
        return res

    def _inv_mix_columns(self, s):
        for c in range(4):
            col = [s[r][c] for r in range(4)]
            s[0][c] = self._mul(col[0], 0x0E) ^ self._mul(col[1], 0x0B) ^ self._mul(col[2], 0x0D) ^ self._mul(col[3], 0x09)
            s[1][c] = self._mul(col[0], 0x09) ^ self._mul(col[1], 0x0E) ^ self._mul(col[2], 0x0B) ^ self._mul(col[3], 0x0D)
            s[2][c] = self._mul(col[0], 0x0D) ^ self._mul(col[1], 0x09) ^ self._mul(col[2], 0x0E) ^ self._mul(col[3], 0x0B)
            s[3][c] = self._mul(col[0], 0x0B) ^ self._mul(col[1], 0x0D) ^ self._mul(col[2], 0x09) ^ self._mul(col[3], 0x0E)

    def decrypt_block(self, in_bytes):
        s = [[in_bytes[r + 4 * c] for c in range(4)] for r in range(4)]
        for r in range(4):
            for c in range(4):
                s[r][c] ^= self.w[self.nr * 4 + c][r]
        for round_idx in range(self.nr - 1, 0, -1):
            s[1] = s[1][3:] + s[1][:3]
            s[2] = s[2][2:] + s[2][:2]
            s[3] = s[3][1:] + s[3][:1]
            for r in range(4):
                for c in range(4):
                    s[r][c] = self.INV_S_BOX[s[r][c]]
            for r in range(4):
                for c in range(4):
                    s[r][c] ^= self.w[round_idx * 4 + c][r]
            self._inv_mix_columns(s)
        s[1] = s[1][3:] + s[1][:3]
        s[2] = s[2][2:] + s[2][:2]
        s[3] = s[3][1:] + s[3][:1]
        for r in range(4):
            for c in range(4):
                s[r][c] = self.INV_S_BOX[s[r][c]]
        for r in range(4):
            for c in range(4):
                s[r][c] ^= self.w[c][r]
        out = bytearray(16)
        for r in range(4):
            for c in range(4):
                out[r + 4 * c] = s[r][c]
        return bytes(out)

    def decrypt_cbc(self, ciphertext, iv):
        blocks = [ciphertext[i:i + 16] for i in range(0, len(ciphertext), 16)]
        plaintext = bytearray()
        prev = iv
        for block in blocks:
            dec = self.decrypt_block(block)
            plaintext.extend([a ^ b for a, b in zip(dec, prev)])
            prev = block
        if plaintext:
            pad = plaintext[-1]
            if 1 <= pad <= 16:
                return bytes(plaintext[:-pad])
        return bytes(plaintext)


def aes_cbc_decrypt(cipher_bytes, key_bytes, iv_bytes):
    if len(cipher_bytes) % 16 != 0:
        return b""
    if FastAES is not None:
        try:
            cipher = FastAES.new(key_bytes, FastAES.MODE_CBC, iv_bytes)
            raw = cipher.decrypt(cipher_bytes)
            if raw:
                pad = raw[-1]
                if 1 <= pad <= 16:
                    return raw[:-pad]
            return raw
        except Exception:
            pass
    try:
        engine = PureAES(key_bytes)
        return engine.decrypt_cbc(cipher_bytes, iv_bytes)
    except Exception:
        return b""


def format_remarks(brand="蝴蝶影视", meta=""):
    clean_meta = str(meta or "").strip()
    clean_meta = re.sub(r"[\r\n\t]+", " ", clean_meta).strip()
    if clean_meta:
        return "%s | %s" % (brand, clean_meta)
    return brand


class Spider(SpiderBase):
    def __init__(self):
        super(Spider, self).__init__()
        self.siteName = "野果短剧"
        self.siteUrl = "https://www.yeguodj.com"
        self.apiBase = "https://www.yeguodj.com/api.php"
        self.tgGroup = "https://t.me/tvshare23"
        self.brandActor = "🦋 TG群: @tvshare23"
        self.brandDirector = "🦋 蝴蝶影视"
        self.brandName = "蝴蝶影视"
        self._ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"

        self.API_KEY = b"2acf7e91e9864673"
        self.API_IV = b"1c29882d3ddfcfd6"
        self.MEDIA_KEY = b"f5d965df75336270"
        self.MEDIA_IV = b"97b60394abc2fbe1"

        self.options = {}

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}
        if self.options.get("apiBase"):
            self.apiBase = self.options["apiBase"].rstrip("/")
        return True

    def getName(self):
        return self.siteName

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".ts"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.options = {}

    def _fetch(self, target_url, data=None, referer="", headers_custom=None):
        if not target_url:
            return {"code": 0, "text": "", "bytes": b"", "err": "", "final_url": ""}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/"):
            target_url = self.siteUrl + target_url

        headers = {
            "User-Agent": self._ua,
            "Referer": referer if referer else (self.siteUrl + "/"),
            "Origin": self.siteUrl,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }
        if headers_custom:
            headers.update(headers_custom)

        req_data = None
        if data is not None:
            if isinstance(data, (dict, list)):
                req_data = json.dumps(data).encode("utf-8")
                headers["Content-Type"] = "application/json;charset=UTF-8"
            elif isinstance(data, str):
                req_data = data.encode("utf-8")
            else:
                req_data = data

        for attempt in range(2):
            try:
                req = urllib.request.Request(target_url, data=req_data, headers=headers)
                with self.opener.open(req, timeout=10) as resp:
                    code = resp.getcode()
                    final_url = resp.geturl()
                    raw = resp.read()
                    enc = getattr(resp, "headers", {}).get("Content-Encoding", "")
                    if raw.startswith(b"\x1f\x8b") or enc == "gzip":
                        raw = gzip.decompress(raw)
                    elif enc == "deflate":
                        try:
                            raw = zlib.decompress(raw)
                        except Exception:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                    try:
                        text = raw.decode("utf-8")
                    except Exception:
                        text = raw.decode("latin1", errors="ignore")
                    return {"code": code, "text": text, "bytes": raw, "err": "", "final_url": final_url}
            except urllib.error.HTTPError as e:
                if attempt == 0 and e.code in (429, 451):
                    continue
                err_raw = b""
                try:
                    err_raw = e.read()
                except Exception:
                    pass
                return {"code": e.code, "text": "", "bytes": err_raw, "err": str(e), "final_url": target_url}
            except Exception as e:
                if attempt == 0:
                    continue
                return {"code": -1, "text": "", "bytes": b"", "err": str(e), "final_url": target_url}

        return {"code": -1, "text": "", "bytes": b"", "err": "timeout", "final_url": target_url}

    def _api_post(self, path, body=None):
        url = "%s%s" % (self.apiBase, path)
        res = self._fetch(url, data=body or {})
        text = res.get("text", "")
        if not text:
            return {}
        try:
            d = json.loads(text)
        except Exception:
            return {}

        data_val = d.get("data")
        if isinstance(data_val, str) and len(data_val) > 20:
            try:
                raw_cipher = base64.b64decode(data_val)
                dec = aes_cbc_decrypt(raw_cipher, self.API_KEY, self.API_IV)
                if dec:
                    d["data"] = json.loads(dec.decode("utf-8", "ignore"))
            except Exception:
                pass
        return d

    def _unwrap(self, d):
        if not d:
            return {}
        x = d.get("data") if d.get("data") is not None else d
        if isinstance(x, dict) and x.get("data") is not None and isinstance(x.get("data"), dict):
            return x.get("data")
        return x

    def _proxy_pic(self, pic_url):
        p = str(pic_url or "").strip()
        if not p:
            return "https://dummyimage.com/600x800/1e293b/ffffff.png?text=NO_COVER"
        proxy = self.getProxyUrl()
        sep = "&" if "?" in proxy else "?"
        return "%s%surl=%s" % (proxy, sep, quote(p, safe=""))

    def _to_vod(self, it):
        if not it:
            return None
        vid = str(it.get("video_id") if it.get("video_id") is not None else (it.get("id") or "")).strip()
        if not vid:
            return None
        title = str(it.get("title") or it.get("video_title") or it.get("name") or vid).strip()
        raw_pic = str(it.get("cover") or it.get("cover_img") or it.get("pic") or "").strip()
        ep = it.get("episode_count") or it.get("episodes") or it.get("total_serial") or ""
        remark = str(it.get("update_status") or it.get("serialize_status_text") or "").strip()
        if not remark and ep:
            remark = "更新至%s集" % ep

        return {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": self._proxy_pic(raw_pic),
            "vod_remarks": format_remarks(self.brandName, remark),
            "style": {"type": "rect", "ratio": 0.75}
        }

    def _list_from_payload(self, d):
        inner = self._unwrap(d)
        arr = []
        if isinstance(inner, dict):
            arr = inner.get("list") or inner.get("top_list") or []
        elif isinstance(inner, list):
            arr = inner
        out = []
        for it in arr:
            v = self._to_vod(it)
            if v:
                out.append(v)
        return out

    def homeContent(self, filter):
        classes = [
            {"type_id": "explore", "type_name": "发现"},
            {"type_id": "rank", "type_name": "排行榜"},
            {"type_id": "dushi", "type_name": "都市"},
            {"type_id": "xiandai", "type_name": "现代"},
            {"type_id": "xiaoyuan", "type_name": "校园"},
            {"type_id": "gudai", "type_name": "古代"},
            {"type_id": "xiangcun", "type_name": "乡村"},
            {"type_id": "zhichang", "type_name": "职场"},
            {"type_id": "chongsheng", "type_name": "重生"},
            {"type_id": "chuanyue", "type_name": "穿越"},
            {"type_id": "xitong", "type_name": "系统"},
            {"type_id": "nixi", "type_name": "逆袭"},
            {"type_id": "mogai", "type_name": "魔改"}
        ]
        res = {"class": classes}
        if filter:
            res["filters"] = {}
        return res

    def homeVideoContent(self):
        d = self._api_post("/api/home/homePage", {})
        inner = self._unwrap(d)
        combined = []
        if isinstance(inner, dict):
            combined.extend(inner.get("top_list") or [])
            mods = (inner.get("modules") or {}).get("list") or []
            for m in mods:
                if isinstance(m, dict):
                    if isinstance(m.get("list"), list):
                        combined.extend(m.get("list"))
                    elif m.get("video_id"):
                        combined.append(m)

        seen = set()
        v_list = []
        for it in combined:
            v = self._to_vod(it)
            if v and v["vod_id"] not in seen:
                seen.add(v["vod_id"])
                v_list.append(v)
        return {"list": v_list[:30]}

    def categoryContent(self, tid, pg, filter, extend):
        del filter, extend
        page = int(pg or 1)
        slug = str(tid).strip()

        bg_map = {
            "dushi": 40,
            "xiandai": 39,
            "xiaoyuan": 47,
            "gudai": 41,
            "xiangcun": 42,
            "zhichang": 44
        }
        setting_map = {
            "chongsheng": 26,
            "chuanyue": 27,
            "xitong": 28,
            "nixi": 53,
            "mogai": 56
        }

        v_list = []
        if slug == "rank":
            d = self._api_post("/api/theater/videoRank", {"page": page, "limit": 24})
            v_list = self._list_from_payload(d)
        elif slug in bg_map:
            d = self._api_post("/api/theater/exploreList", {"page": page, "limit": 24, "background": bg_map[slug]})
            v_list = self._list_from_payload(d)
        elif slug in setting_map:
            d = self._api_post("/api/theater/exploreList", {"page": page, "limit": 24, "setting": setting_map[slug]})
            v_list = self._list_from_payload(d)
        else:
            d = self._api_post("/api/theater/exploreList", {"page": page, "limit": 24})
            v_list = self._list_from_payload(d)

        return {
            "page": page,
            "pagecount": page + 1 if len(v_list) >= 24 else page,
            "limit": 24,
            "total": 9999,
            "list": v_list
        }

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        vid = str(raw_id).strip()
        v_num = int(vid) if vid.isdigit() else vid

        d = self._api_post("/api/playlet/detail", {"video_id": v_num})
        info = self._unwrap(d)
        if isinstance(info, dict) and info.get("video_id") is None and isinstance(info.get("data"), dict):
            info = info.get("data")

        title = str(info.get("title") or vid).strip()
        raw_pic = str(info.get("cover") or info.get("cover_img") or "").strip()
        raw_desc = str(info.get("description") or info.get("intro") or "").strip()

        eps = info.get("episodes") if isinstance(info.get("episodes"), list) else []
        play_urls = []
        if eps:
            for idx, ep in enumerate(eps):
                n = str(ep.get("sort") or ep.get("episode") or (idx + 1)).strip()
                t_name = str(ep.get("title") or ("第%s集" % n)).strip()
                t_name = t_name.replace("$", "").replace("#", "")
                play_urls.append("%s$%s:%s" % (t_name, vid, n))
        else:
            total_cnt = int(info.get("episode_count") or info.get("total_serial") or 1)
            for i in range(1, total_cnt + 1):
                play_urls.append("第%s集$%s:%s" % (i, vid, i))

        full_desc = (
            "【🔥 官方交流群: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "%s"
        ) % (self.tgGroup, raw_desc)

        vod = {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": self._proxy_pic(raw_pic),
            "vod_actor": self.brandActor,
            "vod_director": self.brandDirector,
            "vod_remarks": format_remarks(self.brandName, "全%d集" % len(play_urls)),
            "vod_content": full_desc,
            "vod_play_from": "野果专线",
            "vod_play_url": "#".join(play_urls),
            "style": {"type": "rect", "ratio": 0.75}
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        del flag, vipFlags
        raw = str(id or "").strip()
        parts = raw.split(":")
        vid = parts[0]
        ep = parts[1] if len(parts) > 1 else "1"

        v_num = int(vid) if vid.isdigit() else vid
        ep_num = int(ep) if ep.isdigit() else ep

        d = self._api_post("/api/playlet/play", {"video_id": v_num, "ep": ep_num})
        info = self._unwrap(d)
        if isinstance(info, dict) and info.get("video_url") is None and isinstance(info.get("data"), dict):
            info = info.get("data")

        video_url = str(info.get("video_url") or "").strip()
        if not video_url and isinstance(info.get("episodeAll"), list):
            for e in info["episodeAll"]:
                if str(e.get("sort") or e.get("index") or e.get("id")) == str(ep):
                    video_url = str(e.get("video_url") or "").strip()
                    break

        headers = {
            "User-Agent": self._ua,
            "Referer": self.siteUrl + "/",
            "Origin": self.siteUrl
        }

        return {
            "parse": 0,
            "playUrl": "",
            "url": video_url,
            "header": headers
        }

    def searchContent(self, key, quick, pg="1"):
        del quick
        kw = str(key or "").strip()
        if not kw:
            return {"page": 1, "pagecount": 1, "limit": 0, "total": 0, "list": []}
        page = int(pg or 1)
        d = self._api_post("/api/search/result", {"keyword": kw, "page": page})
        v_list = self._list_from_payload(d)
        return {
            "page": page,
            "pagecount": page + 1 if len(v_list) >= 20 else page,
            "limit": len(v_list),
            "total": 9999,
            "list": v_list
        }

    def localProxy(self, params):
        raw_url = unquote(params.get("url", "")).strip()
        if not raw_url:
            return [404, "text/plain; charset=utf-8", "Missing url parameter"]

        fetch_res = self._fetch(raw_url, referer=self.siteUrl + "/")
        raw_bytes = fetch_res.get("bytes", b"")
        if not raw_bytes:
            return [404, "text/plain; charset=utf-8", "Empty image stream"]

        def _detect_mime(b):
            if b.startswith(b"\xff\xd8"):
                return "image/jpeg"
            if b.startswith(b"\x89PNG"):
                return "image/png"
            if b.startswith(b"GIF8"):
                return "image/gif"
            if b.startswith(b"RIFF") and b[8:12] == b"WEBP":
                return "image/webp"
            return None

        mime = _detect_mime(raw_bytes)
        if mime:
            return [200, mime, raw_bytes]

        dec_bytes = aes_cbc_decrypt(raw_bytes, self.MEDIA_KEY, self.MEDIA_IV)
        if dec_bytes:
            mime = _detect_mime(dec_bytes)
            if mime:
                return [200, mime, dec_bytes]
            return [200, "image/jpeg", dec_bytes]

        return [fetch_res.get("code", 200), _detect_mime(raw_bytes) or "image/jpeg", raw_bytes]

    def liveContent(self):
        return ""

    def action(self, action):
        return {"msg": "ok"}

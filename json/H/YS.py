

import os
import re
import sys
import time
import gzip
import random
import urllib.parse
import urllib.request
import ssl

try:
    import requests
    HAS_REQ = True
except ImportError:
    HAS_REQ = False

try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

try:
    from base.spider import Spider as _TVBoxBase
except ImportError:
    class _TVBoxBase(object):
        def init(self, extend=""):
            pass


SEP = "@@"
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")


# ============================================================
# 玉山源（无锁、无后台线程、纯同步）
# ============================================================
class YushanSource(_TVBoxBase):
    NAME = "玉山"
    M3U_URL = "https://www.liaobagua.com/tv/tv.php?a=play"

    FETCH_HEADERS = {
        "User-Agent": UA_BROWSER,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.liaobagua.com/",
    }

    # 已取消屏蔽：显示全部频道
    RESTRICTED_NAMES = []

    EXACT_MAP = {"凤凰卫视中文台": "大陆"}

    KEYWORD_RULES = {
        "体育": ["CCTV-5", "CCTV5", "风云足球", "高尔夫网球", "央视台球",
                 "广东体育", "五星体育", "快乐垂钓", "Now Sports", "NowSports",
                 "Now Golf", "Now Prime", "NOW CH6", "纬来体育", "ELTA体育",
                 "博斯", "DAZN", "智林体育", "欧洲体育", "EURO SPORT", "NBA"],
        "新闻": ["CCTV-13", "CCTV13", "第一财经", "东方财经", "广东新闻",
                 "广州新闻", "上海新闻", "凤凰资讯", "无线新闻", "Now新闻",
                 "Now直播", "Now财经", "华视新闻", "中视新闻", "民视新闻",
                 "台视新闻", "TVBS新闻", "TVBS News", "中天新闻", "三立新闻",
                 "寰宇新闻", "非凡新闻", "年代新闻", "年代much", "鏡電視",
                 "壹电视新闻", "三立inews", "非凡商業", "德国之声", "Sky News",
                 "NHK News", "CNN", "Bloomberg", "France24", "TV5", "天下卫视"],
        "影视": ["CCTV-8", "CCTV8", "CCTV-11", "CCTV11", "怀旧剧场",
                 "风云剧场", "第一剧场", "CHC", "TVS4", "广州影视",
                 "深圳电视剧", "TVB", "Now爆谷", "Now Viu", "Now 华剧",
                 "Now 華劇", "NowJelli", "紫金", "天映", "CCM", "美亚电影",
                 "八大戏", "龙华", "东森戏", "东森电影", "东森洋片",
                 "纬来电影", "纬来戏", "ELTA影剧", "CineMax", "CATCH", "AMC",
                 "靖天电影", "靖天映画", "靖洋", "EYE TV", "Warner",
                 "好莱坞", "HITS", "龙祥", "公视戏", "Astro",
                 "Disney", "ANIMAX", "CN卡通", "MOMO", "Momo"],
        "日本": ["FIGHTING TV", "サムライ", "HGTV", "NHK", "TVN"],
        "香港": ["翡翠台", "明珠台", "J2", "VIU", "HOY", "TVB", "凤凰",
                 "无线新闻", "Now", "NOW", "美亚", "香港国际财经"],
        "台湾": ["公视", "公視", "华视", "華視", "中视", "中視", "民视", "民視",
                 "台视", "台視", "东森", "東森", "三立", "中天", "TVBS",
                 "八大", "龙华", "龍華", "纬来", "緯來", "ELTA", "寰宇",
                 "非凡", "年代", "JET", "靖天", "靖洋", "博斯", "DAZN",
                 "NatGeo", "HBO", "CineMax", "AMC", "Warner", "HITS",
                 "好莱坞", "龙祥", "美食星球", "动物星球", "CN卡通", "MOMO",
                 "Momo", "Disney", "ANIMAX", "AXN", "MTV", "大爱", "好消息",
                 "国会", "客家", "原住民", "人间卫视", "霹雳", "国兴", "东风",
                 "亚洲旅游", "afc", "Travel", "Outdoor", "TLC", "鏡電視",
                 "佛衛", "高點", "信吉", "智林", "阿里郎", "天下卫视",
                 "CHANNEL V", "BBC", "Z频道", "Fashion", "TV5", "France24",
                 "Discovery", "探索", "CATCH", "台灣藝術", "華藏", "韓國娛樂",
                 "MTV Live", "History", "德国之声", "Bloomberg", "CNN",
                 "EURO SPORT", "TRACE", "Astro", "Sky News", "NHK",
                 "壹电视", "镜电视"],
        "大陆": ["CCTV", "央视", "央視", "浙江", "湖南", "江苏", "北京",
                 "东方卫视", "东南", "辽宁", "广西", "江西", "海南", "厦门",
                 "广东", "广州", "深圳", "TVS", "大湾区", "岭南", "江门",
                 "嘉佳", "金鹰", "卡酷"],
    }

    CATEGORY_ORDER = ["大陆", "日本", "香港", "台湾", "国际",
                      "新闻", "体育", "影视"]

    def __init__(self):
        self._channels = None
        self._flat = None

    def init(self, extend=""):
        # 不做预加载，纯同步：用户点进来才拉
        pass

    @staticmethod
    def _clean_name(name):
        return re.sub(r'\s*\[[^\]]*\]\s*$', '', str(name or '')).strip()

    def _detect_category(self, name):
        if not name:
            return "国际"
        if name in self.EXACT_MAP:
            return self.EXACT_MAP[name]
        low = name.lower()
        for cat, kws in self.KEYWORD_RULES.items():
            for kw in kws:
                if kw.lower() in low:
                    return cat
        return "国际"

    def _fetch_m3u(self):
        h = dict(self.FETCH_HEADERS)

        if HAS_REQ:
            try:
                r = requests.get(self.M3U_URL, headers=h, verify=False,
                                 timeout=12, allow_redirects=True)
                if r.status_code == 200 and r.text:
                    print("[玉山] requests 拉到 %d 字节" % len(r.text),
                          flush=True)
                    return r.text
                else:
                    print("[玉山] requests HTTP %s" % r.status_code, flush=True)
            except Exception as e:
                print("[玉山] requests 失败: %s" % str(e)[:80], flush=True)

        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ctx))
            rq = urllib.request.Request(self.M3U_URL, headers=h)
            with opener.open(rq, timeout=12) as resp:
                raw = resp.read()
                if raw.startswith(b"\x1f\x8b"):
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8", errors="ignore")
                print("[玉山] urllib 拉到 %d 字节" % len(text), flush=True)
                return text
        except Exception as e:
            print("[玉山] urllib 失败: %s" % str(e)[:80], flush=True)

        return ""

    def _parse_m3u(self, text):
        out = []
        cur = None
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#EXTINF"):
                m = re.search(r'tvg-name="([^"]*)"', line)
                tvg = m.group(1).strip() if m else ""
                m = re.search(r'tvg-logo="([^"]*)"', line)
                logo = m.group(1).strip() if m else ""
                display = ""
                last_q = line.rfind('"')
                if last_q >= 0:
                    tail = line[last_q + 1:]
                    if "," in tail:
                        display = tail.split(",", 1)[1].strip()
                elif "," in line:
                    display = line.split(",", 1)[1].strip()
                cur = {"tvg": tvg, "display": display, "logo": logo,
                       "url": "", "ua": "", "referer": ""}
                continue
            if line.startswith("#EXTVLCOPT"):
                if cur is None:
                    continue
                if "http-user-agent=" in line:
                    cur["ua"] = line.split("=", 1)[1].strip()
                elif "http-referrer=" in line:
                    cur["referer"] = line.split("=", 1)[1].strip()
                continue
            if line.startswith("#"):
                continue
            if cur is not None and line.startswith(("http://", "https://")):
                cur["url"] = line
                out.append(cur)
                cur = None
        return out

    def _load_channels(self):
        if self._channels is not None:
            return self._channels

        print("[玉山] 开始拉取 M3U...", flush=True)
        text = self._fetch_m3u()
        if not text:
            print("[玉山] M3U 为空，放弃", flush=True)
            self._channels = []
            return []

        raw_list = self._parse_m3u(text)
        print("[玉山] 解析出 %d 个频道" % len(raw_list), flush=True)

        grouped = {}
        restricted = []
        for item in raw_list:
            display = self._clean_name(item["display"] or item["tvg"])
            if not display:
                continue
            record = {"name": display, "url": item["url"],
                      "logo": item["logo"], "ua": item["ua"],
                      "referer": item["referer"]}
            if (item["tvg"] in self.RESTRICTED_NAMES
                    or display in self.RESTRICTED_NAMES):
                restricted.append(record)
                continue
            cat = self._detect_category(display)
            grouped.setdefault(cat, []).append(record)

        ordered = []
        for cat in self.CATEGORY_ORDER:
            if cat == "限制":
                continue
            if cat in grouped:
                ordered.append((cat, grouped.pop(cat)))
        for cat, lst in grouped.items():
            ordered.append((cat, lst))
        if restricted:
            ordered.append(("限制", restricted))

        print("[玉山] 分组完成: %d 组" % len(ordered), flush=True)
        self._channels = ordered
        return ordered

    def _flat_list(self):
        if self._flat is not None:
            return self._flat
        arr = []
        for cat, lst in (self._load_channels() or []):
            for ch in lst:
                ch2 = dict(ch)
                ch2["cat"] = cat
                arr.append(ch2)
        self._flat = arr
        return arr


# ============================================================
# 主 Spider（单源：玉山）
# ============================================================
class Spider(_TVBoxBase):

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.src = YushanSource()

    def getName(self):
        return "玉山直播"

    def init(self, extend=""):
        try:
            self.src.init(extend)
        except Exception:
            pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter=False):
        return {
            "class": [{"type_id": "ys", "type_name": "📺 玉山直播"}],
            "filters": {},
            "list": []
        }

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        # 一级：列出玉山的所有分类
        try:
            cats = self.src._load_channels() or []
        except Exception as e:
            return {"list": [], "page": 1, "pagecount": 1,
                    "limit": 0, "total": 0}

        videos = []
        for cat, lst in cats:
            if not lst:
                continue
            videos.append({
                "vod_id": "cat@@%s" % cat,
                "vod_name": cat,
                "vod_pic": "",
                "vod_remarks": "%d 个频道" % len(lst),
            })
        return {"list": videos, "page": 1, "pagecount": 1,
                "limit": len(videos), "total": len(videos)}

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        full_id = str(ids[0])

        # 入口 A：点分类 → 列出该分类下所有频道作为多集
        if full_id.startswith("cat@@"):
            cat = full_id[len("cat@@"):]
            return self._cat_detail(cat, full_id)

        # 入口 B：点频道 → 单条详情
        if full_id.startswith("live#"):
            try:
                idx = int(full_id.split("#", 1)[1])
            except Exception:
                return {"list": []}
            arr = self.src._flat_list()
            if 0 <= idx < len(arr):
                ch = arr[idx]
                safe = str(ch["name"]).replace("$", " ").replace("#", " ")
                return {"list": [{
                    "vod_id": full_id,
                    "vod_name": ch["name"],
                    "vod_pic": ch["logo"],
                    "vod_remarks": ch["cat"],
                    "vod_play_from": "玉山直播",
                    "vod_play_url": "%s$%s" % (safe, full_id),
                }]}
        return {"list": []}

    def _cat_detail(self, cat, full_id):
        arr = self.src._flat_list()
        eps = []
        count = 0
        for i, ch in enumerate(arr):
            if ch["cat"] != cat:
                continue
            safe = str(ch["name"]).replace("$", " ").replace("#", " ")
            eps.append("%s$live#%d" % (safe, i))
            count += 1
        if not eps:
            return {"list": [{
                "vod_id": full_id,
                "vod_name": cat,
                "vod_content": "该分类下无频道",
                "vod_play_from": "玉山直播",
                "vod_play_url": "无频道$error",
            }]}
        return {"list": [{
            "vod_id": full_id,
            "vod_name": cat,
            "vod_pic": "",
            "vod_remarks": "%d 个频道" % count,
            "vod_content": "玉山直播 · %s" % cat,
            "vod_play_from": "玉山直播",
            "vod_play_url": "#".join(eps),
        }]}

    def playerContent(self, flag, pid, vipFlags=None):
        s = str(pid or "")
        if "$" in s:
            s = s.split("$", 1)[1]
        if s == "error":
            return {"parse": 0, "jx": 0, "url": "", "header": {}}
        if s.startswith("live#"):
            try:
                idx = int(s.split("#", 1)[1])
            except Exception:
                return {"parse": 0, "jx": 0, "url": "", "header": {}}
            arr = self.src._flat_list()
            if 0 <= idx < len(arr):
                ch = arr[idx]
                headers = {"User-Agent": ch.get("ua") or UA_BROWSER}
                headers["Referer"] = (ch.get("referer")
                                      or "https://www.liaobagua.com/")
                return {"parse": 0, "jx": 0, "url": ch["url"], "header": headers}
        if s.startswith("http"):
            return {"parse": 0, "jx": 0, "url": s, "header": {}}
        return {"parse": 0, "jx": 0, "url": "", "header": {}}

    def searchContent(self, key, quick=False, pg="1"):
        key = str(key or "").lower().strip()
        if not key:
            return {"list": []}
        out = []
        try:
            arr = self.src._flat_list()
        except Exception:
            arr = []
        for i, ch in enumerate(arr):
            if key in ch["name"].lower():
                out.append({
                    "vod_id": "live#%d" % i,
                    "vod_name": ch["name"],
                    "vod_pic": ch["logo"],
                    "vod_remarks": ch["cat"],
                })
        return {"list": out}

    def searchContentPage(self, keywords, quick, page):
        return self.searchContent(keywords, quick, page)

    def localProxy(self, param):
        return [404, "text/plain", b""]

    def action(self, action_str):
        return ""

    def destroy(self):
        return "正在Destroy"


if __name__ == '__main__':
    pass

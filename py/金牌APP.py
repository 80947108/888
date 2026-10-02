# -*- coding: utf-8 -*-

import sys
import os
import re
import json
import time
import hashlib
import urllib.request
import urllib.parse
import http.cookiejar
import gzip
import zlib
import ssl

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"

def format_remarks(brand="蝴蝶影视", meta=""):
    clean_meta = str(meta or "").strip()
    clean_meta = re.sub(r"[\r\n\t]+", " ", clean_meta).strip()
    if clean_meta:
        return "%s | %s" % (brand, clean_meta)
    return brand

class Spider(SpiderBase):
    def getName(self):
        return "华视影院"

    def init(self, extend=""):
        self.home_url = "https://www.lwdys.com"
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        self.error_url = "https://sf1-cdn-tos.huoshanstatic.com/obj/media-fe/xgplayer_doc_video/mp4/xgplayer-demo-720p.mp4"
        self.brandActor = "🦋 TG群: @tvshare23"
        self.brandDirector = "🦋 蝴蝶影视"
        self.tgGroup = "https://t.me/tvshare23"

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".avi", ".ts", ".mpd", "index.png"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, params):
        return [404, "text/plain; charset=utf-8", "Proxy not configured"]

    def _get_sign(self, params_str=""):
        t = str(int(time.time() * 1000))
        if params_str:
            data = "%s&key=cb808529bae6b6be45ecfab29a4889bc&t=%s" % (params_str, t)
        else:
            data = "key=cb808529bae6b6be45ecfab29a4889bc&t=%s" % t
        data_md5 = hashlib.md5(data.encode("utf-8")).hexdigest()
        data_sha1 = hashlib.sha1(data_md5.encode("utf-8")).hexdigest()
        return t, data_sha1

    def _fetch(self, url, headers=None):
        req_headers = {
            "User-Agent": self.ua,
            "Referer": self.home_url + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }
        if headers:
            req_headers.update(headers)

        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers=req_headers)
                with self.opener.open(req, timeout=10) as resp:
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
                    return {"code": resp.getcode(), "text": text}
            except Exception as e:
                if attempt == 0:
                    continue
                return {"code": -1, "text": "", "err": str(e)}
        return {"code": -1, "text": "", "err": "timeout"}

    def homeContent(self, filter):
        return {
            "class": [
                {"type_id": "1", "type_name": "电影"},
                {"type_id": "2", "type_name": "电视剧"},
                {"type_id": "3", "type_name": "综艺"},
                {"type_id": "4", "type_name": "动漫"}
            ],
            "filters": {
                "1": [
                    {"key": "type", "name": "类型", "value": [
                        {"n": "全部", "v": ""}, {"n": "喜剧", "v": "/type/22"}, {"n": "动作", "v": "/type/23"},
                        {"n": "科幻", "v": "/type/30"}, {"n": "爱情", "v": "/type/26"}, {"n": "悬疑", "v": "/type/27"},
                        {"n": "奇幻", "v": "/type/87"}, {"n": "剧情", "v": "/type/37"}, {"n": "恐怖", "v": "/type/36"},
                        {"n": "犯罪", "v": "/type/35"}, {"n": "动画", "v": "/type/33"}, {"n": "惊悚", "v": "/type/34"},
                        {"n": "战争", "v": "/type/25"}, {"n": "冒险", "v": "/type/31"}, {"n": "灾难", "v": "/type/81"},
                        {"n": "伦理", "v": "/type/83"}, {"n": "其他", "v": "/type/43"}
                    ]},
                    {"key": "area", "name": "地区", "value": [
                        {"n": "全部", "v": ""}, {"n": "中国大陆", "v": "/area/中国大陆"}, {"n": "中国香港", "v": "/area/中国香港"},
                        {"n": "中国台湾", "v": "/area/中国台湾"}, {"n": "美国", "v": "/area/美国"}, {"n": "日本", "v": "/area/日本"},
                        {"n": "韩国", "v": "/area/韩国"}, {"n": "印度", "v": "/area/印度"}, {"n": "泰国", "v": "/area/泰国"},
                        {"n": "其他", "v": "/area/其他"}
                    ]},
                    {"key": "year", "name": "年份", "value": [
                        {"n": "全部", "v": ""}, {"n": "2026", "v": "/year/2026"}, {"n": "2025", "v": "/year/2025"},
                        {"n": "2024", "v": "/year/2024"}, {"n": "2023", "v": "/year/2023"}, {"n": "2022", "v": "/year/2022"},
                        {"n": "2021", "v": "/year/2021"}, {"n": "2020", "v": "/year/2020"}, {"n": "2019", "v": "/year/2019"},
                        {"n": "2018", "v": "/year/2018"}, {"n": "2017", "v": "/year/2017"}, {"n": "2016", "v": "/year/2016"},
                        {"n": "2015", "v": "/year/2015"}, {"n": "2014", "v": "/year/2014"}, {"n": "2013", "v": "/year/2013"},
                        {"n": "2012", "v": "/year/2012"}, {"n": "2011", "v": "/year/2011"}, {"n": "2010", "v": "/year/2010"},
                        {"n": "2009~2000", "v": "/year/2009~2000"}
                    ]},
                    {"key": "lang", "name": "语言", "value": [
                        {"n": "全部", "v": ""}, {"n": "国语", "v": "/lang/国语"}, {"n": "英语", "v": "/lang/英语"},
                        {"n": "粤语", "v": "/lang/粤语"}, {"n": "韩语", "v": "/lang/韩语"}, {"n": "日语", "v": "/lang/日语"},
                        {"n": "其他", "v": "/lang/其他"}
                    ]},
                    {"key": "by", "name": "排序", "value": [
                        {"n": "上映时间", "v": "/sortType/1/sortOrder/0"},
                        {"n": "人气高低", "v": "/sortType/3/sortOrder/0"},
                        {"n": "评分高低", "v": "/sortType/4/sortOrder/0"}
                    ]}
                ],
                "2": [
                    {"key": "type", "name": "类型", "value": [
                        {"n": "全部", "v": ""}, {"n": "国产剧", "v": "/type/14"}, {"n": "欧美剧", "v": "/type/15"},
                        {"n": "港台剧", "v": "/type/16"}, {"n": "日韩剧", "v": "/type/62"}, {"n": "其他剧", "v": "/type/68"}
                    ]},
                    {"key": "class", "name": "剧情", "value": [
                        {"n": "全部", "v": ""}, {"n": "古装", "v": "/class/古装"}, {"n": "战争", "v": "/class/战争"},
                        {"n": "喜剧", "v": "/class/喜剧"}, {"n": "家庭", "v": "/class/家庭"}, {"n": "犯罪", "v": "/class/犯罪"},
                        {"n": "动作", "v": "/class/动作"}, {"n": "奇幻", "v": "/class/奇幻"}, {"n": "剧情", "v": "/class/剧情"},
                        {"n": "历史", "v": "/class/历史"}, {"n": "短片", "v": "/class/短片"}
                    ]},
                    {"key": "area", "name": "地区", "value": [
                        {"n": "全部", "v": ""}, {"n": "中国大陆", "v": "/area/中国大陆"}, {"n": "中国香港", "v": "/area/中国香港"},
                        {"n": "中国台湾", "v": "/area/中国台湾"}, {"n": "日本", "v": "/area/日本"}, {"n": "韩国", "v": "/area/韩国"},
                        {"n": "美国", "v": "/area/美国"}, {"n": "泰国", "v": "/area/泰国"}, {"n": "其他", "v": "/area/其他"}
                    ]},
                    {"key": "year", "name": "时间", "value": [
                        {"n": "全部", "v": ""}, {"n": "2026", "v": "/year/2026"}, {"n": "2025", "v": "/year/2025"},
                        {"n": "2024", "v": "/year/2024"}, {"n": "2023", "v": "/year/2023"}, {"n": "2022", "v": "/year/2022"},
                        {"n": "2021", "v": "/year/2021"}, {"n": "2020", "v": "/year/2020"}, {"n": "2019", "v": "/year/2019"},
                        {"n": "2018", "v": "/year/2018"}, {"n": "2017", "v": "/year/2017"}, {"n": "2016", "v": "/year/2016"},
                        {"n": "2015", "v": "/year/2015"}, {"n": "2014", "v": "/year/2014"}, {"n": "2013", "v": "/year/2013"},
                        {"n": "2012", "v": "/year/2012"}, {"n": "2011", "v": "/year/2011"}, {"n": "2010", "v": "/year/2010"}
                    ]},
                    {"key": "lang", "name": "语言", "value": [
                        {"n": "全部", "v": ""}, {"n": "普通话", "v": "/lang/普通话"}, {"n": "英语", "v": "/lang/英语"},
                        {"n": "粤语", "v": "/lang/粤语"}, {"n": "韩语", "v": "/lang/韩语"}, {"n": "日语", "v": "/lang/日语"},
                        {"n": "泰语", "v": "/lang/泰语"}, {"n": "其他", "v": "/lang/其他"}
                    ]},
                    {"key": "by", "name": "排序", "value": [
                        {"n": "最近更新", "v": "/sortType/1/sortOrder/0"},
                        {"n": "添加时间", "v": "/sortType/2/sortOrder/0"},
                        {"n": "人气高低", "v": "/sortType/3/sortOrder/0"},
                        {"n": "评分高低", "v": "/sortType/4/sortOrder/0"}
                    ]}
                ],
                "3": [
                    {"key": "type", "name": "类型", "value": [
                        {"n": "全部", "v": ""}, {"n": "国产综艺", "v": "/type/69"}, {"n": "港台综艺", "v": "/type/70"},
                        {"n": "日韩综艺", "v": "/type/72"}, {"n": "欧美综艺", "v": "/type/73"}
                    ]},
                    {"key": "class", "name": "剧情", "value": [
                        {"n": "全部", "v": ""}, {"n": "真人秀", "v": "/class/真人秀"}, {"n": "音乐", "v": "/class/音乐"},
                        {"n": "脱口秀", "v": "/class/脱口秀"}
                    ]},
                    {"key": "area", "name": "地区", "value": [
                        {"n": "全部", "v": ""}, {"n": "中国大陆", "v": "/area/中国大陆"}, {"n": "中国香港", "v": "/area/中国香港"},
                        {"n": "中国台湾", "v": "/area/中国台湾"}, {"n": "日本", "v": "/area/日本"}, {"n": "韩国", "v": "/area/韩国"},
                        {"n": "美国", "v": "/area/美国"}, {"n": "其他", "v": "/area/其他"}
                    ]},
                    {"key": "year", "name": "时间", "value": [
                        {"n": "全部", "v": ""}, {"n": "2026", "v": "/year/2026"}, {"n": "2025", "v": "/year/2025"},
                        {"n": "2024", "v": "/year/2024"}, {"n": "2023", "v": "/year/2023"}, {"n": "2022", "v": "/year/2022"},
                        {"n": "2021", "v": "/year/2021"}, {"n": "2020", "v": "/year/2020"}
                    ]},
                    {"key": "lang", "name": "语言", "value": [
                        {"n": "全部", "v": ""}, {"n": "国语", "v": "/lang/国语"}, {"n": "英语", "v": "/lang/英语"},
                        {"n": "粤语", "v": "/lang/粤语"}, {"n": "韩语", "v": "/lang/韩语"}, {"n": "日语", "v": "/lang/日语"},
                        {"n": "其他", "v": "/lang/其他"}
                    ]},
                    {"key": "by", "name": "排序", "value": [
                        {"n": "最近更新", "v": "/sortType/1/sortOrder/0"},
                        {"n": "添加时间", "v": "/sortType/2/sortOrder/0"},
                        {"n": "人气高低", "v": "/sortType/3/sortOrder/0"},
                        {"n": "评分高低", "v": "/sortType/4/sortOrder/0"}
                    ]}
                ],
                "4": [
                    {"key": "type", "name": "类型", "value": [
                        {"n": "全部", "v": ""}, {"n": "国产动漫", "v": "/type/75"}, {"n": "日韩动漫", "v": "/type/76"},
                        {"n": "欧美动漫", "v": "/type/77"}
                    ]},
                    {"key": "class", "name": "剧情", "value": [
                        {"n": "全部", "v": ""}, {"n": "喜剧", "v": "/class/喜剧"}, {"n": "科幻", "v": "/class/科幻"},
                        {"n": "热血", "v": "/class/热血"}, {"n": "冒险", "v": "/class/冒险"}, {"n": "动作", "v": "/class/动作"},
                        {"n": "运动", "v": "/class/运动"}, {"n": "战争", "v": "/class/战争"}, {"n": "儿童", "v": "/class/儿童"}
                    ]},
                    {"key": "area", "name": "地区", "value": [
                        {"n": "全部", "v": ""}, {"n": "中国大陆", "v": "/area/中国大陆"}, {"n": "日本", "v": "/area/日本"},
                        {"n": "美国", "v": "/area/美国"}, {"n": "其他", "v": "/area/其他"}
                    ]},
                    {"key": "year", "name": "时间", "value": [
                        {"n": "全部", "v": ""}, {"n": "2026", "v": "/year/2026"}, {"n": "2025", "v": "/year/2025"},
                        {"n": "2024", "v": "/year/2024"}, {"n": "2023", "v": "/year/2023"}, {"n": "2022", "v": "/year/2022"},
                        {"n": "2021", "v": "/year/2021"}, {"n": "2020", "v": "/year/2020"}, {"n": "2019", "v": "/year/2019"},
                        {"n": "2018", "v": "/year/2018"}, {"n": "2017", "v": "/year/2017"}, {"n": "2016", "v": "/year/2016"},
                        {"n": "2015", "v": "/year/2015"}, {"n": "2014", "v": "/year/2014"}, {"n": "2013", "v": "/year/2013"},
                        {"n": "2012", "v": "/year/2012"}, {"n": "2011", "v": "/year/2011"}, {"n": "2010", "v": "/year/2010"}
                    ]},
                    {"key": "lang", "name": "语言", "value": [
                        {"n": "全部", "v": ""}, {"n": "国语", "v": "/lang/国语"}, {"n": "英语", "v": "/lang/英语"},
                        {"n": "日语", "v": "/lang/日语"}, {"n": "其他", "v": "/lang/其他"}
                    ]},
                    {"key": "by", "name": "排序", "value": [
                        {"n": "最近更新", "v": "/sortType/1/sortOrder/0"},
                        {"n": "添加时间", "v": "/sortType/2/sortOrder/0"},
                        {"n": "人气高低", "v": "/sortType/3/sortOrder/0"},
                        {"n": "评分高低", "v": "/sortType/4/sortOrder/0"}
                    ]}
                ]
            }
        }

    def homeVideoContent(self):
        video_list = []
        t, sign = self._get_sign()
        h = {"t": t, "sign": sign}
        target_url = "%s/api/mw-movie/anonymous/home/hotSearch" % self.home_url
        res = self._fetch(target_url, headers=h)
        try:
            data = json.loads(res.get("text", "{}")).get("data", [])
            for i in data:
                raw_remarks = i.get("vodVersion", "") if i.get("typeId1") == 1 else i.get("vodRemarks", "")
                video_list.append({
                    "vod_id": str(i.get("vodId", "")),
                    "vod_name": i.get("vodName", ""),
                    "vod_pic": i.get("vodPic", ""),
                    "vod_remarks": format_remarks("蝴蝶影视", raw_remarks),
                    "style": {"type": "rect", "ratio": 0.75}
                })
        except Exception:
            pass

        return {
            "list": video_list,
            "parse": 0,
            "jx": 0
        }

    def _extract_rsc_list(self, html_text):
        patterns = ['\\"list\\":[', '"list":[']
        candidates = []
        for marker in patterns:
            start = 0
            while True:
                idx = html_text.find(marker, start)
                if idx == -1:
                    break
                bracket_pos = idx + len(marker) - 1
                depth = 0
                end_p = -1
                for i in range(bracket_pos, min(len(html_text), bracket_pos + 150000)):
                    c = html_text[i]
                    if c == "[":
                        depth += 1
                    elif c == "]":
                        depth -= 1
                        if depth == 0:
                            end_p = i + 1
                            break
                if end_p != -1:
                    chunk = html_text[bracket_pos:end_p]
                    if "vodId" in chunk:
                        clean_chunk = chunk.replace('\\"', '"').replace('\\\\', '\\')
                        try:
                            data = json.loads(clean_chunk)
                            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and "vodId" in data[0]:
                                return data
                        except Exception:
                            pass
                start = idx + len(marker)

        return []

    def categoryContent(self, cid, page, filter, ext):
        ext_dict = ext if isinstance(ext, dict) else {}
        _type = ext_dict.get("type", "")
        __class = ext_dict.get("class", "")
        _area = ext_dict.get("area", "")
        _year = ext_dict.get("year", "")
        _lang = ext_dict.get("lang", "")
        _by = ext_dict.get("by", "")
        video_list = []

        sub_path = "%s%s%s%s%s%s" % (_type, __class, _area, _year, _lang, _by)
        encoded_sub_path = urllib.parse.quote(sub_path, safe="/")

        url_path = "/vod/show/id/%s%s/page/%s" % (cid, encoded_sub_path, page)
        target_url = self.home_url + url_path
        res = self._fetch(target_url)
        content = res.get("text", "")

        data_list = self._extract_rsc_list(content)

        for i in data_list:
            raw_remarks = i.get("vodVersion", "") if i.get("typeId1") == 1 else i.get("vodRemarks", "")
            video_list.append({
                "vod_id": str(i.get("vodId", "")),
                "vod_name": i.get("vodName", ""),
                "vod_pic": i.get("vodPic", ""),
                "vod_remarks": format_remarks("蝴蝶影视", raw_remarks),
                "style": {"type": "rect", "ratio": 0.75}
            })

        return {
            "list": video_list,
            "page": int(page or 1),
            "pagecount": 9999 if video_list else 1,
            "limit": 20,
            "total": 9999 if video_list else 0,
            "parse": 0,
            "jx": 0
        }

    def detailContent(self, did):
        ids = did[0] if isinstance(did, (list, tuple)) else str(did)
        video_list = []
        t, sign = self._get_sign("id=%s" % ids)
        h = {"t": t, "sign": sign}
        target_url = "%s/api/mw-movie/anonymous/video/detail?id=%s" % (self.home_url, ids)
        res = self._fetch(target_url, headers=h)
        try:
            data = json.loads(res.get("text", "{}")).get("data", {})
            play_list = data.get("episodeList", [])
            vod_play_url = []
            for i in play_list:
                name = str(i.get("name", "")).replace("$", "_").replace("#", "_")
                play_token = "%s/%s" % (ids, str(i.get("nid", "")))
                vod_play_url.append("%s$%s" % (name, play_token))

            raw_desc = data.get("vodContent", "")
            full_desc = (
                "【🔥 官方交流群: %s】\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "%s"
            ) % (self.tgGroup, raw_desc)

            video_list.append({
                "type_name": data.get("typeName", ""),
                "vod_id": str(ids),
                "vod_name": data.get("vodName", ""),
                "vod_remarks": format_remarks("蝴蝶影视", data.get("vodRemarks", "")),
                "vod_year": str(data.get("vodYear", "")),
                "vod_area": data.get("vodArea", ""),
                "vod_actor": self.brandActor,
                "vod_director": self.brandDirector,
                "vod_content": full_desc,
                "vod_play_from": "蝴蝶专线",
                "vod_play_url": "#".join(vod_play_url)
            })
        except Exception:
            pass

        return {"list": video_list, "parse": 0, "jx": 0}

    def searchContent(self, key, quick, page="1"):
        wd = urllib.parse.quote(key)
        video_list = []
        param_str = "keyword=%s&pageNum=%s&pageSize=12" % (key, page)
        t, sign = self._get_sign(param_str)
        h = {"t": t, "sign": sign}
        target_url = "%s/api/mw-movie/anonymous/video/searchByWord?keyword=%s&pageNum=%s&pageSize=12" % (
            self.home_url, wd, page
        )
        res = self._fetch(target_url, headers=h)
        try:
            data_list = json.loads(res.get("text", "{}")).get("data", {}).get("result", {}).get("list", [])
            for i in data_list:
                raw_remarks = i.get("vodVersion", "") if i.get("typeId1") == 1 else i.get("vodRemarks", "")
                video_list.append({
                    "vod_id": str(i.get("vodId", "")),
                    "vod_name": i.get("vodName", ""),
                    "vod_pic": i.get("vodPic", ""),
                    "vod_remarks": format_remarks("蝴蝶影视", raw_remarks),
                    "style": {"type": "rect", "ratio": 0.75}
                })
        except Exception:
            pass

        return {
            "list": video_list,
            "page": int(page or 1),
            "pagecount": 9999 if video_list else 1,
            "limit": 12,
            "total": 9999 if video_list else 0,
            "parse": 0,
            "jx": 0
        }

    def playerContent(self, flag, pid, vipFlags):
        url = str(pid).strip()
        play_url = self.error_url
        data = url.split("/")
        if len(data) >= 2:
            _id = data[0]
            _nid = data[1]
            param_str = "id=%s&nid=%s" % (_id, _nid)
            t, sign = self._get_sign(param_str)
            h = {"t": t, "sign": sign}
            target_url = "%s/api/mw-movie/anonymous/v2/video/episode/url?id=%s&nid=%s" % (
                self.home_url, _id, _nid
            )
            res = self._fetch(target_url, headers=h)
            try:
                res_json = json.loads(res.get("text", "{}"))
                play_url = res_json.get("data", {}).get("list", [{}])[0].get("url", self.error_url)
            except Exception:
                play_url = self.error_url

        headers = {
            "User-Agent": self.ua,
            "Referer": self.home_url + "/"
        }
        return {
            "parse": 0,
            "jx": 0,
            "url": play_url,
            "header": headers
        }

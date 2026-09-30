# -*- coding: utf-8 -*-
"""
TVBox Python Spider - 荐片影视【缓冲优化版】
适配 FongMi TV / OK影视
"""
import sys
import re
import json
import time
import base64

sys.path.append("..")

try:
    from urllib.parse import quote as _quote, unquote as _unquote
except Exception:
    _quote = lambda x: x
    _unquote = lambda x: x

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def fetch(self, url, headers=None, **kw):
            import requests
            r = requests.get(url, headers=headers or {}, timeout=15, **kw)
            return r
        def post(self, url, data=None, headers=None, **kw):
            import requests
            r = requests.post(url, data=data, headers=headers or {}, timeout=15, **kw)
            return r


_UA_POOL = [
    'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

_HOME_CACHE_TTL = 300
_PLAY_CACHE_TTL = 3600
_REQUEST_TIMEOUT = 15  # 延长超时，原来10改成15
_MAX_RETRY = 2 # 播放链接获取失败重试2次

class Spider(BaseSpider):
    host = "https://m.jpyy.site"
    header = {
        'User-Agent': _UA_POOL[0],
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': 'https://m.jpyy.site/',
    }

    categories = [
        ("dianying", "电影"),
        ("dianshiju", "电视剧"),
        ("zongyi", "综艺"),
        ("dongman", "动漫"),
        ("duanju", "短剧"),
    ]

    def __init__(self):
        self._init_state()

    def _init_state(self):
        if not hasattr(self, '_session') or self._session is None:
            self._session = None
        if not hasattr(self, '_home_html'):
            self._home_html = ''
        if not hasattr(self, '_home_html_time'):
            self._home_html_time = 0
        if not hasattr(self, '_play_cache'):
            self._play_cache = {}
        if not hasattr(self, '_header_inited'):
            self.header = dict(Spider.header)
            self._header_inited = True

    def getName(self):
        return '荐片影视'

    def init(self, extend=""):
        self._init_state()
        self.extend = extend or ''
        if self.extend and self.extend.startswith('http'):
            m = re.match(r'(https?://[^/]+)', self.extend)
            if m:
                self.host = m.group(1).rstrip('/')
                Spider.host = self.host
                self.header['Referer'] = self.host + '/'
        if _HAS_REQUESTS and not self._session:
            self._session = _requests.Session()
            self._session.headers.update(self.header)
        return ''

    def isVideoFormat(self, url):
        if not url or not isinstance(url, str):
            return False
        return any(x in url for x in ['.m3u8', '.mp4', '.flv', '.ts'])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
        self._play_cache.clear()

    def _get_session(self):
        if not self._session and _HAS_REQUESTS:
            self._session = _requests.Session()
            self._session.headers.update(self.header)
        return self._session

    @staticmethod
    def _is_cf_challenge(text):
        if not text or len(text) < 200:
            return True
        markers = ['Just a moment', 'cf-challenge', 'challenge-platform','Attention Required']
        low = text[:2000].lower()
        return any(m.lower() in low for m in markers)

    def _fetch_html(self, path, use_cache=False):
        url = path if path.startswith('http') else self.host + path
        if use_cache:
            now = time.time()
            if self._home_html and (now - self._home_html_time) < _HOME_CACHE_TTL:
                return self._home_html

        for retry in range(_MAX_RETRY +1):
            for ua in _UA_POOL:
                headers = dict(self.header)
                headers['User-Agent'] = ua
                headers['Referer'] = self.host + '/'
                try:
                    r = self.fetch(url, headers=headers, timeout=_REQUEST_TIMEOUT)
                    text = r.text if hasattr(r, 'text') else ''
                    if text and not self._is_cf_challenge(text):
                        if use_cache:
                            self._home_html = text
                            self._home_html_time = time.time()
                        return text
                except Exception:
                    pass
                session = self._get_session()
                if session:
                    try:
                        r = session.get(url, headers=headers, timeout=_REQUEST_TIMEOUT, allow_redirects=True)
                        if r.status_code == 200 and r.text and not self._is_cf_challenge(r.text):
                            if use_cache:
                                self._home_html = r.text
                                self._home_html_time = time.time()
                            return r.text
                    except Exception:
                        continue
            time.sleep(0.3)
        return ''

    @staticmethod
    def _fix_url(url):
        if not url:
            return ''
        url = url.strip()
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return Spider.host + url
        return url

    def _parse_img(self, context):
        for key in ['data-original', 'data-src', 'lay-src', 'data-lazy-src', 'src']:
            m = re.search(r'%s="([^"]+)"' % key, context)
            if m:
                return self._fix_url(m.group(1))
        return ''

    def _parse_cards(self, html):
        if not html:
            return []
        vod_list = []
        seen = set()
        links = re.findall(r'href="(/movie/(\d+)\.html)"', html)
        for href, vid in links:
            if vid in seen:
                continue
            pos = html.find(href)
            if pos < 0:
                continue
            seen.add(vid)
            context = html[max(0, pos - 600):pos + 600]
            title = ''
            title_m = re.search(r'<a[^>]*class="[^"]*item-title[^"]*"[^>]*>([^<]+)</a>', context)
            if title_m:
                title = title_m.group(1).strip()
            if not title:
                title_m = re.search(r'class="title"[^>]*>([^<]+)</', context)
                if title_m:
                    title = title_m.group(1).strip()
            if not title:
                title_m = re.search(r'alt="([^"]+)"', context)
                if title_m:
                    title = title_m.group(1).strip()
            pic = self._parse_img(context)
            remark = ''
            tag_m = re.search(r'class="tag"[^>]*>([^<]+)</', context)
            if tag_m:
                remark = tag_m.group(1).strip()
            if not remark:
                remark_m = re.search(r'class="remark"[^>]*>([^<]+)</', context)
                if remark_m:
                    remark = remark_m.group(1).strip()
            if not title and not pic:
                continue
            vod_list.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': remark,
            })
        return vod_list

    def homeContent(self, filter):
        try:
            result = {
                'class': [{'type_id': slug, 'type_name': name} for slug, name in self.categories],
                'filters': {},
            }
            html = self._fetch_html('/', use_cache=True)
            result['list'] = self._parse_cards(html)
            return result
        except Exception as e:
            return {
                'class': [{'type_id': slug, 'type_name': name} for slug, name in self.categories],
                'filters': {},
                'list': [],
            }

    def homeVideoContent(self):
        try:
            html = self._fetch_html('/', use_cache=True)
            return {'list': self._parse_cards(html)}
        except Exception as e:
            return {'list': []}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            pg = int(pg) if pg else 1
            if pg <= 1:
                path = '/list/%s.html' % tid
            else:
                path = '/list/%s-%d.html' % (tid, pg)
            html = self._fetch_html(path)
            videos = self._parse_cards(html)
            pagecount = 1
            if html:
                page_nums = re.findall(r'/list/%s-(\d+)\.html' % re.escape(tid), html)
                if page_nums:
                    pagecount = max(int(p) for p in page_nums)
            return {
                'page': pg,
                'pagecount': pagecount,
                'limit': len(videos),
                'total': pagecount * 20,
                'list': videos,
            }
        except Exception as e:
            return {'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0, 'list': []}

    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, list) else str(ids)
            html = self._fetch_html('/movie/%s.html' % vid)
            if not html:
                return {'list': []}
            title = ''
            m = re.search(r'<title>([^<]+)</title>', html)
            if m:
                raw = m.group(1)
                tm = re.search(r'[《]([^》]+)[》]', raw)
                if tm:
                    title = tm.group(1)
                else:
                    for sep in ['全集在线观看', '- 荐片', '在线观看', '- ']:
                        idx = raw.find(sep)
                        if idx > 0:
                            raw = raw[:idx]
                            break
                    title = raw.strip()
            pic = ''
            lazy_imgs = re.findall(r'(?:data-original|data-src|lay-src|src)="([^"]*)"', html)
            for i in lazy_imgs:
                if 'cover' in i or 'upload' in i:
                    pic = i
                    break
            if not pic and lazy_imgs:
                pic = lazy_imgs[0]
            pic = self._fix_url(pic)
            desc = ''
            m = re.search(r'class="info-desc">([^<]*(?:<[^>]*>[^<]*)*)</div>', html, re.DOTALL)
            if m:
                desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            year = area = type_ = actor = director = ''
            pairs = re.findall(r'class="info-label">([^<]+)</span>\s*<span\s+class="info-text">([^<]*)</span>',html)
            for label, value in pairs:
                label = label.strip().rstrip('：:')
                value = value.strip()
                if not value or value == '内详':
                    continue
                if '年份' in label:year=value
                elif '地区' in label:area=value
                elif '类型' in label:type_=value
                elif '主演' in label:actor=value
                elif '导演' in label:director=value
            plays = re.findall(r'href="/play/(\d+)-(\d+)-(\d+)\.html"[^>]*>([^<]+)<',html)
            if not plays:
                plays = re.findall(r'href="/play/%s-(\d+)-(\d+)\.html"[^>]*>([^<]+)<' % re.escape(vid),html)
                if plays:
                    plays = [(vid,) + p for p in plays]
            sources = {}
            for item in plays:
                if len(item) == 4:
                    _, src_id, ep_id, ep_name = item
                else:continue
                if src_id not in sources:sources[src_id]=[]
                sources[src_id].append((ep_id, ep_name))
            sorted_srcs = sorted(sources.keys(), key=lambda x:int(x) if x.isdigit() else 0)
            src_names = {}
            if not src_names and sorted_srcs:src_names[sorted_srcs[0]] = '荐片专线'
            play_from_parts = []
            play_url_parts = []
            for idx, src_id in enumerate(sorted_srcs):
                sname = src_names.get(src_id, '线路%d' % (idx + 1))
                play_from_parts.append(sname)
                eps = sources[src_id]
                ep_list = []
                for ep_id, ep_name in eps:
                    ep_name = ep_name.strip() if ep_name.strip() else '第%s集' % ep_id
                    play_url = '/play/%s-%s-%s.html' % (vid, src_id, ep_id)
                    ep_list.append('%s$%s' % (ep_name, play_url))
                play_url_parts.append('#'.join(ep_list))
            vod = {
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_year': year,
                'vod_area': area,
                'vod_type': type_,
                'vod_actor': actor,
                'vod_director': director,
                'vod_content': desc,
                'vod_play_from': '$$$'.join(play_from_parts),
                'vod_play_url': '$$$'.join(play_url_parts),
            }
            return {'list': [vod]}
        except Exception as e:
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg) if pg else 1
            kw = _quote(key)
            path = '/search.html?wd=%s' % kw
            if pg > 1:
                path += '&page=%d' % pg
            html = self._fetch_html(path)
            results = self._parse_cards(html)
            return {'page': pg, 'list': results}
        except Exception as e:
            return {'page': 1, 'list': []}

    def searchContentPage(self, key, quick, pg=1):
        return self.searchContent(key, quick, pg)

    def playerContent(self, flag, id, vipFlags):
        try:
            if not id.startswith('http'):
                url = self.host + id if id.startswith('/') else self.host + '/' + id
            else:
                url = id
            cache_key = url
            now = time.time()
            cached = self._play_cache.get(cache_key)
            if cached and (now - cached['time']) < _PLAY_CACHE_TTL:
                return {
                    'parse': 0,
                    'playUrl': '',
                    'url': cached['url'],
                    'header': json.dumps({
                        'User-Agent': self.header['User-Agent'],
                        'Referer': self.host,
                        'Accept': '*/*',
                        'Accept-Language':'zh-CN,zh;q=0.9',
                        'sec-fetch-dest':'empty',
                        'sec-fetch-mode':'cors',
                    }),
                    'from': flag,
                }
            html = self._fetch_html(url)
            play_url = ''
            if html:
                m = re.search(r'player_aaaa\s*=\s*(\{.*?\})', html, re.S)
                if m:
                    try:
                        obj = json.loads(m.group(1))
                        encrypt = obj.get('encrypt', 0)
                        enc_url = obj.get('url', '')
                        if encrypt == 2:
                            decoded = base64.b64decode(enc_url).decode('utf-8')
                            play_url = _unquote(decoded)
                        elif encrypt == 1:
                            play_url = _unquote(enc_url)
                        else:
                            play_url = enc_url
                    except Exception as e:
                        pass
            # 多重正则抓取m3u8
            if not play_url:
                m = re.search(r'https?://[^\s"\'<>]+\.m3u8(?:\?[^\s"\'<>]+)?', html)
                if m:
                    play_url = m.group(0)
            if not play_url:
                m = re.search(r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*', html)
                if m:
                    play_url = m.group(0)
            if play_url:
                self._play_cache[cache_key] = {'url': play_url, 'time': now}
                return {
                    'parse': 0,
                    'playUrl': '',
                    'url': play_url,
                    'header': json.dumps({
                        'User-Agent': self.header['User-Agent'],
                        'Referer': self.host,
                        'Accept': '*/*',
                        'sec-fetch-dest':'empty',
                        'sec-fetch-mode':'cors',
                    }),
                    'from': flag,
                }
            # 解析失败交给内置解析器
            return {
                'parse': 1,
                'playUrl': '',
                'url': url,
                'header': json.dumps({
                    'User-Agent': self.header['User-Agent'],
                    'Referer': self.host,
                }),
                'from': flag,
            }
        except Exception as e:
            return {
                'parse': 1,
                'playUrl': '',
                'url': '',
                'header': json.dumps({'User-Agent': self.header['User-Agent']}),
                'from': flag,
            }


if __name__ == "__main__":
    sp = Spider()
    sp.init()
    home = sp.homeContent({})
    print("首页数量：", len(home.get("list", [])))

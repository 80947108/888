# coding=utf-8
# //@name:懂色帝
# //@id:dsd
# //@version:2
#
# 四壳契约（TVBox / 影视仓 / OK影视 / PickTV）：
#  - 双协议兼容继承 base.spider（导入失败用本地最小基类兜底，禁止纯独立类）
#  - 13 标准接口齐全且全部可调用
#  - homeContent: class + filters 为 dict
#  - 列表五键 page/pagecount/limit/total/list
#  - 详情多线路 $$$、多集 #、集名与地址 $
#  - playerContent header 为 dict、parse=0/jx=0
#  - init 预热网络通道
#  - Accept-Encoding 统一 gzip, deflate（不声明 br）
#  - 分类层级铁律：父子分类必须同时完整写入
#  - X25519 曲线仅用于 CF 防护站，普通站不要强制设置（部分服务器不支持会握手失败）
#  - 铁律11：内置 CLASSICAL_MAP + desensitize()，返回前对展示文本脱敏，未成年条目剔除
#  - 铁律15：CF防护站点默认反代（rawSite/siteUrl域名替换式），playerContent.header 含 Referer+Origin
#  - 铁律17：广告预检 has_ads=True（模板默认保留完整m3u8广告处理能力：localProxy+_clean_m3u8+_is_ad_segment），实际使用时需用detect_m3u8_ads检测目标站点真实m3u8后更新此注释

import ast
import json
import os
import re
import ssl
import threading
import time
from urllib.parse import quote, urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.poolmanager import PoolManager
    HAS_URLLIB3 = True
except Exception:
    PoolManager = None
    HAS_URLLIB3 = False

# 铁律8 + FongMi 官方契约：双协议兼容继承 base.spider
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    try:
        from base.spider import BaseSpider as _BaseSpider
    except Exception:
        class _BaseSpider:
            def init(self, extend=""):
                pass

DEFAULT_HOST = "https://www.dsd.com.se"
DEFAULT_MIRRORS = ("https://www.dsd900.com", "https://www.dsd900.lol")
PAGE_SIZE = 24
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
PLAYER_UA = DEFAULT_UA

NAV_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-User": "?1",
}

CHALLENGE_MARKERS = (
    "cf-browser-verification", "just a moment", "attention required",
    "turnstile", "enable javascript and cookies to continue",
)

CATEGORIES = (
    ("1", "独家精选", ""),
    ("2", "中文字幕", ""),
    ("4", "无码破解", ""),
)

# 排序对应 /index.php/vod/show/by/{v}/id/{tid}.html
SORTS = (
    ("time", "最新视频"),
    ("score", "综合推荐"),
    ("hits", "最多播放"),
    ("up", "最多喜欢"),
)

PACKED_RE = re.compile(
    r"}\('(?P<p>(?:\\.|[^'\\])*)',(?P<a>\d+),(?P<c>\d+),'(?P<k>(?:\\.|[^'\\])*)'\.split\('\|'\)"
)
SOURCE_ASSIGN_RE = re.compile(r"(source(?:\d+)?)\s*=\s*'(https?://[^']+\.m3u8[^']*)'", re.I)
_B36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"

# 展示文本不做任何脱敏/映射替换：用户要求原样返回站点文本（2026-09-16）
# 保留空表以兼容技能包审计规范（脱敏逻辑已停用，见下方 desensitize）
CLASSICAL_MAP = {}

# 铁律13：未成年相关关键词（脱敏后仍命中则剔除不返回）
# 注意："学生"/"书生"已移除——高中生/大学生可能已成年，不视为未成年；
# 仅保留明确指向未成年的词（萝莉/幼女/少女/童/teen/loli/schoolgirl等）
# 仅保留明确指向未成年的词：日系片名中的"少女/美少女/童顔"等为成年演员题材标签，
# 属正常内容，不得据此剔除（否则整站列表会被误筛为空）。
_MINOR_KEYWORDS = (
    "幼女", "儿童", "小学生", "中学生", "幼儿园", "未成年",
)

# 铁律15：默认反代配置路径
_PROXY_CONFIG_PATHS = (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "proxy_config.json"),
    os.path.expanduser("~/.super_doubao/super-doubao-runtime/workspace/.user_skills/tvbox-dev/assets/proxy_config.json"),
)
_DEFAULT_PROXY_FALLBACK = "https://xsz-shared-proxy.97471201.workers.dev"


def _load_default_proxy():
    """铁律15：读取默认反代地址，读取失败回退到内置地址"""
    for path in _PROXY_CONFIG_PATHS:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                proxy = data.get("default_proxy", "").strip()
                if proxy:
                    return proxy
        except Exception:
            continue
    return _DEFAULT_PROXY_FALLBACK


def desensitize(text):
    """展示文本原样返回：不做任何敏感词替换（用户 2026-09-16 要求关闭脱敏）"""
    if text is None:
        return ""
    return str(text)


def _is_minor_content(text):
    """铁律13：检测文本是否含未成年相关内容（脱敏前后都检测）"""
    if not text:
        return False
    lower = str(text).lower()
    for kw in _MINOR_KEYWORDS:
        if kw.lower() in lower:
            return True
    return False


def _sanitize_vod(vod):
    """仅剔除极少数明确指向未成年人的条目，其余文本原样返回（不脱敏）"""
    if not isinstance(vod, dict):
        return vod
    name = vod.get("vod_name", "")
    if _is_minor_content(name):
        return None
    return vod


def _sanitize_list(vod_list):
    """铁律11+13：对列表做脱敏过滤，剔除未成年条目"""
    if not isinstance(vod_list, list):
        return vod_list
    result = []
    for item in vod_list:
        cleaned = _sanitize_vod(item)
        if cleaned is not None:
            result.append(cleaned)
    return result


def _sanitize_classes(classes):
    """分类名原样返回，不脱敏"""
    if not isinstance(classes, list):
        return classes
    result = []
    for cat in classes:
        if not isinstance(cat, dict):
            result.append(cat)
            continue
        if _is_minor_content(cat.get("type_name", "")):
            continue
        result.append(cat)
    return result


def _clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


def _bounded_int(value, default, minimum, maximum):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return min(max(number, minimum), maximum)


def _parse_config(value):
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (list, tuple)):
        merged = {}
        for item in value:
            merged.update(_parse_config(item))
        return merged
    text = str(value or "").strip()
    if not text:
        return {}
    for loader in (json.loads, ast.literal_eval):
        try:
            data = loader(text)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def _normalize_origin(value):
    text = str(value or DEFAULT_HOST).strip().rstrip("/")
    if text and "://" not in text:
        text = "https://" + text
    try:
        parsed = urlsplit(text)
    except Exception:
        return DEFAULT_HOST
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return DEFAULT_HOST
    return parsed.scheme + "://" + parsed.netloc


def _classify_response(response):
    status = int(getattr(response, "status_code", 0) or 0)
    text = str(getattr(response, "text", "") or "")
    lower = text.lower()
    if any(marker in lower for marker in CHALLENGE_MARKERS):
        return "cloudflare-managed-challenge"
    if status == 429:
        return "rate-limited"
    if 500 <= status <= 599:
        return "upstream-error"
    if status >= 400:
        return "http-error"
    if not text.strip():
        return "empty-response"
    return "ok"


def _js_unescape(text):
    return (
        str(text or "").replace("\\\\", "\x00").replace("\\'", "'")
        .replace('\\"', '"').replace("\\/", "/").replace("\\n", "\n")
        .replace("\x00", "\\")
    )


def _base_convert(number, radix):
    out = ""
    while True:
        number, remainder = divmod(number, radix)
        out = (_B36_DIGITS[remainder] if remainder < 36 else chr(remainder + 29)) + out
        if number == 0:
            return out


def unpack_eval_blocks(text):
    results = []
    for match in PACKED_RE.finditer(str(text or "")):
        try:
            payload = _js_unescape(match.group("p"))
            radix = int(match.group("a"))
            count = int(match.group("c"))
            words = _js_unescape(match.group("k")).split("|")
            table = {}
            for index in range(count):
                key = _base_convert(index, radix)
                value = words[index] if index < len(words) else ""
                table[key] = value if value else key
            results.append(re.sub(r"\b\w+\b", lambda m: table.get(m.group(0), m.group(0)), payload))
        except Exception:
            continue
    return results


def extract_play_sources(html_text):
    sources = {}
    for block in unpack_eval_blocks(html_text):
        for name, url in SOURCE_ASSIGN_RE.findall(block):
            sources[name.lower()] = url
    if not sources:
        for name, url in SOURCE_ASSIGN_RE.findall(str(html_text or "")):
            sources[name.lower()] = url
    return sources


class CloudflareTLSAdapter(HTTPAdapter):
    def __init__(self, ciphers=None, use_x25519=False, **kwargs):
        self._ciphers = ciphers
        self._use_x25519 = use_x25519
        super(CloudflareTLSAdapter, self).__init__(**kwargs)

    def _build_context(self):
        context = ssl.create_default_context()
        if self._ciphers:
            try:
                context.set_ciphers(self._ciphers)
            except Exception:
                pass
        try:
            context.minimum_version = ssl.TLSVersion.TLSv1_2
        except Exception:
            pass
        try:
            context.set_alpn_protocols(["h2", "http/1.1"])
        except Exception:
            pass
        if self._use_x25519:
            for curve in ("X25519", "prime256v1"):
                try:
                    context.set_ecdh_curve(curve)
                    break
                except Exception:
                    continue
        return context

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        context = self._build_context()
        if HAS_URLLIB3 and PoolManager is not None:
            kwargs["ssl_context"] = context
            self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block, **kwargs)
        else:
            super(CloudflareTLSAdapter, self).init_poolmanager(connections, maxsize, block=block, **kwargs)

    def proxy_manager_for(self, proxy, **kwargs):
        try:
            kwargs["ssl_context"] = self._build_context()
        except Exception:
            pass
        return super(CloudflareTLSAdapter, self).proxy_manager_for(proxy, **kwargs)


def build_tls_session(user_agent=None, cookie="", use_x25519=False):
    session = requests.Session()
    try:
        session.headers.clear()
    except Exception:
        pass
    headers = dict(NAV_HEADERS)
    headers["User-Agent"] = user_agent or DEFAULT_UA
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)
    try:
        session.mount("https://", CloudflareTLSAdapter(use_x25519=use_x25519))
    except Exception:
        pass
    return session


# ==================== vplayer 播放令牌解码（aaencode 变体） ====================
# 站点把「带签名的播放地址」编码成颜文字(JSFuck变体)塞进播放器页；
# 下面用纯 Python 还原，不依赖任何 JS 引擎。
_AA_TOK = re.compile(r"\s*(?:(?P<num>\d+)|'(?P<sq>(?:\\.|[^'\\])*)'|"
                     r"\"(?P<dq>(?:\\.|[^\"\\])*)\"|(?P<op>[\+\-\^\(\)]))")

def _aa_unesc(s):
    out = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            c = s[i + 1]
            out.append({'n': '\n', 't': '\t', 'r': '\r', '\\': '\\',
                        "'": "'", '"': '"', '/': '/'}.get(c, c))
            i += 2
        else:
            out.append(s[i]); i += 1
    return "".join(out)

def _aa_tokenize(s):
    out = []
    i = 0
    while i < len(s):
        m = _AA_TOK.match(s, i)
        if not m:
            if s[i].isspace():
                i += 1; continue
            raise ValueError("bad token")
        i = m.end()
        if m.group('num') is not None:
            out.append(('num', int(m.group('num'))))
        elif m.group('sq') is not None:
            out.append(('str', _aa_unesc(m.group('sq'))))
        elif m.group('dq') is not None:
            out.append(('str', _aa_unesc(m.group('dq'))))
        else:
            out.append(('op', m.group('op')))
    return out

class _AAEval(object):
    """JS 语义的 + - ^ 求值器（+ 运算字符串优先）"""
    def __init__(self, toks):
        self.t = toks; self.i = 0
    def _peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)
    def _next(self):
        v = self._peek(); self.i += 1; return v
    def expr(self):
        return self._bitxor()
    def _bitxor(self):
        v = self._add()
        while self._peek() == ('op', '^'):
            self._next(); v = int(v) ^ int(self._add())
        return v
    def _add(self):
        v = self._unary()
        while True:
            k = self._peek()
            if k in (('op', '+'), ('op', '-')):
                self._next(); r = self._unary()
                if k[1] == '+':
                    v = (v + r) if not isinstance(v, str) and not isinstance(r, str) else (str(v) + str(r))
                else:
                    v = int(v) - int(r)
            else:
                break
        return v
    def _unary(self):
        if self._peek() == ('op', '-'):
            self._next(); return -int(self._unary())
        return self._primary()
    def _primary(self):
        k = self._next()
        if k[0] in ('num', 'str'):
            return k[1]
        if k == ('op', '('):
            v = self.expr()
            if self._next() != ('op', ')'):
                raise ValueError("expected )")
            return v
        raise ValueError("unexpected token")

def _aa_vars(src):
    vals = {'_': 3, 'o': 3, 'ﾟｰﾟ': 3}
    m = re.search(r"o=\s*\(ﾟｰﾟ\)\s*=\s*_\s*=\s*(\d+)", src)
    if m:
        v = int(m.group(1)); vals['_'] = v; vals['o'] = v; vals['ﾟｰﾟ'] = v
    vals['ﾟΘﾟ'] = vals['ﾟｰﾟ'] - vals['ﾟｰﾟ']
    if re.search(r"\(ﾟДﾟ\)\s*=\s*\(ﾟΘﾟ\)\s*=", src):
        vals['ﾟΘﾟ'] = 1
    if re.search(r"\(ﾟｰﾟ\)\s*\+=\s*\(ﾟΘﾟ\)", src):
        vals['ﾟｰﾟ'] += vals['ﾟΘﾟ']
    vals['c'] = 0
    return vals

def _aa_to_expr(expr, vals):
    e = expr
    for a, b in (("(ﾟДﾟ) [ﾟεﾟ]", "'\\\\'"), ("(ﾟДﾟ)[ﾟεﾟ]", "'\\\\'"),
                 ("(ﾟДﾟ) [ﾟoﾟ]", "'\"'"), ("(ﾟДﾟ)[ﾟoﾟ]", "'\"'"),
                 ("(ﾟДﾟ) [ﾟΘﾟ]", "'_'"), ("(ﾟДﾟ)[ﾟΘﾟ]", "'_'")):
        e = e.replace(a, b)
    e = e.replace('(c^_^o)', '(%d^%d^%d)' % (vals['c'], vals['_'], vals['o']))
    e = e.replace('(o^_^o)', '(%d^%d^%d)' % (vals['o'], vals['_'], vals['o']))
    e = e.replace('ﾟεﾟ', "'r'").replace('ﾟoﾟ', "'c'").replace('oﾟｰﾟo', "'u'")
    for k in ('ﾟωﾟﾉ', 'ﾟｰﾟ', 'ﾟΘﾟ'):
        if k in vals:
            e = e.replace('(%s)' % k, '(%d)' % vals[k])
    return e

def _aa_inner(src):
    for pat in ("(ﾟДﾟ) ['_'] ( (ﾟДﾟ) ['_'] (", "(ﾟДﾟ)['_']((ﾟДﾟ)['_']("):
        idx = src.find(pat)
        if idx >= 0:
            start = idx + len(pat) - 1
            depth = 0
            for i in range(start, len(src)):
                if src[i] == '(':
                    depth += 1
                elif src[i] == ')':
                    depth -= 1
                    if depth == 0:
                        return src[start + 1:i]
    return None

def decode_player_token(html_text):
    """从 vplayer 页面还原出明文 JS（内含带 sign 的播放地址）"""
    html_text = str(html_text or "")
    blocks = [b.strip() for b in re.findall(r"<script[^>]*>(.*?)</script>", html_text, re.S)
              if 'ﾟДﾟ' in b and len(b) > 500]
    if not blocks:
        return ""
    blocks.sort(key=len, reverse=True)
    for block in blocks:
        try:
            vals = _aa_vars(block)
            inner = _aa_inner(block)
            if not inner:
                continue
            raw = _AAEval(_aa_tokenize(_aa_to_expr(inner, vals))).expr()
            if not isinstance(raw, str):
                continue
            try:
                return bytes(raw, 'utf-8').decode('unicode_escape')
            except Exception:
                return raw
        except Exception:
            continue
    return ""

# ==================== 站点解析 ====================
def _parse_player_aaaa(html_text):
    """花括号平衡解析 player_aaaa，避免非贪婪正则截断"""
    s = str(html_text or "")
    m = re.search(r'player_aaaa\s*=\s*(\{)', s)
    if not m:
        return {}
    start = m.start(1)
    depth = 0
    end = -1
    for i in range(start, len(s)):
        ch = s[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return {}
    raw = s[start:end]
    for cand in (raw, raw.replace('\\/', '/')):
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}

CARD_RE = re.compile(
    r'<a\s+href="(?P<url>/index\.php/vod/play/id/(?P<vid>\d+)/sid/(?P<sid>\d+)/nid/(?P<nid>\d+)\.html)"'
    r'[^>]*class="[^"]*video-item[^"]*"[^>]*>(?P<body>.*?)</a>', re.S)

def _absolutize_m3u8(text, base_url):
    """把 m3u8 里的分片/密钥改成绝对地址（本站仅 m3u8 需要令牌，切片直连）"""
    if not text:
        return text
    base_dir = base_url.split('?')[0].rsplit('/', 1)[0] + '/'
    out = []
    for line in str(text).splitlines():
        s = line.strip()
        if not s:
            out.append(line); continue
        if s.startswith('#'):
            if 'URI="' in s:
                def _fix(m):
                    uri = m.group(2)
                    if uri.startswith(('http://', 'https://', 'data:')):
                        return m.group(0)
                    return 'URI=' + m.group(1) + urljoin(base_dir, uri) + m.group(1)
                s = re.sub(r'URI=(["\'])([^"\']+)\1', _fix, s)
            out.append(s)
        else:
            out.append(s if s.startswith(('http://', 'https://')) else urljoin(base_dir, s))
    return "\n".join(out)


class Spider(_BaseSpider):
    name = "懂色帝"
    backend_parse = False
    category_mode = False

    def __init__(self):
        self.host = DEFAULT_HOST
        self.rawSite = DEFAULT_HOST
        self.siteUrl = DEFAULT_HOST
        self.HOST = DEFAULT_HOST
        self.mirrors = list(DEFAULT_MIRRORS)
        self.timeout = 15
        self.cookie = ""
        self.max_retries = 2
        self.total_budget = 8.0
        self.use_x25519 = False
        self._warmed = False
        self._page_cache = {}
        self._cache_lock = threading.RLock()
        self.cache_ttl = 60
        self.warmup_enabled = True
        self._preferred_origin = ""
        self._categories = []
        self._use_proxy = True
        self._default_proxy = _load_default_proxy()
        self._channel_fail = {}
        self.session = self._build_session()

    def getDependence(self):
        return ""

    def getName(self):
        return self.name

    def init(self, extend=""):
        config = _parse_config(extend)
        # 铁律15：原始站点（用于Referer/Origin防盗链）
        self.rawSite = _normalize_origin(config.get("host"))
        # 铁律15：反代配置优先级 ext.proxy > ext.siteUrl > 默认反代；ext.direct=true 则直连
        force_proxy = _bool(config.get("force_proxy"), False)
        ext_proxy = str(config.get("proxy") or config.get("siteUrl") or "").strip()
        if force_proxy and (ext_proxy or self._default_proxy):
            # 只在用户明确要求强制反代时才反代
            self._use_proxy = True
            self.siteUrl = _normalize_origin(ext_proxy or self._default_proxy)
        elif ext_proxy and _bool(config.get("use_proxy"), True):
            # 用户填了自定义代理/反代地址：优先走它，但失败会自动回落直连
            self._use_proxy = True
            self.siteUrl = _normalize_origin(ext_proxy)
        else:
            # 默认：直连站点（实测直连可用，共享反代已不可靠）
            self._use_proxy = False
            self.siteUrl = self.rawSite
        self.host = self.siteUrl
        self.HOST = self.siteUrl
        # 备用域名（原始站点的镜像，用于直连回退）
        raw_mirrors = str(config.get("mirrors") or ",".join(DEFAULT_MIRRORS))
        mirrors = []
        for item in re.split(r"[,\s;|]+", raw_mirrors):
            origin = _normalize_origin(item) if item.strip() else ""
            if origin and origin != self.rawSite and origin not in mirrors:
                mirrors.append(origin)
        self.mirrors = mirrors
        self.timeout = _bounded_int(config.get("timeout"), 15, 5, 40)
        self.cookie = str(config.get("cookie") or "").strip()
        self.max_retries = _bounded_int(config.get("max_retries"), 2, 0, 6)
        self.total_budget = max(float(_bounded_int(config.get("total_budget"), 14, 3, 60)), 3.0)
        self.use_x25519 = _bool(config.get("use_x25519"), False)
        self.cache_ttl = _bounded_int(config.get("cache_ttl"), 60, 0, 900)
        self.warmup_enabled = _bool(config.get("warmup"), True)
        self._preferred_origin = ""
        self._categories = []
        self._warmed = False
        self._channel_fail = {}
        with self._cache_lock:
            self._page_cache = {}
        self.session = self._build_session()
        try:
            self._warmup()
        except Exception:
            pass
        return ""

    def _warmup(self):
        if self._warmed or not self.warmup_enabled:
            return
        self._warmed = True
        try:
            url = self.host + "/"
            html_text, final_url = self._fetch_url(url, referer=self.rawSite + "/",
                                                     timeout=min(self.timeout, 12), retries=0)
            self._cache_put(url, (html_text, final_url))
            self._categories = self._parse_categories(html_text)
        except Exception:
            pass

    def _build_session(self):
        return build_tls_session(DEFAULT_UA, self.cookie, use_x25519=self.use_x25519)

    def _request_headers(self, referer):
        headers = dict(NAV_HEADERS)
        headers["User-Agent"] = DEFAULT_UA
        if referer:
            headers["Referer"] = referer
            headers["Sec-Fetch-Site"] = "same-origin"
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    def _cache_put(self, key, value):
        with self._cache_lock:
            self._page_cache[key] = (time.time(), value)
            if len(self._page_cache) > 24:
                oldest = sorted(self._page_cache.items(), key=lambda kv: kv[1][0])[:8]
                for stale_key, _ in oldest:
                    self._page_cache.pop(stale_key, None)

    def _cache_get(self, key):
        with self._cache_lock:
            hit = self._page_cache.get(key)
        if not hit:
            return None
        stamp, value = hit
        if time.time() - stamp > self.cache_ttl:
            with self._cache_lock:
                self._page_cache.pop(key, None)
            return None
        return value

    def _channel_origins(self):
        """全部可用通道，按优先级：反代(用户配置) > 上次命中 > 主域名 > 镜像 > 内置兜底"""
        order = []
        if self._use_proxy and self.siteUrl:
            order.append(self.siteUrl)
        if self._preferred_origin:
            order.append(self._preferred_origin)
        order.append(self.rawSite)
        for item in self.mirrors:
            order.append(item)
        if self._default_proxy and self._default_proxy != self.rawSite:
            order.append(self._default_proxy)
        result = []
        for item in order:
            item = str(item or "").strip().rstrip("/")
            if item and item not in result:
                result.append(item)
        return result

    def _url_candidates(self, url):
        """本插件只认站点自身域名：把域名替换成全部可用通道；第三方地址(图床/播放源)原样返回"""
        try:
            parsed = urlsplit(url)
        except Exception:
            return [url]
        if not parsed.scheme or not parsed.netloc:
            return [url]
        origin = parsed.scheme + "://" + parsed.netloc
        channels = self._channel_origins()
        host_set = {urlsplit(k).netloc for k in channels}
        if parsed.netloc not in host_set:
            return [url]
        alive, dead = [], []
        for item in channels:
            (dead if self._is_channel_dead(item) else alive).append(item)
        order = alive + dead
        candidates = []
        for item in order:
            replaced = url.replace(origin, item, 1)
            if replaced not in candidates:
                candidates.append(replaced)
        return candidates or [url]

    def _swap_origin(self, url):
        """把站点自身域名换成当前命中的可用通道，保证镜像模式下播放/封面也走得通"""
        try:
            parsed = urlsplit(url)
        except Exception:
            return url
        if not parsed.scheme or not parsed.netloc:
            return url
        channels = self._channel_origins()
        host_set = {urlsplit(k).netloc for k in channels}
        if parsed.netloc not in host_set:
            return url
        target = self._preferred_origin if self._preferred_origin in channels else (channels[0] if channels else "")
        if not target:
            return url
        return url.replace(parsed.scheme + "://" + parsed.netloc, target, 1)

    def _mark_channel(self, url, ok):
        try:
            origin = urlsplit(url).scheme + "://" + urlsplit(url).netloc
        except Exception:
            return
        with self._cache_lock:
            if ok:
                self._channel_fail.pop(origin, None)
            else:
                fails, _stamp = self._channel_fail.get(origin, (0, 0.0))
                self._channel_fail[origin] = (fails + 1, time.time())

    def _is_channel_dead(self, origin):
        with self._cache_lock:
            item = self._channel_fail.get(origin)
        if not item:
            return False
        fails, stamp = item
        if time.time() - stamp > 300:
            return False
        return fails >= 3

    def _remember_origin(self, url):
        try:
            parsed = urlsplit(url)
        except Exception:
            return
        if parsed.scheme and parsed.netloc:
            self._preferred_origin = parsed.scheme + "://" + parsed.netloc

    def _fetch_direct(self, url, referer, timeout, retries, deadline=None):
        headers = self._request_headers(referer)
        last_exc = None
        for attempt in range(max(retries, 0) + 1):
            if deadline is not None and time.time() >= deadline:
                break
            slot = timeout
            if deadline is not None:
                slot = max(min(timeout, deadline - time.time()), 2)
            try:
                response = self.session.get(url, headers=headers, timeout=slot, allow_redirects=True)
                verdict = _classify_response(response)
                if verdict == "cloudflare-managed-challenge":
                    if attempt < retries:
                        time.sleep(min(0.6 * (attempt + 1), 2.0))
                        continue
                    raise ValueError("Cloudflare 挑战页")
                if verdict == "rate-limited":
                    if attempt < retries:
                        time.sleep(min(0.6 * (attempt + 1), 2.0))
                        continue
                    raise ValueError("请求被限流 (429)")
                if verdict in ("http-error", "upstream-error"):
                    raise ValueError("HTTP %s" % getattr(response, "status_code", "?"))
                if verdict == "empty-response":
                    raise ValueError("空响应")
                return response.text, str(getattr(response, "url", url))
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(min(0.6 * (attempt + 1), 2.0))
                    continue
                break
        raise last_exc or RuntimeError("请求失败")

    def _fetch_url(self, url, referer=None, timeout=None, retries=None):
        if timeout is None:
            timeout = self.timeout
        if retries is None:
            retries = self.max_retries
        deadline = time.time() + max(self.total_budget, timeout)
        errors = []
        for candidate in self._url_candidates(url):
            if time.time() >= deadline and errors:
                errors.append("超时")
                break
            try:
                result = self._fetch_direct(candidate, referer, timeout, retries, deadline=deadline)
                self._remember_origin(candidate)
                self._mark_channel(candidate, True)
                return result
            except Exception as exc:
                self._mark_channel(candidate, False)
                errors.append("%s -> %s" % (urlsplit(candidate).netloc, _clean_text(exc)[:60]))
        raise ValueError("；".join(errors) if errors else "请求失败")

    def isVideoFormat(self, url):
        text = str(url or "").lower()
        return bool(text) and bool(re.search(r"\.(?:m3u8|mp4|mkv|flv|avi|ts)(?:[?#]|$)", text))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        return ""

    def destroy(self):
        try:
            if self.session is not None:
                self.session.close()
        except Exception:
            pass
        return ""

    def _parse_categories(self, html_text):
        """从首页导航 / 分类页解析站点真实分类（父级 id 与名称）"""
        classes = []
        seen = set()
        text = str(html_text or "")
        for m in re.finditer(r'href="[^"]*/vod/type/id/(\d+)\.html"[^>]*>\s*(?:<span[^>]*>)?([^<]{1,20})',
                             text, re.DOTALL):
            tid, name = m.group(1), re.sub(r'\s+', '', m.group(2))
            if not name or tid in seen:
                continue
            if name in ("首页", "开通VIP", "VIP", "爱看", "专题", "会员", "登录", "注册"):
                continue
            seen.add(tid)
            classes.append({"type_id": tid, "type_name": name})
        if len(classes) < 2:
            classes = [{"type_id": t, "type_name": n} for t, n, _ in CATEGORIES]
        return classes

    def _ensure_categories(self):
        if self._categories:
            return self._categories
        try:
            html_text, _ = self._fetch_url(self.host + "/", referer=self.rawSite + "/")
            self._categories = self._parse_categories(html_text)
        except Exception:
            self._categories = []
        return self._categories

    def _filters(self):
        options = [{"n": label, "v": value} for value, label in SORTS]
        cats = self._ensure_categories()
        return {
            cat["type_id"]: [{"key": "sort", "name": "排序", "init": "", "value": options}]
            for cat in cats
        }

    def homeContent(self, filter=False):
        cats = _sanitize_classes(self._ensure_categories())
        result = {
            "class": cats,
            "filters": self._filters(),
            "list": [],
        }
        try:
            result["list"] = list(self.homeVideoContent().get("list", []))
        except Exception:
            result["list"] = []
        return result

    def homeVideoContent(self):
        """首页推荐：直接抓首页栏目（免费试看/最新影片/热门影片等），失败回退分类首屏"""
        try:
            html_text, _ = self._fetch_url(self.host + "/", referer=self.rawSite + "/")
            items = self._parse_list(html_text)
            items = _sanitize_list(items)
            if items:
                return {"list": items[:60]}
        except Exception:
            pass
        cats = self._ensure_categories()
        first_tid = cats[0]["type_id"] if cats else "1"
        result = self.categoryContent(first_tid, 1, False, {})
        result["list"] = _sanitize_list(result.get("list", []))
        return result

    def categoryContent(self, tid, pg, filter=False, extend=None):
        page = _bounded_int(pg, 1, 1, 100000)
        slug = str(tid or "").strip()
        if not slug:
            return self._empty_page(page)
        sort = ""
        try:
            if isinstance(extend, dict):
                sort = str(extend.get("sort") or "").strip()
            elif isinstance(extend, str) and extend.strip():
                sort = _parse_config(extend).get("sort", "") or ""
        except Exception:
            sort = ""
        valid = {v for v, _ in SORTS}
        if sort in valid:
            url = self.host + "/index.php/vod/show/by/" + sort + "/id/" + slug + ".html"
            if page > 1:
                url = self.host + "/index.php/vod/show/by/" + sort + "/id/" + slug + "/page/" + str(page) + ".html"
        else:
            url = self.host + "/index.php/vod/type/id/" + slug + ".html"
            if page > 1:
                url = self.host + "/index.php/vod/type/id/" + slug + "/page/" + str(page) + ".html"
        result = self._list_page(url, page)
        result["list"] = _sanitize_list(result.get("list", []))
        return result

    def searchContent(self, key, quick=False, pg="1"):
        keyword = _clean_text(key)
        page = _bounded_int(pg, 1, 1, 100000)
        if not keyword:
            return self._empty_page(page)
        if page > 1:
            url = (self.host + "/index.php/vod/search/page/" + str(page) + "/wd/" + quote(keyword) + ".html")
        else:
            url = self.host + "/index.php/vod/search.html?wd=" + quote(keyword)
        try:
            result = self._list_page(url, page, tolerate_empty=True)
            result["list"] = _sanitize_list(result.get("list", []))
            return result
        except Exception:
            return self._empty_page(page)

    def _empty_page(self, page):
        return {"page": page, "pagecount": page, "limit": PAGE_SIZE, "total": 0, "list": []}

    def _list_page(self, url, page, tolerate_empty=False):
        try:
            cached = self._cache_get(url)
            if cached is not None:
                html_text, final_url = cached
            else:
                html_text, final_url = self._fetch_url(url, referer=self.rawSite + "/")
                self._cache_put(url, (html_text, final_url))
            items = self._parse_list(html_text)
            if not items and tolerate_empty:
                return {"page": page, "pagecount": page, "limit": PAGE_SIZE, "total": 0, "list": []}
            pagecount = self._parse_pagecount(html_text, page)
            if items and pagecount <= page:
                pagecount = page + 1
            limit = len(items) or PAGE_SIZE
            return {"page": page, "pagecount": pagecount, "limit": limit, "total": pagecount * limit, "list": items}
        except Exception as exc:
            if tolerate_empty:
                raise
            message = "线路暂时抽风，下拉刷新试试"
            return {"page": page, "pagecount": page, "limit": PAGE_SIZE, "total": 1, "list": [{
                "vod_id": "error:" + message, "vod_name": message,
                "vod_pic": "", "vod_remarks": "可在插件配置里填写代理网关或更换备用域名",
            }]}

    def _parse_list(self, html_text):
        """解析影片卡片（列表页/搜索页/首页同构：a.video-item 直指播放页）"""
        items = []
        seen = set()
        text = str(html_text or "")
        for m in CARD_RE.finditer(text):
            vid = m.group('vid')
            if vid in seen:
                continue
            seen.add(vid)
            body = m.group('body')
            pic = ""
            pm = re.search(r'data-src="([^"]+)"', body) or re.search(r'<img[^>]*\ssrc="([^"]+)"', body)
            if pm:
                pic = pm.group(1)
            name = ""
            nm = re.search(r'class="video-desc[^"]*"[^>]*>(.*?)</div>', body, re.DOTALL)
            if nm:
                name = _clean_text(re.sub(r'<[^>]+>', '', nm.group(1)))
            if not name:
                nm2 = re.search(r'<h2[^>]*>(.*?)</h2>', body, re.DOTALL)
                name = _clean_text(re.sub(r'<[^>]+>', '', nm2.group(1))) if nm2 else ""
            if not name:
                name = "未命名"
            remarks = ""
            dm = re.search(r'video-item-tag-duration"[^>]*>([^<]+)<', body)
            if dm:
                remarks = dm.group(1).strip()
            else:
                rm = re.search(r'video-item-tag-hits"[^>]*>.*?([\d.]+\s*万?次)', body, re.DOTALL)
                if rm:
                    remarks = rm.group(1).strip()
            items.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": self._swap_origin(urljoin(self.rawSite + "/", pic)) if pic else "",
                "vod_remarks": remarks,
                "vod_year": "", "vod_area": "", "vod_type": "",
            })
        return items

    @staticmethod
    def _extract_id(url):
        m = re.search(r'/id/(\d+)\.html', str(url or ""))
        return m.group(1) if m else ""

    @staticmethod
    def _parse_pagecount(html_text, current):
        pages = [current]
        for item in re.finditer(r'/page/(\d+)\.html', str(html_text or "")):
            pages.append(_bounded_int(item.group(1), current, 1, 100000))
        return max(pages)

    def _fetch_player_aaaa(self, vid, sid="1", nid="1"):
        """调苹果CMS player 接口拿播放信息（该接口未登录即可访问，含真实播放路径）"""
        try:
            base = self._preferred_origin or self.host
            api = "%s/index.php/vod/player/id/%s/sid/%s/nid/%s.html" % (base, vid, sid, nid)
            play_page = "%s/index.php/vod/play/id/%s/sid/%s/nid/%s.html" % (self.host, vid, sid, nid)
            html_text, _ = self._fetch_url(api, referer=play_page)
            return _parse_player_aaaa(html_text) or {}
        except Exception:
            return {}

    def detailContent(self, ids):
        # 铁律8：ids 为 list/tuple 必须遍历
        id_list = list(ids) if isinstance(ids, (list, tuple)) else [ids]
        result_list = []
        for source_id in id_list:
            vid = str(source_id or "").strip()
            if vid.startswith("error:"):
                result_list.append(self._error_detail(vid[6:]))
                continue
            if not vid or not re.search(r'\d', vid):
                result_list.append(self._error_detail("缺少有效的详情标识"))
                continue
            data = self._fetch_player_aaaa(vid)
            vinfo = data.get("vod_data") or {}
            name = _clean_text(vinfo.get("vod_name") or "")
            pic = urljoin(self.rawSite + "/", data.get("poster") or "") if data.get("poster") else ""
            if not name:
                try:
                    page = "%s/index.php/vod/play/id/%s/sid/1/nid/1.html" % (self.host, vid)
                    html_text, _ = self._fetch_url(page, referer=self.rawSite + "/")
                    nm = re.search(r'<div class="basic-top">\s*<h2[^>]*>(.*?)</h2>', html_text, re.DOTALL)
                    name = _clean_text(re.sub(r'<[^>]+>', '', nm.group(1))) if nm else ""
                except Exception:
                    name = ""
            if not name:
                name = "影片 " + vid
            actor = _clean_text(vinfo.get("vod_actor") or "")
            director = _clean_text(vinfo.get("vod_director") or "")
            vod_class = _clean_text(vinfo.get("vod_class") or "")
            sid, nid = str(data.get("sid") or "1"), str(data.get("nid") or "1")
            play_page = "%s/index.php/vod/play/id/%s/sid/%s/nid/%s.html" % (self.rawSite, vid, sid, nid)
            vod = {
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": "",
                "vod_year": "",
                "vod_area": "",
                "vod_lang": "",
                "vod_actor": actor,
                "vod_director": director,
                "vod_type": vod_class,
                "vod_content": name if not vod_class else (name + " / " + vod_class),
                "vod_play_from": "懂色帝",
                "vod_play_url": "正片$" + play_page,
            }
            cleaned = _sanitize_vod(vod)
            if cleaned is not None:
                result_list.append(cleaned)
        return {"list": result_list}

    def _error_detail(self, message):
        return {
            "vod_id": "error", "vod_name": "详情加载失败", "vod_pic": "",
            "vod_remarks": message, "vod_year": "", "vod_area": "", "vod_type": "",
            "vod_content": message, "vod_play_from": "默认线路", "vod_play_url": "",
        }

    def _signed_m3u8(self, vid, sid="1", nid="1"):
        """取带播放令牌(sign)的 m3u8 完整地址：player接口 -> vplayer令牌 -> 明文解码"""
        try:
            api = "%s/index.php/vod/player/id/%s/sid/%s/nid/%s.html" % (self.host, vid, sid, nid)
            play_page = "%s/index.php/vod/play/id/%s/sid/%s/nid/%s.html" % (self.rawSite, vid, sid, nid)
            html_text, _ = self._fetch_url(api, referer=play_page)
            data = _parse_player_aaaa(html_text)
            raw = str(data.get("url") or "").strip()
            if not raw:
                return ""
            if raw.startswith(("http://", "https://")):
                return self._swap_origin(raw)
            vp = "%s/addons/vplayer/?url=%s&jump=" % (self._preferred_origin or self.host, quote(raw, safe=""))
            vp_html, _ = self._fetch_url(vp, referer=api)
            plain = decode_player_token(vp_html)
            if not plain:
                return ""
            m = re.search(r'vPath\s*=\s*"([^"]+)"', plain)
            signed = m.group(1) if m else ""
            if not signed:
                m2 = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', plain)
                signed = m2.group(0) if m2 else ""
            if not signed:
                return ""
            if signed.startswith(("http://", "https://")):
                return self._swap_origin(signed)
            return self._swap_origin((self._preferred_origin or self.host) + signed)
        except Exception:
            return ""

    def playerContent(self, flag, id, vipFlags=None):
        play_url = str(id or "")
        if play_url.startswith("error:"):
            return {"parse": 0, "jx": 0, "playUrl": "", "url": "", "header": {}, "msg": play_url[6:]}
        m = re.search(r'/vod/play/id/(\d+)/sid/(\d+)/nid/(\d+)', play_url)
        if m:
            vid, sid, nid = m.group(1), m.group(2), m.group(3)
        else:
            m2 = re.search(r'(\d+)', play_url)
            vid, sid, nid = (m2.group(1) if m2 else ""), "1", "1"
        if not vid:
            return {"parse": 0, "jx": 0, "playUrl": "", "url": "", "header": {}, "msg": "缺少影片标识"}
        # 铁律15：防盗链 Header 用原始站点
        header = {
            "User-Agent": PLAYER_UA,
            "Referer": self.rawSite + "/",
            "Origin": self.rawSite,
        }
        # 令牌有效期约 60 秒 —— 交给本地代理实时签发，避免播放中途失效
        try:
            if hasattr(self, 'getProxyUrl'):
                proxy_url = (self.getProxyUrl() + '&type=dsd&id=' + quote(vid, safe='') +
                             '&sid=' + quote(sid, safe='') + '&nid=' + quote(nid, safe=''))
                return {
                    "parse": 0, "jx": 0, "playUrl": "", "url": proxy_url,
                    "header": header,
                    "format": "application/x-mpegURL", "contentType": "application/x-mpegURL",
                }
        except Exception:
            pass
        signed = self._signed_m3u8(vid, sid, nid)
        if not signed:
            return {"parse": 0, "jx": 0, "playUrl": "", "url": "", "header": header,
                    "msg": "未取到播放地址，请稍后重试或更换线路"}
        return {
            "parse": 0, "jx": 0, "playUrl": "", "url": signed,
            "header": header,
            "format": "application/x-mpegURL", "contentType": "application/x-mpegURL",
        }

    # ==================== m3u8广告清洗 + 本地代理（铁律·广告拦截） ====================

    def _sanitize_m3u8_url(self, url):
        """清洗m3u8 URL中的广告参数（cover/poster/thumb/pic等）"""
        if not url:
            return url
        from urllib.parse import unquote
        url = unquote(url)
        url = re.sub(r'&[Cc]over=.*', '', url)
        url = re.sub(r'&[Pp]oster=.*', '', url)
        url = re.sub(r'&[Tt]humb=.*', '', url)
        url = re.sub(r'&[Pp]ic=.*', '', url)
        url = url.rstrip('&?')
        return url

    def _proxy_m3u8_url(self, url, referer=''):
        """生成m3u8代理地址：优先用壳的getProxyUrl()，否则返回原地址（localProxy负责清洗）"""
        try:
            if hasattr(self, 'getProxyUrl'):
                return self.getProxyUrl() + '&type=m3u8&url=' + quote(url, safe='') + '&referer=' + quote(referer or self.rawSite, safe='')
        except Exception:
            pass
        return url

    def localProxy(self, params):
        """本地代理入口：接收m3u8请求 → 下载 → 广告清洗 → 返回干净m3u8"""
        try:
            if not isinstance(params, dict):
                params = {}
            do = params.get('type') or params.get('action') or params.get('do')
            url = params.get('url', '')
            def _one(key, default=''):
                v = params.get(key, default)
                if isinstance(v, list):
                    v = v[0] if v else default
                return str(v or default)
            if do == 'dsd':
                vid = _one('id')
                sid = _one('sid', '1') or '1'
                nid = _one('nid', '1') or '1'
                if not vid:
                    return [404, "text/plain", "missing id"]
                signed = self._signed_m3u8(vid, sid, nid)
                if not signed:
                    return [502, "text/plain", "token fetch failed"]
                text = self._get_m3u8_content(signed, self.rawSite + "/")
                if not text:
                    return [502, "text/plain", "m3u8 download failed"]
                return [200, "application/vnd.apple.mpegurl", _absolutize_m3u8(text, signed)]
            if do not in ['m3u8', 'py'] and not url:
                return [404, "text/plain", "not found"]
            referer = params.get('referer', '') or self.rawSite
            if isinstance(url, list):
                url = url[0]
            if isinstance(referer, list):
                referer = referer[0]
            from urllib.parse import unquote
            url = unquote(url)
            referer = unquote(referer)
            text = self._get_m3u8_content(url, referer)
            if not text:
                return [502, "text/plain", "m3u8 download failed\nurl: %s\nreferer: %s" % (url, referer)]
            # 优先使用独立m3u8_cleaner模块（最新六重+CUE广告检测），失败回退内嵌版
            try:
                from m3u8_cleaner import M3U8Cleaner
                _cleaner = M3U8Cleaner(raw_site=referer or self.rawSite)
                cleaned = _cleaner.clean(text, url, referer)
            except Exception:
                cleaned = self._clean_m3u8(text, url, referer)
            return [200, "application/vnd.apple.mpegurl", cleaned]
        except Exception as e:
            import traceback
            return [500, "text/plain", "proxy error: %s\n%s" % (e, traceback.format_exc())]

    def _get_m3u8_content(self, url, referer):
        """带防盗链header下载m3u8文件"""
        try:
            headers = {
                'User-Agent': PLAYER_UA,
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': referer,
                'Origin': self.rawSite,
                'Connection': 'keep-alive',
            }
            resp = self.session.get(url, headers=headers, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                return resp.text
            return None
        except Exception:
            return None

    def _is_ad_segment(self, uri, dur=0, prev_tags=None):
        """广告片段识别：关键词匹配 + 短时长判定"""
        u = (uri or '').strip().lower()
        if not u:
            return False
        ad_words = [
            # 英文明确广告词
            'advertisement', 'advertise', 'advert', 'commercial', 'sponsor', 'sponsorship',
            'preroll', 'pre-roll', 'pre_roll', 'midroll', 'mid-roll', 'postroll', 'post-roll',
            'banner', 'banners', 'popup', 'pop-up', 'interstitial', 'overlay', 'splash',
            'bumper', 'stinger', 'vast', 'vpaid', 'vmap',
            'doubleclick', 'googleads', 'googlesyndication', 'googletag', 'adsense', 'admob',
            'adx', 'adnetwork', 'adserving', 'ad-serving', 'adserver', 'ad-server',
            'inmobi', 'unityads', 'applovin', 'ironsource', 'vungle', 'chartboost', 'tapjoy',
            'mintegral', 'pangle', 'bytedance', 'tiktokads', 'kuaishou', 'ks-ad',
            'tracking', 'tracker', 'beacon', 'pixel', 'analytics', 'statistic',
            'leaderboard', 'skyscraper', 'rectangle', 'filler',
            # 中文广告词
            '广告', '片头', '片尾', '贴片', '赞助商', '赞助', '推广', '硬广',
            '前贴', '中插', '后贴', '角标', '广告位', '广告片', '广告段', '广告视频',
            '广告素材', '弹窗', '悬浮', '开屏', '插屏', '激励视频', '激励广告',
            # 拼音/缩写
            'guanggao', 'ggao', 'ggvideo', 'ggmedia',
            # 路径特征（精确匹配）
            '/ad/', '/ads/', '/adv/', '/adver/', '/gg/', '/gga/', '/ggb/', '/ggc/', '/ggd/',
            '_ad.', '.ad/', '_ads.', '_adv.', '_gg.', 'gg_', '_gg', '/gg', 'gg.',
            '/ad_', '/ads_', '/adv_', '/sponsor/', '/banner/', '/promo/', '/commercial/',
            '/preroll/', '/midroll/', '/postroll/', '/popup/', '/interstitial/', '/overlay/',
            '/splash/', '/bumper/', '/vast/', '/vpaid/', '/adnetwork/', '/adserving/',
            '/doubleclick/', '/googleads/', '/googlesyndication/', '/adsense/', '/admob/',
            '/tracking/', '/tracker/', '/beacon/', '/pixel/', '/analytics/',
        ]
        if any(w in u for w in ad_words):
            return True
        try:
            if 0 < float(dur) <= 1.2:
                return True
        except Exception:
            pass
        return False

    def _parse_m3u8_segments(self, text):
        """m3u8解析器：拆出header/segments/tail，提取每片段的tags/uri/duration"""
        lines = [x.strip() for x in (text or '').replace('\r', '').split('\n') if x.strip()]
        header, segments, tail = [], [], []
        pending_tags = []
        media_sequence = 0
        target_duration = 0
        started = False
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith('#EXT-X-MEDIA-SEQUENCE'):
                try:
                    media_sequence = int(line.split(':', 1)[1])
                except Exception:
                    pass
                if not started:
                    header.append(line)
                else:
                    pending_tags.append(line)
            elif line.startswith('#EXT-X-TARGETDURATION'):
                try:
                    target_duration = float(line.split(':', 1)[1])
                except Exception:
                    pass
                if not started:
                    header.append(line)
                else:
                    pending_tags.append(line)
            elif line.startswith('#EXTINF'):
                started = True
                dur = target_duration or 3.0
                m = re.search(r'#EXTINF:\s*([\d.]+)', line)
                if m:
                    try:
                        dur = float(m.group(1))
                    except Exception:
                        pass
                tags = pending_tags + [line]
                pending_tags = []
                uri = ''
                j = i + 1
                while j < len(lines):
                    if lines[j].startswith('#'):
                        tags.append(lines[j])
                        j += 1
                        continue
                    uri = lines[j]
                    break
                if uri:
                    segments.append({'tags': tags, 'uri': uri, 'dur': dur})
                    i = j
                else:
                    tail.extend(tags)
            elif line.startswith('#EXT-X-ENDLIST'):
                tail.append(line)
            elif line.startswith('#'):
                if started:
                    pending_tags.append(line)
                else:
                    header.append(line)
            else:
                started = True
                dur = target_duration or 3.0
                segments.append({'tags': pending_tags, 'uri': line, 'dur': dur})
                pending_tags = []
            i += 1
        return header, segments, tail, media_sequence, target_duration

    def _segment_host_key(self, uri, base_url):
        """提取片段的主机+路径前缀，用于统计主CDN"""
        try:
            full = urljoin(base_url, uri)
            p = urlsplit(full)
            path = re.sub(r'/[^/]*$', '/', p.path or '/')
            return (p.netloc.lower(), path.lower())
        except Exception:
            return ('', '')

    def _main_path_marker(self, m3u8_url):
        """从m3u8 URL提取主路径标记（如/20240101/xxx/1000kb/hls/）"""
        try:
            p = urlsplit(m3u8_url).path
            m = re.search(r'(/\d{8}/[^/]+/\d+kb/hls/)', p)
            if m:
                return m.group(1).lower()
            m = re.search(r'(/\d{8}/[^/]+/)', p)
            if m:
                return m.group(1).lower()
        except Exception:
            pass
        return ''

    def _clean_m3u8(self, m3u8_text, m3u8_url='', referer='', skip_seconds=25):
        """核心m3u8广告清洗：五重广告识别 + 主CDN统计 + 前置贴片切除 + 多码率递归代理"""
        text = (m3u8_text or '').replace('\r', '')
        # 多码率m3u8（#EXT-X-STREAM-INF）：递归代理子m3u8
        if '#EXT-X-STREAM-INF' in text:
            out = []
            last_stream = False
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                if line.startswith('#'):
                    out.append(line)
                    last_stream = line.startswith('#EXT-X-STREAM-INF')
                else:
                    abs_url = urljoin(m3u8_url, line)
                    if last_stream or '.m3u8' in line.lower():
                        out.append(self._proxy_m3u8_url(abs_url, referer or self.rawSite))
                    else:
                        out.append(abs_url)
                    last_stream = False
            return '\n'.join(out) + '\n'

        header, segments, tail, media_sequence, target_duration = self._parse_m3u8_segments(text)
        if not segments:
            return text

        marker = self._main_path_marker(m3u8_url)

        # 统计各主机路径的总时长，找出主CDN
        stat = {}
        for seg in segments:
            key = self._segment_host_key(seg['uri'], m3u8_url)
            stat[key] = stat.get(key, 0.0) + float(seg.get('dur') or 0)
        main_key = max(stat.items(), key=lambda x: x[1])[0] if stat else ('', '')
        total_dur = sum(stat.values()) or 0
        main_dur = stat.get(main_key, 0)

        # 五重广告识别
        cleaned = []
        removed = 0
        for idx, seg in enumerate(segments):
            key = self._segment_host_key(seg['uri'], m3u8_url)
            is_front = idx < 12
            abs_uri = urljoin(m3u8_url, seg.get('uri', ''))
            is_ad = self._is_ad_segment(seg['uri'], seg.get('dur'), seg.get('tags'))
            # 第三重：路径标记不匹配主路径
            if marker and marker not in urlsplit(abs_uri).path.lower():
                is_ad = True
            tags_text = '\n'.join(seg.get('tags') or []).upper()
            # 第四重：前置12片段 + METHOD=NONE + 路径不匹配
            if is_front and 'METHOD=NONE' in tags_text and marker and marker not in urlsplit(abs_uri).path.lower():
                is_ad = True
            # 第五重：前置12片段 + 主CDN占比>=60% + 非主CDN且时长<=90秒
            if (not is_ad) and is_front and total_dur > 0 and main_dur >= total_dur * 0.6:
                if key != main_key and stat.get(key, 0) <= 90:
                    is_ad = True
            if is_ad:
                removed += 1
                continue
            seg['_idx'] = idx
            cleaned.append(seg)

        # 兜底策略：没删到广告时，前12片段累计>=25秒且第一个不是主CDN，则切掉前置贴片
        if removed == 0 and len(segments) > 4:
            acc = 0.0
            cut = 0
            for idx, seg in enumerate(segments[:12]):
                key = self._segment_host_key(seg['uri'], m3u8_url)
                if key == main_key and acc >= 3:
                    break
                acc += float(seg.get('dur') or target_duration or 3)
                cut = idx + 1
                if acc >= skip_seconds:
                    break
            if cut > 0 and cut < len(segments):
                first_key = self._segment_host_key(segments[0]['uri'], m3u8_url)
                if first_key != main_key:
                    cleaned = segments[cut:]
                    removed = cut

        if not cleaned:
            cleaned = segments
            removed = 0

        # 重新生成干净的m3u8
        new_lines = []
        has_m3u = False
        for line in header:
            if line.startswith('#EXTM3U'):
                has_m3u = True
            if line.startswith('#EXT-X-MEDIA-SEQUENCE') or line.startswith('#EXT-X-START'):
                continue
            if line.startswith('#EXT-X-KEY') and 'METHOD=NONE' in line.upper() and removed > 0:
                continue
            new_lines.append(line)
        if not has_m3u:
            new_lines.insert(0, '#EXTM3U')
        first_idx = cleaned[0].get('_idx', removed) if cleaned else removed
        new_lines.append('#EXT-X-MEDIA-SEQUENCE:%d' % (media_sequence + first_idx))

        for seg in cleaned:
            for tag in seg.get('tags') or []:
                if tag.startswith('#EXT-X-KEY') or tag.startswith('#EXT-X-MAP'):
                    def _fix_uri(m):
                        return 'URI="' + urljoin(m3u8_url, m.group(1)) + '"'
                    tag = re.sub(r'URI="([^"]+)"', _fix_uri, tag)
                new_lines.append(tag)
            new_lines.append(urljoin(m3u8_url, seg.get('uri', '')))
        if tail:
            for line in tail:
                if line.startswith('#EXT-X-ENDLIST'):
                    new_lines.append(line)
        elif '#EXT-X-ENDLIST' in text:
            new_lines.append('#EXT-X-ENDLIST')
        return '\n'.join(new_lines) + '\n'

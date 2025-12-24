from base.parser import Parser
import requests
import time
import hashlib
import random
import string
from urllib.parse import urlencode, quote
from typing import Dict, Any, Tuple, Union, Iterable
import logging
import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Parser(Parser):
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = {
            'upstream': ['http://66.90.99.154:8278/'],
            'list_url': 'https://cdn.jsdelivr.net/gh/hostemail/cdn@main/data/smart.txt',
            'backup_url': 'https://cdn.jsdelivr.net/gh/hostemail/cdn@main/data/smart1.txt',
            'token_ttl': 2400,
            'cache_ttl': 3600,
            'fallback': 'http://vjs.zencdn.net/v/oceans.mp4',
            'clear_key': 'leifeng'
        }
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Cache-Control': 'no-cache'
        })
        
        self.cache = {}
        self.upstream_index = 0

    def get_upstream(self):
        upstreams = self.config['upstream']
        current = upstreams[self.upstream_index % len(upstreams)]
        self.upstream_index += 1
        return current

    def fetch_url_content(self, url, timeout=5):
        try:
            response = self.session.get(url, timeout=timeout, verify=False)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"请求失败: {e}")
            return None

    def get_channel_list(self, force_refresh=False):
        cache_key = 'channels'
        
        if not force_refresh and cache_key in self.cache:
            cached_time, data = self.cache[cache_key]
            if time.time() - cached_time < self.config['cache_ttl']:
                return data

        raw = self.fetch_url_content(self.config['list_url'])
        if not raw:
            raw = self.fetch_url_content(self.config['backup_url'])
            if not raw:
                return []

        channels = []
        current_group = '默认分组'
        
        for line in raw.split('\n'):
            line = line.strip()
            if not line:
                continue

            if ',#genre#' in line:
                current_group = line.replace(',#genre#', '').strip()
                continue

            if ',' in line:
                parts = line.split(',', 1)
                name = parts[0].strip()
                url_part = parts[1].strip()
                
                channel_id = None
                if '?id=' in url_part:
                    import re
                    match = re.search(r'[?&]id=([^&]+)', url_part)
                    if match:
                        channel_id = match.group(1)
                
                if channel_id:
                    channels.append({
                        'id': channel_id,
                        'name': name,
                        'group': current_group
                    })

        self.cache[cache_key] = (time.time(), channels)
        return channels

    def validate_token(self, token):
        try:
            parts = token.split(':')
            if len(parts) != 2:
                return False
            timestamp = int(parts[1])
            return (time.time() - timestamp) <= self.config['token_ttl']
        except:
            return False

    def manage_token(self, params):
        token = params.get('token', '')
        if token and self.validate_token(token):
            return token
        new_token = ''.join(random.choices(string.hexdigits, k=32)) + ':' + str(int(time.time()))
        return new_token

    def generate_m3u8(self, channel_id, token):
        upstream = self.get_upstream()
        current_time = int(time.time() / 150)
        auth_str = f"tvata nginx auth module/{channel_id}/playlist.m3u8mc42afe745533{current_time}"
        tsum = hashlib.md5(auth_str.encode()).hexdigest()
        
        auth_url = upstream + channel_id + "/playlist.m3u8?" + urlencode({
            'tid': 'mc42afe745533',
            'ct': current_time,
            'tsum': tsum
        })
        
        content = self.fetch_url_content(auth_url)
        if not content:
            return {"url": self.config['fallback']}
        
        import re
        base_url = self.address + "?id=" + quote(channel_id) + "&token=" + quote(token)
        
        def replace_ts(match):
            ts_file = match.group(1)
            return base_url + "&ts=" + quote(ts_file)
        
        content = re.sub(r'(\S+\.ts)', replace_ts, content)
        
        return {
            "content": content,
            "headers": {
                'Content-Type': 'application/vnd.apple.mpegurl'
            }
        }

    def proxy_ts(self, channel_id, ts_file):
        upstream = self.get_upstream()
        url = upstream + channel_id + "/" + ts_file
        
        try:
            response = self.session.get(url, timeout=10, verify=False)
            if response.status_code == 200:
                return {
                    "content": response.content,
                    "headers": {
                        'Content-Type': 'video/MP2T'
                    }
                }
        except Exception as e:
            logger.error(f"代理TS失败: {e}")
        
        return {"error": "404 Not Found"}

    def send_txt_list(self):
        try:
            channels = self.get_channel_list()
        except Exception as e:
            return {"error": f"无法获取频道列表: {e}"}

        grouped = {}
        for channel in channels:
            group = channel['group']
            if group not in grouped:
                grouped[group] = []
            grouped[group].append(channel)

        output = ""
        for group, items in grouped.items():
            output += group + ",#genre#\n"
            for channel in items:
                output += channel['name'] + "," + self.address + "?id=" + channel['id'] + "\n"
            output += "\n"

        return {
            "content": output.strip(),
            "headers": {
                'Content-Type': 'text/plain; charset=utf-8'
            }
        }

    def clear_cache(self, key):
        if key != self.config['clear_key']:
            return {"error": "权限验证失败"}

        self.cache.clear()
        results = ["缓存已清除"]
        
        try:
            channels = self.get_channel_list(force_refresh=True)
            if channels:
                results.append(f"频道列表已重建 数量:{len(channels)}")
        except Exception as e:
            results.append(f"列表重建失败: {e}")

        return {
            "content": "\n".join(results),
            "headers": {'Cache-Control': 'no-store'}
        }

    def parse(self, params: Dict[str, str]) -> Dict[str, Any]:
        try:
            action = params.get('action')
            channel_id = params.get('id')
            ts_file = params.get('ts')
            clear_key = params.get('key')

            if action == 'clear_cache' and clear_key:
                return self.clear_cache(clear_key)
            elif not channel_id:
                return self.send_txt_list()
            elif ts_file:
                token = self.manage_token(params)
                if not self.validate_token(token):
                    new_token = self.manage_token({'token': ''})
                    redirect_url = self.address + "?id=" + quote(channel_id) + "&ts=" + quote(ts_file) + "&token=" + quote(new_token)
                    return {"url": redirect_url}
                return self.proxy_ts(channel_id, ts_file)
            else:
                token = self.manage_token(params)
                return self.generate_m3u8(channel_id, token)

        except Exception as e:
            logger.error(f"系统错误: {e}")
            return {"error": f"系统错误: {e}"}

    def stop(self):
        if self.session:
            self.session.close()

    def proxy(self, url: str, headers: Dict[str, Any]) -> Tuple[Union[bytes, Iterable[bytes]], Dict[str, str]]:
        pass

  if __name__ == "__main__":
    # 创建一个简单的HTTP服务器
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse
    
    class ParserHTTPHandler(BaseHTTPRequestHandler):
        parser = None
        
        def do_GET(self):
            if self.parser is None:
                self.parser = Parser()
                self.parser.address = f"http://{self.headers.get('Host')}"
            
            # 解析URL参数
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            
            # 转换参数格式
            params = {}
            for key, value in query_params.items():
                if value:
                    params[key] = value[0]
            
            try:
                result = self.parser.parse(params)
                
                # 重定向
                if 'url' in result:
                    self.send_response(302)
                    self.send_header('Location', result['url'])
                    self.end_headers()
                    return
                
                # 返回内容
                elif 'content' in result:
                    self.send_response(200)
                    headers = result.get('headers', {})
                    for key, value in headers.items():
                        self.send_header(key, value)
                    self.end_headers()
                    
                    content = result['content']
                    if isinstance(content, str):
                        content = content.encode('utf-8')
                    self.wfile.write(content)
                    return
                    
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"服务器错误: {str(e)}".encode('utf-8'))
        
        def log_message(self, format, *args):
            # 减少日志输出
            pass
    
    # 启动服务器
    port = 5000
    server = HTTPServer(('0.0.0.0', port), ParserHTTPHandler)
    print(f"服务启动: http://localhost:{port}")
    print(f"频道列表: http://localhost:{port}/")
    print(f"播放示例: http://localhost:{port}/?id=cctv1")
    print("按 Ctrl+C 停止服务")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务停止")
        if ParserHTTPHandler.parser:
            ParserHTTPHandler.parser.stop()

from base.parser import Parser
import requests
from typing import Tuple, Any, Dict, Union, Iterable
import logging
import urllib.parse
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from datetime import datetime, timezone, timedelta
import threading

class Parser(Parser):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.proxy_config = None
        self.session = self._create_optimized_session()
        
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        self.logger.info("节目单回看优化版SOCKS5代理解析器初始化完成")

    def _create_optimized_session(self) -> requests.Session:
        """创建优化的HTTP会话"""
        session = requests.Session()
        
        adapter = HTTPAdapter(
            pool_connections=50,
            pool_maxsize=100,
            max_retries=Retry(
                total=1,
                backoff_factor=0.1,
                status_forcelist=[500, 502, 503, 504]
            )
        )
        
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Accept-Encoding': 'identity',
            'Connection': 'keep-alive',
        })
        
        return session

    def _get_proxy_config(self, params: Dict[str, str]) -> Dict[str, str]:
        """从参数中获取代理配置"""
        proxy_url = params.get("proxy", "").strip()
        if proxy_url and proxy_url.startswith('socks5://'):
            return {
                "http": proxy_url,
                "https": proxy_url
            }
        return {}

    def parse(self, params: Dict[str, str]) -> Dict[str, str]:
        """
        解析参数并返回代理播放地址，优化节目单回看支持
        """
        try:
            play_url = params.get("a", "").strip()
            if not play_url:
                return {
                    "error": "缺少播放URL参数",
                    "usage": "请使用 ?a=播放URL&proxy=socks5://代理地址 的形式调用"
                }
            
            if not play_url.startswith(('http://', 'https://')):
                return {
                    "error": "无效的URL格式",
                    "message": "URL必须以 http:// 或 https:// 开头"
                }
            
            # 获取代理配置
            proxy_config = self._get_proxy_config(params)
            proxy_note = "使用动态代理" if proxy_config else "直连模式"
            
            # 处理回看参数 - 支持节目单格式
            playseek = params.get("playseek", "").strip()
            start_time = params.get("start", "").strip()  # 新增：开始时间参数
            end_time = params.get("end", "").strip()      # 新增：结束时间参数
            
            # 优先使用start/end参数（节目单模式）
            if start_time and end_time:
                playseek = self._convert_program_time(start_time, end_time)
            
            original_play_url = play_url
            
            # 构建代理URL参数
            query_params = f"a={urllib.parse.quote(play_url, safe='')}"
            
            if params.get("proxy"):
                query_params += f"&proxy={urllib.parse.quote(params['proxy'], safe='')}"
            
            if playseek:
                query_params += f"&playseek={urllib.parse.quote(playseek, safe='')}"
            
            # 传递start/end参数（用于节目单回看）
            if start_time:
                query_params += f"&start={urllib.parse.quote(start_time, safe='')}"
            if end_time:
                query_params += f"&end={urllib.parse.quote(end_time, safe='')}"
            
            proxy_play_url = f"{self.address}?{query_params}"
            
            # 异步测试连接
            if proxy_config:
                test_thread = threading.Thread(target=self._async_test_connection, args=(original_play_url, proxy_config))
                test_thread.daemon = True
                test_thread.start()
            
            return {
                "url": proxy_play_url,
                "proxy_type": "动态SOCKS5" if proxy_config else "直连",
                "proxy_server": params.get("proxy", "无"),
                "status": "ready",
                "play_url": proxy_play_url,
                "m3u8_url": original_play_url,
                "playseek": playseek if playseek else "无",
                "start_time": start_time if start_time else "无",
                "end_time": end_time if end_time else "无",
                "note": f"节目单回看优化版 - {proxy_note}"
            }
            
        except Exception as e:
            self.logger.error(f"解析参数时出错: {e}")
            return {
                "error": f"解析失败: {str(e)}"
            }

    def _convert_program_time(self, start_time: str, end_time: str) -> str:
        """
        转换节目单时间格式为回看参数
        支持格式：
        - "11-20 07:00-08:00" (月-日 时:分-时:分)
        - "2024-11-20 07:00:00-2024-11-20 08:00:00" (完整日期时间)
        - "07:00-08:00" (当天时间，自动补全日期)
        """
        try:
            # 清理时间字符串
            start_time = start_time.strip()
            end_time = end_time.strip()
            
            # 如果包含日期信息（如"11-20 07:00-08:00"）
            if ' ' in start_time and ' ' in end_time:
                start_date_part, start_time_part = start_time.split(' ', 1)
                end_date_part, end_time_part = end_time.split(' ', 1)
                
                # 处理月份-日期格式（如"11-20"）
                if '-' in start_date_part and len(start_date_part.split('-')) == 2:
                    month, day = start_date_part.split('-')
                    current_year = datetime.now().year
                    start_datetime_str = f"{current_year}-{month}-{day} {start_time_part}"
                    end_datetime_str = f"{current_year}-{end_date_part.split('-')[0]}-{end_date_part.split('-')[1]} {end_time_part}"
                else:
                    start_datetime_str = start_time
                    end_datetime_str = end_time
            else:
                # 只有时间，使用当天日期
                current_date = datetime.now().strftime("%Y-%m-%d")
                start_datetime_str = f"{current_date} {start_time}"
                end_datetime_str = f"{current_date} {end_time}"
            
            # 解析日期时间
            start_dt = self._parse_datetime_string(start_datetime_str)
            end_dt = self._parse_datetime_string(end_datetime_str)
            
            # 转换为回看格式：yyyyMMddHHmmss
            playseek_format = "%Y%m%d%H%M%S"
            start_formatted = start_dt.strftime(playseek_format)
            end_formatted = end_dt.strftime(playseek_format)
            
            return f"{start_formatted}-{end_formatted}"
            
        except Exception as e:
            self.logger.warning(f"转换节目时间失败 {start_time}-{end_time}: {e}")
            # 返回原始时间戳作为fallback
            return f"{int(time.time()*1000)}-{int(time.time()*1000)+3600000}"

    def _parse_datetime_string(self, datetime_str: str) -> datetime:
        """
        解析各种日期时间字符串格式
        """
        try:
            # 尝试常见格式
            formats = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%m-%d %H:%M:%S", 
                "%m-%d %H:%M",
                "%H:%M:%S",
                "%H:%M"
            ]
            
            current_year = datetime.now().year
            current_date = datetime.now().strftime("%Y-%m-%d")
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(datetime_str, fmt)
                    # 如果格式中没有年份，添加当前年份
                    if fmt.startswith("%m-") or fmt.startswith("%H"):
                        dt = dt.replace(year=current_year)
                    return dt
                except ValueError:
                    continue
            
            # 如果所有格式都失败，使用当前时间
            return datetime.now()
            
        except Exception:
            return datetime.now()

    def _parse_time_expression(self, time_expr: str) -> str:
        """
        解析酷九风格的时间表达式
        """
        try:
            clean_expr = time_expr.strip()
            if clean_expr.startswith('${(') and clean_expr.endswith(')}'):
                clean_expr = clean_expr[3:-2]
            else:
                return clean_expr
            
            if '|' in clean_expr:
                format_part, timezone_str = clean_expr.split('|', 1)
            else:
                format_part, timezone_str = clean_expr, None
            
            if format_part in ['b', 'e']:
                return str(int(time.time() * 1000))
            elif format_part in ['b10', 'e10']:
                return str(int(time.time()))
            else:
                time_format = format_part
                if time_format.startswith('b') and len(time_format) > 1:
                    time_format = time_format[1:]
                elif time_format.startswith('e') and len(time_format) > 1:
                    time_format = time_format[1:]
                
                format_mapping = {
                    'yyyy': '%Y', 'MM': '%m', 'dd': '%d',
                    'HH': '%H', 'mm': '%M', 'ss': '%S'
                }
                
                py_format = time_format
                for k, v in format_mapping.items():
                    py_format = py_format.replace(k, v)
                
                if timezone_str:
                    tz_offsets = {
                        'Asia/Shanghai': 8, 'UTC': 0, 'GMT': 0,
                        'US/Eastern': -5, 'US/Pacific': -8,
                        'Europe/London': 0, 'Europe/Paris': 1,
                        'Asia/Tokyo': 9, 'Australia/Sydney': 10,
                    }
                    
                    offset_hours = tz_offsets.get(timezone_str, 8)
                    tz = timezone(timedelta(hours=offset_hours))
                    now = datetime.now(tz)
                else:
                    now = datetime.now()
                
                return now.strftime(py_format)
                
        except Exception as e:
            self.logger.warning(f"解析时间表达式失败 {time_expr}: {e}")
            return str(int(time.time() * 1000))

    def _process_playseek_expression(self, playseek_expr: str) -> str:
        """处理playseek表达式"""
        if not playseek_expr or '-' not in playseek_expr:
            return playseek_expr
        
        try:
            start_expr, end_expr = playseek_expr.split('-', 1)
            start_time = self._parse_time_expression(start_expr.strip())
            end_time = self._parse_time_expression(end_expr.strip())
            return f"{start_time}-{end_time}"
        except Exception as e:
            self.logger.warning(f"处理playseek表达式失败: {e}")
            return playseek_expr

    def _async_test_connection(self, url: str, proxy_config: Dict[str, str]):
        """异步测试连接"""
        try:
            response = self.session.head(url, proxies=proxy_config, timeout=1, verify=False)
            if response.status_code == 200:
                self.logger.info(f"连接测试成功: {response.status_code}")
        except Exception as e:
            self.logger.debug(f"连接测试跳过: {e}")

    def stop(self):
        """停止解析器"""
        if hasattr(self, 'session'):
            self.session.close()
        self.logger.info("代理解析器已停止")

    def proxy(self, url: str, headers: Dict[str, Any]) -> Tuple[Union[bytes, Iterable[bytes]], Dict[str, str]]:
        """
        代理方法 - 支持节目单回看
        """
        start_time = time.time()
        
        try:
            parsed_url = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            target_url = query_params.get('a', [''])[0]
            proxy_url = query_params.get('proxy', [''])[0]
            playseek_expr = query_params.get('playseek', [''])[0]
            start_param = query_params.get('start', [''])[0]    # 新增：开始时间
            end_param = query_params.get('end', [''])[0]        # 新增：结束时间
            
            if not target_url:
                return self._quick_error_response("缺少URL参数a")
            
            # 动态获取代理配置
            proxy_config = {}
            if proxy_url and proxy_url.startswith('socks5://'):
                proxy_config = {
                    "http": proxy_url,
                    "https": proxy_url
                }
            
            # 优先使用节目单时间参数
            final_playseek = ""
            if start_param and end_param:
                final_playseek = self._convert_program_time(start_param, end_param)
                self.logger.info(f"使用节目单时间: {start_param} - {end_param} -> {final_playseek}")
            elif playseek_expr:
                final_playseek = self._process_playseek_expression(playseek_expr)
            
            # 处理最终的目标URL
            final_target_url = self._apply_playseek_to_url(target_url, final_playseek)
            
            # 判断请求类型并设置超时
            is_m3u8 = self._is_m3u8_request(final_target_url, headers)
            timeout = 2 if is_m3u8 else 5
            
            # 直接请求目标URL
            response = self.session.get(
                final_target_url,
                proxies=proxy_config,
                timeout=timeout,
                verify=False,
                stream=True
            )
            
            if response.status_code != 200:
                return self._quick_error_response(f"请求失败: {response.status_code}")
            
            # 快速处理响应
            if is_m3u8:
                content = self._optimized_m3u8_process(
                    response.text, 
                    final_target_url, 
                    proxy_url, 
                    playseek_expr,
                    start_param,  # 传递节目单参数
                    end_param
                )
                content_bytes = content.encode('utf-8')
                
                response_headers = {
                    'Content-Type': 'application/vnd.apple.mpegurl',
                    'Content-Length': str(len(content_bytes)),
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'no-cache, max-age=0',
                    'X-Processing-Time': f'{time.time() - start_time:.2f}s',
                    'X-Playseek': final_playseek if final_playseek else 'none',
                    'X-Program-Start': start_param if start_param else 'none',
                    'X-Program-End': end_param if end_param else 'none'
                }
                
                return content_bytes, response_headers
            else:
                response_headers = {
                    'Content-Type': 'video/mp2t',
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'public, max-age=3600',
                    'X-Processing-Time': f'{time.time() - start_time:.2f}s',
                    'X-Playseek': final_playseek if final_playseek else 'none'
                }
                
                return response.iter_content(chunk_size=8192), response_headers
                
        except requests.exceptions.Timeout:
            return self._quick_error_response("请求超时，请检查网络或源地址")
        except requests.exceptions.ConnectionError:
            return self._quick_error_response("连接失败，请检查代理设置")
        except Exception as e:
            return self._quick_error_response(f"代理错误: {str(e)}")

    def _apply_playseek_to_url(self, target_url: str, playseek: str) -> str:
        """将回看参数应用到目标URL"""
        if not playseek:
            return target_url
            
        try:
            if 'playseek=' in target_url:
                pattern = r'playseek=[^&]*'
                return re.sub(pattern, f'playseek={urllib.parse.quote(playseek)}', target_url)
            else:
                separator = '&' if '?' in target_url else '?'
                return f"{target_url}{separator}playseek={urllib.parse.quote(playseek)}"
            
        except Exception as e:
            self.logger.warning(f"应用回看参数到URL时出错: {e}")
            return target_url

    def _is_m3u8_request(self, url: str, headers: Dict[str, Any]) -> bool:
        """快速判断是否为m3u8请求"""
        return '.m3u8' in url.lower() or headers.get('Accept', '').find('mpegurl') != -1

    def _optimized_m3u8_process(self, content: str, base_url: str, proxy_url: str = "", 
                               playseek_expr: str = "", start_time: str = "", end_time: str = "") -> str:
        """
        优化m3u8处理，支持节目单参数传递
        """
        if not content or not content.strip():
            return content
            
        lines = content.splitlines()
        processed_lines = []
        
        base_dir = base_url.rsplit('/', 1)[0] + '/' if '/' in base_url else base_url
        
        for line in lines:
            if not line or line.startswith('#'):
                processed_lines.append(line)
                continue
                
            if line.startswith(('http://', 'https://')):
                query_params = f"a={urllib.parse.quote(line, safe='')}"
                if proxy_url:
                    query_params += f"&proxy={urllib.parse.quote(proxy_url, safe='')}"
                if playseek_expr:
                    query_params += f"&playseek={urllib.parse.quote(playseek_expr, safe='')}"
                # 传递节目单时间参数
                if start_time:
                    query_params += f"&start={urllib.parse.quote(start_time, safe='')}"
                if end_time:
                    query_params += f"&end={urllib.parse.quote(end_time, safe='')}"
                
                proxy_url_full = f"{self.address}?{query_params}"
                processed_lines.append(proxy_url_full)
            else:
                if line.startswith('/'):
                    parsed = urllib.parse.urlparse(base_url)
                    full_url = f"{parsed.scheme}://{parsed.netloc}{line}"
                else:
                    full_url = urllib.parse.urljoin(base_dir, line)
                
                query_params = f"a={urllib.parse.quote(full_url, safe='')}"
                if proxy_url:
                    query_params += f"&proxy={urllib.parse.quote(proxy_url, safe='')}"
                if playseek_expr:
                    query_params += f"&playseek={urllib.parse.quote(playseek_expr, safe='')}"
                if start_time:
                    query_params += f"&start={urllib.parse.quote(start_time, safe='')}"
                if end_time:
                    query_params += f"&end={urllib.parse.quote(end_time, safe='')}"
                
                proxy_url_full = f"{self.address}?{query_params}"
                processed_lines.append(proxy_url_full)
        
        return '\n'.join(processed_lines)

    def _quick_error_response(self, error_msg: str) -> Tuple[bytes, Dict[str, str]]:
        """快速错误响应"""
        error_bytes = error_msg.encode('utf-8')
        return error_bytes, {
            'Content-Type': 'text/plain',
            'Content-Length': str(len(error_bytes)),
            'Access-Control-Allow-Origin': '*'
        }

    def __del__(self):
        """析构函数"""
        self.stop()
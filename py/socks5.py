from base.parser import Parser
import requests
from typing import Tuple, Any, Dict, Union, Iterable
import logging
import urllib.parse
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from datetime import datetime
import threading

class Parser(Parser):  # 必须继承

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 定义SOCKS5代理配置
        self.proxy_config = {
            "http": "socks5://120.226.12.155:31167",
            "https": "socks5://120.226.12.155:31167"
        }
        
        # 创建优化的session
        self.session = self._create_optimized_session()
        
        # 设置日志
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        self.logger.info("优化版SOCKS5代理解析器初始化完成")

    def _create_optimized_session(self) -> requests.Session:
        """创建优化的HTTP会话"""
        session = requests.Session()
        
        # 设置连接池
        adapter = HTTPAdapter(
            pool_connections=20,      # 增加连接池大小
            pool_maxsize=50,          # 增加最大连接数
            max_retries=Retry(        # 优化重试策略
                total=1,              # 减少重试次数
                backoff_factor=0.1,   # 缩短重试间隔
                status_forcelist=[500, 502, 503, 504]
            )
        )
        
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        # 设置通用headers
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Accept-Encoding': 'identity',
            'Connection': 'keep-alive',
        })
        
        return session

    def parse(self, params: Dict[str, str]) -> Dict[str, str]:
        """
        快速解析参数并返回代理播放地址，优化回看处理
        """
        try:
            # 快速获取播放URL参数
            play_url = params.get("a", "").strip()
            
            if not play_url:
                return {
                    "error": "缺少播放URL参数",
                    "usage": "请使用 ?a=播放URL 的形式调用"
                }
            
            # 快速URL验证
            if not play_url.startswith(('http://', 'https://')):
                return {
                    "error": "无效的URL格式",
                    "message": "URL必须以 http:// 或 https:// 开头"
                }
            
            # 检查回看参数
            playseek = params.get("playseek", "").strip()
            if playseek:
                # 处理回看参数 - 直接生成最终URL
                play_url = self._fast_process_playseek(play_url, playseek)
            
            # 异步测试连接（不阻塞主流程）
            test_thread = threading.Thread(target=self._async_test_connection, args=(play_url,))
            test_thread.daemon = True
            test_thread.start()
            
            # 构建代理URL（不包含回看参数，因为已经处理到play_url中）
            proxy_play_url = f"{self.address}?a={urllib.parse.quote(play_url, safe='')}"
            
            return {
                "url": proxy_play_url,
                "proxy_type": "SOCKS5", 
                "proxy_server": "120.226.12.155:31167",
                "status": "ready",
                "play_url": proxy_play_url,
                "m3u8_url": play_url,
                "note": "优化版代理，快速回看支持"
            }
            
        except Exception as e:
            self.logger.error(f"解析参数时出错: {e}")
            return {
                "error": f"解析失败: {str(e)}"
            }

    def _fast_process_playseek(self, play_url: str, playseek: str) -> str:
        """
        快速处理回看参数，直接生成最终URL
        """
        try:
            # 解析playseek参数格式：开始时间-结束时间
            if '-' not in playseek:
                return play_url
                
            start_time_str, end_time_str = playseek.split('-', 1)
            
            # 快速时间参数处理
            start_time = self._fast_parse_time(start_time_str)
            end_time = self._fast_parse_time(end_time_str)
            
            if start_time and end_time:
                # 根据URL结构决定如何添加参数
                separator = '&' if '?' in play_url else '?'
                
                # 直接使用格式化后的时间参数
                play_url += f"{separator}playseek={start_time}-{end_time}"
            
            return play_url
            
        except Exception as e:
            self.logger.warning(f"快速处理回看参数时出错: {e}")
            return play_url

    def _fast_parse_time(self, time_str: str) -> str:
        """
        快速解析时间参数，优化性能
        """
        try:
            # 移除${()}包装
            clean_str = time_str.strip()
            if clean_str.startswith('${(') and clean_str.endswith(')}'):
                clean_str = clean_str[3:-2]
            
            # 处理时间戳格式
            if clean_str.isdigit():
                if len(clean_str) == 13:  # 13位时间戳
                    return clean_str
                elif len(clean_str) == 10:  # 10位时间戳
                    return f"{clean_str}000"  # 直接补零
            
            # 处理格式化时间
            if '|' in clean_str:
                format_part, timezone = clean_str.split('|', 1)
                return self._format_current_time(format_part)
            else:
                return self._format_current_time(clean_str)
                
        except Exception as e:
            # 出错时返回当前时间戳
            return str(int(time.time() * 1000))

    def _format_current_time(self, format_str: str) -> str:
        """
        格式化当前时间，优化性能
        """
        try:
            # 简化格式映射
            format_mapping = {
                'yyyy': '%Y',
                'MM': '%m', 
                'dd': '%d',
                'HH': '%H',
                'mm': '%M',
                'ss': '%S'
            }
            
            # 快速替换
            py_format = format_str
            for k, v in format_mapping.items():
                py_format = py_format.replace(k, v)
            
            now = datetime.now()
            return now.strftime(py_format)
            
        except Exception:
            # 出错时返回简化时间戳
            return datetime.now().strftime('%Y%m%d%H%M%S')

    def _async_test_connection(self, url: str):
        """异步测试连接，不阻塞主流程"""
        try:
            # 超时缩短为2秒
            response = self.session.head(url, proxies=self.proxy_config, timeout=2, verify=False)
            if response.status_code == 200:
                self.logger.info(f"连接测试成功: {response.status_code}")
        except Exception as e:
            self.logger.debug(f"连接测试跳过: {e}")

    def stop(self):
        """停止解析器"""
        if hasattr(self, 'session'):
            self.session.close()
        self.logger.info("SOCKS5代理解析器已停止")

    def proxy(self, url: str, headers: Dict[str, Any]) -> Tuple[Union[bytes, Iterable[bytes]], Dict[str, str]]:
        """
        极速代理方法 - 专门优化回看性能
        """
        start_time = time.time()
        
        try:
            # 快速解析URL参数
            parsed_url = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            target_url = query_params.get('a', [''])[0]
            
            if not target_url:
                return self._quick_error_response("缺少URL参数a")
            
            # 判断请求类型并设置超时
            is_m3u8 = self._is_m3u8_request(target_url, headers)
            timeout = 3 if is_m3u8 else 8  # 回看m3u8使用3秒超时
            
            # 直接请求目标URL（回看参数已经在parse阶段处理完成）
            response = self.session.get(
                target_url,
                proxies=self.proxy_config,
                timeout=timeout,
                verify=False,
                stream=not is_m3u8  # m3u8不使用流式传输
            )
            
            if response.status_code != 200:
                return self._quick_error_response(f"请求失败: {response.status_code}")
            
            # 快速处理响应
            if is_m3u8:
                # 优化m3u8处理性能
                content = self._optimized_m3u8_process(response.text, target_url)
                content_bytes = content.encode('utf-8')
                
                response_headers = {
                    'Content-Type': 'application/vnd.apple.mpegurl',
                    'Content-Length': str(len(content_bytes)),
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'no-cache, max-age=0',
                    'X-Processing-Time': f'{time.time() - start_time:.2f}s'
                }
            else:
                # TS片段直接返回
                content_bytes = response.content
                response_headers = {
                    'Content-Type': 'video/mp2t',
                    'Content-Length': str(len(content_bytes)),
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'public, max-age=7200',  # 延长TS缓存时间
                    'X-Processing-Time': f'{time.time() - start_time:.2f}s'
                }
            
            total_time = time.time() - start_time
            if total_time > 2.0:  # 只记录较慢的请求
                self.logger.info(f"代理完成: {len(content_bytes)} bytes, 耗时: {total_time:.2f}s")
            
            return content_bytes, response_headers
            
        except requests.exceptions.Timeout:
            return self._quick_error_response("请求超时，请检查网络或源地址")
        except requests.exceptions.ConnectionError:
            return self._quick_error_response("连接失败，请检查代理设置")
        except Exception as e:
            return self._quick_error_response(f"代理错误: {str(e)}")

    def _is_m3u8_request(self, url: str, headers: Dict[str, Any]) -> bool:
        """快速判断是否为m3u8请求"""
        return '.m3u8' in url.lower()

    def _optimized_m3u8_process(self, content: str, base_url: str) -> str:
        """
        优化m3u8处理，提升回看性能
        """
        if not content or not content.strip():
            return content
            
        lines = content.splitlines()
        processed_lines = []
        
        # 预计算基础路径
        base_dir = base_url.rsplit('/', 1)[0] + '/' if '/' in base_url else base_url
        
        for line in lines:
            if not line or line.startswith('#'):
                processed_lines.append(line)
                continue
                
            # 快速URL处理
            if line.startswith(('http://', 'https://')):
                # 完整URL直接代理
                proxy_url = f"{self.address}?a={urllib.parse.quote(line, safe='')}"
                processed_lines.append(proxy_url)
            else:
                # 相对路径转换为绝对路径
                if line.startswith('/'):
                    parsed = urllib.parse.urlparse(base_url)
                    full_url = f"{parsed.scheme}://{parsed.netloc}{line}"
                else:
                    full_url = urllib.parse.urljoin(base_dir, line)
                
                proxy_url = f"{self.address}?a={urllib.parse.quote(full_url, safe='')}"
                processed_lines.append(proxy_url)
        
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

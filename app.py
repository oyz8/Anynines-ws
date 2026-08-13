#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, json, socket, struct, hashlib, base64, asyncio
import logging, ipaddress, threading, aiohttp
import platform
import urllib.request
import importlib.util
from aiohttp import web

# 环境变量（直接使用 SERVER、CLIENT_SECRET、UUID）
UUID = os.environ.get('UUID') or 'c202b33e-03d9-406c-9bba-1ca228036028'   # 节点UUID（代理+哪吒共用）
SERVER = os.environ.get('SERVER') or ''          # 哪吒面板地址
CLIENT_SECRET = os.environ.get('CLIENT_SECRET') or ''  # 哪吒客户端密钥
SUB_PATH = os.environ.get('SUB_PATH') or 'sub'   # 订阅路径
NAME = os.environ.get('NAME') or ''              # 节点名称
WSPATH = os.environ.get('WSPATH') or UUID[:8]    # WebSocket 路径
DOMAIN = os.environ.get('DOMAIN') or ''          # 项目域名（部署时自动注入）
PORT = int(os.environ.get('SERVER_PORT') or os.environ.get('PORT') or 3000)
AUTO_ACCESS = os.environ.get('AUTO_ACCESS', '').lower() == 'true'
DEBUG = os.environ.get('DEBUG', '').lower() == 'true'

# 全局变量
CurrentDomain = DOMAIN
CurrentPort = 443
Tls = 'tls'
ISP = ''

# DNS 服务器与屏蔽域名
DNS_SERVERS = ['8.8.4.4', '1.1.1.1']
BLOCKED_DOMAINS = [
    'speedtest.net', 'fast.com', 'speedtest.cn', 'speed.cloudflare.com',
    'speedof.me', 'testmy.net', 'bandwidth.place', 'speed.io',
    'librespeed.org', 'speedcheck.org'
]

# 日志配置
log_level = logging.DEBUG if DEBUG else logging.INFO
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 确保主 logger 不受子线程修改 root logger 的影响
logger = logging.getLogger(__name__)
logger.setLevel(log_level)

# 禁用访问,连接等日志
logging.getLogger('aiohttp.access').setLevel(logging.WARNING)
logging.getLogger('aiohttp.server').setLevel(logging.WARNING)
logging.getLogger('aiohttp.client').setLevel(logging.WARNING)
logging.getLogger('aiohttp.internal').setLevel(logging.WARNING)
logging.getLogger('aiohttp.websocket').setLevel(logging.WARNING)

# 工具函数
def is_blocked_domain(host: str) -> bool:
    if not host:
        return False
    host_lower = host.lower()
    return any(host_lower == blocked or host_lower.endswith('.' + blocked)
               for blocked in BLOCKED_DOMAINS)

async def get_isp():
    global ISP
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('https://api.ip.sb/geoip',
                                   headers={'User-Agent': 'Mozilla/5.0'},
                                   timeout=3) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ISP = f"{data.get('country_code', '')}-{data.get('isp', '')}".replace(' ', '_')
                    return
    except:
        pass

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('http://ip-api.com/json',
                                   headers={'User-Agent': 'Mozilla/5.0'},
                                   timeout=3) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ISP = f"{data.get('countryCode', '')}-{data.get('org', '')}".replace(' ', '_')
                    return
    except:
        pass

    ISP = 'Unknown'

async def get_ip():
    global CurrentDomain, Tls, CurrentPort
    if not DOMAIN or DOMAIN == 'your-domain.com':
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api-ipv4.ip.sb/ip', timeout=5) as resp:
                    if resp.status == 200:
                        ip = await resp.text()
                        CurrentDomain = ip.strip()
                        Tls = 'none'
                        CurrentPort = PORT
        except Exception as e:
            logger.error(f'Failed to get IP: {e}')
            CurrentDomain = 'change-your-domain.com'
            Tls = 'tls'
            CurrentPort = 443
    else:
        CurrentDomain = DOMAIN
        Tls = 'tls'
        CurrentPort = 443

async def resolve_host(host: str) -> str:
    try:
        ipaddress.ip_address(host)
        return host
    except:
        pass

    for dns_server in DNS_SERVERS:
        try:
            async with aiohttp.ClientSession() as session:
                url = f'https://dns.google/resolve?name={host}&type=A'
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('Status') == 0 and data.get('Answer'):
                            for answer in data['Answer']:
                                if answer.get('type') == 1:
                                    return answer.get('data')
        except:
            continue

    return host  # 解析失败时返回原始域名

# 代理处理器
class ProxyHandler:
    def __init__(self, uuid: str):
        self.uuid = uuid
        self.uuid_bytes = bytes.fromhex(uuid)

    async def handle_vless(self, websocket, first_msg: bytes) -> bool:
        """处理 VLESS 协议"""
        try:
            if len(first_msg) < 18 or first_msg[0] != 0:
                return False

            if first_msg[1:17] != self.uuid_bytes:
                return False

            i = first_msg[17] + 19
            if i + 3 > len(first_msg):
                return False

            port = struct.unpack('!H', first_msg[i:i+2])[0]
            i += 2
            atyp = first_msg[i]
            i += 1

            host = ''
            if atyp == 1:  # IPv4
                if i + 4 > len(first_msg):
                    return False
                host = '.'.join(str(b) for b in first_msg[i:i+4])
                i += 4
            elif atyp == 2:  # 域名
                if i >= len(first_msg):
                    return False
                host_len = first_msg[i]
                i += 1
                if i + host_len > len(first_msg):
                    return False
                host = first_msg[i:i+host_len].decode()
                i += host_len
            elif atyp == 3:  # IPv6
                if i + 16 > len(first_msg):
                    return False
                host = ':'.join(f'{(first_msg[j] << 8) + first_msg[j+1]:04x}'
                                for j in range(i, i+16, 2))
                i += 16
            else:
                return False

            if is_blocked_domain(host):
                await websocket.close()
                return False

            await websocket.send_bytes(bytes([0, 0]))

            resolved_host = await resolve_host(host)

            try:
                reader, writer = await asyncio.open_connection(resolved_host, port)

                if i < len(first_msg):
                    writer.write(first_msg[i:])
                    await writer.drain()

                async def forward_ws_to_tcp():
                    try:
                        async for msg in websocket:
                            if msg.type == aiohttp.WSMsgType.BINARY:
                                writer.write(msg.data)
                                await writer.drain()
                    except:
                        pass
                    finally:
                        writer.close()
                        await writer.wait_closed()

                async def forward_tcp_to_ws():
                    try:
                        while True:
                            data = await reader.read(4096)
                            if not data:
                                break
                            await websocket.send_bytes(data)
                    except:
                        pass

                await asyncio.gather(
                    forward_ws_to_tcp(),
                    forward_tcp_to_ws()
                )

            except Exception as e:
                if DEBUG:
                    logger.error(f"Connection error: {e}")

            return True

        except Exception as e:
            if DEBUG:
                logger.error(f"VLESS handler error: {e}")
            return False

    async def handle_trojan(self, websocket, first_msg: bytes) -> bool:
        """处理 Trojan 协议"""
        try:
            if len(first_msg) < 58:
                return False

            received_hash_bytes = first_msg[:56]

            # 验证密码 - 支持标准UUID和无短横线UUID
            hash_obj1 = hashlib.sha224()
            hash_obj1.update(self.uuid.encode())
            expected_hash_hex1 = hash_obj1.hexdigest()

            # 尝试使用标准UUID（带短横线）
            standard_uuid = UUID
            hash_obj2 = hashlib.sha224()
            hash_obj2.update(standard_uuid.encode())
            expected_hash_hex2 = hash_obj2.hexdigest()

            received_hash_hex = received_hash_bytes.decode('ascii', errors='ignore')

            if received_hash_hex != expected_hash_hex1 and received_hash_hex != expected_hash_hex2:
                return False

            offset = 56
            if first_msg[offset:offset+2] == b'\r\n':
                offset += 2

            cmd = first_msg[offset]
            if cmd != 1:
                return False
            offset += 1

            atyp = first_msg[offset]
            offset += 1

            host = ''
            if atyp == 1:  # IPv4
                host = '.'.join(str(b) for b in first_msg[offset:offset+4])
                offset += 4
            elif atyp == 3:  # 域名
                host_len = first_msg[offset]
                offset += 1
                host = first_msg[offset:offset+host_len].decode()
                offset += host_len
            elif atyp == 4:  # IPv6
                host = ':'.join(f'{(first_msg[j] << 8) + first_msg[j+1]:04x}'
                                for j in range(offset, offset+16, 2))
                offset += 16
            else:
                return False

            port = struct.unpack('!H', first_msg[offset:offset+2])[0]
            offset += 2

            if first_msg[offset:offset+2] == b'\r\n':
                offset += 2

            if is_blocked_domain(host):
                await websocket.close()
                return False

            resolved_host = await resolve_host(host)

            try:
                reader, writer = await asyncio.open_connection(resolved_host, port)

                if offset < len(first_msg):
                    writer.write(first_msg[offset:])
                    await writer.drain()

                async def forward_ws_to_tcp():
                    try:
                        async for msg in websocket:
                            if msg.type == aiohttp.WSMsgType.BINARY:
                                writer.write(msg.data)
                                await writer.drain()
                    except:
                        pass
                    finally:
                        writer.close()
                        await writer.wait_closed()

                async def forward_tcp_to_ws():
                    try:
                        while True:
                            data = await reader.read(4096)
                            if not data:
                                break
                            await websocket.send_bytes(data)
                    except:
                        pass

                await asyncio.gather(
                    forward_ws_to_tcp(),
                    forward_tcp_to_ws()
                )

            except Exception as e:
                if DEBUG:
                    logger.error(f"Connection error: {e}")

            return True

        except Exception as e:
            if DEBUG:
                logger.error(f"Trojan handler error: {e}")
            return False

    async def handle_shadowsocks(self, websocket, first_msg: bytes) -> bool:
        """处理 Shadowsocks 协议"""
        try:
            if len(first_msg) < 7:
                return False

            offset = 0
            atyp = first_msg[offset]
            offset += 1

            host = ''
            if atyp == 1:  # IPv4
                if offset + 4 > len(first_msg):
                    return False
                host = '.'.join(str(b) for b in first_msg[offset:offset+4])
                offset += 4
            elif atyp == 3:  # 域名
                if offset >= len(first_msg):
                    return False
                host_len = first_msg[offset]
                offset += 1
                if offset + host_len > len(first_msg):
                    return False
                host = first_msg[offset:offset+host_len].decode()
                offset += host_len
            elif atyp == 4:  # IPv6
                if offset + 16 > len(first_msg):
                    return False
                host = ':'.join(f'{(first_msg[j] << 8) + first_msg[j+1]:04x}'
                                for j in range(offset, offset+16, 2))
                offset += 16
            else:
                return False

            if offset + 2 > len(first_msg):
                return False
            port = struct.unpack('!H', first_msg[offset:offset+2])[0]
            offset += 2

            if is_blocked_domain(host):
                await websocket.close()
                return False

            resolved_host = await resolve_host(host)

            try:
                reader, writer = await asyncio.open_connection(resolved_host, port)

                if offset < len(first_msg):
                    writer.write(first_msg[offset:])
                    await writer.drain()

                async def forward_ws_to_tcp():
                    try:
                        async for msg in websocket:
                            if msg.type == aiohttp.WSMsgType.BINARY:
                                writer.write(msg.data)
                                await writer.drain()
                    except:
                        pass
                    finally:
                        writer.close()
                        await writer.wait_closed()

                async def forward_tcp_to_ws():
                    try:
                        while True:
                            data = await reader.read(4096)
                            if not data:
                                break
                            await websocket.send_bytes(data)
                    except:
                        pass

                await asyncio.gather(
                    forward_ws_to_tcp(),
                    forward_tcp_to_ws()
                )

            except Exception as e:
                if DEBUG:
                    logger.error(f"Connection error: {e}")

            return True

        except Exception as e:
            if DEBUG:
                logger.error(f"Shadowsocks handler error: {e}")
            return False


# HTTP/WebSocket 处理
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    CUUID = UUID.replace('-', '')
    path = request.path

    if f'/{WSPATH}' not in path:
        await ws.close()
        return ws

    proxy = ProxyHandler(CUUID)

    try:
        first_msg = await asyncio.wait_for(ws.receive(), timeout=5)
        if first_msg.type != aiohttp.WSMsgType.BINARY:
            await ws.close()
            return ws

        msg_data = first_msg.data

        # 尝试 VLESS
        if len(msg_data) > 17 and msg_data[0] == 0:
            if await proxy.handle_vless(ws, msg_data):
                return ws

        # 尝试 Trojan
        if len(msg_data) >= 58:
            if await proxy.handle_trojan(ws, msg_data):
                return ws

        # 尝试 Shadowsocks
        if len(msg_data) > 0 and msg_data[0] in (1, 3, 4):
            if await proxy.handle_shadowsocks(ws, msg_data):
                return ws

        await ws.close()

    except asyncio.TimeoutError:
        await ws.close()
    except Exception as e:
        if DEBUG:
            logger.error(f"WebSocket handler error: {e}")
        await ws.close()

    return ws

async def http_handler(request):
    if request.path == '/':
        try:
            with open('index.html', 'r', encoding='utf-8') as f:
                content = f.read()
            return web.Response(text=content, content_type='text/html')
        except:
            return web.Response(text='Hello world!', content_type='text/html')

    elif request.path == f'/{SUB_PATH}':
        await get_isp()
        await get_ip()

        name_part = f"{NAME}-{ISP}" if NAME else ISP
        tls_param = 'tls' if Tls == 'tls' else 'none'
        ss_tls_param = 'tls;' if Tls == 'tls' else ''

        # 生成配置链接
        vless_url = f"vless://{UUID}@{CurrentDomain}:{CurrentPort}?encryption=none&security={tls_param}&sni={CurrentDomain}&fp=chrome&type=ws&host={CurrentDomain}&path=%2F{WSPATH}#{name_part}"
        trojan_url = f"trojan://{UUID}@{CurrentDomain}:{CurrentPort}?security={tls_param}&sni={CurrentDomain}&fp=chrome&type=ws&host={CurrentDomain}&path=%2F{WSPATH}#{name_part}"

        ss_method_password = base64.b64encode(f"none:{UUID}".encode()).decode()
        ss_url = f"ss://{ss_method_password}@{CurrentDomain}:{CurrentPort}?plugin=v2ray-plugin;mode%3Dwebsocket;host%3D{CurrentDomain};path%3D%2F{WSPATH};{ss_tls_param}sni%3D{CurrentDomain};skip-cert-verify%3Dtrue;mux%3D0#{name_part}"

        subscription = f"{vless_url}\n{trojan_url}\n{ss_url}"
        base64_content = base64.b64encode(subscription.encode()).decode()

        return web.Response(text=base64_content + '\n', content_type='text/plain')

    return web.Response(status=404, text='Not Found\n')


# 保活与清理
async def add_access_task():
    if not AUTO_ACCESS or not DOMAIN:
        return

    full_url = f"https://{DOMAIN}/{SUB_PATH}"
    try:
        async with aiohttp.ClientSession() as session:
            await session.post("https://oyz8.ct8.pl/add-url",
                               json={"url": full_url},
                               headers={'Content-Type': 'application/json'})
        logger.info('Automatic Access Task added successfully')
    except:
        pass

def cleanup_files():
    for file in ['npm', 'config.yaml']:
        try:
            if os.path.exists(file):
                os.remove(file)
        except:
            pass


# ========== 哪吒 Agent 启动器 ==========
def get_python_version():
    return f"{sys.version_info.major}.{sys.version_info.minor}"

def get_arch():
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    elif machine in ("aarch64", "arm64"):
        return "arm64"
    else:
        raise RuntimeError(f"Unsupported architecture: {machine}")

def download_agent_so():
    py_ver = get_python_version()
    arch = get_arch()
    asset_name = f"main-{py_ver}-{arch}.so"

    # 获取最新 Release 的 tag
    api_url = "https://api.github.com/repos/oyz8/agent-v1-so/releases/latest"
    try:
        with urllib.request.urlopen(api_url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            tag = data.get("tag_name")
            if not tag:
                raise ValueError("No tag_name in GitHub API response")
    except Exception as e:
        logger.error(f"Failed to fetch latest release tag: {e}")
        return False

    download_url = f"https://github.com/oyz8/agent-v1-so/releases/download/{tag}/{asset_name}"
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.so")

    try:
        logger.info(f"Downloading agent .so from {download_url}")
        urllib.request.urlretrieve(download_url, local_path)
        logger.info(f"Downloaded {asset_name} successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to download .so file: {e}")
        return False

def start_nezha_agent():
    try:
        logger.info(f"Agent: SERVER={SERVER}, UUID={UUID}")
        if not os.path.exists("main.so"):
            logger.info("main.so not found, downloading...")
            if not download_agent_so():
                logger.error("Failed to download main.so, skip starting Nezha Agent")
                return
            logger.info("main.so downloaded successfully")

        logger.info("Loading main.so module...")
        spec = importlib.util.spec_from_file_location("main", os.path.abspath("main.so"))
        if spec is None or spec.loader is None:
            raise ImportError("Cannot load agent module from main.so")
        main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main)
        logger.info("main.so loaded successfully")

        main.SERVER = SERVER
        main.SECRET = CLIENT_SECRET
        main.UUID = UUID

        os.environ["SERVER"] = SERVER
        os.environ["CLIENT_SECRET"] = CLIENT_SECRET
        os.environ["UUID"] = UUID

        config = {
            "server": SERVER,
            "secret": CLIENT_SECRET,
            "uuid": UUID,
        }

        logger.info("Calling start_worker directly...")
        asyncio.run(main.start_worker(config))
        logger.warning("start_worker returned unexpectedly")
    except Exception as e:
        import traceback
        logger.error(f'Nezha Agent failed to start: {e}')
        logger.error(traceback.format_exc())


# 主函数
async def main():
    # 如果提供了哪吒服务器和密钥，则启动哪吒 Agent
    if SERVER and CLIENT_SECRET:
        logger.info('Starting Nezha Agent via start_worker...')
        nezha_thread = threading.Thread(target=start_nezha_agent, daemon=True)
        nezha_thread.start()
    else:
        logger.info('Nezha variables empty, skipping agent.')

    app = web.Application()

    # 路由
    app.router.add_get('/', http_handler)
    app.router.add_get(f'/{SUB_PATH}', http_handler)
    app.router.add_get(f'/{WSPATH}', websocket_handler)

    # 启动 Web 服务
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    await get_ip()

    logger.info(f"🌐 Public IP/Domain: {CurrentDomain}")
    logger.info(f"✅ server is running on port {PORT}")

    async def delayed_cleanup():
        await asyncio.sleep(180)
        cleanup_files()

    asyncio.create_task(delayed_cleanup())

    await add_access_task()

    try:
        await asyncio.Future()
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped by user")
        cleanup_files()

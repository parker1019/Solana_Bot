import asyncio
import json
import requests
import websockets
import time
from datetime import datetime, timedelta
import pytz
from base58 import b58encode
import logging
from typing import List, Dict, Optional, Any, Set, Tuple
from dataclasses import dataclass
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.logging import RichHandler
import os
import uuid
from dotenv import load_dotenv
import signal
import sqlite3

# 加載.env配置文件
load_dotenv()

# 當前用戶和時間配置
CURRENT_USER = "yanowo"
CURRENT_TIME = datetime.now(pytz.UTC)

# 初始化Rich console用於美化輸出
console = Console()

# 配置日誌系統
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[
        RichHandler(rich_tracebacks=True, console=console),
        logging.FileHandler('raydium_monitor.log', encoding='utf-8')
    ]
)

logger = logging.getLogger("raydium")

# 從.env文件讀取RPC節點配置
rpc_env = os.getenv("RPC_ENDPOINTS", "")
RPC_ENDPOINTS = [endpoint.strip() for endpoint in rpc_env.split(",") if endpoint.strip()]

# 從.env文件讀取WebSocket節點配置
ws_env = os.getenv("WS_ENDPOINTS", "")
WS_ENDPOINTS = [endpoint.strip() for endpoint in ws_env.split(",") if endpoint.strip()]

# 如果環境變量未配置，提供默認值
if not RPC_ENDPOINTS:
    logger.warning("No RPC endpoints found in .env file. Please add RPC_ENDPOINTS=url1,url2,... to your .env file.")
    RPC_ENDPOINTS = [""]

if not WS_ENDPOINTS:
    logger.warning("No WebSocket endpoints found in .env file. Please add WS_ENDPOINTS=url1,url2,... to your .env file.")
    # 嘗試從RPC地址推斷WebSocket地址
    WS_ENDPOINTS = ["wss" + endpoint[4:] if endpoint.startswith("http") else endpoint for endpoint in RPC_ENDPOINTS]

# 系統配置參數
RAYDIUM_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
RECONNECT_INTERVAL = int(os.getenv("RECONNECT_INTERVAL", "5"))  # WebSocket重連間隔(秒)
MAX_RECONNECT_ATTEMPTS = int(os.getenv("MAX_RECONNECT_ATTEMPTS", "10"))  # 最大重連嘗試次數
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))  # 心跳間隔(秒)
DB_PATH = os.getenv("DB_PATH", "raydium_pools.db")  # 資料庫路徑

# 已知token符號的快取
token_symbol_cache = {}

# 常見代幣地址映射
KNOWN_TOKENS = {
    "So11111111111111111111111111111111111111112": "SOL",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj": "stSOL"
}

@dataclass
class PoolInfo:
    """池子信息數據結構"""
    address: str
    signature: str
    timestamp: datetime
    slot: int
    raw_data: Dict
    coin_mint: str = ""
    token_symbol: str = ""  # 代幣符號

class RaydiumMonitor:
    """Raydium池子監控器主類"""
    def __init__(self):
        self.current_rpc_index = 0
        self.current_ws_index = 0
        self.last_check_time = CURRENT_TIME
        self.pools_found: List[PoolInfo] = []
        self.start_time = CURRENT_TIME
        self.debug_mode = os.getenv("DEBUG_MODE", "True").lower() in ("true", "1", "t")
        self._current_rpc = RPC_ENDPOINTS[self.current_rpc_index]
        self._current_ws = WS_ENDPOINTS[self.current_ws_index]
        self.processed_signatures: Set[str] = set()
        self.websocket = None
        self.subscription_id = None
        self.is_running = False
        self.notification_count = 0
        self.last_heartbeat = time.time()
        
        # 初始化資料庫
        self.init_database()
        
    def init_database(self):
        """初始化SQLite資料庫"""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # 創建池子表格
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS pools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pool_address TEXT UNIQUE,
                signature TEXT,
                coin_mint TEXT,
                token_symbol TEXT,
                pair_symbol TEXT,
                timestamp TEXT,
                discovery_time TEXT,
                slot INTEGER
            )
            ''')
            
            conn.commit()
            conn.close()
            console.print(f"[green]Database initialized: {DB_PATH}[/green]")
        except Exception as e:
            console.print(f"[bold red]Error initializing database: {str(e)}[/bold red]")
    
    def save_pool_to_db(self, pool_info: PoolInfo, token_symbol: str, pair_symbol: str):
        """將池子信息保存到資料庫"""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # 檢查是否已存在相同地址的池子
            cursor.execute("SELECT pool_address FROM pools WHERE pool_address = ?", (pool_info.address,))
            existing = cursor.fetchone()
            
            if not existing:
                # 插入新記錄
                cursor.execute('''
                INSERT INTO pools (pool_address, signature, coin_mint, token_symbol, pair_symbol, timestamp, discovery_time, slot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    pool_info.address, 
                    pool_info.signature, 
                    pool_info.coin_mint, 
                    token_symbol, 
                    pair_symbol,
                    pool_info.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC'),
                    datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S UTC'),
                    pool_info.slot
                ))
                conn.commit()
                console.print("[green]Pool saved to database[/green]")
            else:
                console.print("[yellow]Pool already exists in database, skipping...[/yellow]")
                
            conn.close()
        except Exception as e:
            console.print(f"[bold red]Error saving pool to database: {str(e)}[/bold red]")

    @property
    def current_rpc(self) -> str:
        return self._current_rpc
    
    @property
    def current_ws(self) -> str:
        return self._current_ws
    
    def rotate_endpoints(self):
        """輪換RPC和WebSocket端點"""
        if len(RPC_ENDPOINTS) > 1:
            self.current_rpc_index = (self.current_rpc_index + 1) % len(RPC_ENDPOINTS)
            self._current_rpc = RPC_ENDPOINTS[self.current_rpc_index]
        
        if len(WS_ENDPOINTS) > 1:
            self.current_ws_index = (self.current_ws_index + 1) % len(WS_ENDPOINTS)
            self._current_ws = WS_ENDPOINTS[self.current_ws_index]
        
        console.print(f"[yellow]Rotated to RPC: {self._current_rpc}")
        console.print(f"[yellow]Rotated to WebSocket: {self._current_ws}")

    async def rate_limit(self):
        """API請求的速率限制"""
        await asyncio.sleep(0.2)

    async def get_transaction(self, signature: str, max_retries=3) -> Optional[Dict]:
        """獲取交易詳情，帶重試機制"""
        for retry in range(max_retries):
            try:
                console.print(f"[cyan]Fetching transaction details for {signature} (attempt {retry+1}/{max_retries})[/cyan]")
                
                headers = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
                tx_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                }
                
                await self.rate_limit()
                response = requests.post(self.current_rpc, headers=headers, json=tx_payload, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                tx_data = data.get("result", None)
                if tx_data:
                    return tx_data
                
                console.print(f"[yellow]No result found, waiting for 5 seconds before retry...[/yellow]")
                await asyncio.sleep(5)
                
            except Exception as e:
                console.print(f"[bold red]Error on attempt {retry+1}: {str(e)}[/bold red]")
                if retry < max_retries - 1:
                    await asyncio.sleep(2)
                else:
                    console.print(f"[bold red]Failed to fetch transaction after {max_retries} attempts[/bold red]")
                    return None
        
        return None

    def is_pool_initialization(self, tx_data: Dict) -> bool:
        """檢查交易是否為池子初始化"""
        try:
            if 'meta' not in tx_data or 'logMessages' not in tx_data['meta']:
                return False

            logs = tx_data['meta']['logMessages']
            
            if self.debug_mode:
                console.print("\n[bold yellow]Transaction logs:[/bold yellow]")
                for log in logs:
                    console.print(f"  {log}")

            return any("initialize2" in log for log in logs)

        except Exception as e:
            console.print(f"[bold red]Error checking initialization: {str(e)}[/bold red]")
            return False

    def parse_pool_info(self, tx_data: Dict) -> Tuple[Optional[PoolInfo], str, str]:
        """解析交易數據提取池子信息"""
        try:
            if not tx_data or 'transaction' not in tx_data:
                return None, "", ""

            if self.debug_mode:
                console.print("\n[bold yellow]Parsing transaction[/bold yellow]")
                console.print(f"Slot: {tx_data.get('slot')}")
                console.print(f"Block Time: {tx_data.get('blockTime')}")

            instructions = tx_data['transaction']['message']['instructions']
            raydium_instructions = [
                ix for ix in instructions
                if ix.get('programId') == RAYDIUM_PROGRAM_ID
            ]

            if not raydium_instructions:
                return None, "", ""

            # 處理第一個Raydium指令
            instruction = raydium_instructions[0]
            accounts = instruction.get('accounts', [])

            # 確認accounts列表長度足夠
            if len(accounts) <= 9:
                console.print("[bold red]accounts[] length insufficient, unable to parse pool info[/bold red]")
                return None, "", ""

            # 提取池子地址和代幣地址
            pool_address = accounts[4]
            coin_mint = accounts[8]
            pc_mint = accounts[9]
            
            # WSOL地址常量
            WSOL_ADDRESS = "So11111111111111111111111111111111111111112"
            
            # 確定目標代幣和配對代幣
            if pc_mint == WSOL_ADDRESS:
                # 如果pc_mint是WSOL，關注的是coin_mint
                target_mint = coin_mint
                pair_mint = pc_mint
            else:
                # 其他情況以pc_mint為主要關注代幣
                target_mint = pc_mint
                pair_mint = coin_mint
                
            # 建立池子信息對象
            pool_info = PoolInfo(
                address    = pool_address,
                signature  = tx_data.get('transaction', {}).get('signatures', [''])[0],
                timestamp  = datetime.fromtimestamp(tx_data['blockTime'], tz=pytz.UTC),
                slot       = tx_data['slot'],
                raw_data   = tx_data,
                coin_mint  = target_mint
            )
            
            return pool_info, target_mint, pair_mint

        except Exception as e:
            console.print(f"[bold red]Error parsing pool info: {str(e)}[/bold red]")
            return None, "", ""

    async def get_token_symbol(self, mint_address: str) -> str:
        """獲取代幣符號"""
        # 查找快取
        if mint_address in token_symbol_cache:
            return token_symbol_cache[mint_address]
            
        # 查找已知常見代幣
        if mint_address in KNOWN_TOKENS:
            token_symbol_cache[mint_address] = KNOWN_TOKENS[mint_address]
            return KNOWN_TOKENS[mint_address]
        
        # 使用RPC API獲取代幣信息
        try:
            headers = {"Content-Type": "application/json"}
            payload = {
                "jsonrpc": "2.0",
                "id": "token-info",
                "method": "getAsset",
                "params": {"id": mint_address}
            }
            
            api_url = self.current_rpc
            
            response = requests.post(api_url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # 解析響應獲取符號
            symbol = "Unknown"
            if ('result' in data and 'content' in data['result'] and 
                'metadata' in data['result']['content'] and 
                'symbol' in data['result']['content']['metadata']):
                symbol = data['result']['content']['metadata']['symbol']
                token_symbol_cache[mint_address] = symbol
                return symbol
            
            # 獲取失敗時使用地址前綴作為臨時標識
            if symbol == "Unknown":
                symbol = mint_address[:4] + "..."
                token_symbol_cache[mint_address] = symbol
            
            return symbol
            
        except Exception as e:
            console.print(f"[bold red]Error fetching token symbol: {str(e)}[/bold red]")
            # 使用地址前缀作為臨時標識
            symbol = mint_address[:4] + "..."
            token_symbol_cache[mint_address] = symbol
            return symbol

    async def process_log_notification(self, notification: Dict) -> None:
        """處理WebSocket日誌通知"""
        # 增加通知計數
        self.notification_count += 1
        
        # 心跳檢查
        current_time = time.time()
        if current_time - self.last_heartbeat > HEARTBEAT_INTERVAL:
            console.print(f"[dim cyan]{datetime.now().strftime('%H:%M:%S')} - Processed {self.notification_count} notifications in last {HEARTBEAT_INTERVAL}s. Total pools found: {len(self.pools_found)}[/dim cyan]")
            self.notification_count = 0
            self.last_heartbeat = current_time
        
        try:
            # 快速檢查通知結構
            if 'params' not in notification or 'result' not in notification['params'] or 'value' not in notification['params']['result']:
                return
            
            value = notification['params']['result']['value']
            logs = value.get('logs', [])
            
            # 檢查日誌中是否包含池子初始化關鍵詞
            initialize_keywords = ["initialize2", "initializepool", "createpool", "initpool"]
            if not logs or not any(any(keyword in log.lower() for keyword in initialize_keywords) for log in logs):
                return
            
            signature = value.get('signature')
            if not signature or signature in self.processed_signatures:
                return
            
            self.processed_signatures.add(signature)
            
            # 發現潛在新池子
            console.print(f"\n[bold green]Potential new pool detected in transaction: {signature}[/bold green]")
            
            # 獲取完整交易詳情
            tx_data = await self.get_transaction(signature)
            if not tx_data:
                console.print(f"[yellow]Could not fetch transaction details for {signature}[/yellow]")
                return
            
            # 確認並解析池子初始化交易
            if self.is_pool_initialization(tx_data):
                pool_info, target_mint, pair_mint = self.parse_pool_info(tx_data)
                if pool_info:
                    # 獲取代幣符號
                    token_symbol = await self.get_token_symbol(target_mint)
                    pair_symbol = await self.get_token_symbol(pair_mint)
                    
                    # 設置代幣符號
                    pool_info.token_symbol = token_symbol
                    
                    # 添加到發現的池子列表
                    self.pools_found.append(pool_info)
                    
                    # 保存到資料庫
                    self.save_pool_to_db(pool_info, token_symbol, pair_symbol)
                    
                    # 打印新池子信息
                    console.print(f"\n[bold green]New Pool Found:[/bold green]")
                    console.print(f"Address: {pool_info.address}")
                    console.print(f"Transaction: {pool_info.signature}")
                    console.print(f"Coin Mint: {pool_info.coin_mint}")
                    console.print(f"Token Symbol: {token_symbol}")
                    console.print(f"Pair: {token_symbol}-{pair_symbol}")
                    console.print(f"Time: {pool_info.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        except Exception as e:
            console.print(f"[bold red]Error processing log notification: {str(e)}[/bold red]")

    async def subscribe_to_program_logs(self):
        """訂閱程序日誌的WebSocket連接"""
        reconnect_attempts = 0
        while reconnect_attempts < MAX_RECONNECT_ATTEMPTS and self.is_running:
            try:
                console.print(f"\n[bold cyan]Connecting to WebSocket......[/bold cyan]")
                async with websockets.connect(self.current_ws, ping_interval=20, ping_timeout=20, close_timeout=5) as websocket:
                    self.websocket = websocket
                    reconnect_attempts = 0  # 重置重連計數器
                    self.last_heartbeat = time.time()  # 重置心跳計時器
                    
                    # 訂閱Raydium程序的日誌
                    subscribe_message = {
                        "jsonrpc": "2.0",
                        "id": str(uuid.uuid4()),
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [RAYDIUM_PROGRAM_ID]},  # 監聽指定程序ID
                            {"commitment": "finalized"}
                        ]
                    }
                    
                    await websocket.send(json.dumps(subscribe_message))
                    response = await websocket.recv()
                    response_data = json.loads(response)
                    
                    if 'result' in response_data:
                        self.subscription_id = response_data['result']
                        console.print(f"[bold green]Successfully subscribed to logs. Subscription ID: {self.subscription_id}[/bold green]")
                        
                        # 打印訂閱信息摘要
                        console.print("\n[bold cyan]===== WebSocket Subscription =====[/bold cyan]")
                        console.print(f"Program ID: {RAYDIUM_PROGRAM_ID}")
                        console.print(f"Listening for 'initialize2' in logs")
                        console.print(f"Total Pools Found: {len(self.pools_found)}")
                        console.print(f"Heartbeat Interval: {HEARTBEAT_INTERVAL} seconds")
                        
                        # 持續接收通知
                        while self.is_running:
                            try:
                                # 使用超時機制以便更好地響應停止請求
                                message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                                notification = json.loads(message)
                                
                                if 'method' in notification and notification['method'] == 'logsNotification':
                                    await self.process_log_notification(notification)
                            except asyncio.TimeoutError:
                                # 超時只是表示沒有收到消息，非錯誤狀態
                                if not self.is_running:
                                    console.print("[yellow]Received stop signal while waiting for messages.[/yellow]")
                                    break
                                continue
                            except websockets.exceptions.ConnectionClosedError:
                                console.print("[bold yellow]WebSocket connection closed. Reconnecting...[/bold yellow]")
                                break
                            except asyncio.CancelledError:
                                console.print("[yellow]Async task was cancelled. Stopping gracefully...[/yellow]")
                                self.is_running = False
                                break
                    else:
                        console.print(f"[bold red]Failed to subscribe: {response_data}[/bold red]")
                        
            except (websockets.exceptions.ConnectionClosedError, 
                    websockets.exceptions.InvalidStatusCode,
                    ConnectionRefusedError,
                    asyncio.exceptions.TimeoutError) as e:
                reconnect_attempts += 1
                console.print(f"[bold red]WebSocket connection error: {str(e)}[/bold red]")
                console.print(f"[yellow]Reconnect attempt {reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS}. Waiting {RECONNECT_INTERVAL} seconds...[/yellow]")
                self.rotate_endpoints()  # 切換到另一個端點
                await asyncio.sleep(RECONNECT_INTERVAL)
            except asyncio.CancelledError:
                console.print("[yellow]Async operation was cancelled. Stopping gracefully...[/yellow]")
                self.is_running = False
                break
            except Exception as e:
                if self.is_running:
                    console.print(f"[bold red]Unexpected error: {str(e)}[/bold red]")
                    reconnect_attempts += 1
                    await asyncio.sleep(RECONNECT_INTERVAL)
                else:
                    break
        
        # 重連失敗時顯示錯誤
        if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS and self.is_running:
            console.print("[bold red]Max reconnection attempts reached. Exiting...[/bold red]")

    async def unsubscribe(self):
        """取消訂閱"""
        if self.websocket and self.subscription_id:
            try:
                if self.websocket.open:
                    unsubscribe_message = {
                        "jsonrpc": "2.0",
                        "id": str(uuid.uuid4()),
                        "method": "logsUnsubscribe",
                        "params": [self.subscription_id]
                    }
                    await self.websocket.send(json.dumps(unsubscribe_message))
                    console.print("[yellow]Unsubscribed from logs[/yellow]")
                else:
                    console.print("[yellow]WebSocket already closed, no need to unsubscribe[/yellow]")
            except Exception as e:
                console.print(f"[bold red]Error unsubscribing: {str(e)}[/bold red]")
        
        self.is_running = False

    async def monitor_pools(self) -> None:
        """主監控循環"""
        console.print("[bold green]Starting Raydium Pool Monitor with WebSocket...[/bold green]")
        self.is_running = True
        await self.subscribe_to_program_logs()

    async def stop(self):
        """停止監控"""
        self.is_running = False
        console.print("\n[bold yellow]Stopping monitor...[/bold yellow]")
        try:
            await self.unsubscribe()
            console.print("[green]Successfully shutdown the monitor.[/green]")
        except Exception as e:
            console.print(f"[yellow]Shutdown completed with minor issues: {str(e)}[/yellow]")

# 全局變量，用於信號處理程序訪問監控器
monitor = None

# 信號處理函數
async def signal_handler():
    """處理終止信號"""
    if monitor:
        console.print("\n[bold yellow]Received termination signal. Shutting down...[/bold yellow]")
        await monitor.stop()

async def main():
    global monitor
    
    try:
        monitor = RaydiumMonitor()
        
        # 設置信號處理器
        loop = asyncio.get_running_loop()
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    sig,
                    lambda: asyncio.create_task(signal_handler())
                )
        except NotImplementedError:
            # Windows系統不支持loop.add_signal_handler
            console.print("[yellow]Running on Windows, signal handlers not supported. Use Ctrl+C to stop.[/yellow]")
        
        await monitor.monitor_pools()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Program stopped by user[/bold yellow]")
    except Exception as e:
        # 僅在非取消錯誤時顯示錯誤信息
        if not isinstance(e, asyncio.CancelledError):
            import traceback
            console.print(f"\n[bold red]Fatal error: {str(e)}[/bold red]")
            console.print(f"[bold red]Error traceback: {traceback.format_exc()}[/bold red]")
    finally:
        if monitor:
            await monitor.stop()
            console.print("[green]Successfully shutdown the monitor.[/green]")

if __name__ == "__main__":
    console.print("\n" + "="*50)
    console.print("[bold green]🚀 Raydium Pool WebSocket Monitor[/bold green]")
    console.print(f"[bold blue]👤 User: {CURRENT_USER}")
    console.print(f"⏰ Start Time: {CURRENT_TIME.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    console.print("\n[bold yellow]Monitor Settings:")
    console.print(f"- Debug Mode: {os.getenv('DEBUG_MODE', 'True')}")
    console.print(f"- RPC Endpoints: {len(RPC_ENDPOINTS)} configured")
    console.print(f"- WebSocket Endpoints: {len(WS_ENDPOINTS)} configured")
    console.print(f"- Reconnect Interval: {RECONNECT_INTERVAL} seconds")
    console.print(f"- Heartbeat Interval: {HEARTBEAT_INTERVAL} seconds")
    console.print(f"- Program ID: {RAYDIUM_PROGRAM_ID}")
    console.print(f"- Database: {DB_PATH}")
    console.print("="*50 + "\n")

    # 優雅的異常處理
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # main()函數內部會處理清理工作
        pass
    except Exception as e:
        # 過濾掉CancelledError和KeyboardInterrupt相關錯誤
        if not isinstance(e, asyncio.CancelledError) and not str(e).startswith("KeyboardInterrupt"):
            console.print(f"\n[bold red]Program crashed: {str(e)}[/bold red]")
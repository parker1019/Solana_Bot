# 【Day 3: 監控 Solana 鏈上流動池】

## 自動監控 Raydium 新池子，實時獲取最新交易對：
1. 即時捕獲 Raydium 池子初始化事件
2. 自動解析代幣配對關係
3. 生成完整記錄：
   - **池子地址**
   - **代幣符號**
   - **交易對信息**
---

## 🔹 功能簡介
- ✅ **Raydium池子監控系統**
- ✅ **WebSocket流式數據獲取**
- ✅ **SQLite數據庫實時存儲**
- ✅ **自動池子初始化檢測**

---

## 🛠️ 使用方式

### 1️⃣ 安裝必要的 Python 套件：
```sh
pip install websockets requests asyncio rich base58 python-dotenv
```

---

### 2️⃣ 設定 `.env` 檔案（需 RPC 與 WebSocket 端點）
**步驟：**  
- 在專案目錄下建立 `.env` 檔案，內容如下：
```ini
# Solana RPC endpoints
RPC_ENDPOINTS="你的_SOL_RPC_API"

# WebSocket endpoints
WS_ENDPOINTS="你的_SOL_WS_API"

# Debug mode
DEBUG_MODE="False"

# Raydium program address
RAYDIUM_PROGRAM_ID="675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

# 監控設定
# WebSocket重連間隔(秒)
RECONNECT_INTERVAL=5

# 最大重連嘗試次數
MAX_RECONNECT_ATTEMPTS=10

# 心跳間隔(秒)
HEARTBEAT_INTERVAL=30
```

**注意：**  
以上配置參數可以根據您的需求自行調整

---

## ⚡ 執行流程
1. 連接到WebSocket訂閱Raydium合約日誌
2. 實時捕獲新池子初始化事件
3. 識別代幣符號與交易對
4. 更新SQLite數據庫並輸出結果

---

## 🔍 函數功能說明

### 【初始化模組】
```python
def __init__(...):
    - 載入環境變量與設置配置參數
    - 建立SQLite資料庫連接
    - 初始化WebSocket連接狀態
    - 設置端點輪換策略與重試機制
```

### 【資料庫初始化】
```python
def init_database(...):
    - 建立pools主表儲存池子鏈上數據
    - 創建唯一索引確保地址不重複
    - 紀錄池子發現時間與交易簽名
    - 存儲代幣符號與配對關係
```

### 【WebSocket訂閱模組】
```python
async def subscribe_to_program_logs(...):
    - 維持WebSocket長連接
    - 訂閱Raydium程序日誌
    - 執行心跳檢測機制
    - 處理自動重連與端點輪換
```

### 【交易分析模組】
```python
async def process_log_notification(...):
    - 過濾initialize2關鍵事件
    - 提取交易簽名與時間戳
    - 獲取完整交易詳情
    - 解析池子初始化參數
```

### 【池子解析函數】
```python
def parse_pool_info(...):
    - 解析Raydium指令結構
    - 提取池子地址與代幣地址
    - 識別SOL配對情況
    - 返回標準化池子信息
```

### 【代幣識別模組】
```python
async def get_token_symbol(...):
    - 從快取查詢已知代幣
    - 請求鏈上元數據獲取符號
    - 處理未知代幣前綴顯示
    - 優化快取機制降低API請求
```

### 【心跳監控函數】
```python
async def monitor_pools(...):
    - 啟動WebSocket持續監控
    - 顯示流量統計與發現數量
    - 優雅處理終止信號
    - 定期輸出系統運行狀態
```

### 【RPC輪換函數】
```python
def rotate_endpoints(...):
    - 循環切換RPC端點
    - 在遇到連接問題時自動啟用
    - 提供負載均衡能力
    - 增強系統穩定性與可靠性
```

### 【信號處理函數】
```python
async def signal_handler(...):
    - 捕獲系統終止信號
    - 執行優雅關閉流程
    - 取消WebSocket訂閱
    - 確保數據安全存儲
```

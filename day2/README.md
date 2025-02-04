# 【Day 2: 建構Meme幣熱度指標：AI解析社交數據 (Twitter)】

## 自動分析 Twitter 熱度 + 情感指數，3 步驟找出潛力幣：

1. 即時掃描 Pump.fun 最新代幣
2. 深度爬取 Twitter 討論（含情感分析）
3. 生成完整報告：

   - **代幣地址**
   - **社群提及量**
   - **市場情緒指數**

---

## 🔹 功能簡介

- ✅ **自動 Twitter 認證系統**
- ✅ **智能防爬蟲機制**
- ✅ **數據庫即時更新**
- ✅ **NLP 情感模型分析**

---

## 🛠️ 使用方式

### 1️⃣ 安裝必要的 Python 套件：
```sh
pip install python-dotenv transformers playwright httpx solana solders tensorflow
```
**注意：**  
安裝 Playwright 後，需再執行一次瀏覽器安裝指令，以確保必要瀏覽器可用：
```sh
playwright install
```

---

### 2️⃣ 設定 `.env` 檔案（需 RPC 與 Twitter 帳號）

**步驟：**  
- 在專案目錄下建立 `.env` 檔案，內容如下：

```ini
# Solana RPC endpoint
SOLANA_RPC="你的_SOL_API"

# Twitter credentials
TWITTER_USERNAME="推特_username"
TWITTER_PASSWORD="推特_password"
TWITTER_EMAIL="推特_email"

# Pump.fun program addresses
PUMP_FUN_PROGRAM_ID="6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
```

---

## ⚡ 執行流程

1. 掃描鏈上最新代幣
2. 爬取 Twitter 社群討論
3. 計算情緒指數
4. 更新資料庫並輸出結果

---

## 🔍 函數功能說明

### 【初始化模組】
```python
def init(...):
    - 載入環境變量與 NLP 模型
    - 建立 SQLite 資料庫連接
    - 設定爬蟲參數與重試策略
    - 禁用 TensorFlow 冗餘日誌
```

### 【資料庫初始化】
```python
def _init_db(...):
    - 建立 tokens 主表儲存代幣鏈上數據
    - 創建 social_data 表記錄社交指標
    - 使用 DATETIME 類型記錄時間戳
    - 設置 social_analyzed 分析狀態標記
```

### 【Twitter 登入模組】
```python
async def login_twitter(...):
    - Cookie 持久化機制 (加載/保存)
    - 處理雙因素驗證流程
    - 自動填寫帳號/密碼/備用郵件
    - 使用 Playwright 繞過登入檢測
```

### 【批量分析模組】
```python
async def analyze_social_data_batch(...):
    - 啟動無頭 Chromium 實例
    - 執行智慧滾動加載推文
    - 提取 tweetText 元素內容
    - 調用 DistilBERT 模型分析情感
    - 計算平均情緒指數與提及量
```

### 【鏈上掃描模組】
```python
async def fetch_pumpfun_new_tokens(...):
    - 監聽 Pump.fun 合約交易
    - 解析交易 metadata 獲取 mint 地址
    - 過濾重複代幣項目
    - 寫入資料庫觸發後續分析
```

### 【交易解析函數】
```python
async def get_transaction_details(...):
    - 解碼 Solana 交易結構
    - 提取 pre_token_balances 數據
    - 驗證程序 ID 歸屬
    - 返回標準化代幣資訊
```

### 【報告生成函數】
```python
def generate_report(...):
    - 聯表查詢代幣與社交數據
    - 計算總提及次數與情緒均值
    - 格式化控制台輸出
    - 標記高潛力代幣 (情緒 > 0.8)
```

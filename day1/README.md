# 【Day 1】鏈上 Solana 資料擷取：用 Python 即時取得 Meme 幣交易流

要捕捉 Solana 上的 Meme 幣機會，第一步是即時監控鏈上數據。這次的教學主要說明如何用 Python 抓取 Raydium 和 Jupiter 的 Swap 事件，並辨識高潛力新幣。

這份 **Solana 交易監控代碼** 主要用於監測 **Jupiter DEX** 和 **Raydium AMM** 上的大額交易（超過 50 SOL），並記錄 **代幣交換（Swap）資訊** 到本地 SQLite 資料庫。以下是詳細的功能說明：

---

## ⚠️ 工具準備

- **安裝 Python**：  
  [下載 Python](https://python.org/downloads/)
- **安裝 Solana SDK**：  
  在命令中執行 `pip install solana`
- **取得免費 RPC 節點**：  
  QuickNode：[連結](https://refer.quicknode.com/?via=yan)
- **安裝數據庫瀏覽器**：  
  [DB Browser for SQLite](https://sqlitebrowser.org)
- **新增一個 `.py` 執行程序** 用於執行之後的代碼：`sol_scan.py`（可自訂）

---

## 1. Solana RPC 連接

程式透過 **Solana RPC API** 連接區塊鏈，獲取最新的區塊、交易資訊，確保能即時監測到 DEX 上的交易。

```python
self.client = Client(Config.RPC_ENDPOINT)
```

- `RPC_ENDPOINT` 指定 Solana 節點的 API 地址。  
- 這使程式能夠查詢區塊信息、獲取交易數據、解析交易記錄。

---

## 2. 監測 DEX 交易

程式會監測 **Jupiter（Solana DEX 聚合器）** 和 **Raydium（流動性池 AMM）** 相關的交易，並根據智能合約 ID 過濾出這些交易。

```python
JUPITER_PROGRAM_IDS = [
    "JUP2jxvXaqu7NQY1GmNF4m1vodw12LVXYxbFL2uJvfo",  # Jupiter v4
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"   # Jupiter v6
]
RAYDIUM_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
```

- 透過智能合約地址過濾出 **Jupiter** 和 **Raydium** 相關的交易，確保只監測 DEX 交易。

---

## 3. 解析交易中的代幣資訊

當發現 DEX 交易時，程式會提取該筆交易涉及的代幣，包括：

- **輸入代幣（input token）**  
- **輸出代幣（output token）**  

```python
def find_token_transfers(self, tx, account_keys) -> List[dict]:
    tokens = []
    for balance in tx.meta.post_token_balances:
        mint = str(balance.mint)
        token_info = self.get_token_info(mint)
        if token_info["name"] != "Unknown":
            tokens.append(token_info)
    return tokens
```

- 透過 **交易後的 Token 餘額變化** 來識別代幣轉換。  
- 例如，USDC 交換成 SOL，程式會記錄 **USDC（input）-> SOL（output）**。

---

## 4. 記錄大額交易（超過 50 SOL）

程式只記錄超過 **50 SOL** 的大額交易，避免小額交易干擾數據。

```python
if sol_change > Config.MIN_SWAP_AMOUNT:
    tokens = self.find_token_transfers(tx, tx.transaction.message.account_keys)
    if len(tokens) >= 2:
        swap_data = {
            "slot": slot,
            "program_id": str(tx.transaction.message.account_keys[0]),
            "swap_amount": sol_change,
            "input_token_address": tokens[0]["address"],
            "input_token_symbol": tokens[0]["symbol"],
            "output_token_address": tokens[-1]["address"],
            "output_token_symbol": tokens[-1]["symbol"],
            "timestamp": time.time()
        }
        self.save_swap(swap_data)
```

- `sol_change > 50 SOL` 代表這筆交易的 SOL 變化超過 50，才會被記錄。  
- 解析出 **輸入代幣** 和 **輸出代幣**，儲存到數據庫。

---

## 5. 儲存交易資訊到 SQLite

當監測到符合條件的交易時，程式會將數據存入 SQLite 資料庫。

```python
def save_swap(self, swap_data: dict):
    df = pd.DataFrame([swap_data])
    df.to_sql('swaps', self.engine, if_exists='append', index=False)
    logger.info(
        f"保存交易: {swap_data['swap_amount']:.2f} SOL - "
        f"{swap_data['input_token_symbol']} -> {swap_data['output_token_symbol']}"
    )
```

- 透過 **Pandas** 寫入 SQLite 數據庫，方便日後分析。  
- 記錄的交易數據包含：區塊高度（slot）、交易的 SOL 數量、輸入代幣、輸出代幣、交易時間戳。

---

## 6. 定期刷新代幣快取

Solana 代幣的名稱和符號可能會更新，因此程式會定期刷新代幣快取，確保數據最新。

```python
def refresh_token_cache(self):
    response = requests.get(Config.JUPITER_TOKEN_API, timeout=10)
    if response.status_code == 200:
        self.token_cache = {token["address"]: token for token in response.json()}
        self.last_cache_refresh = time.time()
```

- 透過 **Jupiter API** 取得最新的代幣資訊，並快取到 `self.token_cache`。

---

## 7. 監測 Solana 最新交易

程式會每秒檢查最新的 Solana 區塊，並過濾出符合條件的交易。

```python
async def monitor_transactions(self):
    while True:
        current_slot = self.client.get_slot().value
        for slot in range(current_slot - 5, current_slot + 1):
            block = self.client.get_block(slot, max_supported_transaction_version=0).value
            for tx in block.transactions:
                sol_change = max(abs((post - pre) / 1e9) for pre, post in zip(tx.meta.pre_balances, tx.meta.post_balances))
                if sol_change > Config.MIN_SWAP_AMOUNT:
                    tokens = self.find_token_transfers(tx, tx.transaction.message.account_keys)
                    if len(tokens) >= 2:
                        swap_data = {
                            "slot": slot,
                            "program_id": str(tx.transaction.message.account_keys[0]),
                            "swap_amount": sol_change,
                            "input_token_address": tokens[0]["address"],
                            "input_token_symbol": tokens[0]["symbol"],
                            "output_token_address": tokens[-1]["address"],
                            "output_token_symbol": tokens[-1]["symbol"],
                            "timestamp": time.time()
                        }
                        self.save_swap(swap_data)
        await asyncio.sleep(1)

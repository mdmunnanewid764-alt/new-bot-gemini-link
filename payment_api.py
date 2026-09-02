import os
import httpx
import logging
from typing import Optional, Dict, Any
from dotenv import load_dotenv
import database

load_dotenv()

DEFAULT_GATEWAY_URL = "https://binance-api-yrz4.onrender.com/api/v1"
logger = logging.getLogger(__name__)

# Smart contract addresses
USDT_BEP20 = "0x55d398326f99059ff775485246999027b3197955" # 18 decimals
USDT_TRC20_HEX = "41a614f803b6fd780986a42c78ec9c7f77e6ded13c" # 6 decimals
USDT_ERC20 = "0xdac17f958d2ee523a2206206994597c13d831ec7" # 6 decimals

BSC_RPCS = [
    "https://bsc-rpc.publicnode.com",
    "https://binance.llamarpc.com",
    "https://bsc-dataseed1.binance.org"
]

ETH_RPCS = [
    "https://ethereum-rpc.publicnode.com",
    "https://eth.llamarpc.com"
]

class PaymentAPIError(Exception):
    def __init__(self, message: str, status_code: int = 500, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data or {}

class PaymentAPIClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("BINANCE_PAY_BASE_URL") or DEFAULT_GATEWAY_URL).rstrip("/")

    async def get_api_key(self) -> Optional[str]:
        """Fetch merchant API key from database setting or .env."""
        key = await database.get_setting("binance_pay_api_key")
        if not key:
            key = os.getenv("BINANCE_PAY_API_KEY")
        return key.strip() if key else None

    async def _get_headers(self) -> Dict[str, str]:
        key = await self.get_api_key()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["x-api-key"] = key
        return headers

    async def verify_onchain_bep20(self, tx_hash: str, expected_to: str, expected_amount: float) -> Dict[str, Any]:
        """Directly verify BEP20 USDT transaction on BSC blockchain."""
        tx_hash = tx_hash.strip()
        if not tx_hash.startswith("0x"):
            tx_hash = "0x" + tx_hash

        payload = {
            "jsonrpc": "2.0",
            "method": "eth_getTransactionReceipt",
            "params": [tx_hash],
            "id": 1
        }

        for rpc in BSC_RPCS:
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    res = await client.post(rpc, json=payload)
                    if res.status_code != 200:
                        continue
                    data = res.json()
                    receipt = data.get("result")
                    if not receipt:
                        continue

                    # Check status (0x1 is success)
                    if receipt.get("status") != "0x1":
                        return {"success": False, "reason": "Transaction failed or reverted on BSC"}

                    # Parse logs for USDT transfer
                    transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
                    for log in receipt.get("logs", []):
                        if log.get("address", "").lower() == USDT_BEP20:
                            topics = log.get("topics", [])
                            if len(topics) >= 3 and topics[0].lower() == transfer_topic:
                                recipient = "0x" + topics[2][-40:].lower()
                                raw_amount = int(log.get("data", "0x0"), 16)
                                actual_amount = raw_amount / (10 ** 18)

                                expected_clean = expected_to.strip().lower()
                                if expected_clean and recipient != expected_clean:
                                    continue # transfer wasn't to admin's wallet

                                if actual_amount >= (expected_amount - 0.05):
                                    # Security Check: Verify Block Timestamp (Prevent Replay of Old Past TxHashes)
                                    import time
                                    block_num = receipt.get("blockNumber")
                                    block_payload = {
                                        "jsonrpc": "2.0",
                                        "method": "eth_getBlockByNumber",
                                        "params": [block_num, False],
                                        "id": 2
                                    }
                                    b_res = await client.post(rpc, json=block_payload)
                                    if b_res.status_code == 200:
                                        b_data = b_res.json().get("result", {})
                                        ts_hex = b_data.get("timestamp")
                                        if ts_hex:
                                            block_ts = int(ts_hex, 16)
                                            now_ts = int(time.time())
                                            # If transaction was confirmed more than 2 hours (7200s) ago, reject!
                                            if (now_ts - block_ts) > 7200:
                                                logger.warning(f"Rejected old TxHash {tx_hash}: Block age {(now_ts - block_ts)/3600:.1f} hours old")
                                                return {"success": False, "reason": "Transaction timestamp is too old (expired). Old past transactions cannot be reused."}

                                    return {
                                        "success": True,
                                        "status": "PAID",
                                        "amount": actual_amount,
                                        "tx_hash": tx_hash,
                                        "network": "BEP20"
                                    }
            except Exception as e:
                logger.warning(f"Error checking BSC RPC {rpc}: {e}")
                continue

        return {"success": False, "reason": "Transaction not found on BSC or details do not match"}

    async def verify_onchain_tron(self, tx_hash: str, expected_to: str, expected_amount: float) -> Dict[str, Any]:
        """Directly verify TRC20 USDT transaction on TRON blockchain."""
        import time
        tx_hash = tx_hash.strip().replace("0x", "")
        url = "https://api.trongrid.io/wallet/gettransactioninfobyid"
        payload = {"value": tx_hash}

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    receipt = data.get("receipt", {})
                    if receipt.get("result") == "SUCCESS":
                        # Security Check: Verify Block Timestamp (Prevent Replay of Old Past TxHashes)
                        block_ts_ms = data.get("blockTimeStamp", 0)
                        if block_ts_ms:
                            block_ts = block_ts_ms / 1000
                            now_ts = time.time()
                            if (now_ts - block_ts) > 7200:
                                logger.warning(f"Rejected old TRON TxHash {tx_hash}: Block age {(now_ts - block_ts)/3600:.1f} hours old")
                                return {"success": False, "reason": "Transaction timestamp is too old (expired). Old past transactions cannot be reused."}

                        for log in data.get("log", []):
                            # Check USDT contract address in hex
                            if log.get("address", "").lower() == USDT_TRC20_HEX:
                                raw_amt = int(log.get("data", "0"), 16)
                                actual_amount = raw_amt / (10 ** 6) # TRC20 is 6 decimals
                                if actual_amount >= (expected_amount - 0.05):
                                    return {
                                        "success": True,
                                        "status": "PAID",
                                        "amount": actual_amount,
                                        "tx_hash": tx_hash,
                                        "network": "TRC20"
                                    }
        except Exception as e:
            logger.warning(f"Error checking TRON API: {e}")

        return {"success": False, "reason": "Transaction not found on TRON or details do not match"}

    async def verify_onchain_erc20(self, tx_hash: str, expected_to: str, expected_amount: float) -> Dict[str, Any]:
        """Directly verify ERC20 USDT transaction on Ethereum blockchain."""
        import time
        tx_hash = tx_hash.strip()
        if not tx_hash.startswith("0x"):
            tx_hash = "0x" + tx_hash

        payload = {
            "jsonrpc": "2.0",
            "method": "eth_getTransactionReceipt",
            "params": [tx_hash],
            "id": 1
        }

        for rpc in ETH_RPCS:
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    res = await client.post(rpc, json=payload)
                    if res.status_code != 200:
                        continue
                    data = res.json()
                    receipt = data.get("result")
                    if not receipt:
                        continue

                    if receipt.get("status") != "0x1":
                        return {"success": False, "reason": "Transaction failed on Ethereum"}

                    transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
                    for log in receipt.get("logs", []):
                        if log.get("address", "").lower() == USDT_ERC20:
                            topics = log.get("topics", [])
                            if len(topics) >= 3 and topics[0].lower() == transfer_topic:
                                recipient = "0x" + topics[2][-40:].lower()
                                raw_amount = int(log.get("data", "0x0"), 16)
                                actual_amount = raw_amount / (10 ** 6) # ERC20 USDT is 6 decimals

                                expected_clean = expected_to.strip().lower()
                                if expected_clean and recipient != expected_clean:
                                    continue

                                if actual_amount >= (expected_amount - 0.05):
                                    # Timestamp verification
                                    block_num = receipt.get("blockNumber")
                                    block_payload = {
                                        "jsonrpc": "2.0",
                                        "method": "eth_getBlockByNumber",
                                        "params": [block_num, False],
                                        "id": 2
                                    }
                                    b_res = await client.post(rpc, json=block_payload)
                                    if b_res.status_code == 200:
                                        b_data = b_res.json().get("result", {})
                                        ts_hex = b_data.get("timestamp")
                                        if ts_hex:
                                            block_ts = int(ts_hex, 16)
                                            now_ts = int(time.time())
                                            if (now_ts - block_ts) > 7200:
                                                return {"success": False, "reason": "Transaction timestamp is too old (expired)."}

                                    return {
                                        "success": True,
                                        "status": "PAID",
                                        "amount": actual_amount,
                                        "tx_hash": tx_hash,
                                        "network": "ERC20"
                                    }
            except Exception as e:
                logger.warning(f"Error checking Ethereum RPC {rpc}: {e}")
                continue

        return {"success": False, "reason": "Transaction not found on Ethereum"}

    async def create_payment(
        self,
        amount: float,
        currency: str = "USDT",
        goods_name: str = "Bot Balance Deposit",
        goods_detail: str = "Automated Deposit",
        merchant_trade_no: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a payment order supporting Binance Pay and Multi-Chain wallets."""
        headers = await self._get_headers()
        payload = {
            "orderAmount": f"{amount:.2f}",
            "currency": currency,
            "goodsName": goods_name,
            "goodsDetail": goods_detail,
            "merchantTradeNo": merchant_trade_no
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(f"{self.base_url}/payments/create", headers=headers, json=payload)
            data = res.json()
            if res.status_code in (200, 201) and data.get("success"):
                return data.get("order", {})
            msg = data.get("message") or "Payment creation failed"
            raise PaymentAPIError(msg, status_code=res.status_code, data=data)

    async def get_payment_status(self, merchant_trade_no: str) -> Dict[str, Any]:
        """Query real-time status of a payment order."""
        headers = await self._get_headers()
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/payments/{merchant_trade_no}", headers=headers)
            data = res.json()
            if res.status_code == 200 and data.get("success"):
                return data.get("order", {})
            msg = data.get("message") or "Failed to fetch payment status"
            raise PaymentAPIError(msg, status_code=res.status_code, data=data)

    async def submit_tx(self, merchant_trade_no: str, network: str, tx_hash: str) -> Dict[str, Any]:
        """
        Verify transaction:
        1. Check Binance Account Direct Deposit History (Supports off-chain transfers & on-chain txId)
        2. Direct fast on-chain blockchain verification (BSC, TRON, ETH)
        3. Fallback to Gateway API if configured.
        """
        from binance_api import BinanceAPIClient
        binance_client = BinanceAPIClient()

        rec = await database.get_deposit_record(merchant_trade_no)
        expected_amount = rec["amount"] if rec else 0.0
        net = network.upper()
        clean_tx = tx_hash.strip()

        # ── 1. Check Binance Account Deposit History ──
        try:
            binance_deposits = await binance_client.get_recent_deposits(coin="USDT", limit=30)
            for d in binance_deposits:
                d_tx_id = str(d.get("txId", "")).strip()
                d_status = d.get("status")
                # Matches exact or substring (e.g. 'Off-chain transfer 405469248638' matches '405469248638')
                if clean_tx and (clean_tx in d_tx_id or d_tx_id == clean_tx):
                    if d_status == 1: # 1 means success on Binance
                        # Security Check: Ensure TxID was not already credited in any other invoice
                        is_already_credited = await database.is_txhash_used(d_tx_id, current_trade_no=merchant_trade_no)
                        if is_already_credited:
                            logger.warning(f"Anti-Fraud: Blocked reused Binance TxID {d_tx_id} on invoice {merchant_trade_no}")
                            return {"success": False, "status": "REJECTED_DUPLICATE", "reason": "Transaction has already been used and credited."}

                        actual_amt = float(d.get("amount", expected_amount))
                        return {
                            "success": True,
                            "status": "PAID",
                            "amount": actual_amt,
                            "tx_hash": d_tx_id,
                            "network": d.get("network", net)
                        }
        except Exception as be:
            logger.warning(f"Error checking Binance deposit history: {be}")

        # Security Check: Ensure clean_tx is not already credited before on-chain checks
        if await database.is_txhash_used(clean_tx, current_trade_no=merchant_trade_no):
            logger.warning(f"Anti-Fraud: Blocked reused TxHash {clean_tx} on invoice {merchant_trade_no}")
            return {"success": False, "status": "REJECTED_DUPLICATE", "reason": "Transaction hash has already been credited."}

        # ── 2. Check On-Chain Blockchain RPCs ──
        wallet_address = ""
        if net == "BEP20":
            wallet_address = await database.get_setting("wallet_bep20") or ""
            onchain_res = await self.verify_onchain_bep20(clean_tx, wallet_address, expected_amount)
            if onchain_res.get("success"):
                return onchain_res

        elif net == "TRC20":
            wallet_address = await database.get_setting("wallet_trc20") or ""
            onchain_res = await self.verify_onchain_tron(clean_tx, wallet_address, expected_amount)
            if onchain_res.get("success"):
                return onchain_res

        elif net == "ERC20":
            wallet_address = await database.get_setting("wallet_erc20") or ""
            onchain_res = await self.verify_onchain_erc20(clean_tx, wallet_address, expected_amount)
            if onchain_res.get("success"):
                return onchain_res

        # ── 3. Fallback to Gateway API ──
        try:
            headers = await self._get_headers()
            payload = {
                "merchantTradeNo": merchant_trade_no,
                "network": net,
                "txHash": clean_tx
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(f"{self.base_url}/payments/submit-tx", headers=headers, json=payload)
                data = res.json()
                if res.status_code == 200 and data.get("success"):
                    return data.get("order", data)
        except Exception:
            pass

        return {"success": False, "status": "PENDING_VERIFICATION"}


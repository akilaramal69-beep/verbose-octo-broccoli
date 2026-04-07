#!/usr/bin/env python3
"""
Trade Execution Component
Handles buying and selling with dynamic fees and Jito bundles
"""

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum
import aiohttp
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey
from solders.message import Message
from solders.instruction import Instruction, AccountMeta
from solders.system_program import TransferParams, transfer

from config import config

logger = logging.getLogger(__name__)

class TradeStatus(Enum):
    PENDING = "pending"
    BUYING = "buying"
    BOUGHT = "bought"
    SELLING = "selling"
    SOLD = "sold"
    FAILED = "failed"

@dataclass
class TradePosition:
    mint: str
    entry_price: float
    amount_sol: float
    amount_tokens: float
    status: TradeStatus = TradeStatus.PENDING
    sold_portion_1: bool = False
    trailing_high: float = 0.0
    created_at: float = field(default_factory=time.time)
    signature: str = ""

class TradeExecutor:
    def __init__(self, wallet):
        self.wallet = wallet
        self.session: Optional[aiohttp.ClientSession] = None
        self.positions: Dict[str, TradePosition] = {}
        self.current_fees: float = config.MIN_PRIORITY_FEE
        self.last_fee_update: float = 0
        
    async def _get_session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
        
    async def _update_dynamic_fees(self):
        current_time = time.time()
        if current_time - self.last_fee_update < 10:
            return
            
        try:
            session = await self._get_session()
            url = f"{config.RPC_URL}?api-key={config.HELIUS_API_KEY}"
            
            async with session.post(url, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getRecentPrioritizedFees"
            }) as resp:
                data = await resp.json()
                
                if "result" in data:
                    avg_fee = data["result"].get("median", config.MIN_PRIORITY_FEE)
                    self.current_fees = min(
                        max(avg_fee, config.MIN_PRIORITY_FEE),
                        config.MAX_PRIORITY_FEE
                    )
                    
            self.last_fee_update = current_time
            
        except Exception as e:
            logger.debug(f"Fee update failed: {e}")
            self.current_fees = config.MIN_PRIORITY_FEE
            
    async def execute_buy(
        self, 
        mint: str, 
        bonding_curve: str,
        amount_sol: float = None
    ) -> Optional[TradePosition]:
        if amount_sol is None:
            amount_sol = config.TRADE_AMOUNT_SOL
            
        await self._update_dynamic_fees()
        
        position = TradePosition(
            mint=mint,
            entry_price=0,
            amount_sol=amount_sol,
            amount_tokens=0,
            status=TradeStatus.BUYING
        )
        self.positions[mint] = position
        
        try:
            swap_ix = await self._build_swap_instruction(
                mint,
                bonding_curve,
                amount_sol,
                is_buy=True
            )
            
            priority_fee_ix = self._build_priority_fee_instruction()
            
            recent_blockhash = await self._get_recent_blockhash()
            
            instructions = [priority_fee_ix, swap_ix]
            
            tx = self._create_transaction(instructions, recent_blockhash)
            
            position.signature = await self._send_via_jito(tx)
            
            if position.signature:
                await self._confirm_transaction(position.signature)
                
                position.status = TradeStatus.BOUGHT
                position.entry_price = await self._get_token_price(mint)
                position.amount_tokens = amount_sol / position.entry_price
                
                logger.info(f"Buy executed: {mint} @ {position.entry_price}")
                return position
                
        except Exception as e:
            logger.error(f"Buy failed: {e}")
            position.status = TradeStatus.FAILED
            
        return None
        
    async def _build_swap_instruction(
        self,
        mint: str,
        bonding_curve: str,
        amount: float,
        is_buy: bool
    ) -> Instruction:
        pump_fun_program = Pubkey.from_string(config.PUMP_FUN_PROGRAM)
        
        data = base64.b64decode("MS4w")
        if is_buy:
            data += base64.b64decode("AA==")
        else:
            data += base64.b64decode("AQ==")
            
        amount_lamports = int(amount * 1_000_000_000)
        amount_bytes = amount_lamports.to_bytes(8, "little")
        data += amount_bytes
        
        accounts = [
            AccountMeta(pubkey=Pubkey.from_string(bonding_curve), is_signer=False, is_writable=True),
            AccountMeta(pubkey=Pubkey.from_string(mint), is_signer=False, is_writable=True),
            AccountMeta(pubkey=self.wallet.public_key, is_signer=True, is_writable=True),
            AccountMeta(pubkey=Pubkey.from_string("11111111111111111111111111111111"), is_signer=False, is_writable=False),
        ]
        
        return Instruction(pump_fun_program, data, accounts)
        
    def _build_priority_fee_instruction(self) -> Instruction:
        return transfer(TransferParams(
            from_pubkey=self.wallet.public_key,
            to_pubkey=self.wallet.public_key,
            lamports=int(self.current_fees * 1_000_000_000)
        ))
        
    async def _get_recent_blockhash(self) -> str:
        session = await self._get_session()
        url = f"{config.RPC_URL}?api-key={config.HELIUS_API_KEY}"
        
        async with session.post(url, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash"
        }) as resp:
            data = await resp.json()
            return data["result"]["value"]["blockhash"]
            
    def _create_transaction(self, instructions: List[Instruction], blockhash: str) -> str:
        message = Message.new_with_blockhash(
            instructions,
            self.wallet.public_key,
            blockhash
        )
        
        tx = VersionedTransaction(message, [])
        
        return base64.b64encode(bytes(tx)).decode()
        
    async def _send_via_jito(self, tx_base64: str) -> Optional[str]:
        bundle = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [[tx_base64]]
        }
        
        for endpoint in config.JITO_ENDPOINTS:
            try:
                session = await self._get_session()
                async with session.post(endpoint, json=bundle) as resp:
                    result = await resp.json()
                    
                    if "result" in result:
                        logger.info(f"Bundle sent via Jito: {endpoint}")
                        return result["result"][0]
                        
            except Exception as e:
                logger.debug(f"Jito send failed ({endpoint}): {e}")
                
        return await self._send_via_rpc(tx_base64)
        
    async def _send_via_rpc(self, tx_base64: str) -> Optional[str]:
        session = await self._get_session()
        url = f"{config.RPC_URL}?api-key={config.HELIUS_API_KEY}"
        
        async with session.post(url, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                tx_base64,
                {"skipPreflight": True, "maxRetries": 3}
            ]
        }) as resp:
            data = await resp.json()
            if "result" in data:
                return data["result"]
        return None
        
    async def _confirm_transaction(self, signature: str, timeout: int = 30) -> bool:
        start = time.time()
        
        while time.time() - start < timeout:
            try:
                session = await self._get_session()
                url = f"{config.RPC_URL}?api-key={config.HELIUS_API_KEY}"
                
                async with session.post(url, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignatureStatuses",
                    "params": [[signature]]
                }) as resp:
                    data = await resp.json()
                    
                    if "result" in data:
                        status = data["result"]["value"][0]
                        if status:
                            return status.get("confirmationStatus") == "finalized" or status.get("slot")
                            
            except Exception as e:
                logger.debug(f"Confirmation check failed: {e}")
                
            await asyncio.sleep(0.5)
            
        return False
        
    async def _get_token_price(self, mint: str) -> float:
        try:
            session = await self._get_session()
            url = f"https://quote-api.jup.ag/v6/price?ids={mint}"
            
            resolver = config.DNS_RESOLVER.get("quote-api.jup.ag")
            if resolver:
                async with session.get(url, headers={"Host": "quote-api.jup.ag"}) as resp:
                    data = await resp.json()
                    if mint in data:
                        return float(data[mint]["price"])
        except Exception:
            pass
        return 0.000001
        
    async def execute_sell(self, mint: str, percentage: float = 1.0) -> bool:
        position = self.positions.get(mint)
        if not position or position.status != TradeStatus.BOUGHT:
            return False
            
        try:
            amount_tokens = position.amount_tokens * percentage
            
            swap_ix = await self._build_swap_instruction(
                mint,
                position.mint,
                amount_tokens,
                is_buy=False
            )
            
            priority_fee_ix = self._build_priority_fee_instruction()
            
            recent_blockhash = await self._get_recent_blockhash()
            
            tx = self._create_transaction([priority_fee_ix, swap_ix], recent_blockhash)
            
            signature = await self._send_via_jito(tx)
            
            if signature:
                await self._confirm_transaction(signature)
                logger.info(f"Sell executed: {mint} ({percentage*100:.0f}%)")
                return True
                
        except Exception as e:
            logger.error(f"Sell failed: {e}")
            
        return False
        
    async def monitor_and_exit(self, mint: str, bot_callback=None):
        position = self.positions.get(mint)
        if not position:
            return
            
        while position.status == TradeStatus.BOUGHT:
            try:
                current_price = await self._get_token_price(mint)
                
                if current_price > position.trailing_high:
                    position.trailing_high = current_price
                    
                pnl_pct = (current_price - position.entry_price) / position.entry_price
                
                if not position.sold_portion_1 and pnl_pct >= config.PROFIT_TARGET_1:
                    await self.execute_sell(mint, config.SELL_PORTION_1)
                    position.sold_portion_1 = True
                    
                    if bot_callback:
                        await bot_callback(
                            f"💰 PARTIAL PROFIT: {config.PROFIT_TARGET_1*100:.0f}% | Sold {config.SELL_PORTION_1*100:.0f}%"
                        )
                        
                trailing_stop = position.trailing_high * (1 + config.TRAILING_STOP_LOSS)
                if position.sold_portion_1 and current_price <= trailing_stop:
                    await self.execute_sell(mint, 1.0 - config.SELL_PORTION_1)
                    position.status = TradeStatus.SOLD
                    
                    if bot_callback:
                        await bot_callback(
                            f"💰 PROFIT TAKEN: +{(pnl_pct)*100:.0f}% | Status: EXIT COMPLETE"
                        )
                        
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                
            await asyncio.sleep(2)
            
    async def get_sol_balance(self) -> float:
        try:
            session = await self._get_session()
            url = f"{config.RPC_URL}?api-key={config.HELIUS_API_KEY}"
            
            async with session.post(url, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [str(self.wallet.public_key)]
            }) as resp:
                data = await resp.json()
                if "result" in data:
                    return data["result"]["value"] / 1_000_000_000
        except Exception as e:
            logger.error(f"Balance check failed: {e}")
        return 0.0
        
    async def close(self):
        if self.session:
            await self.session.close()

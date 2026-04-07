#!/usr/bin/env python3
"""
Telegram Bot Interface
Commands and real-time notifications for the sniper bot
"""

import asyncio
import logging
import json
import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any, Callable

from config import config

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.session: Optional[aiohttp.ClientSession] = None
        self.update_offset = 0
        self.running = False
        self.handlers: Dict[str, Callable] = {}
        self.stats = {
            "total_trades": 0,
            "successful_trades": 0,
            "failed_trades": 0,
            "total_profit_sol": 0.0,
            "active_positions": 0
        }
        
    async def _get_session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
        
    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        if not self.token or not self.chat_id:
            logger.warning("Telegram not configured")
            return False
            
        try:
            session = await self._get_session()
            url = f"{self.base_url}/sendMessage"
            
            async with session.post(url, json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode
            }) as resp:
                return resp.status == 200
                
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False
            
    async def send_alert(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_message = f"[{timestamp}] {message}"
        await self.send_message(full_message)
        
    async def handle_new_token(self, mint: str, score: int, dev_holding: float, status: str):
        message = (
            f"🚀 *NEW SNIPE*\n"
            f"Mint: `{mint[:8]}...{mint[-4:]}`\n"
            f"Score: {score}/100\n"
            f"Dev Holding: {dev_holding:.1f}%\n"
            f"Status: {status}"
        )
        await self.send_message(message)
        
    async def handle_profit_taken(self, mint: str, profit_pct: float, amount_usd: float):
        message = (
            f"💰 *PROFIT TAKEN*\n"
            f"+{profit_pct:.0f}% | ${amount_usd:.2f} Realized\n"
            f"Mint: `{mint[:8]}...{mint[-4:]}`"
        )
        await self.send_message(message)
        
    async def handle_trade_failed(self, mint: str, reason: str):
        message = (
            f"❌ *TRADE FAILED*\n"
            f"Mint: `{mint[:8]}...{mint[-4:]}`\n"
            f"Reason: {reason}"
        )
        await self.send_message(message)
        
    async def handle_start_command(self) -> str:
        balance = await self._get_wallet_balance()
        active = self.stats["active_positions"]
        
        return (
            "🤖 *PUMP.FUN SNIPER BOT*\n\n"
            f"💧 SOL Balance: {balance:.4f}\n"
            f"📊 Active Trades: {active}\n"
            f"✅ Total Trades: {self.stats['successful_trades']}\n"
            f"❌ Failed: {self.stats['failed_trades']}\n"
            f"💰 Total Profit: {self.stats['total_profit_sol']:.4f} SOL\n\n"
            "Commands:\n"
            "/start - Show stats\n"
            "/status - Bot status\n"
            "/trades - Trade history"
        )
        
    async def handle_status_command(self) -> str:
        status = "🟢 ONLINE" if self.running else "🔴 OFFLINE"
        
        return (
            f"*Bot Status:* {status}\n"
            f"*WebSocket:* {'Connected' if self.running else 'Disconnected'}\n"
            f"*Scanner:* {'Active' if self.running else 'Inactive'}"
        )
        
    async def handle_trades_command(self) -> str:
        trades_text = []
        
        trades_text.append(f"*Recent Trades:*\n")
        trades_text.append(f"Total: {self.stats['total_trades']}")
        trades_text.append(f"Win Rate: {self._calculate_win_rate():.0f}%")
        
        return "\n".join(trades_text)
        
    def _calculate_win_rate(self) -> float:
        total = self.stats['successful_trades'] + self.stats['failed_trades']
        if total == 0:
            return 0
        return (self.stats['successful_trades'] / total) * 100
        
    async def _get_wallet_balance(self) -> float:
        try:
            session = await self._get_session()
            url = f"{config.RPC_URL}?api-key={config.HELIUS_API_KEY}"
            
            async with session.post(url, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [config.WALLET_PRIVATE_KEY[:44]]
            }) as resp:
                data = await resp.json()
                if "result" in data:
                    return data["result"]["value"] / 1_000_000_000
        except Exception:
            pass
        return 0.0
        
    async def register_handler(self, command: str, handler: Callable):
        self.handlers[command] = handler
        
    async def poll_updates(self):
        self.running = True
        
        while self.running:
            try:
                session = await self._get_session()
                url = f"{self.base_url}/getUpdates"
                
                async with session.get(url, params={
                    "offset": self.update_offset,
                    "timeout": 30
                }) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        if data.get("ok") and data.get("result"):
                            for update in data["result"]:
                                await self._process_update(update)
                                self.update_offset = update["update_id"] + 1
                                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Poll error: {e}")
                await asyncio.sleep(5)
                
    async def _process_update(self, update: Dict[str, Any]):
        if "message" not in update:
            return
            
        message = update["message"]
        if "text" not in message:
            return
            
        command = message["text"].strip().lower()
        chat_id = message["chat"]["id"]
        
        if chat_id != int(config.TELEGRAM_CHAT_ID) if config.TELEGRAM_CHAT_ID else True:
            return
            
        response = ""
        
        if command == "/start":
            response = await self.handle_start_command()
        elif command == "/status":
            response = await self.handle_status_command()
        elif command == "/trades":
            response = await self.handle_trades_command()
            
        if response:
            await self.send_message(response)
            
    async def start_polling(self):
        asyncio.create_task(self.poll_updates())
        
    async def stop(self):
        self.running = False
        if self.session:
            await self.session.close()
            
    def update_stats(self, **kwargs):
        for key, value in kwargs.items():
            if key in self.stats:
                self.stats[key] = value

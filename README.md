# Pump.fun Solana Sniper Bot

High-speed algorithmic trading bot for Pump.fun tokens with Dev Trust scoring, deployed on Koyeb free tier.

## Features

- **Real-time Detection** - Subscribes to Helius WebSocket for instant new token alerts
- **Dev Trust Scoring** - Filters honeypots and pump-and-dump tokens
- **Lightning Fast Execution** - Dynamic priority fees + Jito bundles
- **Smart Exits** - 2-Step profit taking with trailing stop-loss
- **Telegram Alerts** - Live notifications for every action

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    TELEGRAM BOT                         │
│  /start | Alerts | Trade History                       │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│                     MAIN (Orchestrator)                 │
│  - Coordinates all components                          │
│  - Handles signals (graceful shutdown)                  │
└───────┬─────────────────────┬─────────────────────────┘
        │                     │
┌───────▼───────┐     ┌───────▼───────┐
│   SCANNER     │     │    TRADE      │
│  WebSocket    │     │   EXECUTOR    │
│  - Log Sub    │     │  - Jito       │
│  - Parse TX   │     │  - Fees       │
└───────┬───────┘     └───────┬───────┘
        │                     │
┌───────▼─────────────────────▼───────┐
│              ALGO                    │
│  Scoring Engine                      │
│  - Mint Auth Check                   │
│  - Dev Buy %                         │
│  - Creator History                   │
└─────────────────────────────────────┘
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `HELIUS_API_KEY` | Helius RPC API key | Required |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | Required |
| `TELEGRAM_CHAT_ID` | Your chat ID | Required |
| `WALLET_PRIVATE_KEY` | Base58 private key | Required |
| `TRADE_AMOUNT_SOL` | Amount per trade | 0.065 |
| `RPC_URL` | Custom RPC | Helius mainnet |
| `WSS_URL` | Custom WebSocket | Helius mainnet |

## Scoring Logic

| Check | Condition | Action |
|-------|-----------|--------|
| Mint Authority | `present` | **Score = 0** (Honeypot) |
| Dev Buy % | `> 15%` | **Score -= 50** (High Risk) |
| Creator History | `> 3 coins/hour` | **Score = 0** (Dumper) |

## Exit Strategy

```
Step 1: Sell 50% at +50% profit
Step 2: Sell remaining 50% at -20% trailing stop
```

## Installation

```bash
# Clone repository
git clone https://github.com/your-username/pump-sniper.git
cd pump-sniper

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env  # Add your keys

# Run locally
python main.py
```

## Docker

```bash
# Build
docker build -t pump-sniper .

# Run
docker run -d \
  --env-file .env \
  --name sniper \
  pump-sniper
```

## Koyeb Deployment

1. Fork this repository to GitHub
2. Go to [app.koyeb.com](https://app.koyeb.com)
3. Click "Create App" → "GitHub"
4. Select your repo and branch
5. Add environment variables:
   - `HELIUS_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `WALLET_PRIVATE_KEY`
6. Deploy (free tier: 0.1 vCPU, 512MB RAM)

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Show bot stats and balance |
| `/status` | Check bot health |
| `/trades` | View trade history |

## Telegram Alerts

```
🚀 NEW SNIPE: 7x9K...f3p | Score: 85/100 | Dev: 2% | Status: BUYING...
💰 PROFIT TAKEN: +25% | $12.50 Realized
❌ TRADE FAILED: Transaction rejected
```

## File Structure

```
pump-sniper/
├── config.py       # All configuration
├── scanner.py      # Helius WebSocket subscription
├── algo.py         # Dev Trust scoring engine
├── trade.py        # Buy/sell execution
├── bot.py          # Telegram interface
├── wallet.py       # Key management
├── main.py         # Entry point
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── koyeb.yaml
└── .env.example
```

## Dependencies

- `solana>=0.30.0` - Solana SDK
- `solders>=0.18.0` - Solana primitives
- `aiohttp>=3.9.0` - Async HTTP/WS
- `pysocks>=1.7.1` - DNS fallback (optional)

## Safety Features

- **Stablecoin Shield** - USDC/USDT whitelisted, no swaps
- **DNS Resolver** - Fallback to 1.1.1.1 for Jupiter API
- **Circuit Breaker** - Rejects tokens with bad scores
- **Confirmation Tracking** - Waits for finality before proceeding

## Disclaimer

This software is for educational purposes. Trading cryptocurrencies involves significant risk. The authors are not responsible for any financial losses.

## License

MIT License

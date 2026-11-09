# White Label: Easy Country & Game Swapping

## Overview
The white label module enables quick configuration changes for different countries and games without code changes. All configurations are YAML-based.

## Created Files

### 1. `configs/geos/BR.yaml` - Brazil Geo Configuration
```yaml
geo: "BR"
rails: ["pix_br"]
min_deposit_minor: 1
max_deposit_minor: 100000000
currency_display: "BRL"
kyc: "none"
```
- Defines Brazil as a geo with PIX payment rail
- PIX is Brazil's instant payment system

### 2. `configs/tenants/br.yaml` - Brazil Tenant Configuration
```yaml
tenant: "br"
brand:
  name: "CasePlatform BR"
  logo_url: ""
  primary_color: "#101014"
domains:
  frontend: ""
  api: ""
games:
  - game_key: "roblox"
    enabled: true
    rtp_profile: {}
geos:
  - geo: "BR"
    enabled: true
    rails: ["pix_br"]
    currency_display: "BRL"
    kyc: "none"
    min_deposit_minor: 1
    max_deposit_minor: 100000000
```
- Tenant 'br' includes Roblox game and Brazil geo
- Enables the full Brazil/Roblox flow

### 3. `configs/games/roblox.yaml` - Roblox Game Configuration
```yaml
game_key: "roblox"
display_name: "Roblox"
rtp_base: 0.90
allowed_modifiers: ["f_win", "f_bet"]
prize_catalog_path: "configs/games/roblox/prizes.yaml"
unit_name: "units"
withdraw_min_minor: 15000
```
- Configures Roblox game with base RTP 90%
- Specifies allowed modifiers (f_win, f_bet) - these will be applied via the fallback mechanism
- Links to prize catalog

## How Easy Swapping Works

### Change Country
Modify the `geos` section in any tenant config:
- Current: Brazil (BR) with pix_br rail
- To switch: just change `geo: "BR"` to `geo: "NG"` and update rails

### Change Game
Modify the `games` section in any tenant config:
- Current: Roblox game
- To switch: replace `game_key: "roblox"` with `game_key: "mlbb"` or any registered game

### Add New Game/Payment
1. Create plugin adapter with `MANIFEST` and `register()` function
2. Add game config in `configs/games/{key}.yaml`
3. Add geo config in `configs/geos/{geo}.yaml`
4. Add/update tenant config

## Plugin Registry Pattern
All games and payments are registered in the central `core.registry.registry.registry`:
- Games: roblox, mlbb, pubgm, crash, mines, standoff2, etc.
- Payments: crypto_usdt, pix_br, qris_id, spei_mx, etc.
- Prizes: giftcard_pool, uid_topup, etc.

Each plugin has `MANIFEST = {"key": "...", "type": "...", "geo": ...}` and a `register(reg)` function.

## Usage Example
To add a new country/game combo:
1. `python -c "from plugins.games.demo_game.plugin import DemoGame; from core.registry.registry import registry; registry.register(DemoGame())"`
2. Create `configs/geos/NEW.yaml`
3. Create/Update `configs/tenants/NEW_TENANT.yaml`

The system is fully dynamic - no code redeployment needed for config changes.
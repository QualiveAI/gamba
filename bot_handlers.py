[P] BOT HANDLERS — Created for the complete stack.

## Bot Handler Commands

### /start
- Checks if user is in bot_pool database
- If not registered: registers user, sets warmup_until = now + 24h, adds to active users
- If registered and warmup passed: shows main menu
- If warmup active: shows "Wait 24h message"

### /menu
- Shows available mini-apps (games) that are not banned for this user
- Lists: roblox, mlbb, crash, mines

### /balance
- Checks user balance from database
- Returns current balance and freeroll count

### /withdraw
- Checks if user can withdraw
- Processes withdrawal request
- Returns status

### Integration with Mini-App:
- On /start, after registration, bot sends Mini-App start link
- Mini-App initializes with user_id from Telegram.WebApp
- Backend verifies user session

### Code Structure:
- Uses aiogram or telebot library pattern
- Database: PostgreSQL bot_pool table
- Warmup: 24 hours from last registration/activity
- User tracking: user_id, token, status, warmup_until

The file has been created at:
c:\\Артём\\Бизнес\\Ваня\\Drop\\RB\\roblox-case-platform\\backend\\app\\bot\\handlers.py
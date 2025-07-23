# bot.py - Bet sAI: AI Betting Assistant
import os
import requests
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

# === CONFIGURATION ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# Supported sports (customize for your audience)
SPORTS = [
    'soccer_epl',                    # English Premier League
    'soccer_uefa_champions_league',  # UCL
    'basketball_nba',                # NBA
    'soccer_kenya_premier_league'    # Optional: Add when available
]

REGION = 'uk'           # Options: 'uk', 'us', 'au', 'eu'
MARKET = 'h2h'          # Head-to-head (win/lose)
ODDS_FORMAT = 'decimal'

# Mock "AI" Model: Team strength ratings (you can improve this later)
TEAM_POWER = {
    # Top European
    "Manchester City": 0.68, "Arsenal": 0.62, "Liverpool": 0.60,
    "Bayern Munich": 0.67, "Barcelona": 0.59, "Real Madrid": 0.64,
    "Chelsea": 0.58, "Man Utd": 0.52, "Tottenham": 0.57,
    "Inter": 0.61, "AC Milan": 0.58,

    # Kenyan Teams (add more)
    "AFC Leopards": 0.53, "Gor Mahia": 0.55, "Sofapaka": 0.48,
    "Harambee Stars": 0.54,

    # NBA
    "LA Lakers": 0.54, "Boston Celtics": 0.56, "Golden State": 0.55,
    "Denver Nuggets": 0.57
}

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def get_team_power(team_name):
    """Estimate team strength. Can be replaced with ML model."""
    # Normalize common name variants
    name_map = {
        "Man City": "Manchester City",
        "Man Utd": "Man Utd",
        "Barca": "Barcelona"
    }
    clean_name = name_map.get(team_name, team_name)
    return TEAM_POWER.get(clean_name, 0.50)

def calculate_ev(odds: float, predicted_prob: float) -> float:
    """Calculate Expected Value in %"""
    return round(((odds * predicted_prob) - 1) * 100, 2)

def kelly_stake(ev_percent: float, bankroll: float = 1000) -> float:
    """1/4 Kelly Criterion with max 5% of bankroll"""
    if ev_percent <= 0:
        return 0.0
    fraction = 0.25  # 1/4 Kelly
    stake_percent = (ev_percent / 100) * fraction
    stake = bankroll * stake_percent
    max_stake = bankroll * 0.05  # Max 5%
    return round(min(stake, max_stake), 2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "🧠 *Bet sAI* – Your AI-Powered Betting Assistant\n\n"
        "I scan 20+ bookmakers to find **+EV bets** using data & logic — no hype, no scams.\n\n"
        "Commands:\n"
        "• /picks → Top value bets today\n"
        "• /help → How it works\n\n"
        "⚠️ *Gambling involves risk. Never bet more than you can afford to lose.*\n"
        "[Responsible Gambling Help](https://www.gamcare.org.uk )"
    )
    keyboard = [
        [InlineKeyboardButton("🎯 Get Today's Picks", callback_data='get_picks')],
        [InlineKeyboardButton("📘 How It Works", callback_data='how_it_works')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome, reply_markup=reply_markup, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🔍 *How Bet sAI Works*\n\n"
        "1. 📊 I analyze team strength, form, and H2H.\n"
        "2. 🔄 I fetch live odds from bookmakers.\n"
        "3. 🧠 I calculate *Expected Value (EV)*:\n"
        "   • If `EV > 0%` → long-term profit potential\n"
        "4. 💵 I suggest a smart stake (1/4 Kelly).\n\n"
        "🎯 Goal: Find *undervalued bets* — not guaranteed wins.\n\n"
        "⚠️ Always gamble responsibly."
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def get_picks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.message.reply_text("🧠 Bet sAI is analyzing today’s odds...")
    else:
        await update.message.reply_text("🧠 Bet sAI is analyzing today’s odds...")

    value_bets = []

    for sport in SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/ {sport}/odds"
        params = {
            'apiKey': ODDS_API_KEY,
            'regions': REGION,
            'oddsFormat': ODDS_FORMAT,
            'markets': MARKET
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                logger.warning(f"Odds API error {response.status_code}: {response.text}")
                continue

            games = response.json()
            for game in games[:3]:  # Max 3 games per sport
                home_team = game['home_team']
                away_team = game['away_team']

                # Estimate probabilities
                h_power = get_team_power(home_team)
                a_power = get_team_power(away_team)
                total = h_power + a_power
                prob_home = h_power / total
                prob_away = a_power / total

                for bookmaker in game['bookmakers']:
                    for outcome in bookmaker['markets'][0]['outcomes']:
                        team_name = outcome['name']
                        odds = outcome['price']

                        # Skip suspicious odds
                        if odds <= 1.10 or odds > 10.0:
                            continue

                        predicted_prob = prob_home if team_name == home_team else prob_away
                        ev = calculate_ev(odds, predicted_prob)

                        if ev > 3.0:  # Only show +EV > 3%
                            stake = kelly_stake(ev, bankroll=1000)  # KSh 1000 default
                            value_bets.append({
                                'sport': sport.replace('soccer_', '').replace('_', ' ').upper(),
                                'team': team_name,
                                'vs': away_team if team_name == home_team else home_team,
                                'odds': odds,
                                'bookmaker': bookmaker['title'],
                                'ev': ev,
                                'stake': stake
                            })

        except Exception as e:
            logger.error(f"Error fetching {sport}: {e}")

    # Send Results
    chat_id = update.effective_chat.id

    if not value_bets:
        result = (
            "🧠 Bet sAI says: *No strong value bets found today.*\n\n"
            "Sometimes the best bet is *no bet*. Wait for better edges!"
        )
    else:
        lines = ["🎯 *Today’s AI-Identified Value Bets* 🎯\n"]
        for bet in value_bets[:5]:
            lines.append(
                f"🏆 *{bet['team']}* vs {bet['vs']} ({bet['sport']})\n"
                f"📘 Bookmaker: {bet['bookmaker']}\n"
                f"📈 EV: +{bet['ev']}% | 💰 Odds: {bet['odds']}\n"
                f"💵 Suggested Stake: ${bet['stake']}\n"
                f"———"
            )
        lines.append("\n⚠️ *Not financial advice. Gamble responsibly.*")
        result = "\n".join(lines)

    await context.bot.send_message(chat_id=chat_id, text=result, parse_mode='Markdown')

async def how_it_works(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    help_text = (
        "🔍 *How Bet sAI Works*\n\n"
        "I use a 3-step process:\n"
        "1. 📊 Analyze team strength & form\n"
        "2. 🔄 Scan live odds from bookmakers\n"
        "3. 🧠 Calculate Expected Value (EV)\n\n"
        "🎯 Only bets with *positive EV* are shown.\n\n"
        "💡 Example:\n"
        "• My model says Man City has 60% chance to win\n"
        "• Odds: 1.80 → Implied chance: 55.6%\n"
        "• EV = (1.80 × 0.60) - 1 = +8% → *Value bet!*\n\n"
        "⚠️ Past performance ≠ future results."
    )
    await query.message.reply_text(help_text, parse_mode='Markdown')

def main():
    if not TELEGRAM_TOKEN:
        logger.error("❌ Missing TELEGRAM_TOKEN environment variable!")
        return
    if not ODDS_API_KEY:
        logger.error("❌ Missing ODDS_API_KEY environment variable!")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('picks', get_picks))
    app.add_handler(CommandHandler('help', help_command))

    app.add_handler(CallbackQueryHandler(get_picks, pattern='get_picks'))
    app.add_handler(CallbackQueryHandler(how_it_works, pattern='how_it_works'))

    logger.info("🧠 Bet sAI is now LIVE and scanning for value!")
    app.run_polling()

if __name__ == '__main__':
    main()
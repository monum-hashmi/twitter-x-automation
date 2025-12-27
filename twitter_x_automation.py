from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains

import time
import json
import random
import logging
import sys
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

# ==========================
# WINDOWS ENCODING FIX
# ==========================
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ==========================
# CONFIG
# ==========================
MY_TWITTER_HANDLE = "SubyxHub"
import os
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


MAX_DAILY_COMMENTS = float("inf")



NOW = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = f"twitter_bot_{NOW}.log"
HISTORY_FILE = "comment_history.json"

# ==========================
# LOGGING
# ==========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

# ==========================
# OPENAI
# ==========================
client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================
# CHROME OPTIONS (RDP SAFE)
# ==========================
def chrome_options():
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--start-maximized")

    # Anti-detection
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    return options

# ==========================
# UTILITIES
# ==========================
def load_history():
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def wait_manual_login(driver):
    logging.info("Waiting for manual login...")
    for _ in range(60):
        try:
            driver.find_element(By.XPATH, "//a[@aria-label='Profile']")
            logging.info("Login detected.")
            return True
        except:
            time.sleep(5)
    return False


REPLY_STYLES = [
    "short opinion",
    "casual observation",
    "neutral comment",
    "light suggestion",
    "soft recommendation"
]

def generate_reply(tweet_text):
    variation_seed = random.choice(REPLY_STYLES)

    prompt = f"""
Tweet: {tweet_text}
Reply style: {variation_seed}

Write a short casual reply (under 20 words).
Reply rules:
- Mention CryptoGem OR play-to-earn OR Solana (not all every time)
- Mention @cryptogemapp only if it fits naturally
- No hashtags
- Human tone, small typo allowed
- Keep it neutral, not hype
- Use a different phrasing than previous replies
"""
    try:
        res = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt
        )
        return res.output_text.strip()
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        return None

def verify_reply_posted(driver, tweet_id, reply_text, my_handle, max_wait=15):
    """Quick verification that reply was posted"""
    logging.info("Verifying reply was posted...")
    
    # Wait for modal to close (sign of success)
    time.sleep(3)
    try:
        modal = driver.find_elements(By.XPATH, "//div[@role='dialog']")
        if not modal or len(modal) == 0:
            logging.info("✓ Compose modal closed - likely successful")
            return True
    except:
        pass
    
    # Check the tweet page
    logging.info(f"Checking tweet page for our reply...")
    original_url = driver.current_url
    
    try:
        driver.get(f"https://x.com/i/status/{tweet_id}")
        time.sleep(4)
        
        # Look for our username in replies
        replies = driver.find_elements(By.XPATH, "//article[@data-testid='tweet']")
        
        for reply in replies[:10]:  # Check first 10 replies
            try:
                username = reply.find_element(
                    By.XPATH, 
                    ".//div[@data-testid='User-Name']"
                ).text
                
                if my_handle.lower() in username.lower():
                    try:
                        text = reply.find_element(
                            By.XPATH,
                            ".//div[@data-testid='tweetText']"
                        ).text.strip()
                        
                        if reply_text.strip() in text or text in reply_text.strip():
                            logging.info("✓ Reply verified on tweet page!")
                            return True
                    except:
                        pass
            except:
                continue
        
        logging.warning("Reply not found on tweet page")
        return False
        
    except Exception as e:
        logging.error(f"Verification error: {e}")
        return False
    finally:
        # Go back to feed
        try:
            driver.back()
            time.sleep(2)
        except:
            pass

def post_reply_safely(driver, post, tweet_text, tweet_id):
    """Post reply with comprehensive error handling"""
    
    try:
        logging.info(f"Processing tweet: {tweet_text[:60]}...")
        
        # Scroll to post
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", post
        )
        time.sleep(1)

        # Click reply button
        try:
            reply_btn = post.find_element(By.XPATH, ".//button[@data-testid='reply']")
            driver.execute_script("arguments[0].click();", reply_btn)
            time.sleep(3)
        except Exception as e:
            logging.error(f"Could not click reply button: {e}")
            return False, None

        # Wait for compose modal
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
            )
            logging.info("Compose modal opened")
        except:
            logging.error("Compose modal did not open")
            return False, None

        # Generate reply
        reply = generate_reply(tweet_text)
        if not reply:
            logging.warning("Failed to generate reply")
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            return False, None

        logging.info(f"Generated: {reply}")

        # Find textbox
        try:
            box = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//div[@role='textbox']"))
            )
            box.click()
            time.sleep(0.5)
        except Exception as e:
            logging.error(f"Could not find textbox: {e}")
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            return False, None

        # Clear and type
        try:
            # Clear
            box.send_keys(Keys.CONTROL + "a")
            box.send_keys(Keys.BACKSPACE)
            time.sleep(0.3)

            # Type reply
            for char in reply:
                box.send_keys(char)
                time.sleep(random.uniform(0.02, 0.06))

            # Trigger React update
            box.send_keys(" ")
            time.sleep(0.2)
            box.send_keys(Keys.BACKSPACE)
            time.sleep(1)
            
            logging.info("Reply typed successfully")

        except Exception as e:
            logging.error(f"Error typing reply: {e}")
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            return False, None

        # Find and click send button
        send_clicked = False
        
        # Try multiple selectors
        send_selectors = [
            "//button[@data-testid='tweetButtonInline']",
            "//button[@data-testid='tweetButton']",
            "//div[@role='dialog']//button[.//span[text()='Reply']]",
            "//button[contains(@data-testid, 'tweet') and not(@disabled)]"
        ]
        
        for selector in send_selectors:
            try:
                logging.info(f"Looking for send button: {selector}")
                send_btn = driver.find_element(By.XPATH, selector)
                
                # Check if disabled
                if send_btn.get_attribute("disabled"):
                    logging.warning("Button is disabled")
                    continue
                
                # Highlight for debugging
                driver.execute_script("arguments[0].style.border='3px solid green'", send_btn)
                time.sleep(0.3)
                
                # Try JavaScript click
                driver.execute_script("arguments[0].click();", send_btn)
                logging.info("✓ Clicked send button!")
                send_clicked = True
                break
                
            except Exception as e:
                logging.debug(f"Selector failed: {e}")
                continue
        
        # Fallback: Try Ctrl+Enter
        if not send_clicked:
            try:
                logging.info("Trying Ctrl+Enter as fallback...")
                box.send_keys(Keys.CONTROL + Keys.ENTER)
                send_clicked = True
                logging.info("✓ Used keyboard shortcut")
            except Exception as e:
                logging.error(f"Keyboard shortcut failed: {e}")
        
        if not send_clicked:
            logging.error("✗ Could not click send button with any method!")
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            return False, None

        # Wait and verify
        time.sleep(4)
        
        if verify_reply_posted(driver, tweet_id, reply, MY_TWITTER_HANDLE):
            logging.info("✓ Reply posted and verified successfully!")
            return True, reply
        else:
            logging.warning("⚠ Could not verify reply")
            # Still return True if modal closed (likely posted)
            try:
                modal = driver.find_elements(By.XPATH, "//div[@role='dialog']")
                if not modal or len(modal) == 0:
                    logging.info("Modal closed, assuming success")
                    return True, reply
            except:
                pass
            
            return False, None

    except Exception as e:
        logging.error(f"Error in post_reply_safely: {e}")
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except:
            pass
        return False, None

# ==========================
# MAIN BOT LOGIC
# ==========================
def wait_for_new_tweet(driver, history, interval=5):
    logging.info("Waiting for a new tweet...")

    while True:
        time.sleep(interval)
        driver.refresh()
        time.sleep(3)  # allow feed to render

        posts = driver.find_elements(By.XPATH, "//article[@data-testid='tweet']")

        for post in posts:
            try:
                link = post.find_element(
                    By.XPATH, ".//a[contains(@href,'/status/')]"
                ).get_attribute("href")

                tweet_id = link.split("/status/")[-1].split("?")[0]

                if tweet_id not in history:
                    logging.info(f"New tweet found: {tweet_id}")
                    return post, tweet_id

            except:
                continue


def run_bot(driver):
    history = load_history()
    daily_count = 0

    logging.info("Starting bot loop...")

    consecutive_failures = 0
    max_consecutive_failures = 5

    while True:
        try:
            logging.info("Refreshing feed...")
            driver.refresh()
            time.sleep(2)

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)

            posts = driver.find_elements(By.XPATH, "//article[@data-testid='tweet']")
            logging.info(f"Found {len(posts)} tweets on page")

            if len(posts) == 0:
                logging.warning("No tweets found! Check if page loaded correctly.")
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    logging.error("Too many consecutive failures. Stopping.")
                    return
                time.sleep(10)
                continue

            consecutive_failures = 0

            for idx, post in enumerate(posts):
                if daily_count >= MAX_DAILY_COMMENTS:
                    logging.info(f"✓ Daily limit reached: {daily_count}/{MAX_DAILY_COMMENTS}")
                    return

                try:
                    # Get tweet ID
                    try:
                        link = post.find_element(
                            By.XPATH, ".//a[contains(@href,'/status/')]"
                        ).get_attribute("href")
                        tweet_id = link.split("/status/")[-1].split("?")[0]
                    except:
                        logging.debug(f"Post {idx}: Could not extract tweet ID")
                        continue

                    # Check history
                    if tweet_id in history:
                        logging.debug(f"Post {idx}: Already replied to {tweet_id}")
                        continue

                    # Skip own tweets and replies (reliable)
                    try:
                        post.find_element(
                            By.XPATH,
                            ".//a[contains(@href, '/{}')]".format(MY_TWITTER_HANDLE)
                        )
                        logging.debug("Skipping own tweet or reply")
                        continue
                    except:
                        pass

                    # Get tweet text
                    try:
                        tweet_text = post.find_element(
                            By.XPATH, ".//div[@data-testid='tweetText']"
                        ).text.strip()
                    except:
                        logging.debug(f"Post {idx}: Could not get tweet text")
                        continue

                    if not tweet_text or len(tweet_text) < 10:
                        logging.debug(f"Post {idx}: Tweet text too short")
                        continue

                    logging.info(f"\n{'='*60}")
                    logging.info(f"Post {idx+1}/{len(posts)} - Tweet ID: {tweet_id}")
                    logging.info(f"{'='*60}")

                    success, reply_text = post_reply_safely(
                        driver, post, tweet_text, tweet_id
                    )

                    if success and reply_text:
                        history[tweet_id] = {
                            "timestamp": datetime.now().isoformat(),
                            "reply": reply_text,
                            "original_tweet": tweet_text[:100]
                        }
                        save_history(history)
                        daily_count += 1
                        logging.info("Reply posted. Refreshing every 5 seconds until a new tweet appears...")
                        logging.info(f"✓✓✓ SUCCESS! Replied {daily_count}/{MAX_DAILY_COMMENTS} ✓✓✓")
                        post, tweet_id = wait_for_new_tweet(driver, history, interval=5)
                        break
                    else:
                        logging.warning(f"✗ Failed to reply to {tweet_id}")
                        time.sleep(3)

                except Exception as e:
                    logging.error(f"Error processing post {idx}: {e}")
                    try:
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    except:
                        pass
                    continue

        except Exception as e:
            logging.error(f"Main loop error: {e}")
            try:
                _ = driver.title
            except:
                logging.error("Browser session lost!")
                return
            time.sleep(20)

# ==========================
# ENTRY POINT
# ==========================
def main():
    logging.info("="*60)
    logging.info("Twitter Reply Bot Starting...")
    logging.info("="*60)
    
    service = Service(executable_path=r"./chromedriver.exe")
    driver = webdriver.Chrome(service=service, options=chrome_options())

    try:
        driver.get("https://x.com")
        time.sleep(3)

        if not wait_manual_login(driver):
            logging.error("Login timeout - please log in within 5 minutes")
            driver.quit()
            return
        logging.info("Please switch to Following feed manually now...")
        time.sleep(10)
        logging.info(f"Feed locked at: {driver.current_url}")

        logging.info("\n" + "="*60)
        logging.info("Login successful! Starting bot...")
        logging.info("="*60 + "\n")

        run_bot(driver)

    except KeyboardInterrupt:
        logging.info("\nBot stopped by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
    finally:
        logging.info("\nBot finished. Press Enter to close browser...")
        input()
        driver.quit()

if __name__ == "__main__":
    main()
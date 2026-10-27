import sys
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import re
from textblob import TextBlob
from bs4 import BeautifulSoup
import math

# Database configuration dictionary
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'ExcaliBR8!',
    'database': 'imdb_reviews'
}

# Define the intended database name
DATABASE_NAME = 'GameReviewIMDB'

# Target game genres to match against
TARGET_GAME_GENRES = [
    'Action', 'Shooter', 'Platformer', 'Strategy', 
    'RPG', 'Racing', 'Simulator'
]

# Global driver instance
driver = None

# --- Utility Functions for DB Connection ---

def get_db_connection(config, use_db=False):
    """
    Establishes a connection to the MySQL server.
    
    Args:
        config: Database configuration dictionary
        use_db: If True, connects to the specific database; if False, connects to server only
    
    Returns:
        MySQL connection object
    
    Raises:
        SystemExit: If connection fails
    """
    try:
        conn_config = config.copy()
        if not use_db:
            conn_config.pop('database', None)
        else:
            conn_config['database'] = DATABASE_NAME

        conn = mysql.connector.connect(**conn_config)
        return conn
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        sys.exit(1)

def init_driver():
    """
    Initializes undetected_chromedriver with optimized settings to bypass bot detection.
    
    Returns:
        WebDriver: Configured Chrome driver instance
    """
    global driver
    if driver is None:
        options = uc.ChromeOptions()
        
        # Stealth options to avoid detection
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-gpu')
        
        # Optional: Run in headless mode (comment out if you want to see the browser)
        # options.add_argument('--headless=new')
        
        # User agent to appear more legitimate
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        driver = uc.Chrome(options=options, version_main=None)
        driver.implicitly_wait(10)
        
        print("Chrome driver initialized successfully")
    
    return driver

def close_driver():
    """
    Closes the Chrome driver and cleans up resources.
    """
    global driver
    if driver:
        driver.quit()
        driver = None
        print("Chrome driver closed")

# --- Core Logic Functions ---

def sqlTablechecker():
    """
    Checks if the database and necessary tables exist. Creates them if they don't.
    
    Tables created:
        - director: Stores director information and aggregate scores
        - games: Stores game metadata (title, director, rating, genre, etc.)
        - reviews: Stores individual user reviews
        - sentimentScore: Stores calculated sentiment scores for each game
    """
    conn = get_db_connection(DB_CONFIG, use_db=False)
    cursor = conn.cursor()

    try:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DATABASE_NAME};")
        print(f"Ensured database '{DATABASE_NAME}' exists.")
        
        cursor.execute(f"USE {DATABASE_NAME};")
        
        # Create 'director' Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS director(
                director_name VARCHAR(50) PRIMARY KEY NOT NULL,
                game_count INT DEFAULT 0,
                aggregate_score DECIMAL(10, 4) DEFAULT 0.0
            );
        """)

        # Create 'games' Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS games(
                game_title VARCHAR(255) NOT NULL PRIMARY KEY,
                director_name VARCHAR(50),
                IMDB_rating DECIMAL(10, 4), 
                release_year INT,
                genre VARCHAR(50),
                age_rating VARCHAR(10), 
                FOREIGN KEY (director_name) REFERENCES director(director_name) ON DELETE SET NULL
            );
        """)

        # Create 'reviews' Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                review_id INT AUTO_INCREMENT PRIMARY KEY,
                game_title VARCHAR(255) NOT NULL,
                reviewer VARCHAR(50) NOT NULL,
                review_date DATE,
                reviewer_rating INT,
                review_text MEDIUMTEXT,
                FOREIGN KEY (game_title) REFERENCES games(game_title) ON DELETE CASCADE,
                UNIQUE KEY unique_review (game_title, reviewer)
            );
        """)

        # Create 'sentimentScore' Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sentimentScore(
                game_title VARCHAR(255) NOT NULL PRIMARY KEY,
                sentiment_score DECIMAL(10, 4),
                FOREIGN KEY (game_title) REFERENCES games(game_title) ON DELETE CASCADE
            );
        """)
        print("Ensured all necessary tables exist.")

        conn.commit()

    except Error as e:
        print(f"Error executing SQL statements: {e}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def dataInserter():
    """
    Primary driver function for user interaction.
    Prompts user for IMDB links and initiates scraping process.
    
    Returns:
        0 when user is done entering links
    """
    print("Starting data insertion process. Input IMDB links for scraping.")
    try:
        while True:
            link = input("Please input an IMDB link for the program to scrape (input 'done' to compile report): ").strip()
            if link.lower() == "done":
                print("User requested to compile report. Exiting data insertion loop.")
                return 0
            elif "imdb.com" in link.lower():
                scraper(link)
            else:
                print(f"Invalid link input: '{link}'. Please input a link containing 'imdb.com' or 'done'.")
                continue

    except Exception as e:
        print(f"There was an error in dataInserter: {e}")

def extract_genre_from_chips(soup):
    """
    Extracts game genre from IMDB's chip list elements.
    
    Args:
        soup: BeautifulSoup object of the page
    
    Returns:
        str: First matching genre from TARGET_GAME_GENRES, or None if no match
    """
    chip_scroller = soup.find('div', class_='ipc-chip-list__scroller')
    if not chip_scroller:
        return None
    
    chip_texts = chip_scroller.find_all('span', class_='ipc-chip__text')
    
    for chip in chip_texts:
        chip_text = chip.text.strip()
        for target_genre in TARGET_GAME_GENRES:
            if target_genre.lower() in chip_text.lower():
                return target_genre
    
    return None

# List of known IMDB date formats to try
IMDB_DATE_FORMATS = [
    '%b %d, %Y',  # Nov 24, 2012 - MOST COMMON
    '%B %d, %Y',  # November 24, 2012
    '%d %B %Y',   # 24 November 2012
    '%d %b %Y',   # 24 Nov 2012
]

def parse_review_date(date_str):
    """
    Attempts to parse a date string using multiple known IMDB formats.
    
    Args:
        date_str: Date string from IMDB review
    
    Returns:
        str: Date in YYYY-MM-DD format for MySQL, or None if parsing fails
    """
    for fmt in IMDB_DATE_FORMATS:
        try:
            dt_obj = datetime.strptime(date_str, fmt)
            return dt_obj.strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None

def scraper(link):
    """
    Main scraping function that extracts game data and reviews from IMDB.
    Uses undetected_chromedriver to bypass bot detection.
    
    Process:
        1. Fetch main game page and extract metadata (title, director, rating, etc.)
        2. Validate that the title is a video game
        3. Insert/update game and director data in database
        4. Navigate to reviews page
        5. Extract all reviews with ratings, dates, and text
        6. Insert reviews into database
        7. Trigger sentiment analysis
    
    Args:
        link: IMDB URL to scrape
    """
    print(f"Starting scraper for link: {link}")
    conn = None
    
    try:
        # Initialize the undetected Chrome driver
        browser = init_driver()
        
        # --- 1. Fetch and Parse Main Page ---
        print("Loading main page...")
        browser.get(link)
        time.sleep(3)  # Wait for page to fully load
        
        # Get page source and parse with BeautifulSoup
        page_source = browser.page_source
        soup = BeautifulSoup(page_source, 'html.parser')

        # Extract Game Title and Type Check
        game_title_tag = soup.find('span', class_='hero__primary-text')
        game_title = game_title_tag.text.strip() if game_title_tag else 'Unknown Game'
        
        # Check if it's a video game
        title_type_tag = soup.find('a', href=re.compile(r'/title/tt\d+/mediavssim/'))
        if title_type_tag and 'Video Game' not in title_type_tag.text:
            print(f"Title '{game_title}' is not identified as a Video Game. Skipping.")
            return 0
        
        print(f"Scraping details for game: {game_title}")

        # Extract director
        director_tag = soup.find('a', href=re.compile(r'/name/nm\d+/\?ref_=tt_ov_1_1'))
        director_name = director_tag.text.strip() if director_tag else 'Unknown'

        # Extract IMDB rating
        rating_tag = soup.find('span', class_='sc-4dc495c1-1') 
        IMDB_rating = None
        if rating_tag:
            rating_text = rating_tag.text.split('/')[0].strip()
            if rating_text.replace('.', '', 1).isdigit():
                IMDB_rating = float(rating_text)
        
        # Extract release year
        date_tag = soup.find('a', href=re.compile(r'/title/tt\d+/releaseinfo/'))
        release_year = 1900
        if date_tag:
            year_match = re.search(r'\d{4}', date_tag.text.strip())
            if year_match:
                release_year = int(year_match.group())

        # Extract genre
        genre = extract_genre_from_chips(soup)
        print(f"Extracted genre: {genre}")

        # Extract age rating
        age_rating = None
        age_rating_link = soup.find('a', href=re.compile(r'/parentalguide/\?ref_=tt_ov_pg#certificates'))
        if age_rating_link:
            age_rating = age_rating_link.text.strip()
        
        print(f"Extracted age rating: {age_rating}")
        print(f"Extracted release year: {release_year}")

        # --- 2. Insert Game and Director Data ---
        conn = get_db_connection(DB_CONFIG, use_db=True)
        cursor = conn.cursor()
        
        try:
            # Insert/Update Director
            cursor.execute("""
                INSERT INTO director (director_name, game_count) 
                VALUES (%s, 1) 
                ON DUPLICATE KEY UPDATE game_count = game_count + 1
            """, (director_name,))

            # Insert/Update Game
            cursor.execute("""
                INSERT INTO games (game_title, director_name, IMDB_rating, release_year, genre, age_rating) 
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    director_name=VALUES(director_name), IMDB_rating=VALUES(IMDB_rating), 
                    release_year=VALUES(release_year), genre=VALUES(genre), age_rating=VALUES(age_rating)
            """, (game_title, director_name, IMDB_rating, release_year, genre, age_rating))
            
            conn.commit()
            print(f"Successfully inserted/updated game and director data for: {game_title}")

        except Error as e:
            print(f"DB Error during game/director insertion: {e}")
            return
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

        # --- 3. Follow Sublink to Reviews and Scrape ---
        review_link_tag = soup.find('a', href=re.compile(r'/reviews/\?ref_=tt_ov_ql_2'))
        if not review_link_tag:
            print("Could not find review link. Skipping review scraping.")
            return

        review_url = "https://www.imdb.com" + review_link_tag['href']
        print(f"Scraping reviews from: {review_url}")
        
        # Navigate to reviews page using Selenium
        browser.get(review_url)
        time.sleep(3)  # Wait for reviews to load
        
        # Get the reviews page source
        review_page_source = browser.page_source
        review_soup = BeautifulSoup(review_page_source, 'html.parser')
        
        # Find all rating elements
        rating_elements = review_soup.find_all('span', class_='ipc-rating-star--rating')
        
        conn = get_db_connection(DB_CONFIG, use_db=True)
        cursor = conn.cursor()
        
        reviews_scraped = 0
        
        # Process each rating element and find associated review data
        for rating_element in rating_elements:
            try:
                # Get the rating value
                reviewer_rating_text = rating_element.text.strip()
                reviewer_rating = int(reviewer_rating_text.split('/')[0]) if '/' in reviewer_rating_text else int(reviewer_rating_text)
                
                # Navigate to find the review text and author
                review_block = rating_element.find_parent('article')
                if not review_block:
                    review_block = rating_element.find_parent('div', class_=re.compile(r'lister-item|review'))
                
                if not review_block:
                    continue
                
                # Find reviewer name
                reviewer_link = review_block.find('a', href=re.compile(r'/user/ur\d+/'))
                reviewer = reviewer_link.text.strip() if reviewer_link else 'Anonymous'
                
                # Parse review date
                review_date = None
                review_date_tag = review_block.find('li', class_='ipc-inline-list__item review-date')
                
                if review_date_tag:
                    date_str = review_date_tag.text.strip()
                    review_date = parse_review_date(date_str)

                if not review_date and review_date_tag:
                    print(f"Warning: Could not parse date string: {date_str} for {game_title}. Setting date to NULL.")
                
                # Find review text
                review_text = None
                
                # Method 1: Look for ipc-html-content-inner-div
                text_divs = review_block.find_all('div', class_='ipc-html-content-inner-div')
                if text_divs:
                    review_text = ' '.join([div.get_text(strip=True) for div in text_divs if div.get_text(strip=True)])
                
                # Method 2: Look for content div
                if not review_text:
                    content_div = review_block.find('div', class_='content')
                    if content_div:
                        review_text = content_div.get_text(strip=True)
                
                # Method 3: Look for text() div
                if not review_text:
                    text_div = review_block.find('div', class_='text')
                    if text_div:
                        review_text = text_div.get_text(strip=True)
                
                if not review_text:
                    print(f"Warning: No review text found for reviewer '{reviewer}'. Skipping.")
                    continue
                
                # Insert Review
                cursor.execute("""
                    INSERT INTO reviews (game_title, reviewer, review_date, reviewer_rating, review_text) 
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                        review_date=VALUES(review_date), reviewer_rating=VALUES(reviewer_rating), review_text=VALUES(review_text)
                """, (game_title, reviewer, review_date, reviewer_rating, review_text))
                
                reviews_scraped += 1
                print(f"Scraped review from {reviewer} (rating: {reviewer_rating}, date: {review_date})")

            except Exception as e:
                print(f"Warning: Error parsing one review: {e}. Skipping.")
                import traceback
                traceback.print_exc()
                continue

        conn.commit()
        print(f"Successfully inserted/updated {reviews_scraped} reviews for {game_title}.")
        
        # After successful scraping, proceed to sentiment analysis
        if reviews_scraped > 0:
            sentimentScoreInserter()
        else:
            print("No reviews were scraped, skipping sentiment analysis.")

    except Exception as e:
        print(f"A critical error occurred during scraping process: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def sentimentScoreer(review_texts, review_ratings, game_title, IMDB_rating):
    """
    Calculates sentiment score for a game based on its reviews.
    
    Formula:
        AVG((Sentiment of review + 1) / 2) + AVG(reviewer ratings) / 10 + IMDB_rating / 10
    
    Components:
        - Sentiment: Polarity from TextBlob normalized to 0-1 range
        - Reviewer ratings: Average of individual ratings normalized to 0-1
        - IMDB rating: Official rating normalized to 0-1
    
    Args:
        review_texts: List of review text strings
        review_ratings: List of individual reviewer ratings (0-10)
        game_title: Title of the game (for logging)
        IMDB_rating: IMDB rating of the game (0-10)
    
    Returns:
        float: The calculated sentiment score (Max is 3.0)
    """
    if not review_texts or len(review_texts) == 0:
        return 0.0
    
    sentiment_sum = 0.0
    for text in review_texts:
        reader = TextBlob(text)
        sentiment_sum += (reader.sentiment.polarity + 1) / 2
    
    # Calculate average sentiment component
    avg_sentiment = sentiment_sum / len(review_texts)    
    # Calculate average reviewer rating component
    avg_reviewer_rating = sum(review_ratings) / len(review_ratings) if review_ratings else 0
    
    # Apply formula
    # Max components: 1.0 (sentiment) + 1.0 (avg rating) + 1.0 (IMDB rating) = 3.0
    value = float(avg_sentiment) + float(avg_reviewer_rating / 10) + float(IMDB_rating / 10)
    return value

def sentimentScoreInserter():
    """
    Fetches all games and their reviews, calculates sentiment scores,
    and inserts them into the sentimentScore table.
    Also updates the director aggregate scores.
    """
    print("Starting sentiment score calculation and insertion...")
    
    conn = get_db_connection(DB_CONFIG, use_db=True)
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Fetch all games with their reviews
        cursor.execute("""
            SELECT g.game_title, g.IMDB_rating, g.director_name, r.review_text, r.reviewer_rating
            FROM games g
            LEFT JOIN reviews r ON g.game_title = r.game_title
            WHERE r.review_text IS NOT NULL
        """)
        
        results = cursor.fetchall()
        
        if not results:
            print("No reviews found to process.")
            return
        
        # Group reviews by game
        games_data = {}
        for row in results:
            game_title = row['game_title']
            if game_title not in games_data:
                games_data[game_title] = {
                    'IMDB_rating': row['IMDB_rating'] if row['IMDB_rating'] else 0,
                    'director': row['director_name'],
                    'reviews': [],
                    'ratings': []
                }
            games_data[game_title]['reviews'].append(row['review_text'])
            if row['reviewer_rating']:
                games_data[game_title]['ratings'].append(row['reviewer_rating'])
        
        # Calculate sentiment scores for each game
        director_scores = {}
        
        for game_title, data in games_data.items():
            sentiment_score = sentimentScoreer(
                data['reviews'],
                data['ratings'],
                game_title, 
                data['IMDB_rating']
            )
            
            # Insert into sentimentScore table
            cursor.execute("""
                INSERT INTO sentimentScore (game_title, sentiment_score) 
                VALUES (%s, %s) 
                ON DUPLICATE KEY UPDATE sentiment_score = VALUES(sentiment_score)
            """, (game_title, sentiment_score))
            
            # Aggregate for director
            director = data['director']
            if director:
                if director not in director_scores:
                    director_scores[director] = []
                director_scores[director].append(sentiment_score)
        
        # Update director aggregate scores
        for director, scores in director_scores.items():
            avg_score = sum(scores) / len(scores)
            cursor.execute("""
                UPDATE director 
                SET aggregate_score = %s 
                WHERE director_name = %s
            """, (avg_score, director))
        
        conn.commit()
        print("Sentiment scores successfully calculated and inserted.")
        
    except Error as e:
        print(f"Error during sentiment score insertion: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

def reportCompiler():
    """
    Generates a comprehensive text report of all directors and their games.
    
    Report includes:
        - Director name and aggregate score
        - List of games directed with similarity scores
        - Similarity score: Cosine similarity between normalized game metrics
          and ideal score vector [1.0, 1.0]
    
    Returns:
        1 on success, 0 on failure
    """
    conn = None
    cursor = None
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"Game_Sentiment_Report-{timestamp}.txt"
    
    try: 
        conn = get_db_connection(DB_CONFIG, use_db=True)
        cursor = conn.cursor(dictionary=True)
        
        # Fetch all directors and their aggregate scores
        cursor.execute("SELECT director_name, aggregate_score FROM director ORDER BY aggregate_score DESC")
        directors = cursor.fetchall()
        
        # Fetch all games with their scores
        cursor.execute("""
            SELECT 
                g.game_title, g.director_name, g.IMDB_rating, s.sentiment_score
            FROM games g
            JOIN sentimentScore s ON g.game_title = s.game_title
            WHERE g.director_name IS NOT NULL
        """)
        games_data = cursor.fetchall()

        # Map games to directors and calculate similarity scores
        director_games_with_scores = {}
        
        for game in games_data:
            director_name = game['director_name']
            game_title = game['game_title']
            
            # Normalize scores (sentiment max: 3.0, IMDB max: 10.0)
            s_raw = float(game['sentiment_score']) if game['sentiment_score'] is not None else 0.0
            s_norm = s_raw / 3.0
            
            r_raw = float(game['IMDB_rating']) if game['IMDB_rating'] is not None else 0.0
            r_norm = r_raw / 10.0
            
            # Calculate cosine similarity with ideal vector [1.0, 1.0]
            similarity_score = 0.0
            if s_norm > 0 or r_norm > 0:
                dot_product = s_norm + r_norm
                magnitude_A = math.sqrt(s_norm**2 + r_norm**2)
                magnitude_P = math.sqrt(2)
                
                if magnitude_A > 0:
                    similarity_score = dot_product / (magnitude_A * magnitude_P)
                
            game_entry = {
                'title': game_title,
                'similarity': similarity_score
            }
            director_games_with_scores.setdefault(director_name, []).append(game_entry)
        
        # Write the report file
        with open(filename, "w") as file:
            file.write("=" * 80 + "\n")
            file.write(f"This is the sentiment report of all game directors as of {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            file.write("The Aggregate Score is the average sentiment/rating score across all their games.\n")
            file.write("The Similarity Score shows how closely the game's normalized Sentiment Score and IMDB Rating match the ideal score of 1.0 (range 0 to 1).\n")
            file.write("=" * 80 + "\n\n")

            if not directors:
                file.write("No director data available in the database.\n")
                print(f"Report compiled: {filename}. No director data found.")
                return 1

            for director in directors:
                name = director['director_name']
                score = director['aggregate_score']
                
                file.write(f"DIRECTOR: {name}\n")
                file.write(f"  Aggregate Score: {score:.4f} \n")
                
                games_list = director_games_with_scores.get(name, [])
                file.write(f"  Games Directed ({len(games_list)} total):\n")
                
                for game_entry in games_list:
                    title = game_entry['title']
                    similarity = game_entry['similarity']
                    file.write(f"    - {title} (Similarity: {similarity:.4f})\n")
                
                file.write("\n" + "-" * 40 + "\n\n")

        print(f"Report compiled successfully to: {filename}")
        return 1

    except Error as e:
        print(f"Database Error during report compilation: {e}")
        return 0
    except Exception as e:
        print(f"There was an file I/O error during report compilation: {e}")
        return 0
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def main():
    """
    Main function to run the script.
    
    Workflow:
        1. Initialize database and tables
        2. Prompt user for IMDB links and scrape data
        3. Calculate sentiment scores for all games
        4. Generate comprehensive report
        5. Clean up resources
    """
    print("Starting IMDB Scraper and Sentiment Analyzer.")
    
    try:
        sqlTablechecker()
        dataInserter()
        sentimentScoreInserter()
        reportCompiler()
        print("Program finished successfully.")
    finally:
        # Always close the driver when done
        close_driver()

# Script entry point
if __name__ == "__main__":
    main()

# IMDb Video Game Review Scraper & Sentiment Analyzer

A command-line Python tool that scrapes video game pages and user reviews from IMDb, stores them in a MySQL database, scores each game using sentiment analysis plus ratings, and writes a plain-text report ranking game directors.

## Features

- **Interactive scraping**: paste IMDb title links one at a time; type `done` to finish.
- **Video game check**: skips titles IMDb doesn't identify as a video game.
- **Metadata extraction**: title, director, IMDb rating, release year, genre, and age rating.
- **Review collection**: reviewer name, date, star rating, and full review text.
- **Bot-detection workaround**: uses `undetected_chromedriver` to load pages in a real Chrome instance.
- **Sentiment scoring**: combines TextBlob polarity, average reviewer rating, and IMDb rating into a single score per game.
- **Director aggregation**: averages each director's game scores.
- **Timestamped report**: outputs `Game_Sentiment_Report-YYYY-MM-DD_HH-MM-SS.txt`.

## Requirements

- Python 3.9+
- MySQL Server (local or remote)
- Google Chrome (installed and up to date)

### Python packages

```bash
pip install mysql-connector-python undetected-chromedriver selenium textblob beautifulsoup4 setuptools
```

> `setuptools` is needed on Python 3.12+, where `undetected_chromedriver` relies on `distutils`, which was removed from the standard library.

## Configuration

Database settings live in the `DB_CONFIG` dictionary at the top of the script:

```python
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '<your-password>',
    'database': 'imdb_reviews'   # ignored, see below
}

DATABASE_NAME = 'GameReviewIMDB'
```

- The script always uses `DATABASE_NAME` (`GameReviewIMDB`); the `database` key in `DB_CONFIG` is overridden.
- The database and tables are created automatically on first run if they don't exist.

> **Security note:** Avoid committing real credentials. Consider loading them from environment variables instead, for example:
> ```python
> import os
> DB_CONFIG = {
>     'host': os.getenv('DB_HOST', 'localhost'),
>     'user': os.getenv('DB_USER', 'root'),
>     'password': os.getenv('DB_PASSWORD'),
> }
> ```

### Genres

Only these genres are recognized (the first match among a title's IMDb genre chips is stored):

`Action`, `Shooter`, `Platformer`, `Strategy`, `RPG`, `Racing`, `Simulator`

Edit `TARGET_GAME_GENRES` to change the list. Games with no matching genre are stored with a `NULL` genre.

### Headless mode

Chrome opens visibly by default. To run it in the background, uncomment this line in `init_driver()`:

```python
# options.add_argument('--headless=new')
```

Note that headless mode is more likely to trigger bot detection.

## Usage

```bash
python scraper.py
```

(Replace `scraper.py` with the script's actual filename.)

Example session:

```
Starting IMDB Scraper and Sentiment Analyzer.
Ensured database 'GameReviewIMDB' exists.
Ensured all necessary tables exist.
Please input an IMDB link for the program to scrape (input 'done' to compile report): https://www.imdb.com/title/tt2140553/
Chrome driver initialized successfully
Loading main page...
Scraping details for game: ...
...
Please input an IMDB link for the program to scrape (input 'done' to compile report): done
Report compiled successfully to: Game_Sentiment_Report-2026-10-27_18-30-00.txt
```

Links must contain `imdb.com`; use the main title page (e.g. `https://www.imdb.com/title/tt1234567/`).

## How It Works

1. **`sqlTablechecker()`** creates the database and tables if needed.
2. **`dataInserter()`** prompts for links and calls `scraper()` on each.
3. **`scraper()`** loads the title page, extracts metadata, saves the game and director, follows the reviews link, and saves each review.
4. **`sentimentScoreInserter()`** recalculates scores for every game in the database and updates director aggregates. It runs after each successful scrape and once more at the end.
5. **`reportCompiler()`** writes the final text report.
6. **`close_driver()`** shuts down Chrome, even if an error occurs.

## Database Schema

| Table | Key columns | Purpose |
|---|---|---|
| `director` | `director_name` (PK), `game_count`, `aggregate_score` | One row per director with their average score |
| `games` | `game_title` (PK), `director_name` (FK), `IMDB_rating`, `release_year`, `genre`, `age_rating` | Game metadata |
| `reviews` | `review_id` (PK), `game_title` (FK), `reviewer`, `review_date`, `reviewer_rating`, `review_text` | Individual reviews; unique per `(game_title, reviewer)` |
| `sentimentScore` | `game_title` (PK, FK), `sentiment_score` | Computed score per game |

Deleting a game cascades to its reviews and sentiment score. Deleting a director sets `director_name` to `NULL` on their games.

## Scoring

### Sentiment score (per game, range 0–3)

```
score = AVG((polarity + 1) / 2)  +  AVG(reviewer_rating) / 10  +  IMDB_rating / 10
```

- **Polarity**: TextBlob sentiment of each review (-1 to 1), rescaled to 0–1.
- **Reviewer rating**: average user star rating (1–10), rescaled to 0–1.
- **IMDb rating**: the title's overall rating, rescaled to 0–1.

### Director aggregate score

The average of the sentiment scores of all that director's games.

### Similarity score (in the report)

For each game, the normalized sentiment score (`score / 3`) and normalized IMDb rating (`rating / 10`) form a 2D vector, which is compared to `[1.0, 1.0]` using cosine similarity. Because cosine similarity measures direction rather than size, this indicates how **balanced** the two metrics are, not how high they are; a game scoring 0.3 on both gets the same 1.0 similarity as one scoring 0.9 on both.

## Sample Report

```
================================================================================
This is the sentiment report of all game directors as of 2026-10-27 18:30:00
...
================================================================================

DIRECTOR: Jane Doe
  Aggregate Score: 2.4512
  Games Directed (2 total):
    - Example Game (Similarity: 0.9987)
    - Another Game (Similarity: 0.9921)

----------------------------------------
```

## Known Limitations

- **Fragile selectors**: extraction depends on IMDb's HTML structure and auto-generated class names (e.g. `sc-4dc495c1-1` for the rating). If IMDb updates its site, fields may come back empty or default (`Unknown`, `1900`, `NULL`).
- **First page of reviews only**: the script does not click "Load more," so only the initially loaded reviews (typically about 25) are collected.
- **Re-scraping inflates `game_count`**: scraping the same game twice increments its director's `game_count` again.
- **Single director per game**: only the first credited director is stored.
- **Titles as keys**: games are identified by title, so two games with the same name will overwrite each other.
- **Fixed waits**: pages are given a flat 3 seconds to load; slow connections may need a longer `time.sleep()`.
- **Terms of use**: automated scraping may conflict with IMDb's terms of service. Use responsibly and at a low request rate.

## License

Add your license here.

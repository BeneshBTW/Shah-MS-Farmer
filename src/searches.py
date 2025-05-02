"""
Fallback keyword-based search system for Microsoft Rewards.
If trend sources fail or are empty, this module generates timestamped,
educational/randomized search phrases to satisfy the Bing search quota.
No external API dependency required.
"""

import dbm.dumb
import logging
import shelve
from enum import Enum, auto
from random import random, randint, shuffle, choice
from time import sleep
from typing import Final

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from src.browser import Browser
from src.utils import CONFIG, getProjectRoot, cooldown
from src.fallback_keywords import generateFallbackKeywords


class RetriesStrategy(Enum):
    EXPONENTIAL = auto()
    CONSTANT = auto()


class Searches:
    maxRetries: Final[int] = CONFIG.retries.max
    baseDelay: Final[float] = CONFIG.get("retries.backoff-factor")
    retriesStrategy = RetriesStrategy[CONFIG.retries.strategy]

    def __init__(self, browser: Browser):
        self.browser = browser
        self.webdriver = browser.webdriver

        dumbDbm = dbm.dumb.open((getProjectRoot() / "google_trends").__str__())
        self.googleTrendsShelf: shelve.Shelf = shelve.Shelf(dumbDbm)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.googleTrendsShelf.__exit__(None, None, None)

    def bingSearches(self) -> None:
        logging.info(f"[BING] Starting {self.browser.browserType.capitalize()} Edge Bing searches...")
        self.browser.utils.goToSearch()

        while True:
            remaining = self.browser.getRemainingSearches(desktopAndMobile=True)
            logging.info(f"[BING] Remaining searches={remaining}")

            if (
                self.browser.browserType == "desktop" and remaining.desktop == 0
            ) or (
                self.browser.browserType == "mobile" and remaining.mobile == 0
            ):
                break

            if remaining.getTotal() > len(self.googleTrendsShelf):
                fallback_keywords = generateFallbackKeywords()
                for keyword in fallback_keywords:
                    self.googleTrendsShelf[keyword] = {"trend_keywords": [keyword]}

            self.bingSearch()
            sleep(randint(10, 15))

        logging.info(f"[BING] Finished {self.browser.browserType.capitalize()} Edge Bing searches!")

    def isSearchSuccessful(self, keyword: str) -> bool:
        try:
            WebDriverWait(self.webdriver, 10).until(
                EC.presence_of_element_located((By.ID, "b_results"))
            )
            page_title = self.webdriver.title.lower()
            return keyword.lower().split()[0] in page_title
        except Exception as e:
            logging.warning(f"[BING] Search success check failed: {e}")
            return False

    def bingSearch(self) -> None:
        pointsBefore = self.browser.utils.getAccountPoints()

        if not self.googleTrendsShelf:
            logging.warning("[BING] No trends available to search.")
            return

        trend = choice(list(self.googleTrendsShelf.keys()))
        trendKeywords = self.googleTrendsShelf[trend]["trend_keywords"]
        shuffle(trendKeywords)
        logging.debug(f"trend={trend}")
        logging.debug(f"shuffled trendKeywords={trendKeywords}")
        baseDelay = Searches.baseDelay

        for i in range(self.maxRetries + 1):
            if i != 0:
                if not trendKeywords:
                    logging.info(f"[BING] No more keywords for trend '{trend}', removing it.")
                    del self.googleTrendsShelf[trend]
                    return

                sleepTime: float
                if Searches.retriesStrategy == Searches.retriesStrategy.EXPONENTIAL:
                    sleepTime = baseDelay * 2 ** (i - 1)
                elif Searches.retriesStrategy == Searches.retriesStrategy.CONSTANT:
                    sleepTime = baseDelay
                else:
                    raise AssertionError
                sleepTime += baseDelay * random()
                logging.debug(f"[BING] Retry {i}/{Searches.maxRetries}, sleeping {sleepTime:.2f} seconds...")
                sleep(sleepTime)

            if not trendKeywords:
                logging.info(f"[BING] Trend '{trend}' is empty, skipping.")
                del self.googleTrendsShelf[trend]
                return

            self.browser.utils.goToSearch()
            searchbar = self.browser.utils.waitUntilClickable(By.ID, "sb_form_q", timeToWait=40)
            searchbar.clear()
            trendKeyword = trendKeywords.pop(0)
            logging.info(f"[BING] Using trendKeyword: '{trendKeyword}'")
            sleep(1)
            searchbar.send_keys(trendKeyword)
            sleep(1)
            searchbar.submit()

            pointsAfter = self.browser.utils.getAccountPoints()
            searchSuccess = self.isSearchSuccessful(trendKeyword)

            if pointsBefore < pointsAfter or searchSuccess:
                logging.info(f"[BING] Search succeeded for keyword '{trendKeyword}', removing trend '{trend}'.")
                del self.googleTrendsShelf[trend]
                cooldown()
                return

        logging.error(f"[BING] Reached max retries for trend '{trend}'. Removing it.")
        del self.googleTrendsShelf[trend]

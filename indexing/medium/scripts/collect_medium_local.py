#!/usr/bin/env python3
"""
Script to run LOCALLY on your machine where you're not blocked by Cloudflare
This will collect all Medium article URLs that you can see
"""

import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json

def collect_all_medium_urls():
    """
    Collect all Medium URLs using Selenium on your local machine
    Run this where you can access Medium without Cloudflare blocks
    """
    
    # Use Chrome (you need ChromeDriver installed)
    driver = webdriver.Chrome()
    
    try:
        print("Opening Medium page...")
        driver.get("https://medium.com/regen-network")
        
        # Wait for page to load
        time.sleep(5)
        
        print("Please make sure you're logged in if needed.")
        print("Scrolling to load all articles...")
        
        all_urls = set()
        last_height = driver.execute_script("return document.body.scrollHeight")
        no_change_count = 0
        
        while no_change_count < 5:  # Stop after 5 scrolls with no new content
            # Scroll down
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)  # Wait for content to load
            
            # Get all article links
            links = driver.find_elements(By.TAG_NAME, "a")
            for link in links:
                href = link.get_attribute("href")
                if href and "medium.com/regen-network/" in href:
                    # Clean URL
                    clean_url = href.split("?")[0]
                    if not any(skip in clean_url for skip in ["/tag/", "/about", "/archive"]):
                        all_urls.add(clean_url)
            
            # Check if new content loaded
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                no_change_count += 1
                print(f"No new content loaded (attempt {no_change_count}/5)")
            else:
                no_change_count = 0
                print(f"Found {len(all_urls)} articles so far...")
                last_height = new_height
        
        print(f"\nFound {len(all_urls)} total articles!")
        
        # Save URLs to file
        with open("medium_urls.json", "w") as f:
            json.dump(list(all_urls), f, indent=2)
        
        print("Saved URLs to medium_urls.json")
        print("\nYou can now send this file to continue the collection process.")
        
        return list(all_urls)
        
    finally:
        driver.quit()

if __name__ == "__main__":
    urls = collect_all_medium_urls()
    print(f"\nCollected {len(urls)} article URLs")
    print("\nFirst 10 URLs:")
    for url in urls[:10]:
        print(f"  - {url}")
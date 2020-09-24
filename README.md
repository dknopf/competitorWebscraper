# competitorWebscraper
Webscraper to scrape competitor lab test directories

I created this Python Selenium webscraper to scrape lab test data from the lab test directories of three major lab testing competitors for a company I worked at over the summer.
This program creates a set of selenium headless chromium browsers and, in parallel, scrapes the test directory websites based on certain pre-established criteria. There are always at least 4 webscraper instances running in parallel.
The program also has built in AWS email error handling, so if certain thresholds aren't met for number of tests scraped or a certain number of errors pop up, my program will send out emails detailing what went wrong and when.

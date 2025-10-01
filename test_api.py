import requests
from bs4 import BeautifulSoup

url = "https://zpbuldhana.maharashtra.gov.in/"
resp = requests.get(url)
resp.raise_for_status()

soup = BeautifulSoup(resp.text, "html.parser")

# Find the div by ID
whats_new_div = soup.find("div", id="whats-new-content")

if whats_new_div:
    # Extract all li elements inside it
    li_items = whats_new_div.find_all("li")
    for i, li in enumerate(li_items, 1):
        print(f"{i}. {li.get_text(strip=True)}")
else:
    print("Div with id 'whats-new-content' not found")

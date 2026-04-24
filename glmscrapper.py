import json
import time
import sys
import pandas as pd
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

API_KEY = "5224498cc5004c18828634cc2c7896c1.IFqKu1J46oECwOF9"
API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

def call_glm(prompt_text, retries=3):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "glm-4.5",  
        "messages": [
            {
                "role": "system", 
                "content": (
                    "You are an expert lead generator. Extract the following information about the hospice/palliative care agency from the provided website text:\n"
                    "- 'Agency Name'\n"
                    "- 'Phone Numbers' (as a single string or list)\n"
                    "- 'General Emails' (as a single string or list)\n"
                    "- 'Address'\n"
                    "- 'Person to Contact' (Name)\n"
                    "- 'Contact Person Email'\n"
                    "- 'Pain Points' (What challenges does the agency face or what do they emphasize needing help with, inferred from their site)\n"
                    "- 'Helpful Outreach Info' (Any other info useful for a sales/outreach pitch)\n"
                    "Return ONLY a raw JSON object with these exact keys. If a field is not found, use null."
                )
            },
            {"role": "user", "content": f"Extract info from this text:\n\n{prompt_text}"}
        ]
    }
    
    for attempt in range(retries):
        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=45)
            response.raise_for_status() 
            
            resp_json = response.json()
            content = resp_json['choices'][0]['message']['content']
            
            # Clean up markdown block if present
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
                
            return json.loads(content.strip())
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                wait_time = (attempt + 1) * 10
                print(f"    [!] Rate limited by GLM (429). Waiting {wait_time}s and retrying...")
                time.sleep(wait_time)
                continue
            else:
                print(f"    [CRITICAL ERROR] The GLM API returned an error: {e}")
                return None
        except Exception as e:
            print(f"    Error parsing GLM response: {e}")
            return None
            
    print("    [!] Max retries reached for GLM API. Skipping this lead.")
    return None

def fetch_and_extract(url):
    try:
        print(f"Scraping: {url}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        for script in soup(["script", "style", "nav", "footer"]):
            script.decompose()
            
        text = soup.get_text(separator=' ')
        # Truncate to avoid exceeding model context limits
        text = ' '.join(text.split())[:15000]
        
        if len(text) < 200:
            print("  Not enough text content found.")
            return None
            
        return call_glm(text)
        
    except Exception as e:
        print(f"  Failed to scrape {url}: {e}")
        return None

def main():
    print("Preparing list of Massachusetts Hospice Agencies...")
    
    # Hardcoded list of prominent MA hospice agencies based on search results and directories
    target_urls = [
        "https://www.caredimensions.org/",
        "https://gscommunitycare.org/",
        "https://www.vnacare.org/",
        "https://hospiceservicesofma.com/",
        "https://www.tuftsmedicine.org/patient-care/services/home-health-hospice-care/hospice-care",
        "https://www.nvna.org/hospice-care/",
        "https://www.bristolelder.org/",
        "https://www.chcrhospice.com/",
        "https://hopehealthco.org/",
        "https://www.vnaofcapecod.org/",
        "https://www.southcoast.org/services/visiting-nurse-association/hospice/",
        "https://www.brocktonvna.org/",
        "https://salmonhealth.com/hospice/",
        "https://www.beaconhospice.com/", # Often redirects to Amedisys but valid
        "https://www.hebrewseniorlife.org/hospice-care",
        "https://www.caringhospice.com/",
        "https://www.constellationhs.com/massachusetts",
        "https://fchc.com/" # Family Continuity
    ]
    
    print(f"Found {len(target_urls)} potential agency websites.")
    
    leads = []
    
    for url in target_urls:
        data = fetch_and_extract(url)
        if data:
            data['Source URL'] = url
            leads.append(data)
            print(f"  Successfully extracted data for: {data.get('Agency Name', 'Unknown')}")
        time.sleep(2) # Be polite
        
    if leads:
        df = pd.DataFrame(leads)
        csv_path = "ma_hospice_leads.csv"
        df.to_csv(csv_path, index=False)
        print(f"\nFinished! Saved {len(leads)} leads to {csv_path}")
    else:
        print("\nNo leads were successfully extracted.")

if __name__ == "__main__":
    main()

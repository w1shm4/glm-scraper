import json
import asyncio
import os
from pathlib import Path
import pandas as pd
import requests
from bs4 import BeautifulSoup
from request_scheduler import schedule_api_request, schedule_request

API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
LOCK_FILE_PATH = Path(".glmscrapper.lock")


def acquire_process_lock(lock_path: Path = LOCK_FILE_PATH) -> None:
    """
    Ensure only one glmscrapper process runs at a time.
    Uses atomic file creation so concurrent starts cannot both succeed.
    """
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(str(os.getpid()))
    except FileExistsError as exc:
        raise RuntimeError(
            f"Another glmscrapper instance is already running (lock: {lock_path})."
        ) from exc


def release_process_lock(lock_path: Path = LOCK_FILE_PATH) -> None:
    if lock_path.exists():
        lock_path.unlink()

async def call_glm(prompt_text):
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

    def _make_glm_request(api_key: str):
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        return asyncio.to_thread(
            requests.post,
            API_URL,
            headers=headers,
            json=data,
            timeout=45,
        )

    try:
        response = await schedule_api_request(
            _make_glm_request,
            request_name="glm_chat_completions",
        )
        response.raise_for_status()

        resp_json = response.json()
        content = resp_json["choices"][0]["message"]["content"]

        # Clean up markdown block if present
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        return json.loads(content.strip())
    except requests.exceptions.HTTPError as e:
        print(f"    [CRITICAL ERROR] The GLM API returned an error: {e}")
        return None
    except Exception as e:
        print(f"    Error parsing GLM response: {e}")
        return None


async def fetch_and_extract(url):
    try:
        print(f"Scraping: {url}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = await schedule_request(
            lambda: asyncio.to_thread(requests.get, url, headers=headers, timeout=15),
            request_name="website_scrape_get",
        )
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
            
        return await call_glm(text)
        
    except Exception as e:
        print(f"  Failed to scrape {url}: {e}")
        return None

async def main():
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
        data = await fetch_and_extract(url)
        if data:
            data['Source URL'] = url
            leads.append(data)
            print(f"  Successfully extracted data for: {data.get('Agency Name', 'Unknown')}")
        await asyncio.sleep(2) # Be polite
        
    if leads:
        df = pd.DataFrame(leads)
        csv_path = "ma_hospice_leads.csv"
        df.to_csv(csv_path, index=False)
        print(f"\nFinished! Saved {len(leads)} leads to {csv_path}")
    else:
        print("\nNo leads were successfully extracted.")

if __name__ == "__main__":
    try:
        acquire_process_lock()
    except RuntimeError as exc:
        print(f"[LOCK] {exc}")
        raise SystemExit(1) from exc

    try:
        asyncio.run(main())
    finally:
        release_process_lock()

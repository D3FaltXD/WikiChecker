from openai import OpenAI
import requests
from bs4 import BeautifulSoup
import urllib.parse
import json

client = OpenAI(api_key="APIKEY")

def guess_wikipedia_search_keywords(website_url):
    """Guess up to 3 search keywords for a company based on its website URL."""
    prompt = (
        f"Given the official website '{website_url}', guess up to 3 different search keywords to find the company's Wikipedia page. "
        "Include: (1) the company name, (2) the full form if it's an abbreviation, (3) the company name plus its main work/domain. "
        "Respond with a comma-separated list of up to 3 keywords or phrases, no explanations."
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    keywords = response.choices[0].message.content.strip()
    return [k.strip() for k in keywords.split(',') if k.strip()]

def search_wikipedia(keyword):
    """Search Wikipedia for a keyword and return a list of page titles."""
    params = {
        'action': 'query',
        'list': 'search',
        'srsearch': keyword,
        'format': 'json',
        'utf8': 1
    }
    resp = requests.get('https://en.wikipedia.org/w/api.php', params=params)
    resp.raise_for_status()
    data = resp.json()
    results = data.get('query', {}).get('search', [])
    return [r['title'] for r in results]

def get_wikipedia_page_url(title):
    """Build the Wikipedia page URL from the title."""
    encoded_title = urllib.parse.quote(title.replace(' ', '_'))
    return f"https://en.wikipedia.org/wiki/{encoded_title}"

def extract_subsidiaries(soup):
    """Extract subsidiaries from a Wikipedia infobox soup."""
    subsidiaries = []
    infobox = soup.find("table", {"class": "infobox"})
    if not infobox:
        return subsidiaries
    for row in infobox.find_all("tr"):
        header = row.find("th")
        if header and 'subsidiar' in header.text.lower():
            cell = row.find("td")
            if cell:
                for link in cell.find_all("a", href=True):
                    name = link.text.strip()
                    href = link['href']
                    if href.startswith("/wiki/"):
                        subsidiaries.append({"name": name, "wiki_url": f"https://en.wikipedia.org{href}"})
                if not cell.find("a", href=True):
                    text = cell.text.strip()
                    if text:
                        subsidiaries.append({"name": text, "wiki_url": None})
    return subsidiaries

def get_official_website_from_infobox(soup):
    """Extract the official website from a Wikipedia infobox soup."""
    infobox = soup.find("table", {"class": "infobox"})
    if not infobox:
        return None
    for row in infobox.find_all("tr"):
        header = row.find("th")
        if header and 'website' in header.text.lower():
            cell = row.find("td")
            if cell:
                link = cell.find("a", href=True)
                if link and link['href'].startswith('http'):
                    return link['href']
    return None

def extract_acquisitions_from_description(soup, company_name):
    paragraphs = [p.text.strip() for p in soup.find_all("p") if p.text.strip()]
    if not paragraphs:
        return []
    description = "\n".join(paragraphs)
    prompt = (
        f"Given the following Wikipedia article text for the company '{company_name}':\n\n{description}\n\n"
        "List the names of companies that have been acquired by this company, if any. "
        "Respond with a comma-separated list of company names only. If none, respond with an empty string."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        names = response.choices[0].message.content.strip()
        return [n.strip() for n in names.split(',') if n.strip()]
    except Exception as e:
        print(f"[OpenAI Error] {e}")
        return []

def extract_acquisitions(soup, company_name=None):
    acquisitions = []
    infobox = soup.find("table", {"class": "infobox"})
    if infobox:
        for row in infobox.find_all("tr"):
            header = row.find("th")
            if header and 'acquisit' in header.text.lower():
                cell = row.find("td")
                if cell:
                    for link in cell.find_all("a", href=True):
                        name = link.text.strip()
                        href = link['href']
                        if href.startswith("/wiki/"):
                            acquisitions.append({"name": name, "wiki_url": f"https://en.wikipedia.org{href}"})
                    if not cell.find("a", href=True):
                        text = cell.text.strip()
                        if text:
                            acquisitions.append({"name": text, "wiki_url": None})
    if not acquisitions and company_name:
        ai_names = extract_acquisitions_from_description(soup, company_name)
        for name in ai_names:
            acquisitions.append({"name": name, "wiki_url": None})
    return acquisitions

def target(company_website):
    """
    Given a company website, find the main Wikipedia page, verify it, extract subsidiaries and their domains and acquisitions.
    Returns a dict: {"main_domain": ..., "wikipedia_url": ..., "subsidiaries": [...], "acquisitions": [...]}
    Returns None if not found/verified.
    """
    keywords = guess_wikipedia_search_keywords(company_website)
    for keyword in keywords:
        titles = search_wikipedia(keyword)
        if not titles:
            continue
        for title in titles:
            url = get_wikipedia_page_url(title)
            try:
                resp = requests.get(url)
                resp.raise_for_status()
            except requests.RequestException:
                continue
            soup = BeautifulSoup(resp.text, 'html.parser')
            valid = False
            infobox = soup.find("table", {"class": "infobox"})
            if infobox:
                links = infobox.find_all("a", href=True)
                for link in links:
                    href = link['href']
                    if company_website.replace("https://", "").replace("http://", "").strip("/") in href:
                        valid = True
                        break
            if valid:
                main_domain = company_website.replace("https://", "").replace("http://", "").strip("/")
                subsidiaries = extract_subsidiaries(soup)
                acquisitions = extract_acquisitions(soup, title)
                # For each acquisition without a wiki_url, try to find it using OpenAI keyword guess and Wikipedia search
                for acq in acquisitions:
                    if not acq.get("wiki_url") and acq["name"]:
                        acq_keywords = guess_wikipedia_search_keywords(acq["name"])
                        for acq_keyword in acq_keywords:
                            acq_titles = search_wikipedia(acq_keyword)
                            if acq_titles:
                                acq["wiki_url"] = get_wikipedia_page_url(acq_titles[0])
                                break
                result = {"main_domain": main_domain, "wikipedia_url": url, "subsidiaries": [], "acquisitions": acquisitions}
                for sub in subsidiaries:
                    sub_domain = None
                    if sub["wiki_url"]:
                        try:
                            sub_resp = requests.get(sub["wiki_url"])
                            sub_resp.raise_for_status()
                            sub_soup = BeautifulSoup(sub_resp.text, 'html.parser')
                            sub_domain = get_official_website_from_infobox(sub_soup)
                        except Exception:
                            sub_domain = None
                    sub_entry = {
                        "name": sub["name"],
                        "domain": sub_domain,
                        "relation": f"subsidiary of {main_domain}"
                    }
                    result["subsidiaries"].append(sub_entry)
                return result
    return None

if __name__ == "__main__":
    res = target("https://www.nvidia.com")
    print(json.dumps(res, indent=2))

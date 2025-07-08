from openai import OpenAI
import requests
from bs4 import BeautifulSoup
import urllib.parse
import json
import re
from urllib.parse import urlparse, unquote

client = OpenAI(api_key="")

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

def extract_subsidiaries(soup, company_name=None):
    """Extract subsidiaries from a Wikipedia page - both infobox and full content."""
    subsidiaries = []
    
    # First, check the infobox
    infobox = soup.find("table", {"class": "infobox"})
    if infobox:
        for row in infobox.find_all("tr"):
            header = row.find("th")
            if header and 'subsidiar' in header.text.lower():
                cell = row.find("td")
                if cell:
                    for link in cell.find_all("a", href=True):
                        name = link.text.strip()
                        href = link['href']
                        if href.startswith("/wiki/") and name:
                            wiki_url = f"https://en.wikipedia.org{href}"
                            print(f"[LINK FOUND] Found Wikipedia link for subsidiary '{name}' in infobox: {wiki_url}")
                            subsidiaries.append({"name": name, "wiki_url": wiki_url})
                    if not cell.find("a", href=True):
                        text = cell.text.strip()
                        if text and text not in ["—", "-", "None", "N/A"]:
                            subsidiaries.append({"name": text, "wiki_url": None})
    
    # Then, scan the full page content for additional subsidiaries using AI
    if company_name:
        print(f"[INFO] Scanning page content for subsidiaries of {company_name}")
        ai_subsidiaries = extract_subsidiaries_from_text(soup, company_name)
        
        # Add AI-found subsidiaries that aren't already in the list
        existing_names = {sub["name"].lower() for sub in subsidiaries}
        for sub_name in ai_subsidiaries:
            if sub_name.lower() not in existing_names and len(sub_name) > 2:
                print(f"[INFO] Found subsidiary in page content: {sub_name}")
                
                # Try to find a Wikipedia link for this subsidiary
                wiki_url = None
                # Look for links in the page that might match this subsidiary
                for link in soup.find_all("a", href=True):
                    if (link.get("href", "").startswith("/wiki/") and 
                        link.text.strip().lower() == sub_name.lower()):
                        wiki_url = f"https://en.wikipedia.org{link['href']}"
                        print(f"[LINK FOUND] Found Wikipedia link for subsidiary '{sub_name}': {wiki_url}")
                        break
                
                if not wiki_url:
                    print(f"[NO LINK] No Wikipedia link found for subsidiary '{sub_name}'")
                
                subsidiaries.append({"name": sub_name, "wiki_url": wiki_url})
    
    # Remove duplicates based on name (case-insensitive)
    seen_names = set()
    unique_subsidiaries = []
    for sub in subsidiaries:
        name_lower = sub["name"].lower()
        if name_lower not in seen_names and len(sub["name"]) > 2:
            seen_names.add(name_lower)
            unique_subsidiaries.append(sub)
    
    return unique_subsidiaries

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
                            wiki_url = f"https://en.wikipedia.org{href}"
                            print(f"[LINK FOUND] Found Wikipedia link for acquisition '{name}' in infobox: {wiki_url}")
                            acquisitions.append({"name": name, "wiki_url": wiki_url})
                    if not cell.find("a", href=True):
                        text = cell.text.strip()
                        if text:
                            acquisitions.append({"name": text, "wiki_url": None})
    if not acquisitions and company_name:
        ai_names = extract_acquisitions_from_description(soup, company_name)
        for name in ai_names:
            wiki_url = None
            # Try to find a Wikipedia link for this acquisition
            for link in soup.find_all("a", href=True):
                if (link.get("href", "").startswith("/wiki/") and 
                    link.text.strip().lower() == name.lower()):
                    wiki_url = f"https://en.wikipedia.org{link['href']}"
                    print(f"[LINK FOUND] Found Wikipedia link for acquisition '{name}': {wiki_url}")
                    break
            if not wiki_url:
                print(f"[NO LINK] No Wikipedia link found for acquisition '{name}'")
            acquisitions.append({"name": name, "wiki_url": wiki_url})
    return acquisitions

def normalize_domain(url):
    """Normalize a URL to get the base domain for comparison."""
    if not url:
        return None
    
    # Remove protocol
    url = url.replace("https://", "").replace("http://", "")
    
    # Remove www prefix
    if url.startswith("www."):
        url = url[4:]
    
    # Remove trailing slash and path
    url = url.split('/')[0]
    
    # Remove port numbers
    url = url.split(':')[0]
    
    return url.lower().strip()

def extract_all_websites_from_infobox(soup):
    """Extract all potential website URLs from a Wikipedia infobox."""
    websites = []
    infobox = soup.find("table", {"class": "infobox"})
    if not infobox:
        return websites
    
    # Look for various website-related fields
    website_keywords = ['website', 'url', 'homepage', 'site', 'web']
    
    for row in infobox.find_all("tr"):
        header = row.find("th")
        if header:
            header_text = header.text.lower().strip()
            # Check if this row contains website information
            if any(keyword in header_text for keyword in website_keywords):
                cell = row.find("td")
                if cell:
                    # Extract all links from the cell
                    for link in cell.find_all("a", href=True):
                        href = link['href']
                        if href.startswith('http'):
                            websites.append(href)
                    
                    # Also check for plain text URLs
                    cell_text = cell.get_text()
                    url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
                    urls = re.findall(url_pattern, cell_text)
                    for url in urls:
                        if not url.startswith('http'):
                            url = 'http://' + url
                        websites.append(url)
    
    return websites

def verify_wikipedia_page_match(soup, target_website):
    """
    Verify that a Wikipedia page matches the target website by checking multiple criteria.
    Returns True only if there's strong evidence this is the correct company page.
    """
    target_domain = normalize_domain(target_website)
    if not target_domain:
        return False
    
    print(f"[DEBUG] Verifying match for target domain: {target_domain}")
    
    # Extract all websites from the infobox
    wiki_websites = extract_all_websites_from_infobox(soup)
    print(f"[DEBUG] Found websites in Wikipedia: {wiki_websites}")
    
    # Check for exact domain matches
    for wiki_url in wiki_websites:
        wiki_domain = normalize_domain(wiki_url)
        if wiki_domain == target_domain:
            print(f"[MATCH] Found exact domain match: {wiki_domain} == {target_domain}")
            return True
    
    # Check for subdomain matches (e.g., investor.nvidia.com should match nvidia.com)
    for wiki_url in wiki_websites:
        wiki_domain = normalize_domain(wiki_url)
        if wiki_domain and target_domain:
            # Check if one is a subdomain of the other
            if (wiki_domain.endswith('.' + target_domain) or 
                target_domain.endswith('.' + wiki_domain)):
                print(f"[MATCH] Found subdomain match: {wiki_domain} <-> {target_domain}")
                return True
    
    # Additional verification: check if the page title or content strongly suggests this is the right company
    page_title = soup.find("h1", {"class": "firstHeading"})
    if page_title:
        title_text = page_title.get_text().lower()
        
        # Extract company name from domain
        company_name_from_domain = target_domain.split('.')[0]
        
        # Check if the company name appears prominently in the title
        if (len(company_name_from_domain) > 3 and 
            company_name_from_domain in title_text):
            
            # Double-check by looking for any website mention in the page
            page_text = soup.get_text().lower()
            if target_domain in page_text:
                print(f"[MATCH] Found company name '{company_name_from_domain}' in title and domain in page text")
                return True
    
    print(f"[NO MATCH] No reliable match found for {target_domain}")
    return False

def extract_subsidiaries_from_text(soup, company_name):
    """Extract subsidiaries from the full Wikipedia page content using AI."""
    paragraphs = [p.text.strip() for p in soup.find_all("p") if p.text.strip()]
    if not paragraphs:
        return []
    
    # Limit content to avoid token limits
    description = "\n".join(paragraphs[:8])  # First 8 paragraphs
    
    prompt = (
        f"Given the following Wikipedia article text for the company '{company_name}':\n\n{description}\n\n"
        "List the names of companies that are subsidiaries of this company, if any mentioned in the text. "
        "Look for phrases like 'subsidiary', 'owns', 'acquired', 'division', 'unit', or similar relationships. "
        "Respond with a comma-separated list of subsidiary company names only. If none, respond with an empty string."
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        names = response.choices[0].message.content.strip()
        if names:
            return [n.strip() for n in names.split(',') if n.strip()]
        return []
    except Exception as e:
        print(f"[ERROR] Failed to extract subsidiaries from text: {e}")
        return []

def _normalize_wiki_path(path):
    """Normalize Wikipedia path for comparison, handling URL encoding and case differences."""
    if not path:
        return None
    
    # Extract just the path part if it's a full URL
    if path.startswith('https://') or path.startswith('http://'):
        try:
            parsed = urlparse(path)
            path = parsed.path
        except:
            path = '/' + '/'.join(path.split('/', 3)[3:])
    
    if not path.startswith('/wiki/'):
        return None
    
    # Get the page name after /wiki/
    page = path[len('/wiki/'):]
    if not page:
        return None
    
    # URL decode the page name
    try:
        page = urllib.parse.unquote(page)
    except:
        pass
    
    # Normalize spaces and underscores (Wikipedia treats them the same)
    page = page.replace('_', ' ').strip()
    
    # Wikipedia is case-insensitive for the first character only
    if page:
        page = page[0].upper() + page[1:]
    
    # Re-encode for consistent comparison
    page_encoded = urllib.parse.quote(page.replace(' ', '_'))
    return f'/wiki/{page_encoded}'

def get_linked_entities_with_domains(soup, entity_list):
    """
    For each entity in entity_list, only include domain if the entity is hyperlinked in the parent page
    (link text matches entity name, case-insensitive, and href matches the entity's Wikipedia URL path, normalized).
    Returns a list of dicts with name, wiki_url, and domain (or None).
    """
    result = []
    # Build a mapping from lowercased link text to hrefs in the parent page
    link_map = {}
    for link in soup.find_all("a", href=True):
        text = link.text.strip().lower()
        href = link['href']
        if text:
            if text not in link_map:
                link_map[text] = []
            link_map[text].append(href)
    for entity in entity_list:
        name = entity["name"]
        wiki_url = entity.get("wiki_url")
        domain = None
        # Only include domain if the entity is hyperlinked in the parent page with exact name match
        if wiki_url:
            entity_name_lc = name.strip().lower()
            entity_url_path = _normalize_wiki_path(wiki_url)
            found_link = False
            if entity_name_lc in link_map and entity_url_path:
                for href in link_map[entity_name_lc]:
                    href_norm = _normalize_wiki_path(href)
                    if href_norm and href_norm == entity_url_path:
                        found_link = True
                        break
            if found_link:
                try:
                    resp = requests.get(wiki_url, timeout=10)
                    resp.raise_for_status()
                    entity_soup = BeautifulSoup(resp.text, 'html.parser')
                    website = get_official_website_from_infobox(entity_soup)
                    if website:
                        domain = normalize_domain(website)
                except Exception as e:
                    print(f"[ERROR] Failed to get domain for entity {name}: {e}")
                    domain = None
        result.append({
            "name": name,
            "wiki_url": wiki_url,
            "domain": domain
        })
    return result

def target(company_website):
    """
    Given a company website, find the main Wikipedia page, verify it, extract subsidiaries and their domains and acquisitions.
    Returns a dict: {"main_domain": ..., "wikipedia_url": ..., "subsidiaries": [...], "acquisitions": [...]}
    Returns None if not found/verified.
    """
    print(f"[INFO] Searching for Wikipedia page for: {company_website}")
    keywords = guess_wikipedia_search_keywords(company_website)
    print(f"[INFO] Generated search keywords: {keywords}")
    
    for keyword in keywords:
        print(f"[INFO] Searching Wikipedia for keyword: '{keyword}'")
        titles = search_wikipedia(keyword)
        if not titles:
            print(f"[INFO] No results found for keyword: '{keyword}'")
            continue
        
        print(f"[INFO] Found {len(titles)} potential pages for '{keyword}': {titles[:5]}")  # Show first 5
        
        for title in titles[:8]:  # Limit to top 8 results per keyword
            url = get_wikipedia_page_url(title)
            print(f"[INFO] Checking page: {title}")
            
            try:
                resp = requests.get(url, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"[ERROR] Failed to fetch {url}: {e}")
                continue
                
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Use the robust verification method
            if verify_wikipedia_page_match(soup, company_website):
                print(f"[SUCCESS] Found verified Wikipedia page: {url}")
                main_domain = normalize_domain(company_website)
                subsidiaries = extract_subsidiaries(soup, title)
                acquisitions = extract_acquisitions(soup, title)
                
                # For each acquisition without a wiki_url, try to find it using OpenAI keyword guess and Wikipedia search
                for acq in acquisitions:
                    if not acq.get("wiki_url") and acq["name"]:
                        print(f"[INFO] Looking up Wikipedia page for acquisition: {acq['name']}")
                        try:
                            acq_keywords = guess_wikipedia_search_keywords(acq["name"])
                            for acq_keyword in acq_keywords:
                                acq_titles = search_wikipedia(acq_keyword)
                                if acq_titles:
                                    candidate_url = get_wikipedia_page_url(acq_titles[0])
                                    # Verify this is actually a page about the entity, not the parent company
                                    if candidate_url != url:  # Don't assign parent company's URL to subsidiary/acquisition
                                        candidate_title = acq_titles[0].lower()
                                        entity_name = acq["name"].lower()
                                        # Simple check: entity name should be in the page title
                                        if any(word in candidate_title for word in entity_name.split() if len(word) > 2):
                                            acq["wiki_url"] = candidate_url
                                            print(f"[INFO] Found Wikipedia page for {acq['name']}: {candidate_url}")
                                            break
                                        else:
                                            print(f"[INFO] Wikipedia page '{acq_titles[0]}' doesn't seem to be about '{acq['name']}'")
                                    else:
                                        print(f"[INFO] Skipping parent company URL for acquisition '{acq['name']}'")
                        except Exception as e:
                            print(f"[ERROR] Failed to find Wikipedia for acquisition {acq['name']}: {e}")
                
                # Only include domain if the entity is hyperlinked in the parent page and its Wikipedia page has an official website
                subsidiaries_with_domains = get_linked_entities_with_domains(soup, subsidiaries)
                acquisitions_with_domains = get_linked_entities_with_domains(soup, acquisitions)
                
                result = {"main_domain": main_domain, "wikipedia_url": url, "subsidiaries": [], "acquisitions": []}
                
                for sub in subsidiaries_with_domains:
                    result["subsidiaries"].append({
                        "name": sub["name"],
                        "domain": sub["domain"],
                        "relation": f"subsidiary of {main_domain}",
                        "wiki_url": sub.get("wiki_url")
                    })
                
                for acq in acquisitions_with_domains:
                    result["acquisitions"].append({
                        "name": acq["name"],
                        "domain": acq["domain"],
                        "wiki_url": acq.get("wiki_url")
                    })
                
                return result
    
    print(f"[ERROR] No verified Wikipedia page found for {company_website}")
    return None

if __name__ == "__main__":
    res = target("google.com")
    print(json.dumps(res, indent=2))

    # Generate plain text report
    def quote(s):
        return f'"{s}"' if s is not None else '""'

    if res:
        lines = []
        lines.append(f"Main domain: {quote(res['main_domain'])}")
        lines.append(f"Wikipedia URL: {quote(res['wikipedia_url'])}")
        lines.append("")
        lines.append("Subsidiaries:")
        if res["subsidiaries"]:
            for sub in res["subsidiaries"]:
                lines.append(f"  - Name: {quote(sub['name'])}")
                lines.append(f"    Domain: {quote(sub['domain'])}")
                lines.append(f"    Wikipedia: {quote(sub['wiki_url'])}")
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append("Acquisitions:")
        if res["acquisitions"]:
            for acq in res["acquisitions"]:
                lines.append(f"  - Name: {quote(acq['name'])}")
                lines.append(f"    Domain: {quote(acq.get('domain'))}")
                lines.append(f"    Wikipedia: {quote(acq.get('wiki_url'))}")
        else:
            lines.append("  (none)")
        report = "\n".join(lines)
        print("\n--- TEXT REPORT ---\n" + report)
        with open("report.txt", "w", encoding="utf-8") as f:
            f.write(report)
    else:
        print("No result to report.")

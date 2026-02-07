import os


def web_search(query: str, page: int = 1, language: str = "en", country: str = "us") -> str:
    """
    Performs a web search based on the user-provided query with pagination.
    Falls back to DuckDuckGo if SERPER_DEV_API_KEY is absent or if Serper API fails.

    Args:
        query (str): The keyword(s) to search for.
        page (int): The page number of the results to return. Defaults to 1.
        language (str): The language of the search results. Defaults to "en", can be "en", "zh-cn", "zh-tw", "ja", "ko".
        country (str): The country of the search results. Defaults to "us", can be "us", "cn", "jp", "kr".

    Returns:
        str: A formatted string containing the title, link, and snippet of the search results for the specified page.
    """
    import requests
    import json

    api_key = os.getenv("SERPER_DEV_API_KEY")
    
    # If API key is absent, go directly to DuckDuckGo
    if not api_key:
        return __search_duckduckgo(query, page, language)

    # Try Serper API first
    url = "https://google.serper.dev/search"

    payload = json.dumps({
        "q": query,
        "page": page,
        "hl": language,
        "gl": country
    })
    headers = {
        'X-API-KEY': api_key,
        'Content-Type': 'application/json'
    }

    try:
        response = requests.request("POST", url, headers=headers, data=payload, timeout=10)
        
        # Check for rejection/limitation errors (401, 403, 429)
        if response.status_code in [401, 403, 429]:
            # Fallback to DuckDuckGo on rejection/limitation
            return __search_duckduckgo(query, page, language)
        
        # Check for other errors
        if response.status_code >= 400:
            # Fallback to DuckDuckGo on other errors
            return __search_duckduckgo(query, page, language)

        try:
            data = response.json()
            return __format_serper_results(data)
        except json.JSONDecodeError:
            # If JSON parsing fails, fallback to DuckDuckGo
            return __search_duckduckgo(query, page, language)
    except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
        # On any network error, fallback to DuckDuckGo
        return __search_duckduckgo(query, page, language)


def __search_duckduckgo(query: str, page: int = 1, language: str = "en") -> str:
    """
    Performs a web search using DuckDuckGo as a fallback.
    
    Args:
        query (str): The keyword(s) to search for.
        page (int): The page number of the results to return. Defaults to 1.
        language (str): The language of the search results. Defaults to "en".
    
    Returns:
        str: A formatted string containing the search results.
    """
    try:
        from duckduckgo_search import DDGS
        
        # Map language codes (DuckDuckGo uses different codes)
        lang_map = {
            "en": "en-us",
            "zh-cn": "zh-cn",
            "zh-tw": "zh-tw",
            "ja": "ja-jp",
            "ko": "ko-kr"
        }
        ddg_lang = lang_map.get(language, "en-us")
        
        # DuckDuckGo search
        with DDGS() as ddgs:
            # Calculate how many results we need for pagination
            max_results = 10  # Results per page
            total_needed = page * max_results
            
            # Fetch all results needed for the requested page
            all_results = list(ddgs.text(
                query,
                region=ddg_lang,
                max_results=total_needed,
                safesearch='moderate'
            ))
            
            # Slice results for the requested page
            offset = (page - 1) * max_results
            results = all_results[offset:offset + max_results]
            
            return __format_duckduckgo_results(results, query)
    except Exception as e:
        return f"Error performing DuckDuckGo search: {str(e)}"


def __format_duckduckgo_results(results: list, query: str) -> str:
    """
    Formats DuckDuckGo search results into a structured string.
    
    Args:
        results (list): List of search result dictionaries from DuckDuckGo.
        query (str): The original search query.
    
    Returns:
        str: A formatted string containing the search results.
    """
    formatted_output = []
    
    if not results:
        formatted_output.append(f"No results found for query: {query}")
        return "\n".join(formatted_output)
    
    formatted_output.append("## Organic Results")
    for i, result in enumerate(results, 1):
        title = result.get("title", "No Title")
        link = result.get("href", "#")
        snippet = result.get("body", "")
        
        formatted_output.append(f"{i}. **[{title}]({link})**")
        if snippet:
            formatted_output.append(f"   {snippet}")
    
    return "\n".join(formatted_output).strip()


def __format_serper_results(data: dict) -> str:
    """
    Formats the raw JSON response from Serper.dev into a structured string.
    """
    formatted_output = []

    # 1. Knowledge Graph
    if "knowledgeGraph" in data:
        kg = data["knowledgeGraph"]
        formatted_output.append("## Knowledge Graph")
        if "title" in kg:
            formatted_output.append(f"**Title**: {kg['title']}")
        if "type" in kg:
            formatted_output.append(f"**Type**: {kg['type']}")
        if "description" in kg:
            if "descriptionSource" in kg and "descriptionLink" in kg:
                 formatted_output.append(f"**Description**: {kg['description']} (Source: [{kg['descriptionSource']}]({kg['descriptionLink']}))")
            else:
                 formatted_output.append(f"**Description**: {kg['description']}")
        
        if "attributes" in kg:
            formatted_output.append("**Attributes**:")
            for key, value in kg["attributes"].items():
                formatted_output.append(f"- {key}: {value}")
        formatted_output.append("")  # Add spacing

    # 2. Organic Results
    if "organic" in data and data["organic"]:
        formatted_output.append("## Organic Results")
        for i, result in enumerate(data["organic"], 1):
            title = result.get("title", "No Title")
            link = result.get("link", "#")
            snippet = result.get("snippet", "")
            formatted_output.append(f"{i}. **[{title}]({link})**")
            if snippet:
                formatted_output.append(f"   {snippet}")
            
            # Optional: Include attributes if useful, but keep it concise
            if "attributes" in result:
                 for key, value in result["attributes"].items():
                      formatted_output.append(f"   - {key}: {value}")
        formatted_output.append("")

    # 3. People Also Ask
    if "peopleAlsoAsk" in data and data["peopleAlsoAsk"]:
        formatted_output.append("## People Also Ask")
        for item in data["peopleAlsoAsk"]:
            question = item.get("question")
            snippet = item.get("snippet")
            link = item.get("link")
            title = item.get("title")
            
            if question:
                formatted_output.append(f"- **{question}**")
            if snippet:
                formatted_output.append(f"  {snippet}")
            if link and title:
                 formatted_output.append(f"  Source: [{title}]({link})")
        formatted_output.append("")
        
    # 4. Related Searches
    if "relatedSearches" in data and data["relatedSearches"]:
        formatted_output.append("## Related Searches")
        queries = [item["query"] for item in data["relatedSearches"] if "query" in item]
        formatted_output.append(", ".join(queries))

    return "\n".join(formatted_output).strip()


def read_webpage_content(url: str) -> str:
    """
    Reads the content of a webpage and returns it as a string.
    """
    import requests
    import time
    from collections import deque
    import threading

    # Rate limiting configuration
    RATE_LIMIT = 20  # requests
    TIME_WINDOW = 60  # seconds

    # Global state for rate limiting (thread-safe)
    if not hasattr(read_webpage_content, "_request_timestamps"):
        read_webpage_content._request_timestamps = deque()
        read_webpage_content._lock = threading.Lock()

    target_url = f"https://r.jina.ai/{url}"
    key = os.getenv("JINA_API_KEY")

    headers = {}
    if key:
        headers["Authorization"] = key
    else:
        # Apply rate limiting if no key is present
        with read_webpage_content._lock:
            current_time = time.time()
            
            # Remove timestamps older than the time window
            while read_webpage_content._request_timestamps and \
                  current_time - read_webpage_content._request_timestamps[0] > TIME_WINDOW:
                read_webpage_content._request_timestamps.popleft()
            
            # Check if limit reached
            if len(read_webpage_content._request_timestamps) >= RATE_LIMIT:
                # Calculate sleep time
                oldest_request = read_webpage_content._request_timestamps[0]
                sleep_time = TIME_WINDOW - (current_time - oldest_request)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
                # After sleeping, we can pop the oldest since it expired (logically)
                # Re-check time/clean just to be safe and accurate, 
                # but effectively we just waited for the slot to free up.
                # Ideally, we add the *new* request time now.
                # Note: after sleep, the current_time has advanced.
                current_time = time.time()
                # Clean up again
                while read_webpage_content._request_timestamps and \
                      current_time - read_webpage_content._request_timestamps[0] > TIME_WINDOW:
                    read_webpage_content._request_timestamps.popleft()

            # Record the execution
            read_webpage_content._request_timestamps.append(time.time())

    response = requests.get(target_url, headers=headers)
    return response.text


if __name__ == "__main__":
    pass

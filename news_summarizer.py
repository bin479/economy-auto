import time, requests, datetime, json, os
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from concurrent.futures import ThreadPoolExecutor

print("✅ 라이브러리 로드 완료")

def authorize_google_sheets():
    google_creds = os.getenv("GOOGLE_CREDENTIALS")
    creds_dict = json.loads(google_creds)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

def call_gemini_with_retry(prompt, max_retries=5, delay=15):
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    for attempt in range(max_retries):
        res = requests.post(GEMINI_URL, headers=headers, data=json.dumps(data))
        if res.status_code == 429:
            wait = delay * (attempt + 1)
            print(f"⚠️ 429 오류, 재시도 중 ({attempt+1}/{max_retries})... {wait}초 대기")
            time.sleep(wait)
        elif res.status_code == 200:
            result = res.json()
            if "candidates" not in result:
                return {"error": "no candidates"}
            return result
        else:
            print(f"❌ API 오류: {res.status_code} - {res.text}")
            time.sleep(5)
    return {"error": "재시도 초과"}

def get_all_page_links():
    print("🔍 링크 수집 시작...")
    url = 'https://media.naver.com/press/015/'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    res = requests.get(url, headers=headers)
    print(f"📡 응답 코드: {res.status_code}")
    soup = BeautifulSoup(res.text, 'html.parser')

    links = []
    for a in soup.select('a'):
        href = a.get('href')
        if not href:
            continue
        if 'n.news.naver.com/article/015/' in href:
            clean_url = href.split('?')[0]
            links.append(clean_url)

    links = list(dict.fromkeys(links))[:100]
    print(f"🔗 발견된 링크 수: {len(links)}개")
    return links

def get_or_create_sheet_tab(spreadsheet, sheet_name):
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        print(f"📄 기존 시트 열기: {sheet_name}")
    except gspread.exceptions.WorksheetNotFound:
        print(f"🆕 시트 생성: {sheet_name}")
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols="10")
        worksheet.append_row(["날짜", "제목", "요약", "스레드"])
    return worksheet

def fetch_article(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        title_tag = soup.select_one('h2.media_end_headline') or soup.select_one('title')
        content_tag = soup.select_one('div#newsct_article') or soup.select_one('div.article-content')
        title = title_tag.get_text(strip=True) if title_tag else "제목 없음"
        content = content_tag.get_text(strip=True) if content_tag else "본문 없음"
        return url, title, content[:2000]
    except Exception as e:
        print(f"❌ 크롤링 실패: {url} - {e}")
        return url, None, None

def summarize_and_thread(title, content):
    prompt = f"""아래 기사의 제목과 본문을 보고 두 가지를 작성해줘.

[SUMMARY]
3줄 요약

[THREAD]
다음 기사 제목과 내용을 보고, 사람들이 흥미롭게 느낄 수 있도록 짧은 트위터(스레드) 스타일 단문(예:🪖 러시아, 우크라 재공격)로 바꿔줘.

형식은: 첫 문장은 이모지를 넣어서 제목 변형 작성해줘. 제목과 본문을 따로 나누되, 한 줄 간격 없이 바로 이어지도록 작성해주세요. 본문은 내용 요약을 참고하여 이모지없이 간결하게 제목보다 긴 15자 이내의 단문으로 작성해주세요 (예: 휴전 협상 교착 속 군사 공격 재개… 유럽은 군사지원 확대 검토)

기사 제목: "{title}"
기사 본문: {content}

트위터 스레드 스타일로 작성해줘:"""

    res = call_gemini_with_retry(prompt)
    if "candidates" not in res:
        return "요약 실패", "스레드 생성 실패"
    raw = res['candidates'][0]['content']['parts'][0]['text'].strip()
    try:
        summary = raw.split("[SUMMARY]")[1].split("[THREAD]")[0].strip()
        thread = raw.split("[THREAD]")[1].strip()
    except:
        summary = raw
        thread = ""
    return summary, thread

def run():
    start = time.time()
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    print(f"✅ run() 시작 - 오늘 날짜: {today}")

    links = get_all_page_links()
    if not links:
        print("❌ 링크 없음. 종료.")
        return

    print("✅ 구글 시트 연결 시도...")
    gc = authorize_google_sheets()
    print("✅ 구글 시트 연결 완료")
    spreadsheet = gc.open("n2")
    worksheet = get_or_create_sheet_tab(spreadsheet, today)
    existing_titles = {row[1] for row in worksheet.get_all_values()[1:] if len(row) > 1}
    print(f"✅ 기존 저장된 기사 수: {len(existing_titles)}개")

    print(f"🌐 기사 크롤링 중... (병렬 20개)")
    articles = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        for url, title, content in executor.map(fetch_article, links):
            if title and title not in existing_titles:
                articles.append((title, content))

    print(f"📰 새 기사 {len(articles)}개 / Gemini 요약+스레드 시작...")

    new_rows = []
    for i, (title, content) in enumerate(articles):
        print(f"🤖 ({i+1}/{len(articles)}) {title[:30]}...")
        summary, thread = summarize_and_thread(title, content)
        new_rows.append([today, title, summary, thread])

    if new_rows:
        worksheet.append_rows(new_rows)
        print(f"📊 {len(new_rows)}개 시트 저장 완료!")
    else:
        print("⏭️ 저장할 새 기사 없음")

    print(f"⏱️ 총 소요 시간: {int(time.time() - start)}초")

if __name__ == "__main__":
    run()

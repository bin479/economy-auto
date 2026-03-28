import time, requests, datetime, json, os
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ✅ Google 인증
def authorize_google_sheets():
    google_creds = os.getenv("GOOGLE_CREDENTIALS")
    creds_dict = json.loads(google_creds)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

# ✅ Gemini API 설정
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
                print(f"⚠️ candidates 없음, 응답: {result}")
                return {"error": "no candidates"}
            return result
        else:
            print(f"❌ API 오류: {res.status_code} - {res.text}")
            time.sleep(5)
    return {"error": "재시도 초과"}

# ✅ 기사 링크 수집 (메인 페이지 기준)
def get_all_page_links():
    url = 'https://media.naver.com/press/015/'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')

    links = []
    for a in soup.select('a'):
        href = a.get('href')
        if href and '/article/' in href and '/015/' in href:
            if href.startswith('/'):
                full_url = 'https://n.news.naver.com' + href
            elif href.startswith('http'):
                full_url = href
            else:
                continue
            links.append(full_url)

    links = list(dict.fromkeys(links))[:100]
    print(f"🔗 발견된 링크 수: {len(links)}개")

    if not links:
        print("⚠️ 링크 없음 - HTML 샘플:")
        print(res.text[:1000])

    return links

# ✅ 기사 본문 추출
def extract_article_info(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')

    title_tag = soup.select_one('h2.media_end_headline') or soup.select_one('title')
    content_tag = soup.select_one('div#newsct_article') or soup.select_one('div.article-content')

    title = title_tag.get_text(strip=True) if title_tag else "제목 없음"
    content = content_tag.get_text(strip=True) if content_tag else "본문 없음"
    return title, content[:2000]

# ✅ Gemini 요약
def summarize_with_gemini_flash(title, content):
    prompt = f"아래 기사의 제목과 본문을 3줄로 요약해줘.\n\n제목: {title}\n본문: {content}"
    res = call_gemini_with_retry(prompt)
    if "candidates" in res:
        return res['candidates'][0]['content']['parts'][0]['text'].strip()
    print(f"⚠️ 요약 실패 이유: {res.get('error', '알 수 없음')}")
    return "요약 실패"

# ✅ 시트 탭 가져오기 또는 생성
def get_or_create_sheet_tab(spreadsheet, sheet_name):
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        print(f"📄 기존 시트 열기: {sheet_name}")
    except gspread.exceptions.WorksheetNotFound:
        print(f"🆕 시트 생성: {sheet_name}")
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols="10")
        worksheet.append_row(["날짜", "제목", "요약", "스레드"])
    return worksheet

# ✅ 요약 실행
def summarize_articles():
    links = get_all_page_links()
    today = datetime.datetime.now().strftime('%Y-%m-%d')  # 오늘 날짜

    gc = authorize_google_sheets()
    spreadsheet = gc.open("n2")
    worksheet = get_or_create_sheet_tab(spreadsheet, today)

    existing_titles = [row[1] for row in worksheet.get_all_values()[1:] if len(row) > 1]

    new_rows = []
    for i, link in enumerate(links):
        try:
            print(f"🔎 ({i+1}/{len(links)}) 기사 요약 중: {link}")
            title, content = extract_article_info(link)

            if title in existing_titles:
                print(f"⏭️ 이미 저장된 기사: {title}")
                continue

            summary = summarize_with_gemini_flash(title, content)
            new_rows.append([today, title, summary, ""])
            print("✅ 요약 완료:", title)

        except Exception as e:
            print(f"❌ 요약 중 오류 발생: {e}")
            continue

    if new_rows:
        worksheet.append_rows(new_rows)
        print(f"📊 {len(new_rows)}개 기사 시트 저장 완료")

# ✅ 스레드 생성
def generate_threads():
    today = datetime.datetime.now().strftime('%Y-%m-%d')  # 오늘 날짜

    gc = authorize_google_sheets()
    spreadsheet = gc.open("n2")
    worksheet = get_or_create_sheet_tab(spreadsheet, today)

    data = worksheet.get_all_values()
    updates = []

    for row_idx in range(1, len(data)):
        row = data[row_idx]
        if len(row) < 3:
            continue

        title, summary = row[1], row[2]
        thread = row[3] if len(row) > 3 else ""

        if not title.strip() or thread.strip():
            continue

        prompt = f"""
다음 기사 제목과 내용을 보고, 사람들이 흥미롭게 느낄 수 있도록 짧은 트위터(스레드) 스타일 단문(예:🪖 러시아, 우크라 재공격)로 바꿔줘.

형식은: 첫 문장은 이모지를 넣어서 제목 변형 작성해줘. 제목과 본문을 따로 나누되, 한 줄 간격 없이 바로 이어지도록 작성해주세요. 본문은 내용 요약을 참고하여 이모지없이 간결하게 제목보다 긴 15자 이내의 단문으로 작성해주세요 (예: 휴전 협상 교착 속 군사 공격 재개… 유럽은 군사지원 확대 검토)

기사 제목: "{title}"
내용 요약: "{summary}"

트위터 스레드 스타일로 작성해줘:
"""

        try:
            response = call_gemini_with_retry(prompt)
            result = response['candidates'][0]['content']['parts'][0]['text'].strip()
            updates.append({
                "range": f"D{row_idx + 1}",
                "values": [[result]]
            })
            print(f"✅ 스레드 생성 완료: {title}")
        except Exception as e:
            print(f"⚠️ 스레드 생성 실패 (Row {row_idx+1}): {e}")
            continue

    if updates:
        worksheet.batch_update(updates)
        print(f"📊 {len(updates)}개 스레드 시트 저장 완료")

# ✅ 실행
if __name__ == "__main__":
    summarize_articles()
    generate_threads()

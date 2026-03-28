import time, requests, datetime, json, os
from datetime import timedelta
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ✅ Google 인증 함수
def authorize_google_sheets():
    try:
        google_creds = os.getenv("GOOGLE_CREDENTIALS")
        if not google_creds:
            print("❌ 오류: GOOGLE_CREDENTIALS 환경 변수가 없습니다.")
            return None
        
        creds_dict = json.loads(google_creds)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"❌ 구글 인증 중 오류 발생: {e}")
        return None

# ✅ Gemini API 호출 함수
def call_gemini_with_retry(prompt, max_retries=5, delay=15):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ 오류: GEMINI_API_KEY가 없습니다.")
        return {"error": "no key"}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    
    for attempt in range(max_retries):
        try:
            res = requests.post(url, headers=headers, data=json.dumps(data))
            if res.status_code == 429:
                wait = delay * (attempt + 1)
                print(f"⚠️ 429(속도제한), {wait}초 대기 중... ({attempt+1}/{max_retries})")
                time.sleep(wait)
            elif res.status_code == 200:
                return res.json()
            else:
                print(f"❌ API 오류: {res.status_code} - {res.text}")
                time.sleep(5)
        except Exception as e:
            print(f"⚠️ API 요청 중 예외 발생: {e}")
            time.sleep(5)
    return {"error": "재시도 초과"}

# ✅ 네이버 기사 링크 수집 (특정 날짜)
def get_all_page_links(date_str):
    formatted_date = date_str.replace("-", "")
    url = f'https://media.naver.com/press/015/newspaper?date={formatted_date}'
    print(f"🔗 {date_str} 한국경제 신문판 조회: {url}")
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        links = []
        for a in soup.select('a'):
            href = a.get('href')
            if href and '/article/' in href and '/015/' in href:
                full_url = 'https://n.news.naver.com' + href if href.startswith('/article/') else href
                links.append(full_url)
        
        unique_links = list(dict.fromkeys(links))
        return unique_links[:100]
    except Exception as e:
        print(f"❌ 링크 수집 중 오류: {e}")
        return []

# ✅ 기사 본문 추출
def extract_article_info(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        title_tag = soup.select_one('h2.media_end_headline') or soup.select_one('title')
        content_tag = soup.select_one('div#newsct_article') or soup.select_one('div.article-content')
        title = title_tag.get_text(strip=True) if title_tag else "제목 없음"
        content = content_tag.get_text(strip=True) if content_tag else "본문 없음"
        return title, content[:2000]
    except:
        return "에러", "에러"

# ✅ 메인 실행 로직
def run_main(target_date):
    print(f"🚀 작업 시작 날짜: {target_date}")
    
    # 1. 시트 연결
    gc = authorize_google_sheets()
    if not gc: return
    try:
        spreadsheet = gc.open("n2")
    except Exception as e:
        print(f"❌ 시트('n2') 열기 실패: {e}")
        return

    # 2. 시트 탭 확인/생성
    try:
        worksheet = spreadsheet.worksheet(target_date)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=target_date, rows="1000", cols="5")
        worksheet.append_row(["날짜", "제목", "요약", "스레드"])

    # 3. 기사 수집 및 요약
    links = get_all_page_links(target_date)
    if not links:
        print(f"ℹ️ {target_date}에 발행된 기사가 없습니다.")
        return

    existing_titles = [row[1] for row in worksheet.get_all_values()[1:] if len(row) > 1]
    
    new_rows = []
    for i, link in enumerate(links):
        title, content = extract_article_info(link)
        if title in existing_titles or title == "제목 없음":
            continue
            
        print(f"🔎 ({i+1}/{len(links)}) 요약 중: {title[:20]}...")
        summary_prompt = f"아래 기사의 내용을 3줄로 요약해줘.\n제목: {title}\n본문: {content}"
        res = call_gemini_with_retry(summary_prompt)
        
        if "candidates" in res:
            summary = res['candidates'][0]['content']['parts'][0]['text'].strip()
            new_rows.append([target_date, title, summary, ""])
        
        time.sleep(1) # API 제한 대비 대기

    if new_rows:
        worksheet.append_rows(new_rows)
        print(f"📊 {len(new_rows)}개 기사 저장 완료.")

    # 4. 스레드(D열) 생성
    data = worksheet.get_all_values()
    updates = []
    for idx, row in enumerate(data[1:], start=2):
        # 제목과 요약은 있는데 스레드(4번째 열)가 비어있는 경우만 실행
        if len(row) >= 3 and (len(row) < 4 or not row[3].strip()):
            title, summary = row[1], row[2]
            print(f"🧵 스레드 생성 중: {title[:20]}...")
            thread_prompt = f"다음 기사 제목과 요약을 보고 흥미로운 트위터 스타일 문구(이모지 포함 제목 1줄 + 요약 1줄)를 만들어줘.\n제목: {title}\n요약: {summary}"
            res = call_gemini_with_retry(thread_prompt)
            if "candidates" in res:
                thread_text = res['candidates'][0]['content']['parts'][0]['text'].strip()
                updates.append({"range": f"D{idx}", "values": [[thread_text]]})

    if updates:
        worksheet.batch_update(updates)
        print(f"✅ {len(updates)}개 스레드 업데이트 완료.")

# ✅ 최종 실행부
if __name__ == "__main__":
    # 어제 날짜 구하기
    yesterday = (datetime.datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    run_main(yesterday)

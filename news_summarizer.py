import time, requests, datetime, json, os
from datetime import timedelta
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from concurrent.futures import ThreadPoolExecutor  # 병렬 처리를 위해 추가

# ✅ Google 인증
def authorize_google_sheets():
    try:
        google_creds = os.getenv("GOOGLE_CREDENTIALS")
        creds_dict = json.loads(google_creds)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"❌ 구글 인증 실패: {e}")
        return None

# ✅ Gemini API 호출 (요약과 스레드를 한 번에 요청하여 속도 향상)
def call_gemini_combined(title, content):
    api_key = os.getenv("GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    # 요약과 스레드 스타일을 한 번에 가져오도록 프롬프트 최적화
    prompt = f"""
    아래 뉴스 기사를 바탕으로 두 가지를 작성해줘.
    1. 요약: 본문을 3줄로 요약.
    2. 스레드: 이모지 포함 흥미로운 제목 1줄 + 본문 1줄 (단문).
    
    형식:
    [SUMMARY]
    (요약 내용)
    [THREAD]
    (스레드 내용)

    기사 제목: {title}
    기사 본문: {content}
    """
    
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    
    for _ in range(3):  # 최대 3회 재시도
        try:
            res = requests.post(url, headers=headers, data=json.dumps(data), timeout=30)
            if res.status_code == 200:
                result = res.json()['candidates'][0]['content']['parts'][0]['text']
                # 결과 파싱
                summary = result.split("[SUMMARY]")[1].split("[THREAD]")[0].strip()
                thread = result.split("[THREAD]")[1].strip()
                return summary, thread
            elif res.status_code == 429:
                time.sleep(5)
        except:
            pass
    return "요약 실패", "스레드 생성 실패"

# ✅ 기사 상세 정보 추출 (병렬 처리용)
def process_article(link):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(link, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        title_tag = soup.select_one('h2.media_end_headline') or soup.select_one('title')
        content_tag = soup.select_one('div#newsct_article') or soup.select_one('div.article-content')
        
        title = title_tag.get_text(strip=True) if title_tag else "제목 없음"
        content = content_tag.get_text(strip=True)[:2000] if content_tag else ""
        
        if title == "제목 없음" or not content:
            return None

        summary, thread = call_gemini_combined(title, content)
        return [title, summary, thread]
    except Exception as e:
        return None

# ✅ 메인 실행 함수
def run_fast_process(target_date):
    start_time = time.time()
    print(f"🚀 {target_date} 작업 시작 (병렬 모드)")

    # 1. 링크 수집
    formatted_date = target_date.replace("-", "")
    list_url = f'https://media.naver.com/press/015/newspaper?date={formatted_date}'
    res = requests.get(list_url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(res.text, 'html.parser')
    links = list(dict.fromkeys(['https://n.news.naver.com' + a.get('href') for a in soup.select('a') if '/article/015/' in a.get('href', '')]))[:50] # 상위 50개만
    
    print(f"🔗 수집된 링크: {len(links)}개")

    # 2. 병렬 처리 (ThreadPoolExecutor) - 10개씩 동시에 처리
    final_data = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(process_article, links))
        for r in results:
            if r: final_data.append([target_date, r[0], r[1], r[2]])

    # 3. 구글 시트 한 번에 저장
    if final_data:
        gc = authorize_google_sheets()
        spreadsheet = gc.open("n2")
        try:
            worksheet = spreadsheet.worksheet(target_date)
        except:
            worksheet = spreadsheet.add_worksheet(title=target_date, rows="1000", cols="5")
            worksheet.append_row(["날짜", "제목", "요약", "스레드"])
        
        worksheet.append_rows(final_data)
        print(f"✅ {len(final_data)}개 기사 처리 완료!")
    
    end_time = time.time()
    print(f"⏱️ 총 소요 시간: {int(end_time - start_time)}초")

if __name__ == "__main__":
    yesterday = (datetime.datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    run_fast_process(yesterday)

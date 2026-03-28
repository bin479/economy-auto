import time, requests, datetime, json, os
from datetime import timedelta
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from concurrent.futures import ThreadPoolExecutor

def run_fast_process(target_date):
    formatted_date = target_date.replace("-", "")
    list_url = f'https://media.naver.com/press/015/newspaper?date={formatted_date}'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    res = requests.get(list_url, headers=headers)
    
    # ✅ 디버깅: 실제 응답 확인
    print(f"📡 응답 코드: {res.status_code}")
    print(f"📄 HTML 길이: {len(res.text)} 글자")
    print(f"🔍 '/article/015/' 포함 여부: {'/article/015/' in res.text}")
    print(f"🔍 '/mnews/article/015/' 포함 여부: {'/mnews/article/015/' in res.text}")
    print("--- HTML 앞부분 500자 ---")
    print(res.text[:500])

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

# ✅ Gemini API 호출 (요약+스레드 통합)
def call_gemini_combined(title, content):
    api_key = os.getenv("GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    prompt = f"""
    아래 뉴스 기사를 바탕으로 두 가지를 작성해줘.
    1. 요약: 본문을 3줄로 요약.
    2. 스레드: 이모지 포함 흥미로운 제목 1줄 + 본문 1줄 (15자 이내 단문).
    
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
    
    try:
        res = requests.post(url, headers=headers, data=json.dumps(data), timeout=20)
        if res.status_code == 200:
            raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
            summary = raw_text.split("[SUMMARY]")[1].split("[THREAD]")[0].strip()
            thread = raw_text.split("[THREAD]")[1].strip()
            return summary, thread
    except:
        pass
    return "요약 실패", "스레드 생성 실패"

# ✅ 개별 기사 처리 (병렬용)
def process_article(link):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        res = requests.get(link, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        title_tag = soup.select_one('h2.media_end_headline') or soup.select_one('title')
        content_tag = soup.select_one('div#newsct_article') or soup.select_one('div.article-content')
        
        if not title_tag or not content_tag:
            return None

        title = title_tag.get_text(strip=True)
        content = content_tag.get_text(strip=True)[:2000]
        
        summary, thread = call_gemini_combined(title, content)
        return [title, summary, thread]
    except:
        return None

# ✅ 메인 실행부
def run_fast_process(target_date):
    start_time = time.time()
    print(f"🚀 {target_date} 작업 시작 (병렬 모드)")

    # 1. 기사 링크 수집 로직 강화
    formatted_date = target_date.replace("-", "")
    list_url = f'https://media.naver.com/press/015/newspaper?date={formatted_date}'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    res = requests.get(list_url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    links = []
    # 모든 a 태그를 검사하여 '015'(한국경제)와 'article'이 포함된 링크 추출
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/article/015/' in href:
            if href.startswith('/'):
                full_url = 'https://n.news.naver.com' + href
            else:
                full_url = href
            links.append(full_url)
    
    links = list(dict.fromkeys(links)) # 중복 제거
    print(f"🔗 발견된 링크 수: {len(links)}개")

    if not links:
        print("❌ 수집된 링크가 없습니다. 종료합니다.")
        return

    # 2. 병렬 처리 (최대 10개 동시 진행)
    final_rows = []
    print(f"🧠 Gemini 요약 및 스레드 생성 중...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(process_article, links[:50])) # 상위 50개만
        for r in results:
            if r:
                final_rows.append([target_date, r[0], r[1], r[2]])

    # 3. 구글 시트 일괄 저장
    if final_rows:
        try:
            gc = authorize_google_sheets()
            spreadsheet = gc.open("n2")
            try:
                worksheet = spreadsheet.worksheet(target_date)
            except:
                worksheet = spreadsheet.add_worksheet(title=target_date, rows="1000", cols="5")
                worksheet.append_row(["날짜", "제목", "요약", "스레드"])
            
            # 기존 데이터와 중복 체크 후 추가
            existing_data = worksheet.get_all_values()
            existing_titles = [row[1] for row in existing_data]
            
            rows_to_add = [r for r in final_rows if r[1] not in existing_titles]
            
            if rows_to_add:
                worksheet.append_rows(rows_to_add)
                print(f"📊 {len(rows_to_add)}개 기사 시트 저장 완료!")
            else:
                print("⏭️ 모든 기사가 이미 시트에 존재합니다.")
        except Exception as e:
            print(f"❌ 시트 저장 중 오류: {e}")

    print(f"⏱️ 총 소요 시간: {int(time.time() - start_time)}초")

if __name__ == "__main__":
    # 어제 날짜 기준 실행
    yesterday = (datetime.datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    run_fast_process(yesterday)

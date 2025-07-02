import os
import requests

def summarize_news():
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    print("요약할 뉴스 가져오는 중... (예시입니다)")

if __name__ == "__main__":
    summarize_news()

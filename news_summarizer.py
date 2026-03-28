import requests
from bs4 import BeautifulSoup

url = 'https://media.naver.com/press/015/'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
res = requests.get(url, headers=headers)

print(f"응답 코드: {res.status_code}")
print(f"HTML 길이: {len(res.text)}자")
print(f"'article' 포함 여부: {'article' in res.text}")
print(f"'/015/' 포함 여부: {'/015/' in res.text}")
print("--- HTML 앞 1500자 ---")
print(res.text[:1500])

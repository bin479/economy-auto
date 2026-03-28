import requests
from bs4 import BeautifulSoup

url = 'https://media.naver.com/press/015/'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
res = requests.get(url, headers=headers)
soup = BeautifulSoup(res.text, 'html.parser')

# 모든 a 태그 href 중 '015' 포함된 것 전부 출력
links_015 = [a.get('href') for a in soup.select('a') if a.get('href') and '015' in a.get('href')]
print(f"'015' 포함 링크 수: {len(links_015)}개")
for l in links_015[:20]:
    print(l)

print("\n--- 'article' 포함 링크 ---")
links_article = [a.get('href') for a in soup.select('a') if a.get('href') and 'article' in a.get('href')]
print(f"'article' 포함 링크 수: {len(links_article)}개")
for l in links_article[:20]:
    print(l)

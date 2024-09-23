from quart import Quart, request, jsonify, render_template
from bs4 import BeautifulSoup
import requests, asyncio
from transformers import BartTokenizer, BartForConditionalGeneration, MBart50Tokenizer, MBartForConditionalGeneration
import re
import aiohttp

app = Quart(__name__)

# BART 모델 및 토크나이저
bart_tokenizer = BartTokenizer.from_pretrained("facebook/bart-large-cnn")
bart_model = BartForConditionalGeneration.from_pretrained("facebook/bart-large-cnn")

# 비동기 HTML 가져오기
async def fetch(session, url):
    async with session.get(url) as response:
        if response.status !=200:
            print(f"Failed to fetch page, status code : {response.status}")
            return None
        return await response.text()

# 카테고리별 뉴스 크롤링
async def fetch_news_by_category(session, category_url):
    headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36',
    'Referer': 'https://news.naver.com/'
    }

    html_content = await fetch(session, category_url)
    soup = BeautifulSoup(html_content, 'html.parser')

    # 응답 상태 코드 확인
    if not html_content:  # HTML이 None이라면
        print("Failed to fetch page or no content returned.")
        return []

    # 최신 10개 뉴스 크롤링
    articles = soup.select('ul.type06_headline li')[:10]
    news_list = []
    
    for article in articles:
        print(111)
        print(article.prettify())

    for article in articles:
        title_tag = article.select_one('dt a img')
        image_tag = article.select_one('dt.photo a img')
        url_tag = article.select_one('dt a')
        print(title_tag)
        print(image_tag)
        title = title_tag['alt'] if title_tag and 'alt' in title_tag.attrs else '제목없음'
        image_url = image_tag['src'] if image_tag else '이미지 없음'
        url = url_tag['href'] if url_tag else 'URL 없음'
        
        news_list.append({
            'title':title,
            'image_url':image_url,
            'url':url
        })
    print(news_list)
    return news_list

# 번역 모델 및 토크나이저
translation_tokenizer = MBart50Tokenizer.from_pretrained("facebook/mbart-large-50-many-to-many-mmt")
translation_model = MBartForConditionalGeneration.from_pretrained("facebook/mbart-large-50-many-to-many-mmt")
# 파파고를 사용한 
def translate_text_papago(text, source_lang, target_lang, client_id, client_secret):
    url = "https://openapi.naver.com/v1/papago/n2mt"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
    }
    data = {
        "source": source_lang,
        "target": target_lang,
        "text": text
    }
    response = requests.post(url, headers=headers, data=data)
    response.raise_for_status()  # 응답 결과 확인용
    result = response.json()
    return result['message']['result']['translatedText']

def clean_text(text):
    text = BeautifulSoup(text, "html.parser").get_text()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s.,!?가-힣]', '', text)
    return text.strip()

def truncate_text(text, max_length=1024):
    tokens = bart_tokenizer.encode(text, truncation=False)
    if len(tokens) > max_length:
        tokens = tokens[:max_length]
        text = bart_tokenizer.decode(tokens, skip_special_tokens=True)
    return text

def summarize_text(text):
    inputs = bart_tokenizer(text, return_tensors="pt", truncation=True, max_length=1024)
    summary_ids = bart_model.generate(
        inputs['input_ids'],
        max_length=300,   # bart모델 생성되는 요약의 최대 길이
        min_length=100,   # bart모델 생성되는 요약의 최소 길이  
        length_penalty=0.5,
        num_beams=2,
        early_stopping=True
    )
    summary = bart_tokenizer.decode(summary_ids[0], skip_special_tokens=True)
    return summary

def translate_text(text, src_lang, tgt_lang):
    # Set source and target language codes
    translation_tokenizer.src_lang = src_lang
    # translation_tokenizer.tgt_lang = tgt_lang
    
    # Prepare the inputs
    inputs = translation_tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    
    # Generate translation
    translation_ids = translation_model.generate(
        inputs['input_ids'],
        max_length=512,
        num_beams=4,
        early_stopping=True,
        forced_bos_token_id=translation_tokenizer.lang_code_to_id[tgt_lang]
    )
    
    # Decode the translated text
    translated_text = translation_tokenizer.decode(translation_ids[0], skip_special_tokens=True)
    
    return translated_text
# 비동기 기사 내용 가져오기
async def fetch_article(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36',
        'Referer': 'https://www.ddaily.co.kr/'
    }
    
    # aiohttp로 세션을 생성하고 비동기적으로 HTML 데이터를 가져옴
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            html_content = await response.text()

    soup = BeautifulSoup(html_content, 'html.parser')

    # 기사 내용을 찾는 부분
    article_div = soup.find('article', id='dic_area')
    if not article_div:
        raise ValueError("Article content not found.")

    article_html = str(article_div)

    # <br> 태그를 개행 문자로 변환
    article_html = article_html.replace('<br>', '\n').replace('</br>', '\n')

    # HTML 태그를 제거하고 텍스트만 추출
    soup = BeautifulSoup(article_html, 'html.parser')
    text = soup.get_text(separator='\n', strip=True)

    return text

@app.route('/')
async def home():
    return await app.send_static_file('home.html')


@app.route('/summarize', methods=['POST'])
async def summarize():
    data = await request.get_json()
    url = data['url']

    try:
        # 비동기적으로 기사 텍스트를 가져옴
        article_text = await fetch_article(url)

        print(f'Original Text: {article_text[:1000]}')
        translated_to_en = translate_text(article_text, src_lang="ko_KR", tgt_lang="en_XX")
        print(f'Translated To Eng: {translated_to_en}')
        clean_text_content = clean_text(translated_to_en)
        print(f'Cleaned Text: {clean_text_content[:100]}')

        if not clean_text_content:
            return jsonify({'summary': 'No content found to summarize.'})

        truncated_text = truncate_text(translated_to_en)
        print(f'Truncated Text: {truncated_text[:100]}')

        summary = summarize_text(truncated_text)
        print(f'Summary: {summary}')

        if not summary or summary.strip() == "":
            return jsonify({'summary': 'No summary available.'})
        translated_to_ko=translate_text(summary,src_lang="en_XX", tgt_lang="ko_KR")
        print(f"translated_summary : {translated_to_ko}")
        return jsonify({'summary' : translated_to_ko})
        # return jsonify({'summary': summary})

    except Exception as e:
        print(f'Error: {str(e)}')
        return jsonify({'summary': f'Error processing the URL: {str(e)}'})
    
@app.route('/news')
async def get_news():
    category = request.args.get('category', '정치')
    print(category)
    category_urls = {
        '정치': 'https://news.naver.com/main/list.naver?mode=LSD&mid=shm&sid1=100',
        '경제': 'https://news.naver.com/main/list.naver?mode=LSD&mid=shm&sid1=101',
        '사회/문화': 'https://news.naver.com/main/list.naver?mode=LSD&mid=shm&sid1=102',
        'IT/과학': 'https://news.naver.com/main/list.naver?mode=LSD&mid=shm&sid1=105',
        '세계': 'https://news.naver.com/main/list.naver?mode=LSD&mid=shm&sid1=104'
    }


    async with aiohttp.ClientSession() as session:
        try:
            news_list = await fetch_news_by_category(session, category_urls[category])
            return jsonify(news_list)
        except Exception as e:
            print(f"Error fetching news: {e}")
            return jsonify({"error": "뉴스를 가져오는 데 실패했습니다."}), 500
@app.route('/watchnews')
async def watchnews():
    return await app.send_static_file('watchnews.html')


@app.route('/summarizepage', methods = ['POST', 'GET'])
async def summarizepage():
    return await app.send_static_file('summarizepage.html')

async def run_app():
    await app.run_task(host='0.0.0.0', port=8000)

if __name__ == '__main__':
    asyncio.run(run_app())
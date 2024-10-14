from quart import Quart, request, jsonify, render_template, redirect, url_for, flash, session
from bs4 import BeautifulSoup
import requests, asyncio, re, aiohttp, asyncpg, os
from transformers import BartTokenizer, BartForConditionalGeneration, MBart50Tokenizer, MBartForConditionalGeneration
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from urllib.parse import unquote

app = Quart(__name__)
# CORS(app)
# BART 모델 및 토크나이저
bart_tokenizer = BartTokenizer.from_pretrained("facebook/bart-large-cnn")
bart_model = BartForConditionalGeneration.from_pretrained("facebook/bart-large-cnn")

# 비동기 PostgreSQL 연결 설정
async def init_db():
    return await asyncpg.connect(
        user='postgres',
        password='1234',
        database='NewsSummarization',
        host='localhost'
    )



 

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

# 기사 내용 정리하기 (공백, 특수문자 제거 등)
def clean_text(text):
    text = BeautifulSoup(text, "html.parser").get_text()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s.,!?가-힣]', '', text)
    return text.strip()
# 기사 내용 분리하기
def truncate_text(text, max_length=1024):
    tokens = bart_tokenizer.encode(text, truncation=False)
    if len(tokens) > max_length:
        tokens = tokens[:max_length]
        text = bart_tokenizer.decode(tokens, skip_special_tokens=True)
    return text
# 기사 내용 요약하기
def summarize_text(text):
    inputs = bart_tokenizer(text, return_tensors="pt", truncation=True, max_length=1024)
    summary_ids = bart_model.generate(
        inputs['input_ids'],
        max_length=150,   # bart모델 생성되는 요약의 최대 길이
        min_length=120,   # bart모델 생성되는 요약의 최소 길이  
        length_penalty=0.8,
        num_beams=2,
        early_stopping=True
    )
    summary = bart_tokenizer.decode(summary_ids[0], skip_special_tokens=True)
    return summary
# 기사 내용 번역하기
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
# 홈 화면
@app.route('/')
async def home():
    isloggedin='userid' in session
    
    return await render_template('home.html', isloggedin=isloggedin)

# 요약 기능 경로
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
# 뉴스 크롤링 호출 경로
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
    print(category)

    async with aiohttp.ClientSession() as session:
        try:
            news_list = await fetch_news_by_category(session, category_urls[category])
            return jsonify(news_list)
        except Exception as e:
            print(f"Error fetching news: {e}")
            return jsonify({"error": "뉴스를 가져오는 데 실패했습니다."}), 500
# 최신뉴스보기 경로
@app.route('/watchnews')
async def watchnews():
    return await render_template('watchnews.html')

# 요약 페이지 경로
@app.route('/summarizepage', methods = ['POST', 'GET'])
async def summarizepage():
    return await render_template('summarizepage.html')




@app.route('/register', methods=['POST'])
async def register():
    try:
        # 폼 데이터 가져오기
        form_data = await request.form
        userid = form_data.get('userid')
        password = form_data.get('password')
        email = form_data.get('email')
        hashed_password = generate_password_hash(password)
        conn = await init_db()

        # 데이터 유효성 검사
        if not userid or not password or not email:
            return await render_template('register.html', error='모든 필드를 입력해야 합니다.')

        # ID 중복 체크
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", userid)
        if user:
            return await render_template('register.html', error='이미 존재하는 아이디입니다.')

        # 회원정보 저장
        await conn.execute(
            "INSERT INTO users (user_id, user_password, user_email) VALUES ($1, $2, $3)",
            userid, hashed_password, email
        )
        
        # DB 연결 닫기
        await conn.close()
        
        return redirect(url_for('registerdone_page'))

    except Exception as e:
        print(f"Error: {e}")
        return await render_template('register.html', error='서버 오류가 발생했습니다.')

# 회원가입
@app.route('/register', methods=['GET'])
async def register_page():
    return await render_template('register.html')

@app.route('/check-username', methods=['POST'])
async def check_username():
    try:
        data = await request.get_json()
        print(data)
        userid = data['userid']

        conn = await init_db()

        # ID 중복 체크
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", userid)
        await conn.close()

        if user:
            return jsonify({'message': '이미 존재하는 아이디입니다.'}), 400
        else:
            return jsonify({'message': '사용 가능한 아이디입니다.'}), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'message': '서버 오류가 발생했습니다.'}), 500

@app.route('/registerdone.html', methods=['GET'])
async def registerdone_page():
    return await render_template('registerdone.html')

# 로그인 라우트
@app.route('/login', methods=['GET', 'POST'])
async def login():
    if request.method == 'POST':
        userid = (await request.form)['userid']
        password = (await request.form)['password']
        conn = await init_db()


        # 데이터베이스에서 유저 정보 확인
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", userid)
        if user:
            print(check_password_hash(user['user_password'], password))
            if check_password_hash(user['user_password'], password):
                print("ifentered")
                session['userid'] = userid
                # 관리자 아이디인 경우
                if userid == 'admin':
                    return redirect(url_for('home'))
                else:
                    print(111111)
                    flash('로그인이 완료되었습니다.', 'success')
                    return redirect(url_for('home'))
            else:
                flash('비밀번호가 잘못되었습니다.', 'error')
                return redirect(url_for('login'))
        else:
            print(222222)
            flash('아이디가 존재하지 않습니다.', 'error')
            print('아이디가 존재하지 않습니다.')
        

            
    print(333333)
    return await render_template('login.html')


# 관리자 페이지 라우트
@app.route('/admin')
async def admin_page():
    return "관리자 페이지입니다."

# 로그아웃 라우트
@app.route('/logout', methods=['POST'])
async def logout():
    session.pop('userid', None)
    return redirect(url_for('home'))


# 사용자가 열람한 뉴스 기록
@app.route('/log-news-click', methods=['POST'])
async def viewed_news_log():
    try:
        # 폼 데이터 가져오기
        user_id = session.get('userid')
        data = await request.get_json()
        # print(f"Received data: {data}")
        title = data.get('title')
        url=data.get('url')
        decoded_title=unquote(title)
        decoded_url=unquote(url)
        if not user_id:
            return "로그인 된 유저가 없습니다.", 403
        conn = await init_db()


        # 회원정보 저장
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        user_key=user['user_key']
        print(user_key)
        await conn.execute(
            "INSERT INTO viewed_news (user_key, news_title, news_url, viewed_time) VALUES ($1, $2, $3, $4)",
            user_key, title, url, datetime.now()
        )
        
        # DB 연결 닫기
        await conn.close()
        

    except Exception as e:
        print(f"Error: {e}")
        return "서버 오류가 발생했습니다.", 500
    
    return "뉴스 열람 기록이 저장되었습니다.", 200

# 사용자가 열람한 뉴스 기록
@app.route('/category-count-up', methods=['POST'])
async def category_count_up():
    try:
        # 폼 데이터 가져오기
        user_id = session.get('userid')
        data = await request.get_json()
        category = data.get('category')
        if not user_id:
            return "로그인 된 유저가 없습니다.", 403
        conn = await init_db()


        # 회원정보 저장
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        user_key=user['user_key']

        # 카테고리 
        _category = await conn.fetchrow("SELECT * FROM categories WHERE category_name = $1", category)
        category_key=_category['category_key']
        print(category_key)
        async with conn as cn:
            quary ="""INSERT INTO cagtegorycount (user_key, category_key, count) 
            VALUES ($1, $2, 1)
            ON CONFLICT (user_key, category_key)
            DO UPDATE SET count = categorycount.count + 1"""
            await cn.execute(quary,user_key, category_key)
        
        return jsonify({"success": True}), 200
        

    except Exception as e:
        print(f"Error: {e}")
        return "서버 오류가 발생했습니다.", 500
    
    

@app.route('/viewednews')
async def viewed_news():
    try:
        # 사용자가 로그인했는지 확인
        user_id = session.get('userid')
        if not user_id:
            return redirect(url_for('home'))  # 로그인 페이지로 리다이렉트

        conn = await init_db()

        # 로그인한 사용자의 정보를 가져옴
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        user_key = user['user_key']

        # 해당 사용자의 뉴스 열람 기록을 데이터베이스에서 가져옴
        viewed_news = await conn.fetch(
            """
            SELECT news_title, news_url, viewed_time 
            FROM viewed_news 
            WHERE user_key = $1
            ORDER BY viewed_time DESC
            """, 
            user_key
        )

        return await render_template('viewednews.html', news_list=viewed_news[:10])
    except Exception as e:
        return f"에러가 발생했습니다: {str(e)}"

app.secret_key = 'your_secret_key'

# 앱 실행 설정
async def run_app():
    port = int(os.environ.get("PORT",8000))
    await app.run_task(host='0.0.0.0', port=port)
# 앱 실행
if __name__ == '__main__':

    asyncio.run(run_app())
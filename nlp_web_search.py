# 생활 꿀팁 검색 요약 서비스

import torch
from boilerpy3 import extractors
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import requests, openai, chardet, re
from sentence_transformers import CrossEncoder

# 전처리 설정
torch.cuda.empty_cache()

# API 키 설정
openai.api_key = "your openai api key"
google_api_key = "your google search api key"
google_cx = "your google cx"

# 모델 정의
model = CrossEncoder('cross-encoder/stsb-roberta-base')

# 1. 유사 쿼리 생성 함수
def generate_similar_queries(query: str, n: int = 3):
    response = openai.ChatCompletion.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": f"‘{query}’와 의미가 비슷한 검색어 문장을 {n}개만 만들어줘. 다음 규칙을 지켜줘:\n- 중복 없이\n- 번호 없이\n- 간결하게\n- 부가 설명 없이\n- 의미가 축소되거나 달라지지 않게\n- 한 줄에 하나씩 출력"},
            {"role": "user", "content": query}
        ],
        max_tokens=100,
        temperature=0.6,
    )

    output = response['choices'][0]['message']['content'].strip()
    return [line for line in output.splitlines() if line.strip()]

# 2. 구글 검색 함수
def google_search(query, api_key, cx):
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': api_key,
        'cx': cx,
        'q': query,
        'num': 2  # 최대 10개까지 가능
    }
    response = requests.get(url, params=params)
    items = response.json().get('items', [])
    results = []
    for item in items:
        if any(x in item['link'] for x in ['tiktok', 'youtube', 'shop', 'pinterest', 'kmong', 'pdf', 'news', 'notice', 'file', 'price', 'promotion', 'event', 'coupon']):
            continue
        results.append(item['link'])
    return results

# 3. 텍스트 추출 함수
def extract_blog_id_log_no(url):
    # ?blogId=…&logNo=… 형태
    m = re.search(r"blogId=([^&]+)&logNo=([^&]+)", url)
    if m:
        return m.group(1), m.group(2)
    # /{blogId}/{logNo} 형태
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None

def extract_naver_blog_text(blog_id, log_no):
    post_url = f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"
    res = requests.get(post_url, headers={"User-Agent":"Mozilla/5.0"})
    soup = BeautifulSoup(res.text, "html.parser")
    # SE 편집기, 구 에디터 영역 모두 커버
    sel = soup.select_one(".se-main-container") or soup.select_one("#postViewArea")
    return sel.get_text(separator="\n").strip() if sel else ""

def extract_text(urls):
    output = []
    for u in urls:
        try:
            extractor = extractors.ArticleExtractor()
            response = requests.get(u, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)

            # 자동 인코딩 감지
            detected = chardet.detect(response.content)
            encoding = detected['encoding'] or 'utf-8'
            html_str = response.content.decode(encoding, errors="ignore")

            extracted = False # 추출 성공 여부 추적

            # 1차 시도: boilerpy3
            txt = extractor.get_doc(html_str).content.strip()
            if txt:
                output.append(txt)
                extracted = True

            # 2차 시도: 수동 추출 (BeautifulSoup)
            elif not extracted:
                soup = BeautifulSoup(html_str, "html.parser")
                body = soup.find("body")
                raw_text = body.get_text(separator="\n").strip() if body else ""
                if raw_text:
                    output.append(raw_text)
                    extracted = True

            # 3차 시도: 네이버 블로그 특수 구조
            if not extracted and "blog.naver.com" in urlparse(u).netloc:
                bid, ln = extract_blog_id_log_no(u)
                if bid and ln:
                    txt = extract_naver_blog_text(bid, ln)
                    if txt:
                        output.append(txt)

        except Exception as e:
            continue # 예외 발생 시 무조건 다음으로 넘어감

    return output

# 4. 블로그 요약 함수
def summarize_text(query, blog_content):
    if not blog_content.strip(): # 공백만 있어도 빈 값으로 판단
        return ""

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": f"다음 블로그 내용을 '{query}' 주제에 맞춰 간결하게 요약해줘. 중요한 정보와 핵심적인 팁을 포함해."},
            {"role": "user", "content": blog_content}
        ],
        max_tokens=500,
        temperature=0.6,
    )
    return response['choices'][0]['message']['content'].strip()

# 5. 요약 통합 함수
def summarize_all_text(query, summaries):
    if not summaries:
        return "검색 결과가 충분하지 않아 정확한 답변을 제공할 수 없습니다."

    combined = "\n".join([f"{i + 1}. {s}" for i, s in enumerate(summaries)])

    response = openai.ChatCompletion.create(
        model="gpt-4-turbo",
        messages = [
            {
                "role": "system",
                "content": (
                    f"아래는 '{query}'에 대한 여러 블로그 요약입니다.\n\n"
                    "이 내용을 다음 규칙에 따라 통합 요약해 주세요:\n"
                    "- 가장 핵심적이고 중요한 방법이나 정보를 먼저 제시해 주세요.\n"
                    "- 필요한 경우 추천 순서(우선순위)를 명확하게 표현해 주세요.\n"
                    "- 주의사항이나 실수하기 쉬운 점은 별도로 강조해 주세요.\n"
                    "- 중복된 내용은 제거하고, 명확하고 간결하게 정리해 주세요.\n"
                    "- 초보자도 이해할 수 있도록 친절하고 부드러운 말투로 설명해 주세요.\n"
                    "- 단계적 설명이 필요한 경우 번호를 매겨 주세요.\n"
                    "- 가능하면 제목(##)과 목록(-, 1.)을 사용해 가독성을 높여주세요.\n"
                    "- 주제에 따라 적절하게 실용성, 신뢰성, 경고 문구를 균형 있게 포함해 주세요.\n"
                    "- 장소명, 전화번호, 예약 안내 등 홍보성 문구는 모두 제외하고 요약해 주세요."
                )
            },
            {
                "role": "user",
                "content": combined
            }
        ],
        max_tokens=1024,
        temperature=0.6,
    )
    return response['choices'][0]['message']['content'].strip()

# 6-1. 문맥 필요 여부
def needs_context_with_history(previous_summary, current_query):
    if previous_summary:
        prompt = (
            f"다음은 이전 대화 요약과 사용자의 현재 질문입니다.\n"
            f"[이전 요약]\n{previous_summary}\n"
            f"[현재 질문]\n{current_query}\n\n"
            "이 질문이 이전 요약 없이 보면 '무엇을 말하는지 알 수 없거나 해석이 애매한 질문'인가요?\n"
            "그렇다면 '예', 아니라면 '아니오'로만 대답해 주세요."
        )


        response = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages = [
                {"role": "system", "content": "당신은 질문이 문맥을 필요로 하는지 판별하는 도우미입니다."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=10,
            temperature=0,
        )

        answer = response['choices'][0]['message']['content'].strip().lower()
        return "예" in answer # 문맥이 필요하다면 True, 아니라면 False 반환

    else:
        return False

# 6-2. 검색 필요 여부
def find_most_similar_question(current_query, chat_history, threshold=0.9):
    if not chat_history:
        return None

    # (current_query, past_query) 페어 리스트 생성
    pairs = [(current_query, chat['q']) for chat in chat_history]

    # CrossEncoder로 점수 예측(0~1)
    scores = model.predict(pairs)

    # 최고점 & 인덱스
    best_idx = int(scores.argmax())
    best_score = float(scores[best_idx])

    if best_score >= threshold:
        return chat_history[best_idx]['a']

    return None



# 6-3. 문맥 반영 검색어 생성 함수
def enrich_query_gpt(previous_summary, current_query):
    prompt = (
        f"다음은 이전 대화 요약과 현재 질문입니다.\n\n"
        f"[이전 요약]\n{previous_summary}\n\n"
        f"[현재 질문]\n{current_query}\n\n"
        "이 둘을 참고하여, 웹 검색에 적합한 한 문장짜리 검색 쿼리를 만들어주세요."
    )

    response = openai.ChatCompletion.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": "당신은 검색어를 최적화해주는 도우미입니다."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=50,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()

# 7. 문맥 반영 검색 및 요약 함수
def run_search_and_summarize(previous_summary, current_query, chat_history):
    # 이전 문맥 필요 여부 파악
    if needs_context_with_history(previous_summary, current_query):
        enriched_query = enrich_query_gpt(previous_summary, current_query)

    else:
        enriched_query = current_query

    # 검색 필요 여부 파악 -> 기존 chat_history에 있다면 그대로 반환, 없으면 새로 검색
    best_answer = find_most_similar_question(enriched_query, chat_history)
    if best_answer:
        return enriched_query, best_answer

    # 아래부터는 검색하는 로직
    # 1. 유사 쿼리 + 원본 쿼리
    similar_queries = generate_similar_queries(enriched_query)
    queries_set = set(similar_queries)
    queries_set.discard(enriched_query)  # 혹시 중복된 원래 query가 있으면 제거
    queries = [enriched_query] + list(queries_set)

    # 2. 검색 결과 URL 수집
    all_urls = []
    for q in queries:
        all_urls.extend(google_search(q, google_api_key, google_cx))
    all_urls = list(set(all_urls))[:10]

    # 3. 본문 텍스트 추출
    texts = extract_text(all_urls)
    texts = [text for text in texts if len(text) <= 10000]

    # 4. 각 블로그별 요약
    summaries = [summarize_text(enriched_query, text) for text in texts]

    # 5. 요약 통합
    combined_summary = summarize_all_text(enriched_query, summaries)
    return enriched_query, combined_summary

# 8. 문맥 요약 누적 함수 -> 이전 요약 + 현재 요약을 하나로 요약시켜 문맥을 유지
def summarize_qa(previous_summary, question, answer):
    # 이전 요약이 있으면 포함, 없으면 생략
    base = f"{previous_summary}\n\n" if previous_summary else ""
    convo = base + f"Q: {question}\nA: {answer}"
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "아래 대화(Q&A)를 한 문단으로 간결하게 요약해 주세요."},
            {"role": "user", "content": convo}
        ],
        max_tokens=200,
        temperature=0.3
    )
    return response['choices'][0]['message']['content'].strip()

# 9. 최종 실행 함수
def run_pipeline_with_context(previous_summary, current_query, chat_history):
    # 문맥 반영 검색 및 요약
    enriched_query, response_text = run_search_and_summarize(
        previous_summary, current_query, chat_history
    )

    # 이전 문맥 + 현재 Q&A 요약을 결합한 새로운 문맥 생성
    new_summary = summarize_qa(previous_summary, current_query, response_text)

    # 값 반환
    return enriched_query, response_text, new_summary
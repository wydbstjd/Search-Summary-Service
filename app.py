from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import json, os
from nlp_web_search import run_pipeline_with_context

app = FastAPI()
CHAT_HISTORY_FILE = "chat_history.json"

class ChatRequest(BaseModel):
    session_id: str
    previous_summary: str
    query: str

class DeleteRequest(BaseModel):
    session_id: str
def load_chat_history():
    # 1) 파일이 없거나, 크기가 0이면 기본 빈 dict 반환
    if not os.path.exists(CHAT_HISTORY_FILE) or os.path.getsize(CHAT_HISTORY_FILE) == 0:
        return {}
    # 2) JSON 파싱 시 에러 나면 빈 dict 반환
    try:
        with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data
    except json.JSONDecodeError:
        return {}

def save_chat_history(session_data):
    with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)

@app.post("/chat")
def chat_with_context(req: ChatRequest):
    #기존 대화 기록 불러오기
    all_sessions = load_chat_history()
    session = all_sessions.get(req.session_id, {"summary": "", "history": []})

    # 문맥 요약 및 대화 이력
    prev_summary = session.get("summary", "")
    history = session.get("history", [])

    # 파이프라인 실행
    enriched_query, response_text, new_summary = run_pipeline_with_context(
        prev_summary, req.query, history
    )

    # 새로운 대화 추가
    history.append({'q': req.query, 'a': response_text})
    session["history"] = history
    session["summary"] = new_summary

    # 저장
    all_sessions[req.session_id] = session
    save_chat_history(all_sessions)

    # 최종 응답 반환
    return {
        "enriched_query": enriched_query,
        "final_answer": response_text,
        "new_summary": new_summary,
        "chat_history": history # 기존 대화 내역 불러오기 위해 같이 반환
    }

@app.delete("/delete_session")
def delete_session(req: DeleteRequest):
    all_sessions = load_chat_history()
    if req.session_id not in all_sessions:
        raise HTTPException(status_code=404, detail="Session ID not found.")
    del all_sessions[req.session_id]
    save_chat_history(all_sessions)
    return {"message": f"Session '{req.session_id}' deleted successfully."}

@app.get("/load_sessions")
def load_sessions():
    return load_chat_history()

# api 실행(bash) -> uvicorn app:app --reload

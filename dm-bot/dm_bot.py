"""광고 쇼츠 DM 자동답장 + 링크 답글 — GitHub Actions 에서 5분마다 돈다(컴퓨터가 꺼져 있어도). 2026-10-24.

원본: D:\\shorts\\5.PROJECT\\tools\\auto_ad\\gh_dm_bot\\ (이 저장소에 올린 사본). 로컬 판 dm_reply.py 와 같은 규칙.
- 인스타그램 댓글 → 댓글 단 사람에게 비공개 답장(DM)으로 구매 링크 + 댓글에 짧은 공개 답글. 댓글당 한 번, 댓글 후 7일 안.
- 인스타그램 DM 으로 먼저 말을 걸어 온 사람 → 최근 영상 링크(대화마다 하루 한 번, 마지막 말이 우리 쪽이면 건너뜀).
- 스레드 답글 → 링크 답글(스레드는 DM API 없음). 하루 THREADS_DAILY 개 상한(2026-10-16 Meta API 차단 이력).
입력: dm-bot/posts.json(PC 의 게시 단계가 올린다 — 영상별 인스타·스레드 id 와 링크 문구)
기록: dm-bot/state.json(처리한 댓글·답글·대화 id 만. 사용자 이름은 남기지 않는다 — 공개 저장소)
비밀: INSTAGRAM_ACCESS_TOKEN, THREADS_ACCESS_TOKEN (저장소 Secrets)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

IG = "https://graph.instagram.com/v23.0"
TH = "https://graph.threads.net/v1.0"
HERE = Path(__file__).parent
POSTS, STATE = HERE / "posts.json", HERE / "state.json"
DAYS, THREADS_DAILY = 7, 10
DRY = "--dry" in sys.argv
PUBLIC_ACK = "DM으로 링크 보내드렸어요 💌"


def log(msg):
    print(f"[{time.strftime('%m-%d %H:%M:%S', time.gmtime(time.time() + 9 * 3600))} KST] {msg}", flush=True)


def api(method, url, params):
    data = None
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method), timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        for k in ("INSTAGRAM_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"):  # 혹시 오류 본문에 토큰이 섞여도 로그에 남기지 않는다
            if os.environ.get(k):
                body = body.replace(os.environ[k], "***")
        raise RuntimeError(f"HTTP {e.code} {body}") from None


def dm_text(msg):
    return "안녕하세요! 영상 속 제품 링크 보내드려요 😊\n" + msg


def main():
    tk, th = os.environ["INSTAGRAM_ACCESS_TOKEN"], os.environ["THREADS_ACCESS_TOKEN"]
    posts = [p for p in json.loads(POSTS.read_text(encoding="utf-8")) if time.time() - p["at"] <= DAYS * 86400]
    posts.sort(key=lambda p: p["at"], reverse=True)
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    for k, v in (("ig_comments", []), ("ig_convos", {}), ("th_replies", []), ("th_daily", {})):
        st.setdefault(k, v)
    me = api("GET", f"{IG}/me", {"fields": "user_id,username", "access_token": tk})
    uid, uname = me["user_id"], me["username"]
    sent = 0

    for p in posts:  # 1) 인스타 댓글 → DM + 공개 답글
        if not p.get("ig"):
            continue
        try:
            cs = api("GET", f"{IG}/{p['ig']}/comments", {"fields": "id,text,username", "limit": 50, "access_token": tk}).get("data", [])
        except RuntimeError as x:
            log(f"{p['slug']}: 인스타 댓글 읽기 실패 {x}")
            continue
        for c in cs:
            if c["id"] in st["ig_comments"] or c.get("username") == uname:
                continue
            if DRY:
                log(f"[시험] {p['slug']}: 댓글 {c['id']} → DM 대상")
                continue
            try:
                api("POST", f"{IG}/{uid}/messages", {"recipient": json.dumps({"comment_id": c["id"]}),
                                                     "message": json.dumps({"text": dm_text(p["msg"])}, ensure_ascii=False), "access_token": tk})
                log(f"{p['slug']}: 댓글 {c['id']} → DM 보냄")
                sent += 1
                try:
                    api("POST", f"{IG}/{c['id']}/replies", {"message": PUBLIC_ACK, "access_token": tk})
                except RuntimeError as x:
                    log(f"  공개 답글 실패(DM 은 보냄) {x}")
            except RuntimeError as x:
                log(f"{p['slug']}: 댓글 {c['id']} DM 실패 {x}")
            st["ig_comments"].append(c["id"])

    if posts:  # 2) 먼저 온 인스타 DM → 최근 영상 링크
        today = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 9 * 3600))
        try:
            convs = api("GET", f"{IG}/me/conversations", {"platform": "instagram", "fields": "id,messages.limit(1){from,message}",
                                                          "access_token": tk}).get("data", [])
        except RuntimeError as x:
            convs = []
            log(f"인스타 DM 목록 읽기 실패 {x}")
        for cv in convs:
            last = ((cv.get("messages") or {}).get("data") or [{}])[0]
            frm = last.get("from") or {}
            if not frm or frm.get("id") == uid or frm.get("username") == uname or st["ig_convos"].get(cv["id"]) == today:
                continue
            if DRY:
                log(f"[시험] 대화 {cv['id']} → 링크 대상")
                continue
            # 댓글 없이 DM 만 온 사람은 어느 영상을 보고 왔는지 모른다 — 최근 48시간 영상(최대 3편)의 링크를 모두 보낸다.
            # 같은 날 여러 상품을 올린 경우에도 원하는 상품 링크를 받게(2026-10-24 사용자: "한번에 여러 개 업로드된 경우 여러 링크")
            recent = [q for q in posts if time.time() - q["at"] <= 48 * 3600][:3] or posts[:1]
            text = dm_text(recent[0]["msg"]) if len(recent) == 1 else \
                "안녕하세요! 최근 영상 속 제품 링크 보내드려요 😊\n\n" + "\n\n".join(q["msg"] for q in recent)
            try:
                api("POST", f"{IG}/{uid}/messages", {"recipient": json.dumps({"id": frm["id"]}),
                                                     "message": json.dumps({"text": text[:990]}, ensure_ascii=False), "access_token": tk})
                log(f"대화 {cv['id']} → 최근 영상 {len(recent)}편 링크 보냄")
                sent += 1
            except RuntimeError as x:
                log(f"대화 {cv['id']} 답장 실패 {x}")
            st["ig_convos"][cv["id"]] = today

    day = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 9 * 3600))
    for p in posts:  # 3) 스레드 답글 → 링크 답글
        if not p.get("th"):
            continue
        try:
            rs = api("GET", f"{TH}/{p['th']}/replies", {"fields": "id,username", "access_token": th}).get("data", [])
        except RuntimeError as x:
            log(f"{p['slug']}: 스레드 답글 읽기 실패 {x}")
            continue
        for r in rs:
            if r["id"] in st["th_replies"] or r.get("username") == uname:
                continue
            if st["th_daily"].get(day, 0) >= THREADS_DAILY:
                break
            if DRY:
                log(f"[시험] {p['slug']}: 스레드 답글 {r['id']} → 링크 답글 대상")
                continue
            try:
                c = api("POST", f"{TH}/me/threads", {"media_type": "TEXT", "text": p["msg"], "reply_to_id": r["id"], "access_token": th})
                time.sleep(5)
                api("POST", f"{TH}/me/threads_publish", {"creation_id": c["id"], "access_token": th})
                log(f"{p['slug']}: 스레드 답글 {r['id']} 에 링크 답글")
                st["th_daily"][day] = st["th_daily"].get(day, 0) + 1
                sent += 1
            except RuntimeError as x:
                log(f"{p['slug']}: 스레드 링크 답글 실패 {x}")
            st["th_replies"].append(r["id"])

    # 오래된 기록 정리(id 목록이 끝없이 커지지 않게) — 날짜 키는 14일만
    st["th_daily"] = {k: v for k, v in st["th_daily"].items() if k >= time.strftime("%Y-%m-%d", time.gmtime(time.time() - 14 * 86400))}
    st["ig_convos"] = {k: v for k, v in st["ig_convos"].items() if v >= time.strftime("%Y-%m-%d", time.gmtime(time.time() - 14 * 86400))}
    st["ig_comments"], st["th_replies"] = st["ig_comments"][-3000:], st["th_replies"][-3000:]
    if not DRY:
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"끝 — 보냄 {sent}건 (최근 {len(posts)}편)")


if __name__ == "__main__":
    main()

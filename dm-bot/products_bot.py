"""쓰레드광고 상품 댓글 → DM 링크 — GitHub Actions 에서 10분마다(컴퓨터가 꺼져 있어도). 2026-10-24.

같은 인스타 계정(@alligator.16136460)의 **쓰레드광고 화보 캐러셀·짧은 영상** 글만 맡는다.
광고 쇼츠(dm_bot.py · posts.json · state.json)는 따로 돈다 — 그쪽 파일은 그쪽 PC 가 덮어쓰므로 건드리지 않는다.

- 최근 7일 글의 댓글에 키워드(링크·link·ㄹㅋ·정보·어디 …)가 있으면 비공개 답장(private reply)으로
  대가성 문구 원문(첫 줄) + 상품명 + **그 글의 상품 링크**(쿠팡 파트너스 또는 토스 쉐어링크)를 보낸다. 댓글엔 짧은 공개 답글.
- 한 댓글에 한 번(products_state.json — 댓글 id 만, 사용자 이름은 남기지 않는다 · 공개 저장소). 자기 댓글은 건너뛴다.
- 비공개 답장은 댓글 뒤 7일 안에만 된다(인스타 규칙). 한 번에 maxPerRun 건까지(몰아 보내면 스팸으로 읽힌다).
입력: dm-bot/products.json — 쓰레드광고 PC 의 scripts/insta_dm.js 가 올린다(글 id · 상품 · 링크 · 보낼 글자 · 키워드)
비밀: INSTAGRAM_ACCESS_TOKEN (저장소 Secrets — 광고 쇼츠와 같은 계정 토큰)
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
HERE = Path(__file__).parent
POSTS, STATE = HERE / "products.json", HERE / "products_state.json"
DAYS = 7
DRY = "--dry" in sys.argv


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
        tok = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
        if tok:
            body = body.replace(tok, "***")  # 오류 본문에 토큰이 섞여도 공개 로그에 남기지 않는다
        raise RuntimeError(f"HTTP {e.code} {body}") from None


def main():
    tk = os.environ["INSTAGRAM_ACCESS_TOKEN"]
    src = json.loads(POSTS.read_text(encoding="utf-8"))
    keywords = [k.lower() for k in src.get("keywords", ["링크"])]
    ack = src.get("publicReply") or ""
    limit = int(src.get("maxPerRun", 10))
    now = time.time()
    posts = [p for p in src.get("posts", []) if now - p["at"] <= DAYS * 86400 and p.get("ig") and p.get("msg")]
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    st.setdefault("done", [])
    done = set(st["done"])
    me = api("GET", f"{IG}/me", {"fields": "user_id,username", "access_token": tk})
    uid, uname = me["user_id"], me["username"]
    sent = 0
    for p in posts:
        try:
            cs = api("GET", f"{IG}/{p['ig']}/comments", {"fields": "id,text,username,timestamp", "limit": 50, "access_token": tk}).get("data", [])
        except RuntimeError as x:
            log(f"{p['ig']}: 댓글 읽기 실패 {x}")
            continue
        for c in cs:
            if c["id"] in done or c.get("username") == uname:
                continue
            if not any(k in str(c.get("text", "")).lower() for k in keywords):
                continue
            if sent >= limit:
                break
            if DRY:
                log(f"[시험] {p['ig']}: 댓글 {c['id']} → DM 대상 ({p.get('상품', '')[:30]})")
                continue
            try:
                api("POST", f"{IG}/{uid}/messages", {"recipient": json.dumps({"comment_id": c["id"]}),
                                                     "message": json.dumps({"text": p["msg"][:990]}, ensure_ascii=False), "access_token": tk})
                log(f"{p['ig']}: 댓글 {c['id']} → DM 보냄 ({p.get('program', '')})")
                sent += 1
                if ack:
                    try:
                        api("POST", f"{IG}/{c['id']}/replies", {"message": ack, "access_token": tk})
                    except RuntimeError as x:
                        log(f"  공개 답글 실패(DM 은 보냄) {x}")
            except RuntimeError as x:
                log(f"{p['ig']}: 댓글 {c['id']} DM 실패 {x}")
            done.add(c["id"])
            st["done"].append(c["id"])
    st["done"] = st["done"][-3000:]
    if not DRY:
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"끝 — 보냄 {sent}건 (최근 {len(posts)}편)")


if __name__ == "__main__":
    main()

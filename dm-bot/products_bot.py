"""쓰레드광고 상품(화보 캐러셀·짧은 영상) 댓글 → DM 링크 — GitHub Actions 에서 5분마다(컴퓨터가 꺼져 있어도). 2026-10-24.

광고 쇼츠 dm_bot.py 와 **같은 규칙·같은 문구**로 맞췄다(2026-10-24 블로그 주인 「이미 동일한 기능의 action 이 있어 — 일치시켜줘」).
그쪽 파일(dm_bot.py · posts.json · state.json)은 그쪽 PC 가 덮어쓰므로 건드리지 않고, 입력·기록만 따로 둔다.
- 인스타그램 댓글 → 댓글 단 사람에게 비공개 답장(DM)으로 **그 글의 상품 링크**(쿠팡 파트너스 또는 토스 쉐어링크) + 댓글에 짧은 공개 답글.
  댓글당 한 번, 댓글 후 7일 안. 자기 댓글은 건너뛴다.
- 먼저 온 DM(대화)은 광고 쇼츠 dm_bot.py 가 답한다 — 두 봇이 같은 대화에 두 번 답하지 않게 여기서는 하지 않는다.
- 스레드는 쓰레드광고 글 본문에 이미 링크가 있어 답글을 달지 않는다.
입력: dm-bot/products.json(쓰레드광고 PC 의 scripts/insta_dm.js 가 올린다 — dm_bot.py 의 posts.json 과 같은 꼴: slug · at · ig · th · msg)
기록: dm-bot/products_state.json(처리한 댓글 id 만. 사용자 이름은 남기지 않는다 — 공개 저장소)
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
PUBLIC_ACK = "DM으로 링크 보내드렸어요 💌"   # dm_bot.py 와 같다


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
        if os.environ.get("INSTAGRAM_ACCESS_TOKEN"):  # 혹시 오류 본문에 토큰이 섞여도 로그에 남기지 않는다
            body = body.replace(os.environ["INSTAGRAM_ACCESS_TOKEN"], "***")
        raise RuntimeError(f"HTTP {e.code} {body}") from None


def dm_text(msg):
    return "안녕하세요! 게시물 속 제품 링크 보내드려요 😊\n" + msg


def main():
    tk = os.environ["INSTAGRAM_ACCESS_TOKEN"]
    posts = [p for p in json.loads(POSTS.read_text(encoding="utf-8")) if time.time() - p["at"] <= DAYS * 86400]
    posts.sort(key=lambda p: p["at"], reverse=True)
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    st.setdefault("ig_comments", [])
    me = api("GET", f"{IG}/me", {"fields": "user_id,username", "access_token": tk})
    uid, uname = me["user_id"], me["username"]
    sent = 0

    for p in posts:  # 인스타 댓글 → DM + 공개 답글
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

    st["ig_comments"] = st["ig_comments"][-3000:]
    if not DRY:
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"끝 — 보냄 {sent}건 (최근 {len(posts)}편)")


if __name__ == "__main__":
    main()

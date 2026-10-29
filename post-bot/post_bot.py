"""광고 쇼츠 예약 게시 — GitHub Actions 에서 매일 23:00(KST) 돈다(컴퓨터가 꺼져 있어도). 2026-10-24.

원본: D:\\shorts\\5.PROJECT\\tools\\auto_ad\\gh_dm_bot\\ (이 저장소에 올린 사본). PC 판 publish.py 와 같은 게시 절차.
대기열: post-queue/<slug>.json — PC(gh_queue.py)가 제작을 마치면 올린다:
  {"slug", "ready_at", "video": "videos/q_<slug>.mp4"(이 저장소, Pages 로 공개), "instagram": 본문, "threads": 본문, "msg": 링크 답글 문구,
   "result": {...게시 도중 결과 — 일부만 성공하면 여기 남겨 다음 실행이 빠진 것만 한다}}
하는 일: 가장 오래된 한 편 → 인스타그램 릴스 + 스레드 영상 게시 → 링크 댓글(인스타)·답글(스레드)
        → dm-bot/posts.json 에 추가(DM 봇이 이 상품 링크로 답한다) → post-bot/posted/<slug>.json 기록 → 대기열·영상 삭제.
한 번에 한 편만(하루 한 편). 대기열이 비어 있으면 아무것도 하지 않는다.
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
ROOT = Path(__file__).resolve().parent.parent
QUEUE, POSTED, DM_POSTS = ROOT / "post-queue", ROOT / "post-bot" / "posted", ROOT / "dm-bot" / "posts.json"
PAGES = os.environ.get("PAGES_BASE", "https://wonrexander.github.io/threads-images")


def log(msg):
    print(f"[{time.strftime('%m-%d %H:%M:%S', time.gmtime(time.time() + 9 * 3600))} KST] {msg}", flush=True)


def call(method, url, params=None):
    q = urllib.parse.urlencode(params or {})
    req = urllib.request.Request(f"{url}?{q}" if method == "GET" else url, data=None if method == "GET" else q.encode(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        for k in ("INSTAGRAM_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"):
            if os.environ.get(k):
                body = body.replace(os.environ[k], "***")
        raise RuntimeError(f"HTTP {e.code} {body}") from None


def wait(url, token, field, label, limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        st = call("GET", url, {"fields": field, "access_token": token}).get(field)
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"{label} 처리 실패({st})")
        time.sleep(6)
    raise RuntimeError(f"{label} 처리가 {limit}초 안에 끝나지 않았다")


def instagram(video_url, caption, tk, uid, cover_ms=800):  # 커버 = 훅 장면(2026-10-29)
    c = call("POST", f"{IG}/{uid}/media", {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true", "thumb_offset": str(cover_ms), "access_token": tk})
    wait(f"{IG}/{c['id']}", tk, "status_code", "인스타그램 영상")
    pub = call("POST", f"{IG}/{uid}/media_publish", {"creation_id": c["id"], "access_token": tk})
    info = call("GET", f"{IG}/{pub['id']}", {"fields": "permalink,timestamp", "access_token": tk})
    return {"id": pub["id"], "permalink": info.get("permalink"), "at": info.get("timestamp")}


def threads(video_url, text, tk):
    me = call("GET", f"{TH}/me", {"fields": "id", "access_token": tk})["id"]
    c = call("POST", f"{TH}/{me}/threads", {"media_type": "VIDEO", "video_url": video_url, "text": text, "access_token": tk})
    wait(f"{TH}/{c['id']}", tk, "status", "스레드 영상")
    pub = call("POST", f"{TH}/{me}/threads_publish", {"creation_id": c["id"], "access_token": tk})
    info = call("GET", f"{TH}/{pub['id']}", {"fields": "permalink,timestamp", "access_token": tk})
    return {"id": pub["id"], "permalink": info.get("permalink"), "at": info.get("timestamp")}


def threads_reply(text, tk, reply_to):
    me = call("GET", f"{TH}/me", {"fields": "id", "access_token": tk})["id"]
    c = call("POST", f"{TH}/{me}/threads", {"media_type": "TEXT", "text": text, "reply_to_id": reply_to, "access_token": tk})
    wait(f"{TH}/{c['id']}", tk, "status", "스레드 답글", limit=120)
    return {"id": call("POST", f"{TH}/{me}/threads_publish", {"creation_id": c["id"], "access_token": tk})["id"]}


def instagram_comment(text, tk, media_id):
    return {"id": call("POST", f"{IG}/{media_id}/comments", {"message": text, "access_token": tk})["id"]}


def video_ready(url):
    for _ in range(30):  # Pages 가 아직 안 열렸으면 최대 5분 기다린다
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=20) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(10)
    return False


def main():
    tk_ig, tk_th = os.environ["INSTAGRAM_ACCESS_TOKEN"], os.environ["THREADS_ACCESS_TOKEN"]
    # 실행 요청은 GitHub 예약(늦다)과 외부 예약 서비스(cron-job.org, 2026-10-27 사용자 선택) 양쪽에서 온다 — 하루 한 편만,
    # 22:30~06:00 KST 에만 올린다. 사람이 '지금 올려'라고 할 때만 force=true 로 둘 다 건너뛴다.
    if os.environ.get("POST_FORCE", "false") != "true":
        k = time.gmtime(time.time() + 9 * 3600)
        hm = k.tm_hour * 60 + k.tm_min
        if not (hm >= 22 * 60 + 30 or hm < 6 * 60):
            log("게시 시간대(22:30~06:00 KST)가 아니다 — 건너뜀")
            return
        recent = [p for p in POSTED.glob("*.json") if time.time() - json.loads(p.read_text(encoding="utf-8")).get("posted_at", 0) < 12 * 3600]
        if recent:
            log(f"오늘 이미 올렸다({recent[0].stem}) — 건너뜀")
            return
    items = sorted(QUEUE.glob("*.json"), key=lambda p: json.loads(p.read_text(encoding="utf-8")).get("ready_at", ""))
    if not items:
        log("게시 대기열이 비어 있다 — 오늘은 올릴 영상이 없다")
        return
    qf = items[0]
    q = json.loads(qf.read_text(encoding="utf-8"))
    res = q.setdefault("result", {})
    url = f"{PAGES}/{q['video']}"
    log(f"게시: {q['slug']} ({url})")
    if not video_ready(url):
        sys.exit(f"영상 공개 주소가 열리지 않는다: {url}")
    uid = call("GET", f"{IG}/me", {"fields": "user_id", "access_token": tk_ig})["user_id"]
    # 이중 안전장치: 최근 12시간 안에 같은 본문의 게시물이 이미 있으면 올린 것으로 본다(중복 게시 방지, 2026-10-29)
    if not res.get("instagram", {}).get("id"):
        for m in call("GET", f"{IG}/{uid}/media", {"fields": "id,caption,timestamp,permalink", "limit": 15, "access_token": tk_ig}).get("data", []):
            if (m.get("caption") or "").strip() == q["instagram"].strip():
                res["instagram"] = {"id": m["id"], "permalink": m.get("permalink"), "at": m.get("timestamp"), "found": "already-posted"}
                log(f"instagram: 같은 본문이 이미 올라가 있다 — 다시 올리지 않는다 {m.get('permalink')}")
                break
    # 스레드도 같은 본문이 최근에 이미 올라가 있으면 다시 올리지 않는다(중복 게시 방지, 2026-10-29)
    if not res.get("threads", {}).get("id"):
        try:
            for t in call("GET", f"{TH}/me/threads", {"fields": "id,text,permalink,timestamp", "limit": 15, "access_token": tk_th}).get("data", []):
                if (t.get("text") or "").strip() == q["threads"].strip():
                    res["threads"] = {"id": t["id"], "permalink": t.get("permalink"), "at": t.get("timestamp"), "found": "already-posted"}
                    log(f"threads: 같은 본문이 이미 올라가 있다 — 다시 올리지 않는다 {t.get('permalink')}")
                    break
        except Exception as e:
            log(f"threads: 중복 확인 실패(그대로 진행) {e}")
    err = None
    for plat, fn, args in (("instagram", instagram, (url, q["instagram"], tk_ig, uid, q.get("cover_ms", 800))), ("threads", threads, (url, q["threads"], tk_th))):
        if res.get(plat, {}).get("id"):
            log(f"{plat}: 이미 올림 {res[plat].get('permalink')}")
            continue
        try:
            res[plat] = fn(*args)
            log(f"{plat}: {res[plat].get('permalink')}")
        except Exception as e:
            err = f"{plat} 게시 실패: {e}"
            log(err)
        qf.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")  # 일부 성공도 바로 남긴다(다시 돌 때 중복 게시 방지)
    for key, plat, fn, tok in (("instagram_comment", "instagram", instagram_comment, tk_ig), ("threads_reply", "threads", threads_reply, tk_th)):
        pid = res.get(plat, {}).get("id")
        if pid and not (res.get(key) or {}).get("id") and q.get("msg"):
            try:
                res[key] = fn(q["msg"], tok, pid)
                log(f"{plat}: 링크 {'댓글' if plat == 'instagram' else '답글'} 달음")
            except Exception as e:
                res[key] = {"error": str(e)[:300]}
                log(f"{plat}: 링크 답글 실패 {e}")
    qf.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    if err:
        sys.exit(err)  # 대기열에 남겨 둔다 — 다음 실행(수동 또는 다음 날)이 빠진 것만 한다

    # DM 봇에 이 상품 링크 알리기(일반 영상은 링크가 없어 건너뛴다, 2026-10-29)
    if q.get("msg"):
        posts = json.loads(DM_POSTS.read_text(encoding="utf-8")) if DM_POSTS.exists() else []
        posts = [p for p in posts if p["slug"] != q["slug"]] + [{"slug": q["slug"], "at": time.time(), "ig": res["instagram"]["id"],
                                                                  "th": res["threads"]["id"], "msg": q.get("msg", "")}]
        DM_POSTS.write_text(json.dumps(posts, ensure_ascii=False, indent=1), encoding="utf-8")
    POSTED.mkdir(parents=True, exist_ok=True)
    (POSTED / f"{q['slug']}.json").write_text(json.dumps({"slug": q["slug"], "posted_at": time.time(), "default": res, **{k: q.get(k) for k in ("hook", "first_line", "format_tag", "program", "sec")}}, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / q["video"]).unlink(missing_ok=True)
    qf.unlink()
    log(f"완료: {q['slug']} — 대기열 {len(items) - 1}편 남음")


if __name__ == "__main__":
    main()

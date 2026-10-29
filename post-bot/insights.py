"""게시한 광고 쇼츠의 성과를 모은다 — GitHub Actions 에서 매일(2026-10-29, 측정 루프).

post-bot/posted/<slug>.json(게시 기록: 인스타 id·훅·첫 대사·형식·길이)을 읽어, 게시 24시간·72시간 뒤 인스타그램 지표를 남긴다.
출력: post-bot/insights.json {slug: {"h24": {...}, "h72": {...}, "hook", "first_line", "format_tag", "program", "sec"}}
      post-bot/insights.csv  (사람이 보기 쉬운 표)
지표: views·reach·평균 시청 시간(초)·시청 비율(평균 시청 / 영상 길이)·저장·공유·좋아요·댓글.
PC 의 대본 작성(writer.py)이 이것을 읽어 잘된 훅·형식을 참고한다.
"""
import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

IG = "https://graph.instagram.com/v23.0"
ROOT = Path(__file__).resolve().parent.parent
POSTED, OUT = ROOT / "post-bot" / "posted", ROOT / "post-bot" / "insights.json"
METRICS = "views,reach,ig_reels_avg_watch_time,saved,shares,likes,comments"


def get(url, **p):
    try:
        with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(p), timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode("utf-8", "replace")[:200]}


def main():
    tk = os.environ["INSTAGRAM_ACCESS_TOKEN"]
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    now = time.time()
    for f in sorted(POSTED.glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        mid = (rec.get("default", {}).get("instagram") or {}).get("id")
        if not mid:
            continue
        d = data.setdefault(rec["slug"], {})
        for k in ("hook", "first_line", "format_tag", "program", "sec"):
            if rec.get(k) is not None:
                d[k] = rec[k]
        age = (now - rec.get("posted_at", now)) / 3600
        for key, h in (("h24", 24), ("h72", 72)):
            if age < h or key in d:
                continue
            r = get(f"{IG}/{mid}/insights", metric=METRICS, access_token=tk)
            if "data" not in r:
                print(rec["slug"], key, "실패", r.get("error"))
                continue
            v = {m["name"]: m["values"][0]["value"] for m in r["data"]}
            v["avg_watch_sec"] = round(v.pop("ig_reels_avg_watch_time", 0) / 1000, 1)
            if d.get("sec"):
                v["watch_ratio"] = round(v["avg_watch_sec"] / d["sec"], 3)
            v["at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime(now + 9 * 3600))
            d[key] = v
            print(rec["slug"], key, v)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    with (ROOT / "post-bot" / "insights.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["slug", "program", "format_tag", "sec", "hook", "first_line", "views_72h", "reach_72h", "avg_watch_sec_72h", "watch_ratio_72h", "saved", "shares", "views_24h"])
        for slug, d in sorted(data.items()):
            h72, h24 = d.get("h72", {}), d.get("h24", {})
            w.writerow([slug, d.get("program"), d.get("format_tag"), d.get("sec"), d.get("hook"), d.get("first_line"), h72.get("views"), h72.get("reach"),
                        h72.get("avg_watch_sec"), h72.get("watch_ratio"), h72.get("saved"), h72.get("shares"), h24.get("views")])
    print(f"성과 {len(data)}편 기록")


if __name__ == "__main__":
    main()

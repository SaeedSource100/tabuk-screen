#!/usr/bin/env python3
"""يجلب الأخبار والمباريات والطقس ويكتب data.json. يعمل على GitHub Actions كل ساعة.
أي مصدر يفشل: تبقى بياناته القديمة كما هي."""
import json, re, sys, urllib.request, datetime as dt
import xml.etree.ElementTree as ET

RIY = dt.timezone(dt.timedelta(hours=3))
UA = {"User-Agent": "Mozilla/5.0 (tabuk-screen data updater)"}
NOW = dt.datetime.now(RIY)

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

# ---------- الأخبار: خلاصة RSS الرسمية لقسم السعودية في العربية ----------
SKIP = ("/art/", "/views/", "/social/", "/sport/", "/aswaq/", "/culture", "/last-page/", "/1300GMT/")
def news():
    root = ET.fromstring(get("https://www.alarabiya.net/feed/rss2/ar/saudi-today.xml"))
    out, seen = [], set()
    for it in root.iter("item"):
        title = re.sub(r"\s+", " ", (it.findtext("title") or "")).strip()
        link = (it.findtext("link") or "").strip()
        if not title or title in seen or any(x in link for x in SKIP):
            continue
        if "/saudi-today/" not in link and not re.search("السعود|المملكة", title):
            continue
        seen.add(title)
        out.append(title)
        if len(out) >= 10:
            break
    if len(out) < 3:
        raise ValueError("عدد الأخبار قليل جداً: %d" % len(out))
    return out

# ---------- المباريات: ESPN (دوري روشن ksa.1) ----------
AR = [("diriyah", "الدرعية"), ("riyadh", "الرياض"), ("taawoun", "التعاون"), ("taawon", "التعاون"),
      ("qadsiah", "القادسية"), ("ettifaq", "الاتفاق"), ("ittihad", "الاتحاد"), ("nassr", "النصر"),
      ("neom", "نيوم"), ("hilal", "الهلال"), ("ahli", "الأهلي"), ("shabab", "الشباب"),
      ("fateh", "الفتح"), ("khaleej", "الخليج"), ("fayha", "الفيحاء"), ("hazem", "الحزم"),
      ("hazm", "الحزم"), ("kholood", "الخلود"), ("khulood", "الخلود"), ("abha", "أبها"),
      ("faisaly", "الفيصلي"), ("fayseli", "الفيصلي"), ("damac", "ضمك"), ("najma", "النجمة"),
      ("orobah", "العروبة"), ("okhdood", "الأخدود"), ("akhdoud", "الأخدود"), ("raed", "الرائد"),
      ("wehda", "الوحدة"), ("tai", "الطائي")]
def ar(name):
    n = re.sub(r"[^a-z]", "", name.lower())
    for k, v in AR:
        if k in n:
            return v
    return name

def parse_utc(s):
    for f in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(s, f).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            pass
    raise ValueError("تنسيق تاريخ غير معروف: " + s)

def fixtures():
    out = []
    today = NOW.date()
    keep = {today.isoformat(), (today + dt.timedelta(days=1)).isoformat()}
    for off in (-1, 0, 1, 2):
        day = (NOW + dt.timedelta(days=off)).strftime("%Y%m%d")
        j = json.loads(get("https://site.api.espn.com/apis/site/v2/sports/soccer/ksa.1/scoreboard?dates=" + day))
        for ev in j.get("events", []):
            st = ev.get("status", {}).get("type", {})
            if "POSTPONED" in str(st.get("name", "")) or "CANCEL" in str(st.get("name", "")):
                continue
            k = parse_utc(ev["date"]).astimezone(RIY)
            if k.date().isoformat() not in keep:
                continue
            comps = ev["competitions"][0]["competitors"]
            home = next(c for c in comps if c.get("homeAway") == "home")
            away = next(c for c in comps if c.get("homeAway") == "away")
            m = {"d": k.date().isoformat(), "t": k.strftime("%H:%M"),
                 "h": ar(home["team"]["displayName"]), "a": ar(away["team"]["displayName"])}
            if st.get("state") == "post":
                m["hs"], m["as"] = int(home.get("score", 0)), int(away.get("score", 0))
            out.append(m)
    uniq = {(m["d"], m["t"], m["h"], m["a"]): m for m in out}
    return sorted(uniq.values(), key=lambda m: (m["d"], m["t"]))

# ---------- الطقس: Open-Meteo ----------
def wmo(c):
    if c == 0: return "clear"
    if c in (1, 2): return "partly"
    if c == 3: return "cloud"
    if 51 <= c <= 67 or 80 <= c <= 82 or c >= 95: return "rain"
    return "cloud"

def weather():
    j = json.loads(get("https://api.open-meteo.com/v1/forecast?latitude=28.3835&longitude=36.5662"
                       "&current=temperature_2m,weather_code&timezone=Asia%2FRiyadh"))
    c = j["current"]
    return {"t": c["temperature_2m"], "c": wmo(c["weather_code"]), "at": c["time"]}

def main(path="data.json"):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        data = {}
    errs = []
    for key, fn in (("news", news), ("fx", fixtures), ("wx", weather)):
        try:
            data[key] = fn()
        except Exception as e:
            errs.append("%s: %s" % (key, e))
    data["generated"] = NOW.strftime("%Y-%m-%dT%H:%M")
    data["updated"] = NOW.date().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    for e in errs:
        print("تحذير:", e, file=sys.stderr)
    print("تم. أخطاء:", len(errs))
    # نفشل التشغيل فقط لو فشلت المصادر الثلاثة كلها
    if len(errs) == 3:
        sys.exit(1)

if __name__ == "__main__":
    main()

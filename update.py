#!/usr/bin/env python3
"""يجلب الأخبار والمباريات والطقس ويكتب data.json. يعمل على GitHub Actions كل ساعة.
أي مصدر يفشل: تبقى بياناته القديمة كما هي."""
import json, re, sys, urllib.request, datetime as dt
import xml.etree.ElementTree as ET

RIY = dt.timezone(dt.timedelta(hours=3))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/rss+xml,application/xml,application/json,text/xml,*/*;q=0.8", "Accept-Language": "ar,en;q=0.8"}
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

def logo(team):
    """رابط شعار الفريق من ESPN (إن غاب الحقل نبنيه من رقم الفريق)."""
    u = team.get("logo") or ((team.get("logos") or [{}])[0] or {}).get("href")
    if not u and team.get("id"):
        u = "https://a.espncdn.com/i/teamlogos/soccer/500/%s.png" % team["id"]
    return u

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
    keep = {(today + dt.timedelta(days=i)).isoformat() for i in range(0, 5)}
    for off in (-1, 0, 1, 2, 3, 4):
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
                 "h": ar(home["team"]["displayName"]), "a": ar(away["team"]["displayName"]),
                 "hl": logo(home["team"]), "al": logo(away["team"])}
            if st.get("state") == "post":
                m["hs"], m["as"] = int(home.get("score", 0)), int(away.get("score", 0))
            out.append(m)
    uniq = {(m["d"], m["t"], m["h"], m["a"]): m for m in out}
    return sorted(uniq.values(), key=lambda m: (m["d"], m["t"]))

# ---------- الأهلي: ترتيب ونتائج وقادم ----------
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/%s/scoreboard?dates=%s"
AHLI = "8346"
EXTRA = [("afc.champions", "دوري أبطال آسيا"), ("afc.cup", "دوري أبطال آسيا 2"), ("ksa.kings.cup", "كأس الملك"),
         ("ksa.super_cup", "كأس السوبر"), ("fifa.cwc", "كأس العالم للأندية")]
def day_events(league, day):
    last = None
    for _ in range(2):
        try:
            for host in ("site.api.espn.com", "site.web.api.espn.com"):
                try:
                    j = json.loads(get((ESPN % (league, day.strftime("%Y%m%d"))).replace("site.api.espn.com", host)))
                    return j.get("events", [])
                except Exception as e:
                    last = e
            raise last
        except Exception as e:
            last = e
    raise last

def events(league, d1, d2):
    """يجلب يوماً بيوم (نطاق التواريخ يرفضه ESPN بخطأ 400) وبشكل متوازٍ."""
    from concurrent.futures import ThreadPoolExecutor
    days = [d1 + dt.timedelta(days=i) for i in range((d2.date() - d1.date()).days + 1)]
    errs = []
    def one(d):
        try:
            return day_events(league, d)
        except Exception as e:
            errs.append(str(e))
            return None
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, days))
    if all(r is None for r in res):
        raise ValueError("تعذر جلب %s (%s)" % (league, errs[0] if errs else ""))
    return [e for r in res if r for e in r]

def ahli():
    evs, seen = [], set()
    for ev in events("ksa.1", NOW - dt.timedelta(days=45), NOW + dt.timedelta(days=25)):
        if ev.get("id") not in seen:
            seen.add(ev.get("id")); evs.append(ev)
    # بطولات أخرى يلعبها الأهلي: كل بطولة اختيارية، وفشلها لا يوقف البقية
    for slug, label in EXTRA:
        try:
            for ev in events(slug, NOW - dt.timedelta(days=21), NOW + dt.timedelta(days=30)):
                comps = ev.get("competitions", [{}])[0].get("competitors", [])
                if ev.get("id") in seen or not any(str(c.get("team", {}).get("id")) == AHLI for c in comps):
                    continue
                seen.add(ev.get("id")); ev["_c"] = label; evs.append(ev)
        except Exception as e:
            print("تخطي بطولة %s: %s" % (slug, e))
    past, fut = [], []
    for ev in evs:
        comps = ev["competitions"][0]["competitors"]
        if not any(str(c["team"].get("id")) == AHLI for c in comps):
            continue
        st = ev.get("status", {}).get("type", {})
        if "POSTPONED" in str(st.get("name", "")) or "CANCEL" in str(st.get("name", "")):
            continue
        me = next(c for c in comps if str(c["team"].get("id")) == AHLI)
        op = next(c for c in comps if c is not me)
        k = parse_utc(ev["date"]).astimezone(RIY)
        if st.get("state") == "post":
            a_, b_ = int(me.get("score", 0)), int(op.get("score", 0))
            past.append({"k": k, "o": ar(op["team"]["displayName"]), "s": "%d-%d" % (a_, b_), "ol": logo(op["team"]), "c": ev.get("_c"),
                         "r": "W" if a_ > b_ else "L" if a_ < b_ else "D"})
        elif st.get("state") == "pre" and k > NOW:
            fut.append({"k": k, "o": ar(op["team"]["displayName"]), "home": me.get("homeAway") == "home", "ol": logo(op["team"]), "c": ev.get("_c")})
    past.sort(key=lambda x: x["k"]); fut.sort(key=lambda x: x["k"])
    out = {"form": [p["r"] for p in past[-5:]][::-1],
           "last": [dict({"o": p["o"], "s": p["s"], "r": p["r"], "ol": p.get("ol")}, **({"c": p["c"]} if p.get("c") else {})) for p in past[-3:]][::-1]}
    if fut:
        n = fut[0]
        out["next"] = {"d": n["k"].date().isoformat(), "t": n["k"].strftime("%H:%M"), "o": n["o"], "home": n["home"], "ol": n.get("ol")}
        if n.get("c"): out["next"]["c"] = n["c"]
    if past and past[-1]["r"] == "W":
        out["win"] = {"at": past[-1]["k"].strftime("%Y-%m-%dT%H:%M"), "s": past[-1]["s"], "o": past[-1]["o"], "ol": past[-1].get("ol")}
    try:  # الترتيب (اختياري)
        j = json.loads(get("https://site.api.espn.com/apis/v2/sports/soccer/ksa.1/standings"))
        for ch in j.get("children", [j]):
            for e in ch.get("standings", {}).get("entries", []):
                if str(e["team"].get("id")) == AHLI:
                    stt = {x["name"]: x.get("value") for x in e["stats"]}
                    out["rank"], out["pts"], out["gp"] = int(stt["rank"]), int(stt["points"]), int(stt.get("gamesPlayed", 0))
                    for k_, n_ in (("w", "wins"), ("d", "ties"), ("l", "losses")):
                        if stt.get(n_) is not None: out[k_] = int(stt[n_])
    except Exception as e:
        print("تحذير: الترتيب:", e, file=sys.stderr)
    return out

# ---------- أبرز مباريات أوروبا (إسبانيا وإنجلترا) ----------
BIG = {  # اسم عربي : وزن
 "esp.1": [("real madrid","ريال مدريد",5),("barcelona","برشلونة",5),("atletico","أتلتيكو مدريد",3),
           ("sevilla","إشبيلية",2),("valencia","فالنسيا",2),("villarreal","فياريال",2),("athletic","أتلتيك بلباو",2),
           ("real sociedad","ريال سوسيداد",2),("betis","ريال بيتيس",2)],
 "eng.1": [("manchester city","مانشستر سيتي",5),("manchester united","مانشستر يونايتد",5),("liverpool","ليفربول",5),
           ("arsenal","أرسنال",5),("chelsea","تشيلسي",4),("tottenham","توتنهام",4),("newcastle","نيوكاسل",3),
           ("aston villa","أستون فيلا",2),("west ham","وست هام",2),("everton","إيفرتون",2)],
 "ita.1": [("juventus","يوفنتوس",5),("inter","إنتر ميلان",5),("milan","ميلان",5),("napoli","نابولي",4),("roma","روما",3)],
 "ger.1": [("bayern","بايرن ميونخ",5),("dortmund","دورتموند",4),("leverkusen","ليفركوزن",3)],
 "fra.1": [("paris saint","باريس سان جيرمان",5),("marseille","مارسيليا",3)],
 "uefa.champions": [("real madrid","ريال مدريد",5),("barcelona","برشلونة",5),("manchester city","مانشستر سيتي",5),("liverpool","ليفربول",5),
           ("bayern","بايرن ميونخ",5),("paris saint","باريس سان جيرمان",5),("arsenal","أرسنال",5),("juventus","يوفنتوس",4),
           ("inter","إنتر ميلان",5),("milan","ميلان",4),("chelsea","تشيلسي",4),("atletico","أتلتيكو مدريد",3),("dortmund","دورتموند",3),("napoli","نابولي",3)]}
SDB = {"esp.1": 4335, "eng.1": 4328}
def raw_matches(lg):
    """يرجع [(وقت الانطلاق بتوقيت الرياض, المضيف, الضيف)] من ESPN، وإن فشل من TheSportsDB."""
    try:
        res = []
        for ev in events(lg, NOW, NOW + dt.timedelta(days=6)):
            st = ev.get("status", {}).get("type", {})
            if "POSTPONED" in str(st.get("name", "")) or "CANCEL" in str(st.get("name", "")):
                continue
            comps = ev["competitions"][0]["competitors"]
            h = next(c for c in comps if c.get("homeAway") == "home")["team"]["displayName"]
            a = next(c for c in comps if c.get("homeAway") == "away")["team"]["displayName"]
            res.append((parse_utc(ev["date"]).astimezone(RIY), h, a, logo(next(c for c in comps if c.get("homeAway") == "home")["team"]), logo(next(c for c in comps if c.get("homeAway") == "away")["team"])))
        return res
    except Exception as e1:
        if lg not in SDB:
            raise
        print("تحذير: %s ESPN فشل (%s)، أجرب مصدراً بديلاً" % (lg, e1), file=sys.stderr)
        j = json.loads(get("https://www.thesportsdb.com/api/v1/json/3/eventsnextleague.php?id=%d" % SDB[lg]))
        res = []
        for ev in j.get("events") or []:
            ts = ev.get("strTimestamp") or (ev["dateEvent"] + "T" + (ev.get("strTime") or "12:00:00"))
            k = dt.datetime.fromisoformat(ts.replace("Z", "")).replace(tzinfo=dt.timezone.utc).astimezone(RIY)
            res.append((k, ev["strHomeTeam"], ev["strAwayTeam"], None, None))
        if not res:
            raise ValueError("المصدر البديل لم يرجع مباريات")
        return res

def eu_league(lg):
    out = []
    near = {(NOW + dt.timedelta(days=i)).date().isoformat() for i in range(3)}
    for k, h, a, hl, al in raw_matches(lg):
        if k < NOW - dt.timedelta(hours=3) or k > NOW + dt.timedelta(days=7):
            continue
        w, arn = 0, {}
        for n in (h, a):
            arn[n] = n
            for key, arabic, wt in BIG[lg]:
                if key in n.lower():
                    w += wt; arn[n] = arabic; break
        if w:
            m = {"d": k.date().isoformat(), "t": k.strftime("%H:%M"), "h": arn[h], "a": arn[a], "lg": lg, "hl": hl, "al": al}
            out.append((0 if m["d"] in near else 1, -w, m["d"], m["t"], m))
    uniq = {(x[4]["d"], x[4]["t"], x[4]["h"], x[4]["a"]): x for x in out}
    out = sorted(uniq.values(), key=lambda x: x[:4])
    return [x[4] for x in out[:2]]

def europe():
    res, ok = [], 0
    for lg in ("esp.1", "eng.1", "ita.1", "ger.1", "fra.1", "uefa.champions"):
        try:
            res += eu_league(lg); ok += 1
        except Exception as e:
            print("تحذير: %s: %s" % (lg, e), file=sys.stderr)
    if ok == 0:
        raise ValueError("تعذر جلب الدوريات الأوروبية")
    uniq = {(m["d"], m["t"], m["h"], m["a"]): m for m in res}  # دوري الأبطال قد يكرر مباراة
    return sorted(uniq.values(), key=lambda m: (m["d"], m["t"]))[:8]

# ---------- ترتيب دوري روشن (أعلى ٨) ----------
def table():
    j = json.loads(get("https://site.api.espn.com/apis/v2/sports/soccer/ksa.1/standings"))
    rows = []
    for ch in j.get("children", [j]):
        for e in ch.get("standings", {}).get("entries", []):
            stt = {x["name"]: x.get("value") for x in e["stats"]}
            t = e["team"]
            rows.append({"r": int(stt["rank"]), "n": ar(t.get("displayName", "")), "p": int(stt["points"]),
                         "g": int(stt.get("gamesPlayed", 0)), "l": logo(t), "me": str(t.get("id")) == AHLI})
    if not rows:
        raise ValueError("الترتيب فارغ")
    rows.sort(key=lambda x: x["r"])
    return rows[:8] if any(x["me"] for x in rows[:8]) else rows[:7] + [x for x in rows if x["me"]][:1]

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
    SRC = {"news": "الأخبار", "fx": "دوري روشن", "wx": "الطقس", "ahli": "بطاقة الأهلي", "eu": "الدوريات الأوروبية", "table": "ترتيب الدوري"}
    status = {}
    for key, fn in (("news", news), ("fx", fixtures), ("wx", weather), ("ahli", ahli), ("eu", europe), ("table", table)):
        try:
            data[key] = fn()
            status[SRC[key]] = {"ok": True}
        except Exception as e:
            errs.append("%s: %s" % (key, e))
            status[SRC[key]] = {"ok": False, "err": "تعذّر الاتصال بالمصدر"}
    data["status"] = status
    data["generated"] = NOW.strftime("%Y-%m-%dT%H:%M")
    data["updated"] = NOW.date().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    for e in errs:
        print("تحذير:", e, file=sys.stderr)
    print("تم. أخطاء:", len(errs))
    # نفشل التشغيل فقط لو فشلت المصادر الخمسة كلها
    if len(errs) == 6:
        sys.exit(1)

if __name__ == "__main__":
    main()

import os, json, datetime, requests, anthropic
from zoneinfo import ZoneInfo

FOOTBALL_KEY = os.environ["FOOTBALL_API_KEY"]
TG_TOKEN = os.environ["TELEGRAM_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]

TZ = "America/Bogota"
LIGAS = {39: "Premier League", 140: "LaLiga", 135: "Serie A", 78: "Bundesliga",
         61: "Ligue 1", 2: "Champions League", 239: "Liga BetPlay"}
MAX_PARTIDOS = 40      # tope de consultas a /predictions por ejecución
TOP_TELEGRAM = 5

H = {"x-apisports-key": FOOTBALL_KEY}
BASE = "https://v3.football.api-sports.io"
hoy = datetime.datetime.now(ZoneInfo(TZ)).date()


def pct(s):
    try:
        return int(str(s).strip("%"))
    except Exception:
        return 0


# 1. Partidos de hoy y mañana (una llamada por fecha, filtrando ligas)
partidos = []
for d in (hoy, hoy + datetime.timedelta(days=1)):
    r = requests.get(f"{BASE}/fixtures", headers=H,
                     params={"date": d.isoformat(), "timezone": TZ}, timeout=30).json()
    for f in r.get("response", []):
        if f["league"]["id"] in LIGAS and f["fixture"]["status"]["short"] == "NS":
            partidos.append(f)
partidos = partidos[:MAX_PARTIDOS]

# 2. Predicciones de la API
items = []
for f in partidos:
    r = requests.get(f"{BASE}/predictions", headers=H,
                     params={"fixture": f["fixture"]["id"]}, timeout=30).json()
    if not r.get("response"):
        continue
    p = r["response"][0]["predictions"]
    probs = {"local": pct(p["percent"]["home"]), "empate": pct(p["percent"]["draw"]),
             "visita": pct(p["percent"]["away"])}
    pick = max(probs, key=probs.get)
    items.append({
        "liga": LIGAS[f["league"]["id"]],
        "fecha": f["fixture"]["date"],
        "local": f["teams"]["home"]["name"],
        "visita": f["teams"]["away"]["name"],
        "probs": probs,
        "pick": pick,
        "prob": probs[pick],
        "consejo": p.get("advice") or "",
        "goles": p.get("under_over") or "",
    })

items.sort(key=lambda x: x["prob"], reverse=True)

# 3. Análisis de Claude solo para los mejores (ahorra costo)
analisis = ""
top = items[:TOP_TELEGRAM]
if top:
    try:
        c = anthropic.Anthropic()
        m = c.messages.create(
            model="claude-sonnet-5-5", max_tokens=700,
            messages=[{"role": "user", "content":
                "Estos son los pronósticos con mayor probabilidad según un modelo estadístico. "
                "Para cada uno escribe 2 líneas con el factor clave que lo sustenta o el riesgo "
                "principal. Sé honesto: ninguna probabilidad es certeza.\n"
                + json.dumps(top, ensure_ascii=False)}])
        analisis = m.content[0].text
    except Exception as e:
        analisis = f"(Análisis no disponible: {e})"

# 4. Guardar para el dashboard

with open("data.json", "w", encoding="utf-8") as fh:
    json.dump({"actualizado": datetime.datetime.now(ZoneInfo(TZ)).isoformat(),
               "partidos": items, "analisis": analisis}, fh, ensure_ascii=False, indent=1)

# 5. Telegram
nombre = {"local": "Gana local", "empate": "Empate", "visita": "Gana visita"}
txt = f"⚽ Pronósticos más probables ({hoy})\n\n"
for i in top:
    txt += (f"{i['liga']}: {i['local']} vs {i['visita']}\n"
            f"→ {nombre[i['pick']]} ({i['prob']}%)\n\n")
if not top:
    txt += "Hoy no hay partidos de las ligas configuradas."
if analisis:
    txt += "\n" + analisis
url = os.environ.get("DASHBOARD_URL")
if url:
    txt += f"\n\nVer todos: {url}"
requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
              data={"chat_id": TG_CHAT, "text": txt[:4000]}, timeout=30)

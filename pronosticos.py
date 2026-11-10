import os, json, re, datetime, requests, anthropic
from zoneinfo import ZoneInfo

TG_TOKEN = os.environ["TELEGRAM_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]
TZ = "America/Bogota"
LIGAS = "Premier League, LaLiga, Serie A, Bundesliga, Ligue 1, Champions League y Liga BetPlay de Colombia"
MAX_BUSQUEDAS = 8     # limite de busquedas web por ejecucion (controla el costo)
MAX_PARTIDOS = 10
TOP_TELEGRAM = 5

ahora = datetime.datetime.now(ZoneInfo(TZ))
hoy = ahora.date()
manana = hoy + datetime.timedelta(days=1)

prompt = f"""Hoy es {hoy.isoformat()} (hora de Colombia). Busca en la web los partidos de {hoy.isoformat()} y {manana.isoformat()}
de estas competiciones: {LIGAS}. Elige hasta {MAX_PARTIDOS} partidos que aun no hayan empezado.
Para cada uno revisa forma reciente, lesiones/suspensiones, local o visitante y, si lo encuentras, las cuotas.
Estima probabilidades (enteros que sumen 100) de victoria local, empate y victoria visitante.
Responde SOLO con un arreglo JSON, sin texto antes ni despues, con objetos asi:
{{"liga":"...","fecha":"2026-11-10T15:00:00-05:00","local":"...","visita":"...",
"probs":{{"local":50,"empate":28,"visita":22}},"consejo":"mercado recomendado en pocas palabras",
"analisis":"2 lineas con el factor clave y el riesgo principal"}}
Se honesto: si hay poca informacion, baja la confianza y reparte mejor las probabilidades.
Si no hay partidos, responde []."""

client = anthropic.Anthropic()
tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_BUSQUEDAS}]
msgs = [{"role": "user", "content": prompt}]
for _ in range(5):
    r = client.messages.create(model="claude-sonnet-5-5", max_tokens=6000,
                               tools=tools, messages=msgs)
    if r.stop_reason == "pause_turn":
        msgs.append({"role": "assistant", "content": r.content})
        continue
    break

texto = "".join(b.text for b in r.content if b.type == "text")
items = []
try:
    crudo = json.loads(texto[texto.index("["): texto.rindex("]") + 1])
    for x in crudo:
        probs = {k: int(x["probs"][k]) for k in ("local", "empate", "visita")}
        pick = max(probs, key=probs.get)
        items.append({"liga": x.get("liga", ""), "fecha": x.get("fecha", ""),
                      "local": x["local"], "visita": x["visita"], "probs": probs,
                      "pick": pick, "prob": probs[pick],
                      "consejo": x.get("consejo", ""), "goles": "",
                      "analisis": x.get("analisis", "")})
except Exception as e:
    print("No pude leer la respuesta:", e, texto[:500])

items.sort(key=lambda i: i["prob"], reverse=True)
top = items[:TOP_TELEGRAM]
analisis = "\n\n".join(f"{i['local']} vs {i['visita']}: {i['analisis']}" for i in top)

with open("data.json", "w", encoding="utf-8") as fh:
    json.dump({"actualizado": ahora.isoformat(), "partidos": items, "analisis": analisis},
              fh, ensure_ascii=False, indent=1)

nombre = {"local": "Gana local", "empate": "Empate", "visita": "Gana visita"}
txt = f"⚽ Pronósticos más probables ({hoy})\n\n"
for i in top:
    txt += f"{i['liga']}: {i['local']} vs {i['visita']}\n→ {nombre[i['pick']]} ({i['prob']}%)\n\n"
if not top:
    txt += "Hoy no encontré partidos de las ligas configuradas (o hubo un error al leer la respuesta)."
else:
    txt += "Son estimaciones, no certezas."
url = os.environ.get("DASHBOARD_URL")
if url:
    txt += f"\n\nVer todos: {url}"
requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
              data={"chat_id": TG_CHAT, "text": txt[:4000]}, timeout=30)

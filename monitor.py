"""
Monitor externo para servidor de Minecraft.

Hace un Server List Ping (SLP) real -- el handshake de aplicación del
protocolo de Minecraft -- contra el hostname público. Esto es distinto
de un simple chequeo de puerto TCP: valida que el juego realmente
responde, no solo que "algo" acepta la conexión.

Requiere: pip install mcstatus
"""

import json
import os
import time
import urllib.parse
import urllib.request

from mcstatus import JavaServer

MC_HOST = os.environ["MC_HOST"]
MC_PORT = int(os.environ.get("MC_PORT", "25565"))
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
HEALTHCHECKS_URL = os.environ.get("HEALTHCHECKS_URL")  # opcional

STATE_FILE = "state.json"
FAILURE_THRESHOLD = 2  # fallos consecutivos antes de alertar


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"consecutive_failures": 0, "alerted": False}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(url, data=data)
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Error enviando Telegram: {e}")


def ping_healthcheck(suffix=""):
    if not HEALTHCHECKS_URL:
        return
    try:
        urllib.request.urlopen(HEALTHCHECKS_URL + suffix, timeout=10)
    except Exception as e:
        print(f"Error avisando a Healthchecks.io: {e}")


def check_server():
    try:
        server = JavaServer.lookup(f"{MC_HOST}:{MC_PORT}", timeout=10)
        status = server.status()
        detail = (
            f"OK - {status.players.online}/{status.players.max} jugadores, "
            f"latencia {status.latency:.0f}ms"
        )
        return True, detail
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main():
    state = load_state()
    ok, detail = check_server()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    if ok:
        if state["consecutive_failures"] >= FAILURE_THRESHOLD and state.get("alerted"):
            send_telegram(
                f"✅ Recuperado ({timestamp})\n"
                f"El servidor {MC_HOST} volvió a responder correctamente.\n"
                f"{detail}"
            )
        state["consecutive_failures"] = 0
        state["alerted"] = False
        ping_healthcheck()
        print(f"[{timestamp}] {detail}")
    else:
        state["consecutive_failures"] += 1
        print(f"[{timestamp}] FALLO #{state['consecutive_failures']}: {detail}")

        if state["consecutive_failures"] >= FAILURE_THRESHOLD and not state.get("alerted"):
            send_telegram(
                f"🔴 ALERTA: {MC_HOST} no responde ({timestamp})\n"
                f"Fallos consecutivos: {state['consecutive_failures']}\n"
                f"Detalle: {detail}\n\n"
                f"Este chequeo es un Server List Ping real (protocolo de "
                f"Minecraft), no solo verificación de puerto.\n"
                f"Revisar: IP pública actual del servidor, resolución DNS "
                f"de {MC_HOST}, estado del proceso/servicio."
            )
            ping_healthcheck("/fail")
            state["alerted"] = True

    save_state(state)


if __name__ == "__main__":
    main()

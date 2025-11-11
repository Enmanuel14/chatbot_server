import os
import random
import json
import time
from twilio.twiml.messaging_response import MessagingResponse
from flask import Flask, request, Response
from google import genai
from google.genai import types

# ----------------------------------------------------------------------
# CONFIGURACIÓN DE CREDENCIALES (¡OBTENIDAS DEL ENTORNO!)
# ----------------------------------------------------------------------

# Se obtienen del entorno (Railway Variables)
ACCOUNT_SID = os.environ.get("ACCOUNT_SID", None)
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", None)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", None)

# ----------------------------------------------------------------------
# CONFIGURACIÓN DE PERSONALIDAD Y CONTEXTO
# ----------------------------------------------------------------------

# ¡ESTA VARIABLE FALTABA Y ES CRUCIAL PARA DARLE PERSONALIDAD!
SYSTEM_PROMPT = """Eres un bot de prueba de WhatsApp llamado Psicobot. Debes responder con el texto: 'Mensaje recibido correctamente. Confirmo que estoy activo.'"""

# El archivo donde se guarda el historial (Railway debe tener un 'chat_history.json' inicializado con {})
HISTORY_FILE = 'chat_history.json'

CONSEJOS_TECNICAS = [
    """**Técnica de la respiración diafragmática:** Intenta inhalar lentamente contando hasta 4, mantén por 4, y exhala lentamente contando hasta 6. Repítelo 5 veces. Esta técnica es excelente para reducir la ansiedad.""",
    """**Mindfulness (Atención Plena):** Dedica 5 minutos a concentrarte solo en una actividad sensorial (ej. tomar un café), prestando atención a cada detalle. Esto te ancla en el presente.""",
    """**Registro de Pensamientos:** La próxima vez que sientas estrés, escribe la situación, el pensamiento exacto que tuviste y la emoción. Esto ayuda a identificar patrones negativos.""",
    """**Relajación Muscular Progresiva (Jacobson):** Tensa y luego relaja un grupo muscular a la vez, empezando por los pies y subiendo. Esto reduce la tensión física asociada al estrés."""
]

def dar_consejo():
    """Selecciona un consejo aleatorio de la lista local."""
    return random.choice(CONSEJOS_TECNICAS)

# Inicializar cliente de Gemini fuera del webhook para eficiencia
client = None
try:
    # client.Client() toma la clave de GEMINI_API_KEY automáticamente
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    # Esto te dirá si la clave no se cargó o es incorrecta.
    print(f"Error CRÍTICO al inicializar el cliente de Gemini: {e}")

# ----------------------------------------------------------------------
# LÓGICA DE GEMINI Y CONTEXTO
# ----------------------------------------------------------------------

def get_gemini_response(incoming_msg, from_number):
    """
    Gestiona el historial de chat, llama a la API de Gemini
    e implementa la lógica de REINTENTO para evitar fallos por cuota.
    """
    global client

    # **FIX CRÍTICO 1:** Si el cliente no se inicializó, devuelve un error claro.
    if client is None:
        print("FALLO: El cliente de Gemini no se pudo inicializar (revisa GEMINI_API_KEY).")
        return "🤖 Lo siento, la conexión con la IA falló al iniciar. Por favor, avisa a soporte para revisar la clave API."

    # 1. Cargar el historial completo (debe estar inicializado como {})
    try:
        with open(HISTORY_FILE, 'r') as f:
            chat_history = json.load(f)
    except:
        chat_history = {} # Si el archivo no existe o está vacío, crea un historial vacío.

    current_messages = chat_history.get(from_number, [])

    # 2. Limitar el historial para ahorrar tokens (USAR SOLO LOS ÚLTIMOS 4 MENSAJES de contexto)
    context_messages = current_messages[-4:]

    # 3. Construir la lista final de contenidos para la API, incluyendo el SYSTEM_PROMPT.
    # El SYSTEM_PROMPT se añade como primer mensaje del 'model' para darle el rol.
    content_list = [
        {'role': 'model', 'parts': [{'text': SYSTEM_PROMPT}]} # El rol del bot
    ] + context_messages + [
        {'role': 'user', 'parts': [{'text': incoming_msg}]} # El mensaje actual del usuario
    ]

    # 4. Lógica de REINTENTO (Retry Loop) para gestionar errores de cuota/conexión
    reply_text = ""
    
    for attempt in range(3): # Intentará hasta 3 veces
        try:
            # Llamada a la API de Gemini
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=content_list
            )

            reply_text = response.text
            
            # **FIX CRÍTICO 2:** Si la respuesta está vacía (posible filtro de seguridad), aborta y da un consejo.
            if not reply_text or len(reply_text.strip()) < 5: 
                 raise Exception("Respuesta de Gemini vacía o filtrada por seguridad.")
            
            # Si tiene éxito:
            # 5. Actualizar y guardar el historial de chat
            current_messages.append({'role': 'user', 'parts': [{'text': incoming_msg}]})
            current_messages.append({'role': 'model', 'parts': [{'text': reply_text}]})
            chat_history[from_number] = current_messages
            
            with open(HISTORY_FILE, 'w') as f:
                json.dump(chat_history, f)
            
            return reply_text # ¡Éxito! Salir de la función

        except Exception as e:
            # Si falla (por cuota, error de red, o respuesta vacía)
            print(f"ERROR: Fallo de Gemini en el intento {attempt + 1}. Mensaje: {e}")
            
            if attempt < 2:
                # Si no es el último intento, esperar y reintentar
                time.sleep(2) # Espera 2 segundos antes de reintentar
            else:
                # Si falla en el último intento, devuelve un mensaje de error y un consejo
                consejo = dar_consejo()
                return f"🤖 Lo siento, estoy experimentando una congestión alta y no puedo responder ahora. Vuelve a intentarlo en un minuto.\n\n💡 CONSEJO RÁPIDO: {consejo}" 
    
    # Fallback si el bucle termina por alguna razón
    return "🤖 No se pudo contactar a la IA después de varios intentos (Fallo total de la conexión)."

# ----------------------------------------------------------------------
# WEBHOOK Y SERVIDOR FLASK
# ----------------------------------------------------------------------

app = Flask(__name__)

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    """
    Este es el Webhook que Twilio llama cuando recibe un mensaje de WhatsApp.
    """
    incoming_msg = request.values.get('Body', '')
    from_number = request.values.get('From', '')
    
    # Log: Esto debe aparecer en Railway para confirmar que Twilio llama al servidor
    print(f"\n--- Mensaje Recibido ---\nDe: {from_number}\nMensaje: {incoming_msg}")
    
    reply_text = get_gemini_response(incoming_msg, from_number)
    
    resp = MessagingResponse()
    resp.message(reply_text)
    
    # FIX CRUCIAL PARA TWILIO: Devuelve la respuesta como XML con el encabezado MIME correcto
    return Response(str(resp), mimetype='application/xml')

# ----------------------------------------------------------------------
# EJECUCIÓN DEL SERVIDOR
# ----------------------------------------------------------------------

if __name__ == "__main__":
    # El puerto 8080 es el estándar para Google Cloud Run y un puerto seguro para Railway.
    print("SERVIDOR DE PSICOBOT INICIADO (Modo Local de Prueba)")
    app.run(host='0.0.0.0', port=8080)



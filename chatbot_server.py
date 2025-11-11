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
# Get from the environment (Railway Variables)
ACCOUNT_SID = os.environ.get("ACCOUNT_SID", None)
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", None)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", None)

# ----------------------------------------------------------------------
# CONFIGURACIÓN DE PERSONALIDAD Y CONTEXTO
# ----------------------------------------------------------------------

SYSTEM_PROMPT = """Eres un Psicobot (Bot Psicólogo) empático y de apoyo.
Tu objetivo es escuchar, validar los sentimientos del usuario, y ofrecer apoyo emocional y técnicas sencillas
para manejar el estrés o la ansiedad.
- Sé calmado, reflexivo y profesional.
- No diagnostiques ni proporciones asesoramiento médico; siempre enfatiza que no eres un sustituto de un terapeuta humano.
- Responde de forma concisa (máximo 4 oraciones) para mantener el flujo de la conversación por WhatsApp."""

# El archivo donde se guarda el historial (Railway debe tener un 'chat_history.json' inicializado con {})
# The file where the history is saved (Railway must have an initialized 'chat_history.json' with {})
HISTORY_FILE = 'chat_history.json'

CONSEJOS_TECNICAS = [
    """**Técnica de la respiración diafragmática:** Intenta inhalar lentamente contando hasta 4, mantén por 4, y exhala lentamente contando hasta 6. Repítelo 5 veces. Esta técnica es excelente para reducir la ansiedad.""",
    """**Mindfulness (Atención Plena):** Dedica 5 minutos a concentrarte solo en una actividad sensorial (ej. tomar un café), prestando atención a cada detalle. Esto te ancla en el presente.""",
    """**Registro de Pensamientos:** La próxima vez que sientas estrés, escribe la situación, el pensamiento exacto que tuviste y la emoción. Esto ayuda a identificar patrones negativos.""",
    """**Relajación Muscular Progresiva (Jacobson):** Tensa y luego relaja un grupo muscular a la vez, empezando por los pies y subiendo. Esto reduce la tensión física asociada al estrés."""
]

def dar_consejo():
    """Selecciona un consejo aleatorio de la lista local."""
    # Selects a random tip from the local list.
    return random.choice(CONSEJOS_TECNICAS)

# Inicializar cliente de Gemini fuera del webhook para eficiencia
# Initialize Gemini client outside the webhook for efficiency
client = None
if GEMINI_API_KEY:
    try:
        # CORRECCIÓN CRÍTICA: Se pasa la clave API directamente para evitar errores de entorno.
        # CRITICAL FIX: The API key is passed directly to avoid environment errors.
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Cliente de Gemini inicializado correctamente.") # Nuevo log de éxito
    except Exception as e:
        # Esto atrapará el error si la clave es inválida.
        # This will catch the error if the key is invalid.
        print(f"❌ Error CRÍTICO al inicializar el cliente de Gemini: {e}")
else:
    # Si la clave no se encontró.
    # If the key was not found.
    print("❌ Error CRÍTICO: La variable GEMINI_API_KEY está vacía o no se cargó.")

# ----------------------------------------------------------------------
# LÓGICA DE GEMINI Y CONTEXTO
# ----------------------------------------------------------------------

def get_gemini_response(incoming_msg, from_number):
    """
    Gestiona el historial de chat, llama a la API de Gemini
    e implementa la lógica de REINTENTO.
    """
    global client

    # Si el cliente falló al iniciar, devuelve un mensaje de error CLARO.
    # If the client failed to start, return a CLEAR error message.
    if client is None:
        # ESTE ES EL MENSAJE DE DIAGNÓSTICO EN RAILWAY
        print("💥 DIAGNÓSTICO: Cliente de Gemini NO inicializado. Fallo de la clave API.")
        return "🤖 Lo siento, la conexión con la IA falló al iniciar. Por favor, avisa a soporte para revisar la clave API."

    # 1. Cargar el historial completo
    # 1. Load the complete history
    try:
        with open(HISTORY_FILE, 'r') as f:
            chat_history = json.load(f)
    except:
        chat_history = {} # Si el archivo no existe, crea un historial vacío.

    current_messages = chat_history.get(from_number, [])

    # 2. Limitar el historial para ahorrar tokens (USAR SOLO LOS ÚLTIMOS 4 MENSAJES de contexto)
    # 2. Limit history to save tokens (USE ONLY THE LAST 4 context messages)
    context_messages = current_messages[-4:]

    # 3. Construir la lista final de contenidos para la API, incluyendo el SYSTEM_PROMPT.
    # 3. Build the final list of contents for the API, including the SYSTEM_PROMPT.
    content_list = [
        {'role': 'model', 'parts': [{'text': SYSTEM_PROMPT}]} # El rol del bot
    ] + context_messages + [
        {'role': 'user', 'parts': [{'text': incoming_msg}]} # El mensaje actual del usuario
    ]

    # 4. Lógica de REINTENTO (Retry Loop) para gestionar errores
    # 4. RETRY Logic (Retry Loop) to manage errors
    reply_text = ""
    
    for attempt in range(3): # Intentará hasta 3 veces / It will try up to 3 times
        try:
            # Llamada a la API de Gemini
            # Gemini API Call
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=content_list
            )
            print(f"✅ Respuesta de Gemini exitosa en intento {attempt + 1}.") # Nuevo log de éxito
            
            reply_text = response.text
            
            # Si la respuesta está vacía (posible filtro de seguridad), aborta.
            # If the response is empty (possible security filter), abort.
            if not reply_text or len(reply_text.strip()) < 5: 
                 raise Exception("Respuesta de Gemini vacía o filtrada por seguridad.")
            
            # Si tiene éxito:
            # If successful:
            # 5. Actualizar y guardar el historial de chat
            # 5. Update and save chat history
            current_messages.append({'role': 'user', 'parts': [{'text': incoming_msg}]})
            current_messages.append({'role': 'model', 'parts': [{'text': reply_text}]})
            chat_history[from_number] = current_messages
            
            with open(HISTORY_FILE, 'w') as f:
                json.dump(chat_history, f)
            
            return reply_text # ¡Éxito!
        
        except Exception as e:
            # Si falla, registra el error e intenta de nuevo.
            # If it fails, log the error and try again.
            print(f"❌ ERROR: Fallo de Gemini en el intento {attempt + 1}. Mensaje: {e}")
            
            if attempt < 2:
                time.sleep(2) # Espera 2 segundos antes de reintentar
            else:
                # Si falla en el último intento, devuelve un mensaje de error y un consejo
                # If it fails on the last attempt, return an error message and a tip
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
    # This is the Webhook that Twilio calls when it receives a WhatsApp message.
    incoming_msg = request.values.get('Body', '')
    from_number = request.values.get('From', '')
    
    # Log: Esto debe aparecer en Railway
    print(f"\n--- Mensaje Recibido ---\nDe: {from_number}\nMensaje: {incoming_msg}")
    
    reply_text = get_gemini_response(incoming_msg, from_number)
    
    resp = MessagingResponse()
    resp.message(reply_text)
    
    # FIX CRUCIAL PARA TWILIO: Devuelve la respuesta como XML
    # CRUCIAL FIX FOR TWILIO: Returns the response as XML
    return Response(str(resp), mimetype='application/xml')

# ----------------------------------------------------------------------
# EJECUCIÓN DEL SERVIDOR
# ----------------------------------------------------------------------

if __name__ == "__main__":
    print("SERVIDOR DE PSICOBOT INICIADO (Modo Local de Prueba)")
    app.run(host='0.0.0.0', port=8080)

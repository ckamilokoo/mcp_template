# Preparación de entorno y configuración con .env

Objetivo
- Dejar listo el entorno en Windows y configurar claves y parámetros de forma segura con .env.

Requisitos
- Python 3.12+ (este repo incluye venvs locales, puedes usar uno o tu propio entorno).
- Docker Desktop.
- Una API key para el LLM (OpenAI u OpenRouter).

Variables de entorno (.env)
- Copia .env.example a .env y ajusta:
  - OPENAI_API_KEY=tu_clave
  - MODEL_PROVIDER=openai (o openrouter)
  - MODEL_NAME=gpt-4o-mini (u otro compatible)
  - DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD (si usas valores distintos a los del docker-compose)

Carga automática de .env
- mcp_chat.py usa python-dotenv para cargar .env automáticamente al inicio.
- Beneficio: no necesitas exportar variables manualmente; cuida no committear claves.

Comandos útiles (PowerShell)
- Cambiar a la carpeta del proyecto:
  - cd "c:\Users\Camilo Campos\Downloads\mcp_test_db-main\mcp_test_db-main"
- Verificar que Python ve el entorno (opcional):
  - .\.venv_new\Scripts\python.exe --version
- Ejecutar el cliente con un prompt de prueba:
  - .\.venv_new\Scripts\python.exe mcp_chat.py "Lista los primeros 3 empleados"

Seguridad de claves
- Nunca subas .env al repositorio público.
- Usa .env para local y secretos de CI/CD en entornos remotos.

Ejercicio
- Abre .env y configura proveedor/modelo del LLM.
- Verifica que mcp_chat.py puede leer la clave (si falla, revisa el formato y nombre del archivo).

Checklist de comprensión
- Sé dónde y cómo configurar .env.
- Entiendo que mcp_chat.py carga .env automáticamente.
- Puedo ejecutar un comando de prueba en Windows PowerShell.
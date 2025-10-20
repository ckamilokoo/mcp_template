# MCP Test DB — Servidor MCP (FastAPI + SSE) y Cliente Chat LLM

Este proyecto demuestra un flujo completo donde:
- Un servidor MCP (basado en FastAPI) expone herramientas para acceder a una base de datos PostgreSQL.
- La comunicación cliente-servidor se realiza vía SSE (Server‑Sent Events) usando JSON‑RPC.
- Un cliente de chat LLM (`mcp_chat.py`) interactúa con el servidor, descubre herramientas y las invoca (p. ej., listar y agregar empleados) para responder en conversación.

## Arquitectura
- Docker Compose levanta:
  - `company_postgres`: Base de datos PostgreSQL inicializada con `init.sql`.
  - `company_mcp_server`: Servidor FastAPI con endpoint SSE en `/sse`.
- El cliente `mcp_chat.py` (Python) se conecta al SSE, negocia `session_id`, y usa un lector en segundo plano para mantener el stream y emparejar respuestas por `id`.

## Herramientas disponibles (MCP)
- `list_employees` (GET): Lista empleados. Parámetros típicos:
  - `limit` (opcional, int): número máximo de empleados a devolver.
- `add_employee` (POST): Agrega un empleado. Parámetros típicos:
  - `name` (str), `position` (str), `department` (str), `salary` (number).

La base de datos se inicializa con datos de ejemplo (ver `init.sql`).

## Cliente de Chat LLM (`mcp_chat.py`)
- Carga `.env` automáticamente (via `python-dotenv`).
- Soporta múltiples proveedores de modelos:
  - OpenAI: `MODEL_PROVIDER=openai`, `MODEL_NAME=gpt-4o-mini` (ejemplo).
  - OpenRouter: `MODEL_PROVIDER=openrouter`, `MODEL_NAME=meta-llama/llama-3.1-8b-instruct` (ejemplo).
- Convierte los esquemas de herramientas MCP a formato de “function calling” del proveedor y realiza la llamada real al servidor vía SSE.
- Patrón SSE robusto:
  - Un solo lector en segundo plano mantiene el stream.
  - Extrae y guarda `session_id`.
  - Respuestas se almacenan por `id` del mensaje JSON‑RPC.

## Requisitos
- Docker y Docker Compose.
- Python 3.11+ en tu sistema para ejecutar `mcp_chat.py`.
- Variables de entorno (en `.env`):
  - OpenAI: `OPENAI_API_KEY`.
  - OpenRouter: `OPENROUTER_API_KEY`.
  - Selección de modelo: `MODEL_PROVIDER`, `MODEL_NAME`.

> Importante: No publiques tu `.env` en repositorios públicos.

## Cómo ejecutar
1) Levantar servidor y base de datos:
   - `docker-compose up -d`
2) Ejecutar el cliente de chat:
   - `python mcp_chat.py`
3) Escribe consultas naturales. Ejemplos:
   - "Lista los primeros 5 empleados"
   - "Agrega un empleado llamado Pedro con salario 62000 en Analytics"

El agente decidirá si debe invocar una herramienta (p. ej., `list_employees` o `add_employee`). Los resultados reales del servidor se integran a la conversación para producir una respuesta final.

## Contenido del repositorio

- main.py — Servidor MCP (FastAPI) con endpoint SSE (/sse) y herramientas de base de datos (listar y agregar empleados).
- mcp_chat.py — Cliente de chat (LLM + SSE) que descubre y llama herramientas del servidor.
- docker-compose.yml — Orquestación de Postgres y servidor MCP.
- init.sql — Inicialización de la base de datos.
- .env / .env.example — Variables de entorno.
- Dockerfile — Imagen del servidor MCP.
- pyproject.toml — Dependencias y configuración de Python.
- uv.lock — Archivo de lock para uv.

## Guía incremental (docs/)
Para compartir con el equipo, consulta los módulos paso a paso:
- docs/01-introduccion-mcp.md — Qué es MCP y arquitectura del repo
- docs/02-entorno-y-dotenv.md — Preparación de entorno y configuración segura con .env
- docs/03-docker-compose-db-server.md — Cómo levantar Postgres y el servidor MCP con Docker Compose

## Buenas prácticas SSE
- Mantener un único lector SSE para toda la sesión.
- Guardar `session_id` tras `initialize`.
- Emparejar cada respuesta JSON‑RPC por `id`.
- No cerrar el stream hasta terminar la sesión.

## Solución a problemas comunes
- “Falla la conexión SSE”: Verificar que el servidor esté corriendo (`docker-compose ps`), firewall y puerto.
- “Falta la API key”: Asegurar `.env` cargado y variables correctas (`OPENAI_API_KEY` u `OPENROUTER_API_KEY`).
- “Timeout esperando respuesta”: Confirmar que no haya múltiples lectores y que el `id` del mensaje se use para emparejar la respuesta.
- Pydantic v2: Evitar el uso de `model.dict()`, usar `model_dump()`.

## Estado del repositorio
Se eliminaron scripts de prueba antiguos para simplificar el proyecto. La interacción recomendada es a través de `mcp_chat.py` usando las herramientas del servidor. Documentos de referencia sobre SSE se conservan para apoyo.
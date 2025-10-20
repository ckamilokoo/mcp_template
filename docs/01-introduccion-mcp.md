# Introducción a MCP (Model Context Protocol)

Objetivo
- Entender qué es MCP, cómo se relacionan servidor y cliente, y cómo este repo lo implementa.

Conceptos clave
- MCP Server: expone herramientas (funciones) que un LLM puede invocar para leer/escribir datos o ejecutar acciones.
- MCP Client: un proceso que conversa con el LLM; cuando el modelo necesita datos o acciones, el cliente realiza llamadas a las herramientas del servidor.
- Canal de comunicación: en este proyecto usamos SSE (Server-Sent Events) para intercambiar mensajes de forma continua.

Arquitectura del proyecto
- docker-compose.yml: levanta Postgres (DB) y el MCP Server (contenedor Python) que expone herramientas.
- main.py: define el servidor FastMCP, la conexión a Postgres y registra herramientas (list_employees, add_employee, índices, vistas, EXPLAIN, etc.).
- mcp_chat.py: cliente de chat que configura el LLM (OpenAI/OpenRouter), carga .env automáticamente (python-dotenv) y se conecta al servidor por SSE.
- init.sql: inicializa la base con tablas y datos de ejemplo.
- .env / .env.example: variables de entorno (API keys, modelo, datos de conexión a DB).

Flujo de alto nivel
1) El servidor arranca y registra herramientas MCP.
2) El cliente se conecta por SSE y anuncia al LLM qué herramientas están disponibles.
3) El LLM, guiado por tu prompt, decide invocar herramientas del servidor para cumplir la tarea (p.ej. listar empleados, crear índice, crear vista).
4) El cliente muestra la respuesta final, combinando salida del LLM con resultados de herramientas.

Ejercicio de reconocimiento
- Abre README.md y ubica los componentes: cliente (mcp_chat.py), servidor (main.py), DB (Postgres via Docker), y .env.
- Tarea: describe en una frase qué hace cada archivo.

Checklist de comprensión
- Entiendo qué es MCP y el rol de server/cliente.
- Puedo ubicar dónde están las herramientas en el código.
- Sé que mcp_chat.py carga .env automáticamente y se conecta por SSE.
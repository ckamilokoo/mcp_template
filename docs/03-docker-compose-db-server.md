# Levantar la base de datos y el MCP Server con Docker Compose

Objetivo
- Tener Postgres y el servidor MCP ejecutándose para pruebas.

Componentes
- docker-compose.yml: define servicios company_postgres y company_mcp_server.
- init.sql: inicializa tablas y datos de ejemplo.

Pasos
1) Arrancar servicios:
- docker-compose up -d

2) Verificar contenedores:
- docker ps

3) Reconstruir (cuando cambies main.py):
- docker-compose up -d --build

4) Revisar logs del servidor (opcional):
- docker-compose logs -f company_mcp_server

Prueba rápida del cliente
- Ejecuta:
- .\.venv_new\Scripts\python.exe mcp_chat.py "Lista los primeros 3 empleados"
- Espera: conexión SSE, listado de herramientas, ejecución de list_employees y respuesta con 3 empleados.

Solución de problemas
- Si la DB no arranca: revisa puertos y variables de entorno en docker-compose.yml.
- Si el server no muestra herramientas: verifica excepciones en logs y que main.py registre las herramientas correctamente.
- Si mcp_chat.py falla la API key: confirmá que .env está cargado y sin comillas extra ni espacios.

Ejercicio
- Modifica main.py (por ejemplo, el mensaje de una herramienta) y reconstruye contenedores con --build.
- Verifica el cambio conectándote nuevamente con mcp_chat.py.

Checklist de comprensión
- Sé cómo levantar, verificar y reconstruir servicios con Docker Compose.
- Puedo leer logs y entender si el server registró herramientas.
- Puedo ejecutar el cliente y validar el flujo end-to-end.
#!/usr/bin/env python3
"""
Agente de chat con LLM que usa el servidor MCP por SSE para llamar herramientas
(list_employees, add_employee) y acceder a la base de datos.

Requisitos:
- Servidor MCP corriendo (docker-compose up) en http://localhost:3000
- Variable de entorno OPENAI_API_KEY o OPENROUTER_API_KEY según el proveedor
- Paquetes: openai, httpx

Ejecución:
# Selección de proveedor y modelo por entorno
#   MODEL_PROVIDER=openai|openrouter
#   MODEL_NAME=gpt-4o-mini | anthropic/claude-3.5-sonnet | mistralai/mistral-large | meta-llama/llama-3.1-70b-instruct, etc.
# Ejemplo OpenAI:
#   set MODEL_PROVIDER=openai
#   set MODEL_NAME=gpt-4o-mini
#   set OPENAI_API_KEY=...
# Ejemplo OpenRouter (Anthropic Claude vía OpenRouter):
#   set MODEL_PROVIDER=openrouter
#   set MODEL_NAME=anthropic/claude-3.5-sonnet
#   set OPENROUTER_API_KEY=...
python mcp_chat.py
"""
import os
import asyncio
import json
from typing import Dict, Any, Optional

import httpx
from openai import OpenAI
from dotenv import load_dotenv  # <-- nuevo: carga .env

# [Configuración del entorno]
# Cargar variables desde .env automáticamente. Esto permite definir API keys y el modelo
# sin hardcodear credenciales. Ver docs/02-entorno-y-dotenv.md
load_dotenv()

# --------------------- Cliente MCP (SSE robusto) ---------------------
# Esta clase implementa el cliente JSON-RPC para el servidor MCP, usando SSE.
# - Abre una conexión SSE para recibir eventos del servidor (incluye session_id)
# - Envía mensajes JSON-RPC (initialize, tools/list, tools/call) por HTTP POST
# - Mantiene un buffer responses para correlacionar respuestas asincrónicas por ID
class MCPClient:
    def __init__(self, base_url: str = "http://localhost:3000"):
        self.base_url = base_url
        self.session_id: Optional[str] = None
        self.client: Optional[httpx.AsyncClient] = None
        self.sse_client: Optional[httpx.AsyncClient] = None
        self.sse_task: Optional[asyncio.Task] = None
        self.responses: Dict[int, Dict[str, Any]] = {}
        self.message_counter: int = 0

    def get_next_id(self) -> int:
        # [Correlación JSON-RPC] Genera un ID incremental para cada mensaje
        self.message_counter += 1
        return self.message_counter

    async def __aenter__(self):
        # [Lifecycle] Crea clientes HTTP y SSE asincrónicos
        self.client = httpx.AsyncClient(timeout=30.0)
        self.sse_client = httpx.AsyncClient(timeout=None)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # [Cleanup] Cancela el loop SSE y cierra los clientes
        if self.sse_task:
            self.sse_task.cancel()
            try:
                await self.sse_task
            except asyncio.CancelledError:
                pass
        if self.sse_client:
            await self.sse_client.aclose()
        if self.client:
            await self.client.aclose()

    async def connect_sse(self) -> bool:
        # [Conexión SSE] Inicia el loop de lectura de eventos y espera session_id
        try:
            print("📡 Conectando al endpoint SSE...")
            self.sse_task = asyncio.create_task(self._sse_loop())
            end_time = asyncio.get_event_loop().time() + 10
            while asyncio.get_event_loop().time() < end_time:
                if self.session_id:
                    print("✅ Conexión SSE establecida")
                    return True
                await asyncio.sleep(0.05)
            print("⚠️ No se pudo obtener session_id del SSE")
            return False
        except Exception as e:
            print(f"❌ Error conectando SSE: {e}")
            return False

    async def _sse_loop(self):
        # [Loop SSE] Abre un stream tipo EventSource y procesa líneas data: ...
        try:
            async with self.sse_client.stream(
                # Método HTTP para suscribir SSE. Ver main.py (/sse)
                "GET",
                f"{self.base_url}/sse",
                headers={"Accept": "text/event-stream"}
            ) as response:
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_content = line[5:].strip()
                    # El servidor envía session_id en un evento data: ...
                    if "session_id=" in data_content and self.session_id is None:
                        try:
                            self.session_id = data_content.split("session_id=")[1].split()[0].split("&")[0]
                            print(f"📋 Session ID: {self.session_id}")
                        except Exception:
                            pass
                    # Mensajes JSON-RPC llegan como JSON en data:
                    elif data_content.startswith("{"):
                        try:
                            message = json.loads(data_content)
                            if "id" in message:
                                # Buffer responses por ID para send_message_and_wait
                                self.responses[message["id"]] = message
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            print(f"❌ Error en SSE loop: {e}")

    async def send_message_and_wait(self, message: Dict[str, Any], timeout: int = 15) -> Optional[Dict[str, Any]]:
        # [Solicitud JSON-RPC] Envía el mensaje por POST y espera respuesta
        # - Si el servidor responde 202, la respuesta llegará vía SSE y se espera en responses
        if not self.session_id:
            print("❌ No hay session_id disponible")
            return None
        msg_id = message["id"]
        try:
            resp = await self.client.post(
                f"{self.base_url}/messages/?session_id={self.session_id}",
                json=message,
                headers={"Content-Type": "application/json"}
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 202:
                end_time = asyncio.get_event_loop().time() + timeout
                while asyncio.get_event_loop().time() < end_time:
                    if msg_id in self.responses:
                        return self.responses.pop(msg_id)
                    await asyncio.sleep(0.1)
                print(f"⏰ Timeout esperando respuesta para ID {msg_id}")
                return None
            else:
                print(f"❌ Error {resp.status_code}: {resp.text}")
                return None
        except Exception as e:
            print(f"❌ Error enviando mensaje: {e}")
            return None

    async def initialize(self) -> Optional[Dict[str, Any]]:
        # [Handshake MCP] Inicializa sesión con protocolo MCP y capacidades
        message = {
            "jsonrpc": "2.0",
            "id": self.get_next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {"listChanged": True}, "sampling": {}},
                "clientInfo": {"name": "chat-agent", "version": "1.0.0"}
            }
        }
        result = await self.send_message_and_wait(message, timeout=10)
        if result:
            # Notifica que el cliente está listo
            await self.send_initialized_notification()
        return result

    async def send_initialized_notification(self):
        # [Ready] Notificación estándar MCP de cliente inicializado
        message = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        await self.client.post(
            f"{self.base_url}/messages/?session_id={self.session_id}",
            json=message,
            headers={"Content-Type": "application/json"}
        )

    async def list_tools(self) -> Optional[Dict[str, Any]]:
        # [Descubrimiento] Solicita al servidor MCP el catálogo de tools disponibles
        message = {"jsonrpc": "2.0", "id": self.get_next_id(), "method": "tools/list", "params": {}}
        return await self.send_message_and_wait(message, timeout=15)

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # [Ejecución de tool] Invoca una herramienta MCP con sus argumentos
        message = {
            "jsonrpc": "2.0",
            "id": self.get_next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments}
        }
        return await self.send_message_and_wait(message, timeout=20)

# --------------------- Agente de chat con proveedor configurable ---------------------
# El ChatAgent puentea el LLM (OpenAI/OpenRouter) con las tools MCP:
# - Traduce el catálogo MCP a "function tools" del formato OpenAI compatible
# - Gestiona el flujo de tool_calls: primera respuesta del LLM -> llamadas MCP -> respuesta final
class ChatAgent:
    def __init__(self, mcp_client: MCPClient):
        self.mcp_client = mcp_client
        self.tools_schema = []
        self.history = []
        # Selección de proveedor y modelo
        self.provider = os.getenv("MODEL_PROVIDER", "openai").lower()
        self.model_name = os.getenv("MODEL_NAME", "gpt-4o-mini")
        # Clientes por proveedor
        self.openai_client: Optional[OpenAI] = None
        self.http_client: Optional[httpx.Client] = None
        if self.provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("Falta OPENAI_API_KEY para proveedor openai")
            self.openai_client = OpenAI(api_key=api_key)
        elif self.provider == "openrouter":
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise RuntimeError("Falta OPENROUTER_API_KEY para proveedor openrouter")
            # Cliente HTTP para OpenRouter (API OpenAI-compatible)
            self.http_client = httpx.Client(
                base_url="https://openrouter.ai/api/v1",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }, timeout=30.0
            )
        else:
            raise RuntimeError(f"Proveedor no soportado: {self.provider}")

    @staticmethod
    def mcp_tools_to_openai(tools_result: Dict[str, Any]) -> list:
        # [Traducción de catálogo MCP] Convierte tools MCP a schema de function tools
        tools = []
        try:
            for tool in tools_result.get("result", {}).get("tools", []):
                input_schema = tool.get("inputSchema", {"type": "object", "properties": {}})
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": input_schema
                    }
                })
        except Exception:
            pass
        return tools

    def _request_completion(self, messages: list, tools: list) -> Dict[str, Any]:
        """Solicita una completion al proveedor seleccionado."""
        # [LLM request] Envía mensajes y (opcionalmente) las function tools
        if self.provider == "openai":
            resp = self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
            return resp.dict() if hasattr(resp, "dict") else resp
        elif self.provider == "openrouter":
            payload = {"model": self.model_name, "messages": messages}
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
            r = self.http_client.post("/chat/completions", json=payload)
            r.raise_for_status()
            return r.json()
        else:
            raise RuntimeError("Proveedor no soportado")

    def _extract_message(self, resp: Dict[str, Any]) -> Dict[str, Any]:
        """Extrae el primer mensaje del formato OpenAI/OpenRouter."""
        return resp["choices"][0]["message"]

    async def setup(self):
        # [Setup del agente] Conecta SSE, inicializa MCP y obtiene el catálogo de tools
        if not await self.mcp_client.connect_sse():
            raise RuntimeError("No se pudo conectar al SSE del servidor MCP")
        init = await self.mcp_client.initialize()
        if not init:
            raise RuntimeError("No se pudo inicializar el cliente MCP")
        tools_res = await self.mcp_client.list_tools()
        if not tools_res:
            raise RuntimeError("No se pudo obtener la lista de herramientas")
        self.tools_schema = self.mcp_tools_to_openai(tools_res)

    async def chat_once(self, user_text: str) -> str:
        # [Ciclo de conversación]
        # 1) Se arma el prompt (system + history + user)
        # 2) Se consulta al LLM; si pide tool_calls, se ejecutan contra el servidor MCP
        # 3) Se añade cada resultado como mensaje role=tool
        # 4) Se pide una segunda completion al LLM con los resultados para la respuesta final
        system_msg = {
            "role": "system",
            "content": (
                "Eres un asistente para gestión de empleados. Puedes usar herramientas MCP "
                "para listar empleados y agregar nuevos registros. Si necesitas datos reales, "
                "usa las herramientas disponibles."
            )
        }
        messages = [system_msg] + self.history + [{"role": "user", "content": user_text}]

        # Primera respuesta del LLM
        resp = self._request_completion(messages, self.tools_schema)
        msg = self._extract_message(resp)
        self.history.append({"role": "user", "content": user_text})

        # Si el LLM solicita herramientas
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            self.history.append({
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": [
                    {
                        "id": tc.get("id"),
                        "type": "function",
                        "function": {
                            "name": tc.get("function", {}).get("name"),
                            "arguments": tc.get("function", {}).get("arguments")
                        }
                    } for tc in tool_calls
                ]
            })
            # Ejecutar cada tool_call
            for tc in tool_calls:
                name = tc.get("function", {}).get("name")
                try:
                    args = json.loads(tc.get("function", {}).get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await self.mcp_client.call_tool(name, args)
                # Resultado de la tool se agrega al historial como role=tool
                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": json.dumps(result or {})
                })
            # Respuesta final ya con resultados
            final_resp = self._request_completion([system_msg] + self.history, [])
            final_msg = self._extract_message(final_resp).get("content", "")
            self.history.append({"role": "assistant", "content": final_msg})
            return final_msg
        else:
            self.history.append({"role": "assistant", "content": msg.get("content", "")})
            return msg.get("content", "")

# --------------------- Main (bucle interactivo) ---------------------
async def main():
    # [Validaciones de entorno] Verifica API keys según proveedor en uso
    provider = os.getenv("MODEL_PROVIDER", "openai").lower()
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        print("❌ Falta OPENAI_API_KEY en el entorno (.env)")
        return
    if provider == "openrouter" and not os.getenv("OPENROUTER_API_KEY"):
        print("❌ Falta OPENROUTER_API_KEY en el entorno (.env)")
        return

    async with MCPClient() as mcp:
        # [Arranque] Crea el agente y hace setup (SSE + initialize + tools)
        agent = ChatAgent(mcp)
        await agent.setup()
        model_name = os.getenv("MODEL_NAME", "gpt-4o-mini")
        print(f"🤖 Agente listo con proveedor '{provider}' y modelo '{model_name}'. Escribe 'salir' para terminar.")
        # [Loop interactivo] Lee input del usuario y produce respuesta del LLM (con tools si aplica)
        while True:
            try:
                user_input = input("\n👤 Tú: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n👋 Saliendo...")
                break
            if user_input.lower() in {"salir", "exit", "quit"}:
                print("👋 Adiós!")
                break
            if not user_input:
                continue
            print("\n🤖 Pensando...")
            answer = await agent.chat_once(user_input)
            print(f"\n🤖 {answer}")

if __name__ == "__main__":
    asyncio.run(main())
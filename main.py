import os
import logging
from typing import List, Dict, Any, Optional, Callable, Awaitable
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql  # nuevo: composición segura de SQL
from fastmcp import FastMCP
import anyio
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Middleware ASGI personalizado para manejar errores SSE
# --- MCP Server: Este archivo implementa un servidor FastMCP que expone herramientas ("tools")
# --- para que un cliente LLM (mcp_chat.py) las invoque vía SSE. Incluye:
# --- 1) Middleware/manejo de errores SSE
# --- 2) Conexión y consultas a Postgres
# --- 3) Herramientas básicas (listar/agregar empleados)
# --- 4) Herramientas avanzadas (índices, vistas, materialized, EXPLAIN)
class SSEErrorHandlerMiddleware:
    """Middleware ASGI que maneja anyio.ClosedResourceError de forma graceful"""
    
    def __init__(self, app: Callable):
        self.app = app
        # Propagar el atributo state si existe
        if hasattr(app, 'state'):
            self.state = app.state
    
    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Intercepta y maneja errores SSE a nivel ASGI"""
        
        async def wrapped_send(message: dict) -> None:
            """Wrapper para send que maneja errores de conexión cerrada"""
            try:
                # Formatear el mensaje SSE según el estándar
                if message['type'] == 'http.response.body':
                    body = message.get('body', b'').decode('utf-8')
                    formatted_message = f"data: {body}\n\n".encode('utf-8')
                    message['body'] = formatted_message

                await send(message)
            except (anyio.ClosedResourceError, anyio.BrokenResourceError) as e:
                logger.info(f"Cliente SSE desconectado durante envío: {type(e).__name__}")
                # Re-lanzar el error para que FastMCP pueda manejarlo apropiadamente
                raise
            except Exception as e:
                logger.error(f"Error inesperado en send: {e}")
                raise
        
        try:
            await self.app(scope, receive, wrapped_send)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError) as e:
            logger.info(f"Cliente SSE desconectado inesperadamente: {type(e).__name__}")
            # Solo manejar el error si es una conexión HTTP y no se ha enviado respuesta
            if scope.get("type") == "http" and not hasattr(scope, "_response_started"):
                try:
                    await wrapped_send({
                        "type": "http.response.start",
                        "status": 499,  # Client Closed Request
                        "headers": [[b"content-type", b"text/plain"]],
                    })
                    await wrapped_send({
                        "type": "http.response.body",
                        "body": b"Client disconnected",
                    })
                except:
                    # Si ya se envió una respuesta, ignorar
                    pass
        except Exception as e:
            logger.error(f"Error no manejado en middleware SSE: {e}")
            raise
    
    def __getattr__(self, name):
        # Delegar cualquier atributo no encontrado a la aplicación original
        return getattr(self.app, name)

# [Registro del servidor MCP] Instanciamos FastMCP con un nombre lógico del servidor.
# Las funciones decoradas con @mcp.tool quedan registradas como herramientas disponibles
# para que el LLM (cliente) las descubra y las invoque según el prompt del usuario.
mcp = FastMCP("company-db-server")

# Monkey patch para anyio streams para manejar ClosedResourceError en el origen
import anyio.streams.memory
original_send = anyio.streams.memory.MemoryObjectSendStream.send
original_send_nowait = anyio.streams.memory.MemoryObjectSendStream.send_nowait

async def patched_send(self, item):
    """Send con manejo de ClosedResourceError"""
    try:
        return await original_send(self, item)
    except anyio.ClosedResourceError:
        logger.warning("Stream cerrado durante send - ignorando silenciosamente")
        return
    except anyio.BrokenResourceError:
        logger.warning("Stream roto durante send - ignorando silenciosamente")
        return

def patched_send_nowait(self, item):
    """Send_nowait con manejo de ClosedResourceError"""
    try:
        return original_send_nowait(self, item)
    except anyio.ClosedResourceError:
        logger.info("Stream cerrado durante send_nowait - cliente desconectado: ClosedResourceError")
        # Re-lanzar el error para que el código upstream pueda manejarlo apropiadamente
        raise
    except anyio.BrokenResourceError:
        logger.info("Stream roto durante send_nowait - cliente desconectado: BrokenResourceError")
        # Re-lanzar el error para que el código upstream pueda manejarlo apropiadamente
        raise

# Aplicar monkey patch
anyio.streams.memory.MemoryObjectSendStream.send = patched_send
anyio.streams.memory.MemoryObjectSendStream.send_nowait = patched_send_nowait

# Context manager para manejo de errores SSE (mantenido para compatibilidad)
@asynccontextmanager
async def handle_sse_errors():
    """Context manager para manejar errores SSE de forma graceful"""
    try:
        yield
    except anyio.ClosedResourceError:
        logger.warning("Cliente SSE desconectado inesperadamente - manejando gracefully")
        # No re-lanzar el error, simplemente loggearlo
    except anyio.BrokenResourceError:
        logger.warning("Recurso SSE roto - cliente desconectado")
        # No re-lanzar el error
    except Exception as e:
        logger.error(f"Error inesperado en SSE: {e}")
        # Re-lanzar otros errores para que sean manejados por FastMCP
        raise

def get_db_connection():
    """Obtiene una conexión a la base de datos con manejo de errores mejorado"""
    try:
        logger.info("Intentando conectar a la base de datos")
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST"),
            port=int(os.environ.get("DB_PORT", 5432)),
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD"),
            database=os.environ.get("DB_DATABASE"),
            cursor_factory=RealDictCursor
        )
        logger.info("Conexión a la base de datos establecida exitosamente")
        return conn
    except psycopg2.Error as e:
        logger.error(f"Error de PostgreSQL al conectar: {e}")
        raise
    except Exception as e:
        logger.error(f"Error inesperado al conectar a la base de datos: {e}")
        raise

@mcp.tool
async def list_employees(limit: int = 5) -> List[Dict[str, Any]]:
    """Listar los empleados con validaciones y logging mejorado"""
    async with handle_sse_errors():
        logger.info(f"Solicitando lista de empleados con límite: {limit}")
        
        # Validaciones de entrada
        if limit <= 0:
            error_msg = "El límite debe ser mayor a 0"
            logger.warning(f"Validación fallida: {error_msg}")
            return {"error": error_msg}
        
        if limit > 100:
            error_msg = "El límite no puede ser mayor a 100"
            logger.warning(f"Validación fallida: {error_msg}")
            return {"error": error_msg}
        
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, name, position, department, salary, hire_date
                FROM employees 
                ORDER BY id 
                LIMIT %s
                """,
                (limit,)
            )

            rows = cursor.fetchall()
            employees = []

            for row in rows:
                employees.append({
                    "id": row['id'],
                    "name": row['name'],
                    "position": row['position'],
                    "department": row['department'],
                    "salary": float(row['salary']),
                    "hire_date": str(row['hire_date'])
                })

            logger.info(f"Se obtuvieron {len(employees)} empleados exitosamente")
            return employees

        except psycopg2.Error as e:
            error_msg = f"Error de base de datos al obtener empleados: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"Error inesperado al obtener empleados: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg}
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
            logger.debug("Recursos de base de datos liberados")

@mcp.tool
async def add_employee(
    name: str,
    position: str,
    department: str,
    salary: float,
    hire_date: Optional[str] = None
):
    """Agrega un nuevo empleado con validaciones robustas y logging detallado"""
    async with handle_sse_errors():
        logger.info(f"Solicitando agregar empleado: {name} - {position}")
        
        # Validaciones de entrada mejoradas
        if not name or not name.strip():
            error_msg = "El nombre es requerido y no puede estar vacío"
            logger.warning(f"Validación fallida: {error_msg}")
            return {"error": error_msg}
        
        if not position or not position.strip():
            error_msg = "La posición es requerida y no puede estar vacía"
            logger.warning(f"Validación fallida: {error_msg}")
            return {"error": error_msg}
        
        if not department or not department.strip():
            error_msg = "El departamento es requerido y no puede estar vacío"
            logger.warning(f"Validación fallida: {error_msg}")
            return {"error": error_msg}
        
        if salary <= 0:
            error_msg = "El salario debe ser mayor a 0"
            logger.warning(f"Validación fallida: {error_msg}")
            return {"error": error_msg}
        
        if salary > 1000000:
            error_msg = "El salario no puede ser mayor a 1,000,000"
            logger.warning(f"Validación fallida: {error_msg}")
            return {"error": error_msg}

        # Validar formato de fecha si se proporciona
        if hire_date:
            try:
                datetime.strptime(hire_date, '%Y-%m-%d')
            except ValueError:
                error_msg = "El formato de fecha debe ser YYYY-MM-DD"
                logger.warning(f"Validación fallida: {error_msg}")
                return {"error": error_msg}
        else:
            hire_date = datetime.now().strftime('%Y-%m-%d')
            logger.info(f"Usando fecha actual como fecha de contratación: {hire_date}")
        
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Limpiar datos de entrada
            clean_name = name.strip()
            clean_position = position.strip()
            clean_department = department.strip()
            
            cursor.execute(
                """
                INSERT INTO employees (name, position, department, salary, hire_date)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, position, department, salary, hire_date
                """,
                (clean_name, clean_position, clean_department, salary, hire_date)
            )
            
            new_employee = cursor.fetchone()
            conn.commit()
            
            result = {
                "success": True,
                "employee": {
                    "id": new_employee['id'],
                    "name": new_employee['name'],
                    "position": new_employee['position'],
                    "department": new_employee['department'],
                    "salary": float(new_employee['salary']),
                    "hire_date": str(new_employee['hire_date'])
                }
            }
            
            logger.info(f"Empleado agregado exitosamente con ID: {new_employee['id']}")
            return result
            
        except psycopg2.IntegrityError as e:
            error_msg = f"Error de integridad en la base de datos: {str(e)}"
            logger.error(error_msg)
            if conn:
                conn.rollback()
            return {"error": error_msg}
        except psycopg2.Error as e:
            error_msg = f"Error de base de datos al agregar empleado: {str(e)}"
            logger.error(error_msg)
            if conn:
                conn.rollback()
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"Error inesperado al agregar empleado: {str(e)}"
            logger.error(error_msg)
            if conn:
                conn.rollback()
            return {"error": error_msg}
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
            logger.debug("Recursos de base de datos liberados")

# --------------------- Herramientas avanzadas de base de datos ---------------------
SAFE_INDEX_METHODS = {"btree", "hash", "gist", "gin", "brin", "spgist"}

@mcp.tool
async def create_index(
    table_name: str,
    columns: List[str],
    method: Optional[str] = "btree",
    index_name: Optional[str] = None,
    unique: bool = False,
    concurrently: bool = False,
    include: Optional[List[str]] = None
):
    """Crea un índice en la tabla indicada.
    Limitaciones de seguridad: se permite definir método, columnas e INCLUDE.
    """
    async with handle_sse_errors():
        # Validaciones
        if not table_name or not columns:
            return {"error": "table_name y columns son obligatorios"}
        if method and method.lower() not in SAFE_INDEX_METHODS:
            return {"error": f"Método de índice no permitido: {method}"}
        if include and not isinstance(include, list):
            return {"error": "include debe ser una lista de columnas"}

        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            method_sql = sql.SQL(" USING {} ").format(sql.SQL(method.lower())) if method else sql.SQL("")
            idx_name_sql = sql.Identifier(index_name) if index_name else sql.Identifier(f"idx_{table_name}_" + "_".join(columns))
            unique_sql = sql.SQL("UNIQUE ") if unique else sql.SQL("")
            concurrently_sql = sql.SQL(" CONCURRENTLY ") if concurrently else sql.SQL("")

            cols_sql = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
            include_sql = sql.SQL(" INCLUDE (" + ", ".join(["{}" for _ in (include or [])]) + ")") if include else sql.SQL("")
            if include:
                include_sql = sql.SQL(" INCLUDE (") + sql.SQL(", ").join(sql.Identifier(c) for c in include) + sql.SQL(")")

            stmt = sql.SQL("CREATE {unique} INDEX{concurrently} {idx_name} ON {table}{method} ( {cols} ){include}")\
                .format(
                    unique=unique_sql,
                    concurrently=concurrently_sql,
                    idx_name=idx_name_sql,
                    table=sql.Identifier(table_name),
                    method=method_sql,
                    cols=cols_sql,
                    include=include_sql,
                )

            cur.execute(stmt)
            conn.commit()
            return {"success": True, "index": sql.SQL("{}").format(idx_name_sql).as_string(cur)}
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            return {"error": f"PostgreSQL: {e}"}
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

@mcp.tool
async def drop_index(index_name: str, concurrently: bool = False, if_exists: bool = True, cascade: bool = False):
    """Elimina un índice por nombre."""
    async with handle_sse_errors():
        if not index_name:
            return {"error": "index_name es obligatorio"}
        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            concurrently_sql = sql.SQL(" CONCURRENTLY ") if concurrently else sql.SQL("")
            if_exists_sql = sql.SQL(" IF EXISTS ") if if_exists else sql.SQL(" ")
            cascade_sql = sql.SQL(" CASCADE") if cascade else sql.SQL("")
            stmt = sql.SQL("DROP INDEX{concurrently}{ifexists} {idx}{cascade}")\
                .format(
                    concurrently=concurrently_sql,
                    ifexists=if_exists_sql,
                    idx=sql.Identifier(index_name),
                    cascade=cascade_sql
                )
            cur.execute(stmt)
            conn.commit()
            return {"success": True}
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            return {"error": f"PostgreSQL: {e}"}
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

@mcp.tool
async def create_view(view_name: str, select_sql: str, materialized: bool = False, replace: bool = False):
    """Crea una vista (o materialized) a partir de un SELECT.
    Por seguridad, solo se permite SELECT sin punto y coma.
    """
    async with handle_sse_errors():
        if not view_name or not select_sql:
            return {"error": "view_name y select_sql son obligatorios"}
        sel = select_sql.strip()
        if ";" in sel:
            return {"error": "No se permiten múltiples sentencias en select_sql"}
        if not sel.lower().startswith("select"):
            return {"error": "select_sql debe comenzar con SELECT"}

        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            kind_sql = sql.SQL(" MATERIALIZED") if materialized else sql.SQL("")
            replace_sql = sql.SQL(" OR REPLACE") if (replace and not materialized) else sql.SQL("")
            # Nota: OR REPLACE no aplica a materialized views
            stmt = sql.SQL("CREATE{replace}{kind} VIEW {vname} AS ")\
                .format(replace=replace_sql, kind=kind_sql, vname=sql.Identifier(view_name)) + sql.SQL(sel)
            cur.execute(stmt)
            conn.commit()
            return {"success": True}
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            return {"error": f"PostgreSQL: {e}"}
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

@mcp.tool
async def drop_view(view_name: str, materialized: bool = False, if_exists: bool = True, cascade: bool = False):
    """Elimina una vista o materialized view."""
    async with handle_sse_errors():
        if not view_name:
            return {"error": "view_name es obligatorio"}
        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            kind_sql = sql.SQL(" MATERIALIZED") if materialized else sql.SQL("")
            if_exists_sql = sql.SQL(" IF EXISTS ") if if_exists else sql.SQL(" ")
            cascade_sql = sql.SQL(" CASCADE") if cascade else sql.SQL("")
            stmt = sql.SQL("DROP{kind} VIEW{ifexists} {vname}{cascade}")\
                .format(kind=kind_sql, ifexists=if_exists_sql, vname=sql.Identifier(view_name), cascade=cascade_sql)
            cur.execute(stmt)
            conn.commit()
            return {"success": True}
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            return {"error": f"PostgreSQL: {e}"}
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

@mcp.tool
async def refresh_materialized_view(view_name: str, concurrently: bool = False):
    """Refresca una materialized view."""
    async with handle_sse_errors():
        if not view_name:
            return {"error": "view_name es obligatorio"}
        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            concurrently_sql = sql.SQL(" CONCURRENTLY ") if concurrently else sql.SQL("")
            stmt = sql.SQL("REFRESH MATERIALIZED VIEW{concurrently} {vname}")\
                .format(concurrently=concurrently_sql, vname=sql.Identifier(view_name))
            cur.execute(stmt)
            conn.commit()
            return {"success": True}
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            return {"error": f"PostgreSQL: {e}"}
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

@mcp.tool
async def explain_query(sql_text: str, analyze: bool = False, verbose: bool = False, buffers: bool = False) -> List[str]:
    """Ejecuta EXPLAIN (opcional ANALYZE/VERBOSE/BUFFERS) sobre una consulta SELECT."""
    async with handle_sse_errors():
        if not sql_text:
            return {"error": "sql_text es obligatorio"}
        sel = sql_text.strip()
        if ";" in sel:
            return {"error": "No se permiten múltiples sentencias"}
        if not sel.lower().startswith("select"):
            return {"error": "Solo se permite EXPLAIN sobre SELECT"}

        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            parts = ["EXPLAIN"]
            if analyze:
                parts.append("ANALYZE")
            if verbose:
                parts.append("VERBOSE")
            if buffers:
                parts.append("BUFFERS")
            explain_prefix = " ".join(parts) + " "
            cur.execute(explain_prefix + sel)
            rows = cur.fetchall()
            # En psycopg2, EXPLAIN retorna una columna 'QUERY PLAN'
            plan_lines = [r.get('QUERY PLAN') or next(iter(r.values())) for r in rows]
            return plan_lines
        except psycopg2.Error as e:
            return {"error": f"PostgreSQL: {e}"}
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

# Exponer la aplicación ASGI de FastMCP con transporte SSE
asgi_app = mcp.http_app(transport="sse")
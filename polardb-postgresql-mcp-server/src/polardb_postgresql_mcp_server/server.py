from starlette.applications import Starlette
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.routing import Mount, Route
from mcp.server import Server
import uvicorn
import logging
import os
import psycopg
from psycopg import OperationalError as Error
from mcp.types import Resource, ResourceTemplate, Tool, TextContent
from pydantic import AnyUrl
from dotenv import load_dotenv
import asyncio
import re
import sqlparse
from psycopg import sql as psycopg_sql

_IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*$')


def _validate_identifier(name, kind="identifier"):
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid {kind}: {name!r}")
    return name


_RESTRICTED_KEYWORDS = {
    "INSERT": "INSERT",
    "COPY": "INSERT",
    "DELETE": "DELETE",
    "UPDATE": "UPDATE",
    "CREATE": "DDL",
    "ALTER": "DDL",
    "DROP": "DDL",
    "TRUNCATE": "DDL",
    "GRANT": "DDL",
    "REVOKE": "DDL",
    "REINDEX": "DDL",
    "VACUUM": "DDL",
    "CLUSTER": "DDL",
    "REFRESH": "DDL",
    "DO": "DDL",
    "CALL": "DDL",
    "EXECUTE": "DDL",
    "LOAD": "DDL",
    "SECURITY": "DDL",
}


_DOLLAR_TAG_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def _strip_dollar_quotes(sql_text):
    """Replace $tag$...$tag$ bodies with bare whitespace-padded contents so
    embedded statements inside DO/CREATE FUNCTION blocks are visible to the
    keyword scanner. PostgreSQL dollar-quote tags must match exactly to close.
    """
    out = []
    i = 0
    n = len(sql_text)
    while i < n:
        m = _DOLLAR_TAG_RE.match(sql_text, i)
        if not m:
            out.append(sql_text[i])
            i += 1
            continue
        tag = m.group(0)
        end = sql_text.find(tag, m.end())
        if end == -1:
            # unterminated dollar quote; keep remainder as-is to be conservative
            out.append(sql_text[m.end():])
            break
        out.append(" ")
        out.append(sql_text[m.end():end])
        out.append(" ")
        i = end + len(tag)
    return "".join(out)


def get_sql_operations(sql_text):
    """Return (set of restricted ops anywhere in sql, non-empty statement count)."""
    normalized = _strip_dollar_quotes(sql_text)
    parsed = sqlparse.parse(normalized)
    statement_count = sum(
        1 for s in parsed if s.token_first(skip_ws=True, skip_cm=True) is not None
    )
    operations = set()
    for stmt in parsed:
        for token in stmt.flatten():
            if token.ttype is None:
                continue
            ttype_str = str(token.ttype)
            if "Keyword" not in ttype_str:
                continue
            kw = token.value.upper()
            if kw in _RESTRICTED_KEYWORDS:
                operations.add(_RESTRICTED_KEYWORDS[kw])
    return operations, statement_count


enable_delete = False
enable_update = False
enable_insert = False
enable_ddl = False
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger("polardb-postgresql-mcp-server")
VERSION = "0.0.1"
def get_db_config():
    """Get database configuration from environment variables."""
    statement_timeout_s = int(os.getenv("POLARDB_POSTGRESQL_STATEMENT_TIMEOUT", "60"))
    config = {
        "host": os.getenv("POLARDB_POSTGRESQL_HOST", "localhost"),
        "port": int(os.getenv("POLARDB_POSTGRESQL_PORT", "5432")),
        "user": os.getenv("POLARDB_POSTGRESQL_USER"),
        "password": os.getenv("POLARDB_POSTGRESQL_PASSWORD"),
        "dbname": os.getenv("POLARDB_POSTGRESQL_DBNAME"),
        "application_name": f"polardb-postgresql-mcp-server-{VERSION}",
        "options": f"-c statement_timeout={statement_timeout_s * 1000}",
    }
    
    if not all([config["user"], config["password"], config["dbname"]]):
        logger.error("Missing required database configuration. Please check environment variables:")
        logger.error("POLARDB_POSTGRESQL_USER, POLARDB_POSTGRESQL_PASSWORD, and POLARDB_POSTGRESQL_DBNAME are required")
        raise ValueError("Missing required database configuration")
    
    return config

# Initialize server
app = Server("polardb-postgresql-mcp-server")
@app.list_resources()
async def list_resources() -> list[Resource]:
    try:
        return [
            Resource(
                uri=f"polardb-postgresql://schemas",
                name="get_schemas",
                description=" List all schemas for PolarDB PostgreSQL schemas in the current database",
                mimeType="text/plain"
            )
        ]
    except Exception as e:
        logger.error(f"Error listing resources: {str(e)}")
        raise

@app.list_resource_templates()
async def list_resource_templates() -> list[ResourceTemplate]:
    return [
        ResourceTemplate(
            uriTemplate=f"polardb-postgresql://{{schema}}/tables",  
            name="list_tables",
            description="List all tables in a specific schema",
            mimeType="text/plain"
        ),
        ResourceTemplate(
            uriTemplate=f"polardb-postgresql://{{schema}}/{{table}}/field",  
            name="table_field_info",
            description="get the name,type and comment of the field in the table",
            mimeType="text/plain"
        ),
        ResourceTemplate(
            uriTemplate=f"polardb-postgresql://{{schema}}/{{table}}/data", 
            name="table_data",
            description="get data from the table,default limit 50 rows",
            mimeType="text/plain"
        )
    ]


@app.read_resource()
async def read_resource(uri: AnyUrl) -> str:
    config = get_db_config()
    uri_str = str(uri)
    logger.info(f"Reading resource: {uri_str}")
    prefix = "polardb-postgresql://"
    if not uri_str.startswith(prefix):
        logger.error(f"Invalid URI scheme: {uri_str}")
        raise ValueError(f"Invalid URI scheme: {uri_str}")
    try:
        with psycopg.connect(**config) as conn:
            conn.autocommit = True
            with conn.cursor() as cursor: 
                parts = uri_str[len(prefix):].split('/')
                if len(parts) == 1 and parts[0] == "schemas": 
                    #polardb-postgresql://schemas,list all schemas
                    query = """
                            SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN 
                            ('cron','information_schema', 'pg_bitmapindex','pg_catalog','pg_toast','polar_catalog','polar_feature_utils')
                            ORDER BY schema_name;
                        """
                    cursor.execute(query)
                    rows = cursor.fetchall()
                    return "\n".join([row[0] for row in rows])
                elif len(parts) == 2 and parts[1] == "tables":
                    #polardb-postgresql://{schema}/tables,list all tables in a schema
                    query = """
                   SELECT 
                        c.relname AS table_name,              
                        obj_description(c.oid) AS table_comment 
                    FROM 
                        pg_class c
                    JOIN 
                        pg_namespace n ON n.oid = c.relnamespace
                    WHERE 
                        c.relkind = 'r'
                        AND n.nspname = %s
                    ORDER BY 
                        c.relname;
                    """
                    cursor.execute(query, (parts[0],))
                    rows = cursor.fetchall()
                    return "\n".join([f"{row[0]} ({row[1]})" for row in rows])
                elif len(parts) == 3 and parts[2] == "field":
                    # polardb-postgresql://{schema}/{table}/field,list all field info(name,type,comment) in a table
                    schema = _validate_identifier(parts[0], "schema")
                    table = _validate_identifier(parts[1], "table")
                    query = """
                    SELECT a.attname AS column_name,              
                        pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type, 
                        col_description(a.attrelid, a.attnum) AS column_comment 
                    FROM 
                        pg_catalog.pg_attribute a
                    WHERE 
                        a.attnum > 0                            
                        AND NOT a.attisdropped                  
                        AND a.attrelid = %s::regclass 
                    ORDER BY 
                        a.attnum;   
                    """
                    cursor.execute(query, (f"{schema}.{table}",))
                    rows = cursor.fetchall()
                    result = [",".join(map(str, row)) for row in rows]
                    return "\n".join(result)
                elif len(parts) == 3 and parts[2] == "data":
                    # polardb-postgresql://{schema}/{table}/data,list all data in a table
                    schema = _validate_identifier(parts[0], "schema")
                    table = _validate_identifier(parts[1], "table")
                    query = psycopg_sql.SQL("SELECT * FROM {}.{} LIMIT 50").format(
                        psycopg_sql.Identifier(schema),
                        psycopg_sql.Identifier(table),
                    )
                    cursor.execute(query)
                    rows = cursor.fetchall()
                    result = [",".join(map(str, row)) for row in rows]
                    return "\n".join(result)
                else:
                    raise ValueError(f"Invalid URI: {uri_str}")
    except Error as e:
        logger.error(f"Database error: {str(e)}")
        raise RuntimeError(f"Database error: {str(e)}")
@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available PolarDB PostgreSQL tools."""
    logger.info("Listing tools...")
    return [
        Tool(
            name="execute_sql",
            description="Execute an SQL query on the PolarDB PostgreSQL server",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The SQL query to execute"
                    }
                },
                "required": ["query"]
            }
        )
    ]


def get_sql_operation_type(sql):
    """Deprecated; retained for backwards compatibility with external callers."""
    operations, _ = get_sql_operations(sql)
    for op in ('INSERT', 'DELETE', 'UPDATE', 'DDL'):
        if op in operations:
            return op
    return 'OTHER'
def execute_sql(arguments: str) -> str:
    config = get_db_config()
    query = arguments.get("query")
    if not query:
        raise ValueError("Query is required")
    operations, statement_count = get_sql_operations(query)
    logger.info(f"SQL operations: {operations}, statements: {statement_count}")
    if statement_count > 1:
        logger.info("multi-statement queries are not allowed")
        return [TextContent(type="text", text="Multi-statement queries are not allowed")]
    global enable_delete,enable_update,enable_insert,enable_ddl
    if 'INSERT' in operations and not enable_insert:
        logger.info(f"INSERT operation is not enabled,please check POLARDB_POSTGRESQL_ENABLE_INSERT")
        return [TextContent(type="text", text=f"INSERT operation is not enabled in current tool")]
    if 'UPDATE' in operations and not enable_update:
        logger.info(f"UPDATE operation is not enabled,please check POLARDB_POSTGRESQL_ENABLE_UPDATE")
        return [TextContent(type="text", text=f"UPDATE operation is not enabled in current tool")]
    if 'DELETE' in operations and not enable_delete:
        logger.info(f"DELETE operation is not enabled,please check POLARDB_POSTGRESQL_ENABLE_DELETE")
        return [TextContent(type="text", text=f"DELETE operation is not enabled in current tool")]
    if 'DDL' in operations and not enable_ddl:
        logger.info(f"DDL operation is not enabled,please check POLARDB_POSTGRESQL_ENABLE_DDL")
        return [TextContent(type="text", text=f"DDL operation is not enabled in current tool")]
    logger.info(f"will Executing SQL: {query}")
    try:
        with psycopg.connect(**config) as conn:
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute(query)
                if cursor.description is not None:
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    result = [",".join(map(str, row)) for row in rows]
                    return [TextContent(type="text", text="\n".join([",".join(columns)] + result))]
                else:
                    conn.commit()
                    return [TextContent(type="text", text=f"Query executed successfully")]
    except Error as e:
        logger.error(f"Error executing SQL '{query}': {e}")
        return [TextContent(type="text", text=f"Error executing query: {str(e)}")]
@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info(f"Calling tool: {name} with arguments: {arguments}")
    if name == "execute_sql":
        return await asyncio.to_thread(execute_sql, arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")
   



def create_starlette_app(app: Server, *, debug: bool = False) -> Starlette:
    """Create a Starlette application that can server the provied mcp server with SSE."""
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
                request.scope,
                request.receive,
                request._send,  # noqa: SLF001
        ) as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )

    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )


def sse_main(bind_host: str="127.0.0.1", bind_port: int = 8082):
    # Bind SSE request handling to MCP server
    starlette_app = create_starlette_app(app, debug=True)
    logger.info(f"Starting MCP SSE server on {bind_host}:{bind_port}/sse")
    uvicorn.run(starlette_app, host=bind_host, port=bind_port)

async def stdio_main():
    """Main entry point to run the MCP server."""
    from mcp.server.stdio import stdio_server
    
    logger.info("Starting PolarDB PostgreSQL MCP server with stdio mode...")
    config = get_db_config()
    logger.info(f"Database config: {config['host']}/{config['dbname']} as {config['user']}")
    
    async with stdio_server() as (read_stream, write_stream):
        try:
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
        except Exception as e:
            logger.error(f"Server error: {str(e)}", exc_info=True)
            raise

def get_bool_env(var_name: str, default: bool = False) -> bool:
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.lower() in ['true', '1', 't', 'y', 'yes']

def main():
    load_dotenv()
    global enable_delete,enable_update,enable_insert,enable_ddl
    enable_delete = get_bool_env("POLARDB_POSTGRESQL_ENABLE_DELETE")
    enable_update = get_bool_env("POLARDB_POSTGRESQL_ENABLE_UPDATE")
    enable_insert = get_bool_env("POLARDB_POSTGRESQL_ENABLE_INSERT")
    enable_ddl = get_bool_env("POLARDB_POSTGRESQL_ENABLE_DDL")
    logger.info(f"enable_delete: {enable_delete}, enable_update: {enable_update}, enable_insert: {enable_insert}, enable_ddl: {enable_ddl}")
    if os.getenv("RUN_MODE")=="stdio":
        asyncio.run(stdio_main())
    else:
        bind_host = os.getenv("SSE_BIND_HOST")
        bind_port = int(os.getenv("SSE_BIND_PORT"))
        sse_main(bind_host,bind_port)

if __name__ == "__main__":
    main()

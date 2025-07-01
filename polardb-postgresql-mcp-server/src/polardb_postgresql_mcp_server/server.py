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
import sqlparse
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
    config = {
        "host": os.getenv("POLARDB_POSTGRESQL_HOST", "localhost"),
        "port": int(os.getenv("POLARDB_POSTGRESQL_PORT", "5432")),
        "user": os.getenv("POLARDB_POSTGRESQL_USER"),
        "password": os.getenv("POLARDB_POSTGRESQL_PASSWORD"),
        "dbname": os.getenv("POLARDB_POSTGRESQL_DBNAME"),
        "application_name": f"polardb-postgresql-mcp-server-{VERSION}"
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
                    query = f"""
                   SELECT 
                        c.relname AS table_name,              
                        obj_description(c.oid) AS table_comment 
                    FROM 
                        pg_class c
                    JOIN 
                        pg_namespace n ON n.oid = c.relnamespace
                    WHERE 
                        c.relkind = 'r'
                        AND n.nspname = '{parts[0]}'               
                    ORDER BY 
                        c.relname;
                    """
                    cursor.execute(query)
                    rows = cursor.fetchall()
                    return "\n".join([f"{row[0]} ({row[1]})" for row in rows])
                elif len(parts) == 3 and parts[2] == "field":
                    # polardb-postgresql://{schema}/{table}/field,list all field info(name,type,comment) in a table
                    schema = parts[0]
                    table = parts[1]
                    query = f"""
                    SELECT a.attname AS column_name,              
                        pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type, 
                        col_description(a.attrelid, a.attnum) AS column_comment 
                    FROM 
                        pg_catalog.pg_attribute a
                    WHERE 
                        a.attnum > 0                            
                        AND NOT a.attisdropped                  
                        AND a.attrelid = '{schema}.{table}'::regclass 
                    ORDER BY 
                        a.attnum;   
                    """
                    cursor.execute(query)
                    rows = cursor.fetchall()
                    result = [",".join(map(str, row)) for row in rows]
                    return "\n".join(result)
                elif len(parts) == 3 and parts[2] == "data":
                    # polardb-postgresql://{schema}/{table}/data,list all data in a table
                    schema = parts[0]
                    table = parts[1]
                    query = f"SELECT * FROM {schema}.{table} LIMIT 50"
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
    """
    get sql operation type
    :param sql: input sql
    :return: return sql operation type ('INSERT', 'DELETE', 'UPDATE', 'DDL',  or 'OTHER')
    """
    parsed = sqlparse.parse(sql)
    if not parsed:
        return 'OTHER'  #parse sql failed

    # get first statement
    statement = parsed[0]
    
    # get first keyword
    first_token = statement.token_first(skip_ws=True, skip_cm=True)
    if not first_token:
        return 'OTHER'

    keyword = first_token.value.upper()  # convert to upper case for uniform comparison

    # judge sql type
    if keyword == 'INSERT':
        return 'INSERT'
    elif keyword == 'DELETE':
        return 'DELETE'
    elif keyword == 'UPDATE':
        return 'UPDATE'
    elif keyword in ('CREATE', 'ALTER', 'DROP', 'TRUNCATE'):
        return 'DDL'
    else:
        return 'OTHER'
def execute_sql(arguments: str) -> str:
    config = get_db_config()
    query = arguments.get("query")
    if not query:
        raise ValueError("Query is required")
    operation_type = get_sql_operation_type(query)
    logger.info(f"SQL operation type: {operation_type}")
    global enable_delete,enable_update,enable_insert,enable_ddl
    if operation_type == 'INSERT' and not enable_insert:
        logger.info(f"INSERT operation is not enabled,please check POLARDB_POSTGRESQL_ENABLE_INSERT")
        return [TextContent(type="text", text=f"INSERT operation is not enabled in current tool")]
    elif operation_type == 'UPDATE' and not enable_update:
        logger.info(f"UPDATE operation is not enabled,please check POLARDB_POSTGRESQL_ENABLE_UPDATE")
        return [TextContent(type="text", text=f"UPDATE operation is not enabled in current tool")]
    elif operation_type == 'DELETE' and not enable_delete:
        logger.info(f"DELETE operation is not enabled,please check POLARDB_POSTGRESQL_ENABLE_DELETE")
        return [TextContent(type="text", text=f"DELETE operation is not enabled in current tool")]
    elif operation_type == 'DDL' and not enable_ddl:
        logger.info(f"DDL operation is not enabled,please check POLARDB_POSTGRESQL_ENABLE_DDL")
        return [TextContent(type="text", text=f"DDL operation is not enabled in current tool")] 
    else:   
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
        return execute_sql(arguments)
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

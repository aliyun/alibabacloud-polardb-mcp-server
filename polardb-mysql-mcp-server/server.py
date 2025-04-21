from starlette.applications import Starlette
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.routing import Mount, Route
from mcp.server import Server
import uvicorn
import logging
import os
from mysql.connector import connect, Error
from mcp.types import Resource, Tool, TextContent
from pydantic import AnyUrl
from dotenv import load_dotenv
import asyncio
import sqlparse
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger("polardb-mysql-mcp-server")

def get_db_config():
    """Get database configuration from environment variables."""
    config = {
        "host": os.getenv("POLARDB_MYSQL_HOST", "localhost"),
        "port": int(os.getenv("POLARDB_MYSQL_PORT", "3306")),
        "user": os.getenv("POLARDB_MYSQL_USER"),
        "password": os.getenv("POLARDB_MYSQL_PASSWORD"),
        "database": os.getenv("POLARDB_MYSQL_DATABASE")
    }
    
    if not all([config["user"], config["password"], config["database"]]):
        logger.error("Missing required database configuration. Please check environment variables:")
        logger.error("POLARDB_MYSQL_USER, POLARDB_MYSQL_PASSWORD, and POLARDB_MYSQL_DATABASE are required")
        raise ValueError("Missing required database configuration")
    
    return config

# Initialize server
app = Server("polardb-mysql-mcp-server")

@app.list_resources()
async def list_resources() -> list[Resource]:
    """List PolarDB MySQL tables as resources."""
    logger.info("Listing resources...!")
    config = get_db_config()
    try:
        with connect(**config) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SHOW TABLES")
                tables = cursor.fetchall()
                logger.info(f"Found tables: {tables} in current database: {config['database']}")
                resources = []
                for table in tables:
                    resources.append(
                        Resource(
                            uri=f"polardb-mysql://{config['database']}/{table[0]}/data",
                            name=f"content for table({table[0]})",
                            mimeType="text/plain",
                            description=f"data in table ({table[0]})"
                        )
                    )
                    resources.append(Resource(
                            uri=f"polardb-mysql://{config['database']}/{table[0]}/schema",
                            name=f"schema for table({table[0]})",
                            mimeType="text/plain",
                            description=f"field information for table ({table[0]})"
                        )
                    )
                logger.info(f"Found {len(resources)} resources: {resources}")
                return resources
    except Error as e:
        logger.error(f"Failed to list resources: {str(e)}")
        return []

@app.read_resource()
async def read_resource(uri: AnyUrl) -> str:
    """Read table contents and schema"""
    config = get_db_config()
    uri_str = str(uri)
    logger.info(f"Reading resource: {uri_str}")
    prefix = "polardb-mysql://" + config['database'] + "/"
    if not uri_str.startswith(prefix):
        raise ValueError(f"Invalid URI scheme: {uri_str}")
    parts = uri_str[len(prefix):].split('/')
    table = parts[0]
    resource_type = parts[1]
    try:
        with connect(**config) as conn:
            with conn.cursor() as cursor:
                if resource_type == "data":
                    cursor.execute(f"SELECT * FROM {table} LIMIT 50")
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    result = [",".join(map(str, row)) for row in rows]
                    return "\n".join([",".join(columns)] + result)
                elif resource_type == "schema":
                    cursor.execute(f"SELECT COLUMN_NAME,COLUMN_TYPE,COLUMN_COMMENT FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = '{config['database']}' AND TABLE_NAME = '{table}'")
                    rows = cursor.fetchall()
                    result = [",".join(map(str, row)) for row in rows]
                    return "\n".join(result)
                
    except Error as e:
        logger.error(f"Database error reading resource {uri}: {str(e)}")
        raise RuntimeError(f"Database error: {str(e)}")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available PolarDB MySQL tools."""
    logger.info("Listing tools...")
    return [
        Tool(
            name="execute_sql",
            description="Execute an SQL query on the PolarDB MySQL server",
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
    parsed = sqlparse.parse(sql)
    if not parsed:
        return "UNKNOWN"
    stmt = parsed[0]
    return stmt.get_type().upper()
@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute SQL commands."""
    config = get_db_config()
    logger.info(f"Calling tool: {name} with arguments: {arguments}")
    
    if name != "execute_sql":
        raise ValueError(f"Unknown tool: {name}")
    
    query = arguments.get("query")
    if not query:
        raise ValueError("Query is required")
    operation_type = get_sql_operation_type(query)
    logger.info(f"SQL operation type: {operation_type}")
    try:
        with connect(**config) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                if cursor.description is not None:
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    result = [",".join(map(str, row)) for row in rows]
                    return [TextContent(type="text", text="\n".join([",".join(columns)] + result))]
                else:
                    conn.commit()
                    return [TextContent(type="text", text=f"Query executed successfully. Rows affected: {cursor.rowcount}")]
    except Error as e:
        logger.error(f"Error executing SQL '{query}': {e}")
        return [TextContent(type="text", text=f"Error executing query: {str(e)}")]



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


def sse_main(bind_host: str="127.0.0.1", bind_port: int = 8080):
    # Bind SSE request handling to MCP server
    starlette_app = create_starlette_app(app, debug=True)
    logger.info(f"Starting MCP SSE server on {bind_host}:{bind_port}/sse")
    uvicorn.run(starlette_app, host=bind_host, port=bind_port)

async def stdio_main():
    """Main entry point to run the MCP server."""
    from mcp.server.stdio import stdio_server
    
    logger.info("Starting PolarDB MySQL MCP server with stdio mode...")
    config = get_db_config()
    logger.info(f"Database config: {config['host']}/{config['database']} as {config['user']}")
    
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


if __name__ == "__main__":
    load_dotenv()
    if os.getenv("RUN_MODE")=="stdio":
        asyncio.run(stdio_main())
    else:
        bind_host = os.getenv("SSE_BIND_HOST")
        bind_port = int(os.getenv("SSE_BIND_PORT"))
        sse_main(bind_host,bind_port)

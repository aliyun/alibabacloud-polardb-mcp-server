from starlette.applications import Starlette
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.routing import Mount, Route
from mcp.server import Server
import uvicorn
import logging
import os
from mysql.connector import connect, Error
from mcp.types import Resource, Tool, TextContent, ResourceTemplate
from pydantic import AnyUrl
from dotenv import load_dotenv
import asyncio
import sqlparse
enable_write = False
enable_update = False
enable_insert = False
enable_ddl = False
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
    try:
        return [
            Resource(
                uri=f"polardb-mysql://tables",
                name="get_tables",
                description=" List all tables for PolarDB MySQL in the current database",
                mimeType="text/plain"
            ),
             Resource(
                uri=f"polardb-mysql://models",
                name="get_models",
                description=" List all models for Polar4ai and PolarDB MySQL in the current database",
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
            uriTemplate=f"polardb-mysql://{{table}}/field",  
            name="table_field_info",
            description="get the name,type and comment of the field in the table",
            mimeType="text/plain"
        ),
        ResourceTemplate(
            uriTemplate=f"polardb-mysql://{{table}}/data", 
            name="table_data",
            description="get data from the table,default limit 50 rows",
            mimeType="text/plain"
        )
    ]
@app.read_resource()
async def read_resource(uri: AnyUrl) -> str:
    """Read table contents and schema"""
    config = get_db_config()
    uri_str = str(uri)
    logger.info(f"Reading resource: {uri_str}")
    prefix = "polardb-mysql://"
    if not uri_str.startswith(prefix):
        logger.error(f"Invalid URI: {uri_str}")
        raise ValueError(f"Invalid URI scheme: {uri_str}")
    parts = uri_str[len(prefix):].split('/')
    try:
        with connect(**config) as conn:
            with conn.cursor() as cursor:
                if len(parts) == 1 and parts[0] == "tables":
                    cursor.execute(f"SHOW TABLES")
                    rows = cursor.fetchall()
                    result = [row[0] for row in rows]
                    return "\n".join(result)
                elif len(parts) == 1 and parts[0] == "models":
                    cursor.execute(f"/*polar4ai*/SHOW MODELS;")
                    rows = cursor.fetchall()
                    result = [row[0] for row in rows]
                    return "\n".join(result)
                elif len(parts) == 2 and parts[1] == "data" or parts[1] == 'field':
                    table = parts[0]
                    resource_type = parts[1]
                    if resource_type == "data":
                        cursor.execute(f"SELECT * FROM {table} LIMIT 50")
                        columns = [desc[0] for desc in cursor.description]
                        rows = cursor.fetchall()
                        result = [",".join(map(str, row)) for row in rows]
                        return "\n".join([",".join(columns)] + result)
                    elif resource_type == "field":
                        cursor.execute(f"SELECT COLUMN_NAME,COLUMN_TYPE,COLUMN_COMMENT FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = '{config['database']}' AND TABLE_NAME = '{table}'")
                        rows = cursor.fetchall()
                        result = [",".join(map(str, row)) for row in rows]
                        return "\n".join(result)
                else:
                    logger.error(f"Invalid URI: {uri_str}")
                    raise ValueError(f"Invalid URI: {uri_str}")
                
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
        ),
        Tool(
            name="polar4ai_create_models",
            description="使用polar4ai语法，创建模型，参数只含有以下字段model_name,model_class,x_cols,y_cols,table_name。",
            inputSchema={
                "type": "object",
                "properties": {
                    {
                        "type": "json",
                        "description": "一个json，不要生成其他字段，只含有以下字段model_name,model_class,x_cols,y_cols,table_name。例如{\"model_name\":\"gbdt_test\",\"model_class\":\"gbdt\",\"x_cols\":\"test_feature\",\"y_cols\":\"test_label\",\"table_name\":\"testfile\"}"
                    }
                },
                "required": ["json"]
            }
        )
    ]

def polar4ai_create_models(query_dict: dict) -> list[TextContent]:
    """
    使用polar4ai语法，创建模型
    """
    config = get_db_config()
    config['compress']=True
    logger.info(str(query_dict))
    logger.info(f"Reading polar4ai_create_models")
    try:
        with connect(**config) as conn:
            with conn.cursor() as cursor:
                query_str = "/*polar4ai*/CREATE MODEL "+str(query_dict['model_name'])+" WITH (model_class = \'"+str(query_dict['model_class'])+"\',x_cols = \'"+str(query_dict['x_cols'])+"\',y_cols=\'"+str(query_dict['y_cols'])+"\')AS (SELECT * FROM "+str(query_dict['table_name'])+");"
                cursor.execute(query_str)
                logger.info("create model ok")
                return [TextContent(type="text", text=f"创建{str(query_dict['model_name'])}模型成功")]
                
    except Error as e:
        logger.error(f"Database error polar4ai : {str(e)}")
        return [TextContent(type="text", text=f"创建{str(query_dict['model_name'])}模型失败")]


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
    if operation_type == 'INSERT' and not enable_insert:
        logger.info(f"INSERT operation is not enabled,please check POLARDB_MYSQL_ENABLE_INSERT")
        return [TextContent(type="text", text=f"INSERT operation is not enabled in current tool")]
    elif operation_type == 'UPDATE' and not enable_update:
        logger.info(f"UPDATE operation is not enabled,please check POLARDB_MYSQL_ENABLE_UPDATE")
        return [TextContent(type="text", text=f"UPDATE operation is not enabled in current tool")]
    elif operation_type == 'DELETE' and not enable_write:
        logger.info(f"DELETE operation is not enabled,please check POLARDB_MYSQL_ENABLE_WRITE")
        return [TextContent(type="text", text=f"DELETE operation is not enabled in current tool")]
    elif operation_type == 'DDL' and not enable_ddl:
        logger.info(f"DDL operation is not enabled,please check POLARDB_MYSQL_ENABLE_DDL")
        return [TextContent(type="text", text=f"DDL operation is not enabled in current tool")] 
    else:   
        logger.info(f"will Executing SQL: {query}")
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
@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info(f"Calling tool: {name} with arguments: {arguments}")
    if name == "execute_sql":
        return execute_sql(arguments)
    elif name == "polar4ai_create_models":
        return polar4ai_create_models(arguments)
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

def get_bool_env(var_name: str, default: bool = False) -> bool:
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.lower() in ['true', '1', 't', 'y', 'yes']
def main():
    load_dotenv()
    enable_write = get_bool_env("POLARDB_MYSQL_ENABLE_WRITE")
    enable_update = get_bool_env("POLARDB_MYSQL_ENABLE_UPDATE")
    enable_insert = get_bool_env("POLARDB_MYSQL_ENABLE_INSERT")
    enable_ddl = get_bool_env("POLARDB_MYSQL_ENABLE_DDL")
    logger.info(f"enable_write: {enable_write}, enable_update: {enable_update}, enable_insert: {enable_insert}, enable_ddl: {enable_ddl}")
    if os.getenv("RUN_MODE")=="stdio":
        asyncio.run(stdio_main())
    else:
        bind_host = os.getenv("SSE_BIND_HOST")
        bind_port = int(os.getenv("SSE_BIND_PORT"))
        sse_main(bind_host,bind_port)

if __name__ == "__main__":
    main()
from starlette.applications import Starlette
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.routing import Mount, Route
from mcp.server import Server
import uvicorn
import logging
import os
import sys
from mysql.connector import connect, Error
from mcp.types import Resource, Tool, TextContent, ResourceTemplate
from pydantic import AnyUrl
from dotenv import load_dotenv
from polardb_mysql_mcp_server.doc_import import DocImport
import asyncio
import re
import sqlparse
import numbers

_IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*$')


def _validate_identifier(name, kind="identifier"):
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid {kind}: {name!r}")
    return name


def _quote_identifier(name, kind="identifier"):
    safe = _validate_identifier(name, kind)
    return "`" + safe.replace("`", "``") + "`"


def _validate_identifier_list(value, kind="column"):
    if not isinstance(value, str):
        raise ValueError(f"Invalid {kind} list: {value!r}")
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        raise ValueError(f"Empty {kind} list")
    for p in parts:
        _validate_identifier(p, kind)
    return ",".join(parts)


_ALLOWED_MODEL_CLASSES = {
    "lightgbm", "deepfm", "kmeans", "randomforestreg",
    "gbrt", "gbdt", "linearreg", "svr", "bst",
}


def _escape_sql_string(value):
    if not isinstance(value, str):
        raise ValueError("expected string")
    if "\x00" in value:
        raise ValueError("NUL byte not allowed in SQL string")
    return (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\x1a", "\\Z")
    )


_RESTRICTED_KEYWORDS = {
    "INSERT": "INSERT",
    "REPLACE": "INSERT",
    "LOAD": "INSERT",
    "DELETE": "DELETE",
    "UPDATE": "UPDATE",
    "CREATE": "DDL",
    "ALTER": "DDL",
    "DROP": "DDL",
    "TRUNCATE": "DDL",
    "RENAME": "DDL",
    "GRANT": "DDL",
    "REVOKE": "DDL",
    "CALL": "DDL",
    "HANDLER": "DDL",
}


_MYSQL_EXEC_COMMENT_RE = re.compile(r"/\*!\d*\s?", re.IGNORECASE)


def _strip_mysql_exec_comments(sql):
    """Unwrap MySQL conditional-execution comments like /*!50000 DELETE ... */
    so sqlparse sees the embedded statement body. Returns the rewritten sql.
    """
    out = []
    i = 0
    n = len(sql)
    while i < n:
        m = _MYSQL_EXEC_COMMENT_RE.match(sql, i)
        if not m:
            out.append(sql[i])
            i += 1
            continue
        # find matching */
        end = sql.find("*/", m.end())
        if end == -1:
            # malformed, treat as opaque comment; keep as-is to be safe
            out.append(sql[i:])
            break
        out.append(" ")
        out.append(sql[m.end():end])
        out.append(" ")
        i = end + 2
    return "".join(out)


def get_sql_operations(sql):
    """Return (set of restricted ops anywhere in sql, non-empty statement count)."""
    normalized = _strip_mysql_exec_comments(sql)
    parsed = sqlparse.parse(normalized)
    statement_count = sum(
        1 for s in parsed if s.token_first(skip_ws=True, skip_cm=True) is not None
    )
    operations = set()
    for stmt in parsed:
        for token in stmt.flatten():
            if token.ttype is None:
                continue
            if "Keyword" not in str(token.ttype):
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
logger = logging.getLogger("polardb-mysql-mcp-server")

def get_db_config():
    """Get database configuration from environment variables."""
    config = {
        "host": os.getenv("POLARDB_MYSQL_HOST", "localhost"),
        "port": int(os.getenv("POLARDB_MYSQL_PORT", "3306")),
        "user": os.getenv("POLARDB_MYSQL_USER"),
        "password": os.getenv("POLARDB_MYSQL_PASSWORD"),
        "database": os.getenv("POLARDB_MYSQL_DATABASE"),
        "read_timeout": int(os.getenv("POLARDB_MYSQL_READ_TIMEOUT", "60")),
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
    """Read resource contents"""
    uri_str = str(uri)
    logger.info(f"Reading resource: {uri_str}")

    # Handle polardb-mysql:// URIs for PolarDB API resources
    if uri_str.startswith("polardb-mysql://"):
        prefix = "polardb-mysql://"
        parts = uri_str[len(prefix):].split('/')

        if len(parts) == 1 and parts[0] == "tables":
            config = get_db_config()
            try:
                with connect(**config) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(f"SHOW TABLES")
                        rows = cursor.fetchall()
                        result = [row[0] for row in rows]
                        return "\n".join(result)
            except Error as e:
                logger.error(f"Database error reading tables: {str(e)}")
                raise RuntimeError(f"Database error: {str(e)}")

        elif len(parts) == 1 and parts[0] == "models":
            config = get_db_config()
            try:
                with connect(**config) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(f"/*polar4ai*/SHOW MODELS;")
                        rows = cursor.fetchall()
                        result = [row[0] for row in rows]
                        return "\n".join(result)
            except Error as e:
                logger.error(f"Database error reading models: {str(e)}")
                raise RuntimeError(f"Database error: {str(e)}")

        elif len(parts) == 2 and (parts[1] == "data" or parts[1] == 'field'):
            config = get_db_config()
            table = parts[0]
            try:
                _validate_identifier(table, "table")
            except ValueError as e:
                logger.error(f"Invalid table name in URI: {table!r}")
                raise ValueError(str(e))
            resource_type = parts[1]
            try:
                with connect(**config) as conn:
                    with conn.cursor() as cursor:
                        if resource_type == "data":
                            cursor.execute(f"SELECT * FROM {_quote_identifier(table, 'table')} LIMIT 50")
                            columns = [desc[0] for desc in cursor.description]
                            rows = cursor.fetchall()
                            result = [",".join(map(str, row)) for row in rows]
                            return "\n".join([",".join(columns)] + result)
                        elif resource_type == "field":
                            cursor.execute(
                                "SELECT COLUMN_NAME,COLUMN_TYPE,COLUMN_COMMENT FROM INFORMATION_SCHEMA.COLUMNS "
                                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                                (config['database'], table),
                            )
                            rows = cursor.fetchall()
                            result = [",".join(map(str, row)) for row in rows]
                            return "\n".join(result)
            except Error as e:
                logger.error(f"Database error reading resource: {str(e)}")
                raise RuntimeError(f"Database error: {str(e)}")

        else:
            logger.error(f"Invalid URI: {uri_str}")
            raise ValueError(f"Invalid URI: {uri_str}")

    else:
        logger.error(f"Invalid URI scheme: {uri_str}")
        raise ValueError(f"Invalid URI scheme: {uri_str}")

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
            name="polar4ai_update_index_for_text_2_sql",
            description="""
                        利用polardb的AI节点,为当前数据库的表更新索引,这些索引用于文本转换SQL或者chart(polar4ai_text_2_sql/polar4ai_text_2_chart).
                        一般在更新索引后,如果该数据库没有再执行DDL更改表结构,则无需执行该更新操作,否则需要执行该更新操作.
                        默认如果发现索引表schema_index有数据,且force_update为false,则不执行更新操作,否则会更新索引表schema_index.
                        更新过程需要一定的时间,请耐心等待.
                        """,
            inputSchema={
                "type": "object",
                "properties": {
                    "force_update": {
                        "type": "boolean",
                        "description": "是否强制更新索引,若果schema_index有数据并且该值为false,则不执行更新操作,否则强制更新"
                    }
                },
                "required": ["force_update"]
            }
        ),
        Tool(
            name="polar4ai_text_2_sql",
            description="利用polardb的AI节点,将用户的文本转换成sql语句",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "需要转换的文本"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="polar4ai_text_2_chart",
            description="利用polardb的AI节点,将用户的文本统计需求直接转换成图表",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "需要转换的文本"
                    },
                    "chart_type": {
                        "type": "string",
                        "enum": ["柱状图", "折线图", "饼状图"],
                        "description": "图表类型"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="polar4ai_create_models",
            description="使用polar4ai语法，创建模型，参数只含有以下字段model_name,model_class,x_cols,y_cols,table_name。",
            inputSchema={
                "type": "object",
                "properties": {
                    "model":{
                        "type": "object",
                        "properties": {
                            "model_name": {
                                "type": "string",
                                "description": "模型名称"
                            },
                            "model_class": {
                                "type": "string",
                                "enum": [
                                    "lightgbm", "deepfm", "kmeans", "randomforestreg",
                                    "gbrt", "gbdt", "linearreg", "svr", "bst"
                                ],
                                "description":"""
                                    模型类型算法选择，可选值有：
                                        lightgbm-LightGBM算法,
                                        deepfm-DeepFM算法,
                                        kmeans-K均值聚类算法,
                                        randomforestreg-随机森林回归算法,
                                        gbrt-梯度提升回归树算法,gbdt-决策树算法,
                                        linearreg-线性回归算法,
                                        svr-支持向量回归算法,
                                        bst-BST算法
                                    """
                            },
                            "table_name": {
                                "type": "string",
                                "description":"数据库中输入特征表的表名"
                                },
                            "x_cols": {
                                "type": "string",
                                "description":"数据库中输入特征表的列名，多个列用逗号分隔"
                                },
                            "y_cols": {
                                "type": "string",
                                "description":"数据库中输入特征表的列名，多个列用逗号分隔"
                                }
                        },
                        "required": ["model_name", "model_class", "table_name", "x_cols", "y_cols"]
                    }
                },
                "required": ["model"]
            }
        ),
         Tool(
            name="polar4ai_import_doc",
            description="将本地某个目录下的所有后缀为docx和md文件导入到PolarDB中,生成一个知识库",
            inputSchema={
                "type": "object",
                "properties": {
                    "dir": {
                        "type": "string",
                        "description": "本地目录"
                    },
                    "table_name": {
                        "type": "string",
                        "description": "知识库的名称,为表的名称(默认使用default_knowledge_base)"
                    }
                },
                "required": ["dir"]
            }
        ),
        Tool(
            name="polar4ai_search_doc",
            description="从PolarDB的知识库中搜索相关的知识",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要搜索的内容"
                    },
                    "table_name": {
                        "type": "string",
                        "description": "要查询知识库的名称,为表的名称(默认使用default_knowledge_base)"
                    },
                    "count": {
                        "type": "integer",
                        "description": "返回的知识的条目,默认为5条"
                    }
                },
                "required": ["text"]
            }
        )
    ]

def exec_sql(config, sql):
    rows=[]
    try:
        with connect(**config) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                if cursor.description is not None:
                    return cursor.fetchall(),True
                else:
                    conn.commit()
                    return rows,True
    except Error as e:
        logger.error(f"Error executing SQL '{sql}': {e}")
        return rows, False
def polar4ai_update_index_for_text_2_sql(arguments: str, index_table_name='schema_index'):
    config = get_db_config()
    force_update = arguments.get("force_update")
    if force_update is None:
        raise ValueError("force_update is required for tool polar4ai_update_index_for_text_2_sql")
    _validate_identifier(index_table_name, "index_table_name")
    table_sql = f'/*polar4ai*/show tables;'
    rows, ok = exec_sql(config, table_sql)
    if not ok:
        raise ValueError("Error executing SQL '/*polar4ai*/show tables'")
    index_table_exist = False
    for row in rows:
        if row[0] == index_table_name:
            index_table_exist = True
            break
    logging.info(f"force_update:{force_update},index_table_exist:{index_table_exist}")
    if not index_table_exist:
        create_index_sql = f'/*polar4ai*/CREATE TABLE {index_table_name}(id integer, table_name varchar, table_comment text_ik_max_word, table_ddl text_ik_max_word, column_names text_ik_max_word, column_comments text_ik_max_word, sample_values text_ik_max_word, vecs vector_768, ext text_ik_max_word, PRIMARY KEY (id));'
        rows, ok = exec_sql(config, create_index_sql)
        if not ok:
            raise ValueError("Error executing SQL '/*polar4ai*/CREATE TABLE {index_table_name}'")
    table_count=0
    table_count_sql = f'/*polar4ai*/SELECT COUNT(*) FROM {index_table_name};'
    rows, ok = exec_sql(config, table_count_sql)
    if ok and len(rows) == 1:
        table_count = int(rows[0][0])
    else:
        raise ValueError("Error executing SQL '/*polar4ai*/SELECT COUNT(*) FROM {index_table_name}'")
    if force_update or table_count == 0:
        update_sql=f"/*polar4ai*/SELECT * FROM PREDICT (MODEL _polar4ai_text2vec, SELECT '') WITH (mode='async', resource='schema') INTO {index_table_name};"
        rows, ok = exec_sql(config, update_sql)
        if not ok:
            raise ValueError("Error executing SQL '/*polar4ai*/SELECT * FROM PREDICT (MODEL _polar4ai_text2vec, SELECT xxxx'")
    return [TextContent(type="text", text=f"更新索引表({index_table_name})成功")]


def polar4ai_text_2_sql(arguments: str,index_table_name='schema_index'):
    config = get_db_config()
    text = arguments.get("text")
    if not text:
        raise ValueError("text is required for tool polar4ai_text_2_sql")
    _validate_identifier(index_table_name, "index_table_name")
    safe_text = _escape_sql_string(text)
    sql = f"/*polar4ai*/SELECT * FROM PREDICT (MODEL _polar4ai_nl2sql, SELECT '{safe_text}') WITH (basic_index_name='{index_table_name}')";
    rows, ok = exec_sql(config, sql)
    if ok and len(rows) == 1:
        return [TextContent(type="text", text=f"{rows[0][0]}")]
    else :
        raise ValueError("Error executing SQL '/*polar4ai*/SELECT * FROM PREDICT (MODEL _polar4ai_nl2sql, SELECT xxxx'")
_ALLOWED_CHART_TYPES = {"柱状图", "折线图", "饼状图"}


def polar4ai_text_2_chart(arguments: str,index_table_name='schema_index'):
    config = get_db_config()
    text = arguments.get("text")
    chart_type= arguments.get("chart_type")
    if not text:
        raise ValueError("text is required for tool polar4ai_text_2_chart")
    if not chart_type:
        chart_type='柱状图'
    if chart_type not in _ALLOWED_CHART_TYPES:
        raise ValueError(f"Invalid chart_type: {chart_type!r}")
    _validate_identifier(index_table_name, "index_table_name")
    safe_text = _escape_sql_string(text)
    safe_chart = _escape_sql_string(chart_type)
    sql = f"/*polar4ai*/SELECT * FROM PREDICT (MODEL _polar4ai_nl2sql, SELECT '{safe_text}') WITH (basic_index_name='{index_table_name}')";
    rows, ok = exec_sql(config, sql)
    if ok and len(rows) == 1:
        sql = rows[0][0]
    else:
        ValueError("Error executing SQL '/*polar4ai*/SELECT * FROM PREDICT (MODEL _polar4ai_nl2sql, SELECT xxxx'")
    sql = sql.replace(";","")
    chart_sql = f"/*polar4ai*/SELECT * FROM PREDICT (MODEL _polar4ai_nl2chart,{sql}) WITH (usr_query = '{safe_text},{safe_chart}', result_type = 'IMAGE');"
    rows, ok = exec_sql(config, chart_sql)
    if ok and len(rows) == 1:
        return [TextContent(type="text", text=f"{rows[0][0]}")]
    else:
        raise ValueError("Error executing SQL '/*polar4ai*/SELECT * FROM PREDICT (MODEL _polar4ai_nl2chart, SELECT xxxx'")
def polar4ai_create_models(model: dict) -> list[TextContent]:
    """
    使用polar4ai语法，创建模型
    """
    config = get_db_config()
    #config['compress']=True
    logger.info(str(model))
    logger.info(f"Reading polar4ai_create_models")
    try:
        model_name = _validate_identifier(str(model['model_name']), "model_name")
        table_name = _validate_identifier(str(model['table_name']), "table_name")
        model_class = str(model['model_class'])
        if model_class not in _ALLOWED_MODEL_CLASSES:
            raise ValueError(f"Invalid model_class: {model_class!r}")
        x_cols = _validate_identifier_list(str(model['x_cols']), "x_cols")
        y_cols = _validate_identifier_list(str(model['y_cols']), "y_cols")
    except (KeyError, ValueError) as e:
        logger.error(f"Invalid model arguments: {e}")
        return [TextContent(type="text", text=f"创建模型失败: {e}")]
    try:
        with connect(**config) as conn:
            with conn.cursor() as cursor:
                query_str = (
                    f"/*polar4ai*/CREATE MODEL {model_name} "
                    f"WITH (model_class = '{model_class}',"
                    f"x_cols = '{x_cols}',y_cols='{y_cols}')"
                    f"AS (SELECT * FROM {_quote_identifier(table_name, 'table_name')});"
                )
                cursor.execute(query_str)
                logger.info("create model ok")
                return [TextContent(type="text", text=f"创建{model_name}模型成功")]

    except Error as e:
        logger.error(f"Database error polar4ai : {str(e)}")
        return [TextContent(type="text", text=f"创建模型失败")]


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
        raise ValueError("query is required for tool execute_sql")
    operations, statement_count = get_sql_operations(query)
    logger.info(f"SQL operations: {operations}, statements: {statement_count}")
    if statement_count > 1:
        logger.info("multi-statement queries are not allowed")
        return [TextContent(type="text", text="Multi-statement queries are not allowed")]
    global enable_delete,enable_update,enable_insert,enable_ddl
    if 'INSERT' in operations and not enable_insert:
        logger.info(f"INSERT operation is not enabled,please check POLARDB_MYSQL_ENABLE_INSERT")
        return [TextContent(type="text", text=f"INSERT operation is not enabled in current tool")]
    if 'UPDATE' in operations and not enable_update:
        logger.info(f"UPDATE operation is not enabled,please check POLARDB_MYSQL_ENABLE_UPDATE")
        return [TextContent(type="text", text=f"UPDATE operation is not enabled in current tool")]
    if 'DELETE' in operations and not enable_delete:
        logger.info(f"DELETE operation is not enabled,please check POLARDB_MYSQL_ENABLE_DELETE")
        return [TextContent(type="text", text=f"DELETE operation is not enabled in current tool")]
    if 'DDL' in operations and not enable_ddl:
        logger.info(f"DDL operation is not enabled,please check POLARDB_MYSQL_ENABLE_DDL")
        return [TextContent(type="text", text=f"DDL operation is not enabled in current tool")]
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

def polar4ai_import_doc(arguments: str):
    dir_path = arguments.get("dir")
    if not dir_path:
        logger.error("dir is required")
        raise ValueError("dir is required for tool import_doc")
    table_name = arguments.get("table_name")
    if not table_name:
        table_name =''
    config = get_db_config()
    doc_import = DocImport(config)
    logger.info(f"will import files in {dir_path} to table {table_name}")
    result_text = doc_import.import_doc(dir_path,table_name)
    return [TextContent(type="text", text=f"{result_text}")]
def polar4ai_search_doc(arguments: str):
    text = arguments.get("text")
    if not text:
        logger.error("text is required")
        raise ValueError("text is required for tool search_doc")
    table_name = arguments.get("table_name")
    if not table_name:
        table_name=''
    count = arguments.get("count") or 5
    config = get_db_config()
    doc_import = DocImport(config)
    logger.info(f"will query_knowledge,text={text},count={count},table_name={table_name}")
    result = doc_import.query_knowledge(text, count, table_name)
    return [TextContent(type="text", text=f"{result}")]
@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info(f"Calling tool: {name} with arguments: {arguments}")
    if name == "execute_sql":
        return await asyncio.to_thread(execute_sql, arguments)
    elif name == "polar4ai_update_index_for_text_2_sql":
        return await asyncio.to_thread(polar4ai_update_index_for_text_2_sql, arguments)
    elif name == "polar4ai_text_2_sql":
        return await asyncio.to_thread(polar4ai_text_2_sql, arguments)
    elif name == "polar4ai_text_2_chart":
        return await asyncio.to_thread(polar4ai_text_2_chart, arguments)
    elif name == "polar4ai_create_models":
        query_dict = arguments.get("model")
        if query_dict is None:
            raise ValueError("Missing 'query_dict' in arguments")
        return await asyncio.to_thread(polar4ai_create_models, query_dict)
    elif name == "polar4ai_import_doc":
        return await asyncio.to_thread(polar4ai_import_doc, arguments)
    elif name == "polar4ai_search_doc":
        return await asyncio.to_thread(polar4ai_search_doc, arguments)
    else:
        logger.error(f"Unknown tool: {name}")
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
    global enable_delete,enable_update,enable_insert,enable_ddl
    enable_delete = get_bool_env("POLARDB_MYSQL_ENABLE_DELETE")
    enable_update = get_bool_env("POLARDB_MYSQL_ENABLE_UPDATE")
    enable_insert = get_bool_env("POLARDB_MYSQL_ENABLE_INSERT")
    enable_ddl = get_bool_env("POLARDB_MYSQL_ENABLE_DDL")
    logger.info(f"enable_delete: {enable_delete}, enable_update: {enable_update}, enable_insert: {enable_insert}, enable_ddl: {enable_ddl}")
    if os.getenv("RUN_MODE")=="stdio":
        asyncio.run(stdio_main())
    else:
        bind_host = os.getenv("SSE_BIND_HOST")
        bind_port = int(os.getenv("SSE_BIND_PORT"))
        sse_main(bind_host,bind_port)

if __name__ == "__main__":
    main()

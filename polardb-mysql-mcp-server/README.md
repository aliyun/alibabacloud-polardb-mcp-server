PolarDB MySQL MCP Server
=======================
# Prepare
1. install uv(if not exist)  
  curl -LsSf https://astral.sh/uv/install.sh | sh  
2. The project requires at least Python 3.10, if not available then install Python 3.12  
  uv python install 3.12  
# Environment Variables  
  The following environment variables are required to connect to PolarDB MySQL database,environment Variables can be set in .env file  or set in command line  
* POLARDB_MYSQL_HOST: Database host address  
* POLARDB_MYSQL_PORT: Database port 
* POLARDB_MYSQL_USER: Database user  
* POLARDB_MYSQL_PASSWORD: Database password  
* POLARDB_MYSQL_DATABASE: Database name  
* POLARDB_MYSQL_ENABLE_UPDATE: Enable update operation(default:false)  
* POLARDB_MYSQL_ENABLE_DELETE:  Enable delete operation(default:false)  
* POLARDB_MYSQL_ENABLE_INSERT:  Enable insert operation(default:false)  
* POLARDB_MYSQL_ENABLE_DDL:  Enable ddl operation(default:false)  
* SSE_BIND_HOST: The host address to bind for SSE mode  
* SSE_BIND_PORT: The port to bind for SSE mode  
* RUN_MODE: The run mode(sse|stdio),(default:sse)

# Build and Run
  git clone https://github.com/aliyun/alibabacloud-polardb-mcp-server.git  
  cd alibabacloud-polardb-mcp-server/polardb-mysql-mcp-server  
  uv venv  
  source .venv/bin/activate  
  cp .env_example .env #set env file with your database information  
  uv run src/polardb_mysql_mcp_server/server.py  
# Components
## Tools
* execute_sql: 执行符合PolarDB MySQL语法的SQL语句
* polar4ai_update_index_for_text_2_sql: 利用polardb的AI节点,对当前库的表建索引，用于文本转SQL或者文本转chart
* polar4ai_text_2_sql:利用polardb的AI节点,将用户的文本转换成sql语句
* polar4ai_text_2_chart:利用polardb的AI节点,将用户的文本统计需求直接转换成图表
* polar4ai_create_models:使用polar4ai语法，创建各种自定义算法模型  
* polar4ai_import_doc:利用polardb的AI节点,将用户本地目录的文档导入到PolarDB中形成知识库
* polar4ai_search_doc:利用polardb的AI节点,从PolarDB中的知识库中搜索用户问题并返回答案  
## Resources
* polardb-mysql://tables: 列出当前数据库中所有的表  
* polardb-mysql://models: 列出当前数据库中创建的所有自定义算法模型   
## Resource Templates
* polardb-mysql://{table}/field: 获取到表中字段的名称、类型和注释
* polardb-mysql://{table}/data: 从表中获取数据，默认获取50条数据 
# Usage
## Run with source code  
```json
{
  "mcpServers": {
    "polardb-mysql-mcp-server": {
      "command": "uv",
      "args": [
        "--directory",
        "/xxxx/alibabacloud-polardb-mcp-server/polardb-mysql-mcp-server",
        "run",
        "src/polardb_mysql_mcp_server/server.py"
      ],
      "env": {
        "POLARDB_MYSQL_HOST": "127.0.0.1",
        "POLARDB_MYSQL_PORT": "15001",
        "POLARDB_MYSQL_USER": "xxxx",
        "POLARDB_MYSQL_PASSWORD": "xxx",
        "POLARDB_MYSQL_DATABASE": "xxx",
        "RUN_MODE": "stdio",
        "POLARDB_MYSQL_ENABLE_UPDATE": "false",
        "POLARDB_MYSQL_ENABLE_DELETE": "false",
        "POLARDB_MYSQL_ENABLE_INSERT": "false",
        "POLARDB_MYSQL_ENABLE_DDL": "false"
      }
    }
  }
}
```
## Run with packages from PyPI
```json
{
  "mcpServers": {
    "polardb-mysql-mcp-server": {
      "command": "uvx",
      "args": [
        "--from",
        "polardb-mysql-mcp-server",
        "run_polardb_mysql_mcp_server"
      ],
      "env": {
        "POLARDB_MYSQL_HOST": "127.0.0.1",
        "POLARDB_MYSQL_PORT": "15001",
        "POLARDB_MYSQL_USER": "xxxx",
        "POLARDB_MYSQL_PASSWORD": "xxx",
        "POLARDB_MYSQL_DATABASE": "xxx",
        "RUN_MODE": "stdio",
        "POLARDB_MYSQL_ENABLE_UPDATE": "false",
        "POLARDB_MYSQL_ENABLE_DELETE": "false",
        "POLARDB_MYSQL_ENABLE_INSERT": "false",
        "POLARDB_MYSQL_ENABLE_DDL": "false"
      }
    }
  }
}
```

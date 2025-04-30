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
* POLARDB_MYSQL_ENABLE_WRITE:  Enable write operation(default:false)  
* POLARDB_MYSQL_ENABLE_INSER:  Enable insert operation(default:false)  
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
  uv run server.py
# Components
## Tools
* execute_sql: execute sql  
## Resources
* polardb-mysql://tables: List all tables for PolarDB MySQL in the current database  
## Resource Templates
* polardb-mysql://{table}/field: get the name,type and comment of the field in the table  
* polardb-mysql://{table}/data:  get data from the table,default limit 50 rows  
# Usage
## Cursor 
1. config for mcp.json  
```json
{
  "mcpServers": {
    "polardb-mysql-mcp-server": {
      "command": "uv",
      "args": [
        "--directory",
        "/xxxx/alibabacloud-polardb-mcp-server/polardb-mysql-mcp-server",
        "run",
        "server.py"
      ],
      "env": {
        "POLARDB_MYSQL_HOST": "127.0.0.1",
        "POLARDB_MYSQL_PORT": "15001",
        "POLARDB_MYSQL_USER": "xxxx",
        "POLARDB_MYSQL_PASSWORD": "xxx",
        "POLARDB_MYSQL_DATABASE": "xxx",
        "RUN_MODE": "stdio",
        "POLARDB_MYSQL_ENABLE_UPDATE": "false",
        "POLARDB_MYSQL_ENABLE_UPDATE": "false",
        "POLARDB_MYSQL_ENABLE_INSER": "false",
        "POLARDB_MYSQL_ENABLE_DDL": "false"
      }
    }
  }
}
```

## Client
1. set RUN_MODE=sse and other env variables in .env file  
2. cd alibabacloud-polardb-mcp-server/polardb-mysql-mcp-server && uv run server.py  
3. Set Remote Server  
![set remote server](./images/11.jpg)


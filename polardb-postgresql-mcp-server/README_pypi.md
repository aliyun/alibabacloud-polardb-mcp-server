PolarDB PostgreSQL MCP Server
=======================
# Environment Variables  
* POLARDB_POSTGRESQL_HOST: Database host address  
* POLARDB_POSTGRESQL_PORT: Database port 
* POLARDB_POSTGRESQL_USER: Database user  
* POLARDB_POSTGRESQL_PASSWORD: Database password  
* POLARDB_POSTGRESQL_DBNAME: Database name  
* POLARDB_POSTGRESQL_ENABLE_UPDATE: Enable update operation(default:false)  
* POLARDB_POSTGRESQL_ENABLE_DELETE:  Enable delete operation(default:false)  
* POLARDB_POSTGRESQL_ENABLE_INSERT:  Enable insert operation(default:false)  
* POLARDB_POSTGRESQL_ENABLE_DDL:  Enable ddl operation(default:false)  
* SSE_BIND_HOST: The host address to bind for SSE mode  
* SSE_BIND_PORT: The port to bind for SSE mode  
* RUN_MODE: The run mode(sse|stdio),(default:sse)  
# Components
## Tools
* execute_sql: execute sql  
## Resources
* polardb-postgresql://schemas: List all schemas for PolarDB PostgreSQL in the current database  
## Resource Templates
* polardb-postgresql://{schema}/tables: List all tables for a schema 
* polardb-postgresql://{schema}/{table}/field: get the name,type and comment of the field in the table  
* polardb-postgresql://{schema}/{table}/data:  get data from the table,default limit 50 rows  
# Usage
## Run with packages from PyPI
```json
{
  "mcpServers": {
    "polardb-postgresql-mcp-server": {
      "command": "uvx",
      "args": [
        "--from",
        "polardb-postgresql-mcp-server",
        "run_polardb_postgresql_mcp_server"
      ],
      "env": {
        "POLARDB_POSTGRESQL_HOST": "127.0.0.1",
        "POLARDB_POSTGRESQL_PORT": "15001",
        "POLARDB_POSTGRESQL_USER": "xxxx",
        "POLARDB_POSTGRESQL_PASSWORD": "xxx",
        "POLARDB_POSTGRESQL_DBNAME": "xxx",
        "RUN_MODE": "stdio",
        "POLARDB_POSTGRESQL_ENABLE_UPDATE": "false",
        "POLARDB_POSTGRESQL_ENABLE_DELETE": "false",
        "POLARDB_POSTGRESQL_ENABLE_INSERT": "false",
        "POLARDB_POSTGRESQL_ENABLE_DDL": "false"
      }
    }
  }
}
```
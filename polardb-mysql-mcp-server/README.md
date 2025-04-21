PolarDB MySQL MCP Server
=======================

# 安装

git clone <git@gitlab.alibaba-inc.com>:rds_proxy/polardb_mcp_server.git  
cd polardb_mcp_server/polardb-mysql-mcp-server  
uv venv  
source .venv/bin/activate  
cp .env_example .env #修改.env文件,配置成你自己DB环境变量  
uv run server.py  

# 使用

## 通过Cursor来验证
1. .env文件中的模式认证为RUN_MODE=stdio
2. mcp.json文件内容
```json
{
  "mcpServers": {
    "PolarDB-MySQL": {
      "command": "uv",
      "args": [
        "--directory",
        "/xxxx/polardb_mcp_server/polardb-mysql-mcp-server",
        "run",
        "server.py"
      ]
    }
  }
}
```

## 通过Cline来验证
1. .env文件中的模式认证为RUN_MODE=sse
2. mcp.json文件内容
```json
{
  "mcpServers": {
    "PolarDB-MySQL-SSE": {
      "autoApprove": [],
      "disabled": false,
      "timeout": 60,
      "url": "http://127.0.0.1:8080/sse",
      "transportType": "sse"
    }
  }
}
```
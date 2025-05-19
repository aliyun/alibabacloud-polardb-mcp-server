PolarDB MySQL MCP Server
=======================
# Prepare
1. install uv(if not exist)  
  curl -LsSf https://astral.sh/uv/install.sh | sh  
2. The project requires at least Python 3.10, if not available then install Python 3.12  
  uv python install 3.12  
# Environment Variables  
  The following environment variables are required to connect to PolarDB MySQL database,environment Variables can be set in .env file  or set in command line  
* SSE_BIND_HOST: The host address to bind for SSE mode  
* SSE_BIND_PORT: The port to bind for SSE mode  
* RUN_MODE: The run mode(sse|stdio),(default:stdio)
* ALIBABA_CLOUD_ACCESS_KEY_ID: Access Key ID of your Alibaba Cloud account
* ALIBABA_CLOUD_ACCESS_KEY_SECRET: Access Key Secret of your Alibaba Cloud account
# Build and Run
  git clone https://github.com/aliyun/alibabacloud-polardb-mcp-server.git  
  cd alibabacloud-polardb-mcp-server/polardb-mysql-mcp-server  
  uv venv  
  source .venv/bin/activate  
  cp .env_example .env #set env file with your database information  
  uv run server.py
# Components
## Tools
* polardb_describe_regions: List all available regions for Alibaba Cloud PolarDB
* polardb_describe_db_clusters: List all PolarDB clusters in a specific region
* polardb_describe_db_cluster: Get detailed information about a specific PolarDB cluster
* polardb_describe_available_resources: List available resources for creating PolarDB clusters
* polardb_create_cluster: Create a new PolarDB cluster
## Resources
* polardb-mysql://regions: List all available regions for Alibaba Cloud PolarDB
* polardb-mysql://clusters: List all PolarDB clusters across all regions
## Resource Templates
* polardb-mysql://{{region_id}}/clusters: get all PolarDB clusters in a specific region
polardb-mysql://classes/{{region_id}}/{{db_type}}: get all PolarDB classes specifications for a specific region and database type
# Usage
```
## Claude
1. config for claude_desktop_config.json
```json
{
    "polardb-mysql-mcp-server": {
      "command": "/bin/bash",
      "args": [
        "-c",
        "cd your_path/git/polardb_mcp_server/polardb-mysql-mcp-server && source ./bin/activate && python server.py"
      ]
    }
}
```

## Client
1. set RUN_MODE=stido and other env variables in .env file  
2. cd alibabacloud-polardb-mcp-server/polardb-openapi-mcp-server && python server.py  
3. Set Remote Server  
![set remote server](./images/11.jpg)


<p align="center">English | <a href="./README_CN.md">中文</a><br></p>
# Alibaba Cloud PolarDB OpenAPI MCP Server
MCP server for PolarDB Services via OPENAPI

## Prerequisites
1. Install `pipx` with `brew install pipx` (macOS) or equivalent for your OS
2. Python >=3.12
3. Alibaba Cloud credentials with access to Alibaba Cloud PolarDB services

## Quick Start

### Simple Setup with [cherry-studio](https://github.com/CherryHQ/cherry-studio) - SSE Mode (Recommended)

**Easy 2-step setup:**

#### Step 1: Install the server
```bash
pipx install polardb-openapi-mcp-server
```

#### Step 2: Start server and configure Cherry Studio

**Start the server:**
```bash
export ALIBABA_CLOUD_ACCESS_KEY_ID="your-access-key-id"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your-access-key-secret"
export ALIBABA_CLOUD_REGION="cn-hangzhou"
export RUN_MODE="sse"
export SSE_BIND_HOST="127.0.0.1"
export SSE_BIND_PORT="12345"

run_polardb_openapi_mcp_server
```

**Configure Cherry Studio with this JSON:**
```json
{
  "mcpServers": {
    "polardb-openapi": {
      "type": "sse",
      "url": "http://127.0.0.1:12345/sse"
    }
  }
}
```

Replace the credentials with your actual Alibaba Cloud access keys. The server will start and Cherry Studio will connect automatically.

### Alternative: Claude Desktop Setup

For Claude Desktop, you can use stdio mode:

#### Step 1: Install the server
```bash
pipx install polardb-openapi-mcp-server
```

#### Step 2: Configure Claude Desktop
Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "polardb-openapi": {
      "command": "run_polardb_openapi_mcp_server",
      "args": [],
      "env": {
        "ALIBABA_CLOUD_ACCESS_KEY_ID": "your-access-key-id",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "your-access-key-secret",
        "ALIBABA_CLOUD_REGION": "cn-hangzhou",
        "RUN_MODE": "stdio"
      }
    }
  }
}
```

Replace the credentials with your actual Alibaba Cloud access keys.

### Using Local Client

#### Key Advantages

* **Security & Privacy**: Your organization may have policies restricting the use of cloud-based MCP clients, as they typically log operational activities that could contain sensitive or proprietary information.
* **Reliability & Ease of Use**: Many existing MCP clients can be complex to configure and may experience frequent downtime due to high traffic loads. Our local client provides a stable, straightforward alternative for managing your PolarDB OpenAPI MCP server.
* **PolarDB Optimization**: Our client includes specialized PolarDB domain knowledge and enhanced features specifically designed for PolarDB operations that are not available in generic MCP clients.

#### Setup and Usage

Start your local MCP client service with the following command:

```bash
# If using source code
cd /path/to/polardb_mcp_server/polardb-openapi-mcp-server
python3 fixed_mcp_protocol_web.py /path/to/polardb_mcp_server/polardb-openapi-mcp-server
```

Or if you have installed the package:
```bash
# Set your credentials
export ALIBABA_CLOUD_ACCESS_KEY_ID="your-access-key-id"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your-access-key-secret"  
export ALIBABA_CLOUD_REGION="cn-hangzhou"

# Start the local client
python3 -m fixed_mcp_protocol_web
```

You can then open the following URL in your browser to access the MCP client:
**http://localhost:4657/**

You can then ask any question by inputting your question into the "Natural Language Interface", then press the "Ask" button.

#### Features of the Local Client

- **Natural Language Interface**: Ask questions in plain English or Chinese
- **Interactive Tool Testing**: Test all PolarDB operations directly in the browser
- **Real-time Responses**: See immediate results from your PolarDB clusters
- **Debug and Development**: Perfect for testing new features and debugging
- **Secure Local Execution**: No data sent to external services
- **PolarDB-Optimized UI**: Specialized interface designed for PolarDB operations

## Features

This MCP server provides comprehensive access to Alibaba Cloud PolarDB services including:

### Core Database Operations
- **Cluster Management**: Create, describe, modify, and delete PolarDB clusters
- **Database Operations**: Create databases, manage accounts, configure endpoints
- **Performance Monitoring**: Real-time cluster and node performance metrics
- **Security Management**: Access whitelist configuration and management

### Advanced Features
- **Slow Log Analysis**: Query and analyze slow query logs with intelligent insights
- **Error Log Investigation**: Access and analyze database error logs
- **Performance Optimization**: Automated performance analysis and recommendations  
- **Cloud DBA Integration**: Advanced database administration tools
- **Multi-language Support**: Full Chinese and English language support

### AI-Enhanced Capabilities
- **Smart Query Dispatcher**: Natural language processing for query intent recognition
- **Text-to-SQL**: Convert natural language to SQL queries
- **Performance Insights**: AI-powered performance analysis and recommendations
- **Document Knowledge Base**: Import and search documentation with AI assistance

### Network and Infrastructure
- **VPC Management**: Virtual Private Cloud configuration and management
- **Endpoint Management**: Database connection endpoint configuration
- **Parameter Configuration**: Database parameter tuning and optimization
- **Resource Monitoring**: Comprehensive resource usage monitoring

## Available OpenAPI Tools

This server provides the following PolarDB management tools:

### Cluster Management
* `polardb_create_cluster`: Create a new PolarDB cluster
* `polardb_describe_regions`: List all available regions for Alibaba Cloud PolarDB
* `polardb_describe_db_clusters`: List all PolarDB clusters in a specific region with comprehensive cluster details
* `polardb_describe_db_cluster`: Get detailed information about a specific PolarDB cluster
* `polardb_describe_available_resources`: List available resources for creating PolarDB clusters
* `polardb_modify_db_cluster_description`: Modify the description of a PolarDB cluster with comprehensive validation
* `polardb_tag_resources`: Add tags to PolarDB resources (clusters, nodes, etc.)

### Database and Account Management
* `polardb_create_account`: Create a database account for a PolarDB cluster with specified privileges
* `polardb_describe_accounts`: List database accounts for a PolarDB cluster, including account types, status, and database privileges
* `polardb_describe_databases`: List databases in a specific PolarDB cluster, optionally filtered by database name

### Network and Connectivity
* `polardb_create_db_endpoint_address`: Create a new database endpoint address for a PolarDB cluster
* `polardb_describe_db_cluster_endpoints`: List database endpoints for a specific PolarDB cluster, including connection strings and IP addresses
* `polardb_describe_db_cluster_access_whitelist`: Get the current active access whitelist configuration for a PolarDB cluster
* `polardb_modify_db_cluster_access_whitelist`: Modify the access whitelist for a PolarDB cluster to control which IP addresses can connect
* `polardb_describe_global_security_ipgroup_relation`: Get global security IP group relations for a specific PolarDB cluster
* `polardb_describe_db_cluster_connectivity`: Test network connectivity to a PolarDB cluster from a specific source IP address

### Performance and Monitoring
* `polardb_describe_slow_log_records`: Get slow log records for a specific PolarDB cluster within a time range
* `polardb_describe_db_node_performance`: Get performance metrics for a specific PolarDB database node within a time range
* `polardb_describe_db_cluster_performance`: Get performance metrics for a specific PolarDB cluster within a time range with enhanced analysis
* `polardb_describe_db_proxy_performance`: Get proxy performance metrics for a specific PolarDB cluster within a time range with enhanced analysis

### Configuration and Parameters
* `polardb_describe_db_node_parameters`: Get configuration parameters for a specific PolarDB database node
* `polardb_describe_db_cluster_parameters`: Get configuration parameters for a PolarDB cluster, organized by category with important parameters highlighted
* `polardb_modify_db_node_parameters`: Modify configuration parameters for PolarDB database nodes
* `polardb_modify_db_cluster_parameters`: Modify configuration parameters for PolarDB cluster

### Node Management
* `polardb_extract_node_ids`: Extract node IDs from a PolarDB cluster by role (reader/writer)
* `polardb_restart_db_node`: Restart a specific PolarDB database node with comprehensive monitoring guidance and safety recommendations

### VPC and Network Infrastructure
* `vpc_describe_vpcs`: List all VPCs (Virtual Private Clouds) in a specific region with detailed network configuration information
* `vpc_describe_vswitches`: List all VSwitches (Virtual Switches) in a specific region with detailed subnet configuration information

## Configuration Options

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `ALIBABA_CLOUD_ACCESS_KEY_ID` | Alibaba Cloud Access Key ID | - | Yes |
| `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | Alibaba Cloud Access Key Secret | - | Yes |
| `ALIBABA_CLOUD_REGION` | Alibaba Cloud Region | `cn-hangzhou` | No |
| `RUN_MODE` | Server mode (`stdio` or `sse`) | `stdio` | No |
| `SSE_BIND_HOST` | SSE server bind host | `127.0.0.1` | No |
| `SSE_BIND_PORT` | SSE server bind port | `8080` | No |

### Permissions

Ensure your Alibaba Cloud credentials have the following permissions:
- PolarDB read/write access
- VPC read access  
- DAS (Database Autonomy Service) access
- CloudMonitor access for performance metrics

## Development

### Local Development Setup
```bash
git clone https://github.com/aliyun/alibabacloud-polardb-mcp-server.git
cd alibabacloud-polardb-mcp-server/polardb-openapi-mcp-server

# Install dependencies
pipx install -e .

# Run tests
pytest test/
```

### Building from Source
```bash
uv build
uv publish  # For maintainers only
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Support

- **Documentation**: [Alibaba Cloud PolarDB Documentation](https://www.alibabacloud.com/help/en/polardb)
- **Issues**: Report issues on [GitHub](https://github.com/aliyun/alibabacloud-polardb-mcp-server/issues)
- **MCP Protocol**: [Model Context Protocol](https://modelcontextprotocol.io)

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](../LICENSE) file for details.
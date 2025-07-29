#!/usr/bin/env python3
"""
Fixed MCP Web Interface with Proper Protocol Sequence
Save as: fixed_mcp_protocol_web.py
"""

from flask import Flask, send_from_directory, request, jsonify
import json
import subprocess
import time
import os
import sys
import select
import ast
from typing import Dict, Any
import logging
import statistics
from datetime import datetime, timedelta
import shutil

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Hardcoded tools list based on your server.py - COMPLETE LIST
HARDCODED_TOOLS = [
    {
        "name": "polardb_smart_query",
        "description": "🤖 智能查询工具 - 支持自然语言查询PolarDB资源。可以理解中文和英文的自然语言指令，自动识别用户意图并执行相应操作。支持: 重启节点、集群性能、节点性能、集群信息、白名单查看、节点提取等操作。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "自然语言查询，例如: '重启节点pi-1udu07821xcd49u02', '获取集群pc-123的性能', 'restart node pi-123', 'get performance for cluster pc-456' 等。支持中英文混合输入。"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "重启节点",
        "description": "🔄 重启PolarDB数据库节点 - 当用户说'重启节点pi-xxxxx'时使用此工具。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbnode_id": {
                    "type": "string",
                    "description": "要重启的数据库节点ID，必须以pi-开头，例如: pi-1udu07821xcd49u02"
                }
            },
            "required": ["dbnode_id"]
        }
    },
    {
        "name": "polardb_restart_db_node",
        "description": "🔄 Restart a PolarDB database node - English version",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbnode_id": {
                    "type": "string",
                    "description": "Database node ID to restart, must start with 'pi-', e.g., pi-1udu07821xcd49u02"
                }
            },
            "required": ["dbnode_id"]
        }
    },
    {
        "name": "polardb_describe_regions",
        "description": "List all available regions for Alibaba Cloud PolarDB",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "polardb_describe_db_clusters",
        "description": "List all PolarDB clusters in a specific region",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {
                    "type": "string",
                    "description": "Region ID to list clusters from (e.g., cn-hangzhou)"
                }
            },
            "required": ["region_id"]
        }
    },
    {
        "name": "polardb_describe_db_cluster",
        "description": "Get detailed information about a specific PolarDB cluster",
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_cluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster"
                }
            },
            "required": ["db_cluster_id"]
        }
    },
    {
        "name": "polardb_describe_available_resources",
        "description": "List available resources for creating PolarDB clusters",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {
                    "type": "string",
                    "description": "Region ID to list available resources from (e.g., cn-hangzhou)"
                },
                "zone_id": {
                    "type": "string",
                    "description": "Zone ID to list available resources from"
                },
                "db_type": {
                    "type": "string",
                    "description": "Database type (e.g., MySQL, PostgreSQL)"
                },
                "db_version": {
                    "type": "string",
                    "description": "Database version (e.g., 8.0, 5.7)"
                },
                "pay_type": {
                    "type": "string",
                    "description": "Payment type (e.g., Prepaid, Postpaid, default: Postpaid)"
                }
            },
            "required": []
        }
    },
    {
        "name": "polardb_create_cluster",
        "description": "Create a new PolarDB cluster",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {
                    "type": "string",
                    "description": "Region ID where to create the cluster (e.g., cn-hangzhou)"
                },
                "dbtype": {
                    "type": "string",
                    "description": "Database type (e.g., MySQL, PostgreSQL)"
                },
                "dbversion": {
                    "type": "string",
                    "description": "Database version (e.g., 8.0, 5.7)"
                },
                "dbnode_class": {
                    "type": "string",
                    "description": "Instance class specification (e.g., polar.mysql.g1.tiny.c)"
                },
                "pay_type": {
                    "type": "string",
                    "description": "Payment type (Postpaid for pay-as-you-go, Prepaid for subscription)"
                },
                "storage_space": {
                    "type": "integer",
                    "description": "Storage space in GB (minimum 50)"
                },
                "zone_id": {
                    "type": "string",
                    "description": "Zone ID where to create the cluster"
                },
                "vpc_id": {
                    "type": "string",
                    "description": "VPC ID for the cluster"
                },
                "vswitch_id": {
                    "type": "string",
                    "description": "VSwitch ID for the cluster"
                },
                "db_cluster_description": {
                    "type": "string",
                    "description": "Description for the PolarDB cluster"
                },
                "resource_group_id": {
                    "type": "string",
                    "description": "Resource group ID"
                },
                "period": {
                    "type": "string",
                    "description": "Period for prepaid instances (Month/Year)"
                },
                "used_time": {
                    "type": "integer",
                    "description": "Used time for prepaid instances"
                },
                "client_token": {
                    "type": "string",
                    "description": "Idempotence token"
                }
            },
            "required": ["dbnode_class"]
        }
    },
    {
        "name": "polardb_describe_db_node_parameters",
        "description": "Get configuration parameters for a specific PolarDB database node",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbnode_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB database node"
                },
                "db_cluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster"
                }
            },
            "required": ["dbnode_id", "db_cluster_id"]
        }
    },
    {
        "name": "polardb_modify_db_node_parameters",
        "description": "Modify configuration parameters for PolarDB database nodes",
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_cluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster"
                },
                "dbnode_ids": {
                    "type": "string",
                    "description": "The IDs of the PolarDB database nodes, separate multiple values with commas"
                },
                "parameters": {
                    "type": "string",
                    "description": "Parameters to modify in JSON format, e.g., {\"wait_timeout\":\"86\",\"innodb_old_blocks_time\":\"10\"}"
                }
            },
            "required": ["db_cluster_id", "dbnode_ids", "parameters"]
        }
    },
    {
        "name": "polardb_describe_slow_log_records",
        "description": "Get slow log records for a specific PolarDB cluster within a time range",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {
                    "type": "string",
                    "description": "Region ID where the cluster is located (e.g., cn-hangzhou)"
                },
                "db_cluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster"
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time for slow log query in ISO 8601 format (e.g., 2025-05-28T16:00Z)"
                },
                "end_time": {
                    "type": "string",
                    "description": "End time for slow log query in ISO 8601 format (e.g., 2025-05-29T04:00Z)"
                },
                "node_id": {
                    "type": "string",
                    "description": "The ID of the database node (optional)"
                },
                "dbname": {
                    "type": "string",
                    "description": "Database name to filter slow logs (optional)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (default: 30, max: 2147483647)"
                },
                "page_number": {
                    "type": "integer",
                    "description": "Page number for pagination (default: 1)"
                },
                "sqlhash": {
                    "type": "string",
                    "description": "SQL hash to filter specific slow queries (optional)"
                }
            },
            "required": ["region_id", "db_cluster_id", "start_time", "end_time"]
        }
    },
    {
        "name": "polardb_describe_db_node_performance",
        "description": "Get performance metrics for a specific PolarDB database node within a time range",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbnode_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB database node (e.g., pi-1udn03901ed4u2i1e)"
                },
                "key": {
                    "type": "string",
                    "description": "Performance metrics to retrieve, comma-separated (e.g., 'PolarDBDiskUsage,PolarDBCPU,PolarDBMemory')"
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time for performance query in ISO 8601 format (e.g., 2025-05-28T16:00Z)"
                },
                "end_time": {
                    "type": "string",
                    "description": "End time for performance query in ISO 8601 format (e.g., 2025-05-29T04:00Z)"
                },
                "db_cluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (optional, but recommended for better API compatibility)"
                }
            },
            "required": ["dbnode_id", "key", "start_time", "end_time"]
        }
    },
    {
        "name": "polardb_describe_db_cluster_performance",
        "description": "Get performance metrics for a specific PolarDB cluster within a time range",
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_cluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-1udn03901ed4u2i1e)"
                },
                "key": {
                    "type": "string",
                    "description": "Performance metrics to retrieve, comma-separated (e.g., 'PolarDBDiskUsage,PolarDBCPU,PolarDBMemory')"
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time for performance query in ISO 8601 format (e.g., 2025-05-28T16:00Z)"
                },
                "end_time": {
                    "type": "string",
                    "description": "End time for performance query in ISO 8601 format (e.g., 2025-05-29T04:00Z)"
                }
            },
            "required": ["db_cluster_id", "key", "start_time", "end_time"]
        }
    },
    {
        "name": "polardb_tag_resources",
        "description": "Add tags to PolarDB resources (clusters, nodes, etc.)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {
                    "type": "string",
                    "description": "Region ID where the resources are located (e.g., cn-hangzhou, cn-shanghai)"
                },
                "resource_type": {
                    "type": "string",
                    "description": "Type of resource to tag (e.g., 'cluster')",
                    "enum": ["cluster"]
                },
                "resource_ids": {
                    "type": ["string", "array"],
                    "description": "Resource ID(s) to tag. Can be a single ID string or comma-separated string, or array of IDs",
                    "items": {
                        "type": "string"
                    }
                },
                "tags": {
                    "type": ["array", "object"],
                    "description": "Tags to apply. Can be array of {key, value} objects or a simple key-value object",
                    "oneOf": [
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {"type": "string"},
                                    "value": {"type": "string"}
                                },
                                "required": ["key", "value"]
                            }
                        },
                        {
                            "type": "object",
                            "additionalProperties": {"type": "string"}
                        }
                    ]
                }
            },
            "required": ["region_id", "resource_type", "resource_ids", "tags"]
        }
    },
    {
        "name": "polardb_create_db_endpoint_address",
        "description": "Create a new database endpoint address for a PolarDB cluster",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbcluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                },
                "net_type": {
                    "type": "string",
                    "description": "Network type for the endpoint",
                    "enum": ["Public", "Private", "Inner"]
                },
                "dbendpoint_id": {
                    "type": "string",
                    "description": "The ID of the database endpoint (e.g., pe-6nn5trlkr263c0uce)"
                },
                "connection_string_prefix": {
                    "type": "string",
                    "description": "Custom prefix for the connection string (optional)"
                },
                "port": {
                    "type": "integer",
                    "description": "Port number for the endpoint (optional, default varies by engine)"
                }
            },
            "required": ["dbcluster_id", "net_type", "dbendpoint_id"]
        }
    },
    {
        "name": "polardb_modify_db_cluster_access_whitelist",
        "description": "Modify the access whitelist for a PolarDB cluster to control which IP addresses can connect",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbcluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                },
                "security_ips": {
                    "type": "string",
                    "description": "IP addresses or CIDR blocks allowed to access the cluster. Use comma-separated values for multiple IPs (e.g., '192.168.1.1,10.0.0.1' or '0.0.0.0/0' for all IPs)"
                },
                "db_cluster_iparray_name": {
                    "type": "string",
                    "description": "Name of the IP array group (optional, default is 'default')"
                },
                "modify_mode": {
                    "type": "string",
                    "description": "How to modify the whitelist (optional, default: 'Cover')",
                    "enum": ["Cover", "Append", "Delete"],
                    "default": "Cover"
                },
                "security_group_ids": {
                    "type": "string",
                    "description": "Security group IDs for ECS-based access control (optional, comma-separated)"
                }
            },
            "required": ["dbcluster_id", "security_ips"]
        }
    },
    {
        "name": "polardb_create_account",
        "description": "Create a database account for a PolarDB cluster with specified privileges",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbcluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                },
                "account_name": {
                    "type": "string",
                    "description": "Database account name (2-16 characters, alphanumeric and underscore only)"
                },
                "account_password": {
                    "type": "string",
                    "description": "Account password (8-32 characters, must contain uppercase, lowercase, number, and special character)"
                },
                "account_type": {
                    "type": "string",
                    "description": "Account type (optional, default: 'Super')",
                    "enum": ["Normal", "Super"],
                    "default": "Super"
                },
                "account_description": {
                    "type": "string",
                    "description": "Description of the account (optional, max 256 characters)"
                },
                "db_name": {
                    "type": "string",
                    "description": "Database name to grant access to (optional, for Normal accounts)"
                },
                "account_privilege": {
                    "type": "string",
                    "description": "Privilege level for the specified database (optional, default: 'ReadWrite')",
                    "enum": ["ReadWrite", "ReadOnly", "DMLOnly", "DDLOnly", "ReadIndex"],
                    "default": "ReadWrite"
                }
            },
            "required": ["dbcluster_id", "account_name", "account_password"]
        }
    },
    {
        "name": "polardb_describe_db_cluster_access_whitelist",
        "description": "View the current access whitelist configuration for a PolarDB cluster to see which IP addresses are allowed to connect",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbcluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                }
            },
            "required": ["dbcluster_id"]
        }
    },
    {
        "name": "polardb_describe_accounts",
        "description": "List database accounts for a PolarDB cluster, including account types, status, and database privileges",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbcluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                },
                "account_name": {
                    "type": "string",
                    "description": "Optional: Filter by specific account name to get details for a single account"
                }
            },
            "required": ["dbcluster_id"]
        }
    },
    {
        "name": "polardb_describe_databases",
        "description": "List databases in a specific PolarDB cluster, optionally filtered by database name",
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_cluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                },
                "db_name": {
                    "type": "string",
                    "description": "Optional: Specific database name to describe (e.g., 'information_schema', 'mysql'). If not provided, lists all databases in the cluster"
                },
                "page_number": {
                    "type": "integer",
                    "description": "Page number for pagination (optional, default: 1)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (optional, default: 30)"
                }
            },
            "required": ["db_cluster_id"]
        }
    },
    {
        "name": "polardb_describe_db_cluster_access_whitelist",
        "description": "Get the current access whitelist configuration for a PolarDB cluster to see which IP addresses are allowed to connect",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbcluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                }
            },
            "required": ["dbcluster_id"]
        }
    },
    {
        "name": "polardb_describe_db_cluster_endpoints",
        "description": "List database endpoints for a specific PolarDB cluster, including connection strings, IP addresses, and endpoint configurations",
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_cluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                }
            },
            "required": ["db_cluster_id"]
        }
    },
    {
        "name": "polardb_describe_db_cluster_parameters",
        "description": "Get configuration parameters for a PolarDB cluster, organized by category with important parameters highlighted",
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_cluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                }
            },
            "required": ["db_cluster_id"]
        }
    },
    {
        "name": "polardb_describe_global_security_ipgroup_relation",
        "description": "Get global security IP group relations for a specific PolarDB cluster. Global security IP groups provide centralized IP whitelist management that can be shared across multiple clusters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {
                    "type": "string",
                    "description": "Region ID where the cluster is located (e.g., cn-hangzhou, cn-beijing, cn-shanghai)"
                },
                "dbcluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-1udt379icjl5032b1)"
                }
            },
            "required": ["region_id", "dbcluster_id"]
        }
    },
    {
        "name": "vpc_describe_vpcs",
        "description": "List all VPCs (Virtual Private Clouds) in a specific region with detailed network configuration information including CIDR blocks, vSwitches, route tables, and connectivity status",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {
                    "type": "string",
                    "description": "Region ID to list VPCs from (e.g., cn-hangzhou, cn-beijing, cn-shanghai). Default: cn-hangzhou if not specified"
                }
            },
            "required": []
        }
    },
    {
        "name": "vpc_describe_vswitches",
        "description": "List all VSwitches (Virtual Switches) in a specific region with detailed subnet configuration information including CIDR blocks, available IP addresses, zone distribution, and route table associations",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region_id": {
                    "type": "string",
                    "description": "Region ID to list VSwitches from (e.g., cn-hangzhou, cn-beijing, cn-shanghai). Default: cn-hangzhou if not specified"
                },
                "vpc_id": {
                    "type": "string",
                    "description": "Optional: VPC ID to filter VSwitches (e.g., vpc-bp1awijx0p7r8tnhk49iy). If provided, only VSwitches in this VPC will be returned"
                },
                "zone_id": {
                    "type": "string",
                    "description": "Optional: Zone ID to filter VSwitches (e.g., cn-hangzhou-j, cn-hangzhou-k). If provided, only VSwitches in this zone will be returned"
                },
                "vswitch_id": {
                    "type": "string",
                    "description": "Optional: Specific VSwitch ID to describe (e.g., vsw-bp1l2aim43gvyuozzab9o). If provided, only this specific VSwitch will be returned"
                }
            },
            "required": []
        }
    },
    {
        "name": "polardb_modify_db_cluster_access_whitelist",
        "description": "Modify the access whitelist for a PolarDB cluster to control which IP addresses or security groups can connect. Supports both IP-based and SecurityGroup-based access control with Cover (replace all), Append (add new), and Delete (remove existing) modes for flexible access management.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbcluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                },
                "white_list_type": {
                    "type": "string",
                    "description": "Type of whitelist to modify (optional, default: 'IP'). 'IP' for IP address-based access control, 'SecurityGroup' for ECS security group-based access control",
                    "enum": ["IP", "SecurityGroup"],
                    "default": "IP"
                },
                "security_ips": {
                    "type": "string",
                    "description": "IP addresses or CIDR blocks allowed to access the cluster (required when white_list_type is 'IP'). Use comma-separated values for multiple IPs. Examples: '192.168.1.1' (single IP), '192.168.1.1,10.0.0.1' (multiple IPs), '192.168.1.0/24' (subnet), '0.0.0.0/0' (all IPs - not recommended for production)"
                },
                "security_group_ids": {
                    "type": "string",
                    "description": "Security group IDs for ECS-based access control (required when white_list_type is 'SecurityGroup', optional when white_list_type is 'IP'). Use comma-separated values for multiple groups (e.g., 'sg-12345,sg-67890'). Provides dynamic access control based on ECS instance membership"
                },
                "db_cluster_iparray_name": {
                    "type": "string",
                    "description": "Name of the IP array group (optional, default is 'default'). Use different names to manage multiple IP groups for different purposes (e.g., 'production', 'development', 'admin')"
                },
                "modify_mode": {
                    "type": "string",
                    "description": "How to modify the whitelist (optional, default: 'Cover'). Cover: replace all existing entries, Append: add to existing entries, Delete: remove specified entries from existing list",
                    "enum": ["Cover", "Append", "Delete"],
                    "default": "Cover"
                }
            },
            "required": ["dbcluster_id"]
        }
    },
    {
        "name": "polardb_modify_db_cluster_description",
        "description": "Modify the description of a PolarDB cluster with comprehensive validation and formatting guidelines. Helps organize and document cluster purposes with proper content validation and best practice recommendations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbcluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                },
                "dbcluster_description": {
                    "type": "string",
                    "description": "New description for the cluster. Must be 2-256 characters long and cannot start with 'http://' or 'https://'. Should be descriptive and meaningful for cluster identification and management purposes. Examples: 'Production MySQL cluster for e-commerce web application', 'Development database for user authentication service - Team Alpha'",
                    "minLength": 2,
                    "maxLength": 256
                }
            },
            "required": ["dbcluster_id", "dbcluster_description"]
        }
    },
    {
        "name": "polardb_restart_db_node",
        "description": "Restart a specific PolarDB database node with comprehensive monitoring guidance, safety recommendations, and impact assessment. Includes detailed validation to ensure correct node ID format and provides step-by-step restart monitoring instructions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbnode_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB database node to restart. CRITICAL: Must start with 'pi-' (e.g., 'pi-6nnp9h5z59l323jpf'). Do NOT use cluster IDs that start with 'pc-'. Use polardb_extract_node_ids or polardb_describe_db_cluster to find correct node IDs if unsure.",
                    "pattern": "^pi-[a-zA-Z0-9]+$"
                },
                "db_cluster_id": {
                    "type": "string",
                    "description": "Optional: The ID of the PolarDB cluster that contains the node (e.g., 'pc-6nnupu6o754068f16'). Recommended for additional validation and context. Helps ensure the node belongs to the intended cluster."
                }
            },
            "required": ["dbnode_id"]
        }
    },
    {
        "name": "polardb_modify_db_cluster_parameters",
        "description": "Modify configuration parameters for PolarDB cluster",
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_cluster_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster"
                },
                "parameters": {
                    "type": "string",
                    "description": "Parameters to modify in JSON format"
                }
            },
            "required": ["db_cluster_id", "parameters"]
        }
    },
    {
        "name": "polardb_describe_db_cluster_connectivity",
        "description": "🌐 测试PolarDB集群网络连接性 - 验证特定源IP地址到数据库集群的网络连通性，检查IP白名单配置和访问权限。用于排查连接问题和验证安全设置。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbcluster_id": {
                    "type": "string",
                    "description": "要测试连接的PolarDB集群ID，必须以'pc-'开头（例如：'pc-1udt379icjl5032b1'）。请勿使用以'pi-'开头的节点ID。如不确定，可使用polardb_describe_db_clusters查找正确的集群ID。",
                    "pattern": "^pc-[a-zA-Z0-9]+$"
                },
                "source_ip_address": {
                    "type": "string", 
                    "description": "测试连接的源IP地址，必须是有效的IPv4地址格式（例如：'192.168.1.100', '10.0.0.50'）。这应该是需要连接数据库集群的机器或网络的IP地址。",
                    "pattern": "^(\\d{1,3}\\.){3}\\d{1,3}$"
                }
            },
            "required": ["dbcluster_id", "source_ip_address"]
        }
    },
    {
        "name": "polardb_describe_db_proxy_performance",
        "description": "获取PolarDB集群代理(Proxy)在指定时间范围内的性能指标数据，支持多种代理性能指标分析和北京时间自动转换。系统会自动进行性能分析并提供优化建议。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dbcluster_id": {
                    "type": "string",
                    "description": "PolarDB集群ID (例如: pc-1udt379icjl5032b1)"
                },
                "dbnode_id": {
                    "type": "string",
                    "description": "PolarDB数据库节点ID (例如: pi-1udt379icjl5032b1)"
                },
                "key": {
                    "type": "string", 
                    "description": "代理性能指标，逗号分隔，最多5个。如不提供则使用默认指标 (PolarProxy_CurrentConns, PolarProxy_DBConns, PolarProxy_DBActionOps)。\n\n核心代理指标:\n• PolarProxy_CurrentConns - 当前连接数\n• PolarProxy_DBConns - 数据库连接数\n• PolarProxy_DBActionOps - 数据库操作次数\n\n扩展代理指标:\n• PolarProxy_CPU - 代理CPU使用率\n• PolarProxy_Memory - 代理内存使用率\n• PolarProxy_NetworkIn - 网络输入流量\n• PolarProxy_NetworkOut - 网络输出流量\n• PolarProxy_QPS - 每秒查询数\n• PolarProxy_TPS - 每秒事务数\n• PolarProxy_AvgResponseTime - 平均响应时间\n• PolarProxy_SlowQueries - 慢查询数量\n• PolarProxy_ConnectionPool - 连接池使用情况\n• PolarProxy_ThreadPool - 线程池使用情况\n\n示例: 'PolarProxy_CurrentConns, PolarProxy_DBConns, PolarProxy_CPU' (注意逗号后有空格)"
                },
                "start_time": {
                    "type": "string",
                    "description": "开始时间，支持多种格式，系统会自动转换为北京时间。示例: '2025-07-10 09:00:00', '2025-07-10T01:00Z', '2025-07-10T09:00+08:00'"
                },
                "end_time": {
                    "type": "string",
                    "description": "结束时间，支持多种格式，系统会自动转换为北京时间。示例: '2025-07-10 10:00:00', '2025-07-10T02:00Z', '2025-07-10T10:00+08:00'"
                }
            },
            "required": ["dbcluster_id", "dbnode_id", "start_time", "end_time"]
        }
    },
    {
        "name": "polardb_describe_error_log_records",
        "description": "Get error log records for a specific PolarDB cluster/instance within a time range using DAS API. Helps identify database errors, connection issues, and server problems.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance_id": {
                    "type": "string",
                    "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                },
                "start_time": {
                    "type": ["integer", "string"],
                    "description": "Start time for error log query. Can be Unix timestamp in seconds/milliseconds (e.g., 1752590400) or ISO format string (e.g., '2025-07-11T20:50Z')"
                },
                "end_time": {
                    "type": ["integer", "string"],
                    "description": "End time for error log query. Can be Unix timestamp in seconds/milliseconds (e.g., 1753309143) or ISO format string (e.g., '2025-07-12T22:50Z')"
                },
                "node_id": {
                    "type": "string",
                    "description": "The ID of the database node (required, e.g., pi-6nn73sf067du4tto7)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (optional, default: 10, max: 100)"
                },
                "page_number": {
                    "type": "integer",
                    "description": "Page number for pagination (optional, default: 1)"
                }
            },
            "required": ["instance_id", "start_time", "end_time", "node_id"]
        }
    }
]

HARDCODED_RESOURCES = [
    {
        "uri": "polardb-mysql://regions",
        "name": "get_regions",
        "description": "List all available regions for Alibaba Cloud PolarDB"
    },
    {
        "uri": "polardb-mysql://clusters",
        "name": "get_clusters", 
        "description": "List all PolarDB clusters across all regions"
    }
]

class FixedMCPClient:
    def __init__(self, server_command):
        self.server_command = server_command
    
    def call_tool_with_proper_protocol(self, tool_name: str, arguments: Dict[str, Any] = None):
        """Call a tool using the complete MCP protocol sequence"""
        if arguments is None:
            arguments = {}
        
        print(f"🚀 Starting complete MCP protocol sequence for: {tool_name}")
        
        try:
            # Start process
            process = subprocess.Popen(
                self.server_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=0
            )
            
            # Wait for server to start
            time.sleep(3)
            
            # Check if process started successfully
            if process.poll() is not None:
                stderr_output = process.stderr.read()
                return {"error": f"MCP server failed to start: {stderr_output}"}
            
            # STEP 1: Initialize
            print("📤 STEP 1: Sending initialize request")
            init_message = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                        "resources": {}
                    },
                    "clientInfo": {
                        "name": "fixed-mcp-client",
                        "version": "1.0.0"
                    }
                }
            }
            
            init_response = self._send_and_wait(process, init_message, timeout=30)
            if 'error' in init_response:
                process.terminate()
                return {"error": f"Initialize failed: {init_response['error']}"}
            
            print("✅ STEP 1: Initialize successful")
            
            # STEP 2: Send initialized notification (CRITICAL!)
            print("📤 STEP 2: Sending initialized notification")
            initialized_notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {}
            }
            
            # Send notification (no response expected)
            notif_str = json.dumps(initialized_notification) + '\n'
            print(f"📤 Notification: {notif_str.strip()}")
            process.stdin.write(notif_str)
            process.stdin.flush()
            
            print("✅ STEP 2: Initialized notification sent")
            
            # STEP 3: Wait a moment for server to complete initialization
            print("⏳ STEP 3: Waiting for server to complete initialization...")
            time.sleep(1)
            
            # STEP 4: Now send the tool call
            print("📤 STEP 4: Sending tool call request")
            tool_message = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            
            print(f"🔧 Calling: {tool_name} with args: {arguments}")
            response = self._send_and_wait(process, tool_message, timeout=120)
            
            # Clean up
            process.terminate()
            process.wait()
            
            print("✅ STEP 4: Tool call completed")
            return response
            
        except Exception as e:
            if 'process' in locals():
                try:
                    process.terminate()
                except:
                    pass
            return {"error": f"Exception in protocol: {str(e)}"}
    
    def _send_and_wait(self, process, message, timeout=60):
        """Send message and wait for response with detailed logging"""
        try:
            # Send message
            message_str = json.dumps(message) + '\n'
            print(f"📤 Sending: {message_str.strip()}")
            
            process.stdin.write(message_str)
            process.stdin.flush()
            
            # Wait for response
            start_time = time.time()
            while time.time() - start_time < timeout:
                # Check if process died
                if process.poll() is not None:
                    stderr_output = process.stderr.read()
                    return {"error": f"Process died. Exit: {process.poll()}. Stderr: {stderr_output}"}
                
                # Check for response
                if hasattr(select, 'select'):
                    ready, _, _ = select.select([process.stdout], [], [], 1)
                    if ready:
                        response_str = process.stdout.readline()
                        if response_str.strip():
                            elapsed = time.time() - start_time
                            print(f"📥 Response after {elapsed:.2f}s: {response_str.strip()}")
                            try:
                                response = json.loads(response_str.strip())
                                return response
                            except json.JSONDecodeError as e:
                                print(f"❌ JSON decode error: {e}")
                                continue
                else:
                    time.sleep(0.5)
            
            elapsed = time.time() - start_time
            return {"error": f"Timeout after {elapsed:.2f} seconds"}
            
        except Exception as e:
            return {"error": f"Communication error: {str(e)}"}


def parse_json_performance_metrics(data):
    """Parse the new JSON format performance metrics - handles both old and new node formats"""
    analysis = {
        "summary": {},
        "metrics": {},
        "insights": [],
        "recommendations": []
    }
    
    try:
        # Handle NEW node performance format from your server
        if "node_id" in data and "status" in data:
            print("🎯 Parsing NEW node performance format")
            
            # Basic info from new node format
            analysis["summary"] = {
                "db_node_id": data.get("node_id", "Unknown"),
                "db_cluster_id": data.get("cluster_id", "N/A"),
                "db_type": data.get("db_type", "Unknown"),
                "db_version": data.get("db_version", "Unknown"),
                "time_range": f"{data.get('time_range', {}).get('start', 'Unknown')} to {data.get('time_range', {}).get('end', 'Unknown')}"
            }
            
            # Process metrics from new format
            metrics = data.get("metrics", [])
            
            if not metrics:
                print("⚠️ No metrics found in JSON data")
                return analysis
            
            for metric in metrics:
                try:
                    measurement = metric.get("measurement", "")
                    metric_name = metric.get("metric_name", "")
                    points = metric.get("points", [])
                    
                    print(f"🔍 Processing metric: {measurement} - {metric_name} with {len(points)} points")
                    
                    if points:
                        # Extract values from new format
                        values = []
                        timestamps = []
                        
                        for point in points:
                            try:
                                value = float(point.get("value", 0))
                                timestamp = point.get("timestamp", "")
                                values.append(value)
                                timestamps.append(timestamp)
                            except (ValueError, TypeError) as e:
                                print(f"⚠️ Skipping invalid point: {point} - Error: {e}")
                                continue
                        
                        if not values:
                            print(f"⚠️ No valid values found for {measurement} - {metric_name}")
                            continue
                        
                        metric_analysis = {
                            "values": values,
                            "avg": round(statistics.mean(values), 2),
                            "min": round(min(values), 2),
                            "max": round(max(values), 2),
                            "latest": round(values[-1], 2) if values else 0,
                            "trend": analyze_trend(values),
                            "data_points": len(values)
                        }
                        
                        # Add to metrics with friendly name
                        friendly_name = get_friendly_metric_name(measurement, metric_name)
                        analysis["metrics"][friendly_name] = metric_analysis
                        print(f"✅ Added metric: {friendly_name}")
                        
                except Exception as e:
                    print(f"⚠️ Error processing metric {measurement}-{metric_name}: {e}")
                    continue
        
        # Handle OLD cluster performance format
        elif "cluster_id" in data or "cluster_info" in data:
            print("🎯 Parsing cluster performance format")
            return parse_cluster_performance_json(data)
        
        # Handle LEGACY format 
        else:
            print("🎯 Parsing LEGACY node performance format")
            
            # Basic info from legacy format
            analysis["summary"] = {
                "db_node_id": data.get("DBNodeId", "Unknown"),
                "db_type": data.get("DBType", "Unknown"),
                "db_version": data.get("DBVersion", "Unknown"),
                "time_range": f"{data.get('StartTime', 'Unknown')} to {data.get('EndTime', 'Unknown')}"
            }
            
            # Process performance items from legacy format
            performance_items = data.get("PerformanceKeys", {}).get("PerformanceItem", [])
            
            if not performance_items:
                print("⚠️ No performance items found in legacy data")
                return analysis
            
            for item in performance_items:
                try:
                    measurement = item.get("Measurement", "")
                    metric_name = item.get("MetricName", "")
                    points = item.get("Points", {}).get("PerformanceItemValue", [])
                    
                    print(f"🔍 Processing legacy metric: {measurement} - {metric_name} with {len(points)} points")
                    
                    if points:
                        # Safely convert values to float
                        values = []
                        timestamps = []
                        
                        for point in points:
                            try:
                                value = float(point.get("Value", 0))
                                timestamp = int(point.get("Timestamp", 0))
                                values.append(value)
                                timestamps.append(timestamp)
                            except (ValueError, TypeError) as e:
                                print(f"⚠️ Skipping invalid legacy point: {point} - Error: {e}")
                                continue
                        
                        if not values:
                            print(f"⚠️ No valid values found for legacy {measurement} - {metric_name}")
                            continue
                        
                        metric_analysis = {
                            "values": values,
                            "avg": round(statistics.mean(values), 2),
                            "min": round(min(values), 2),
                            "max": round(max(values), 2),
                            "latest": round(values[-1], 2) if values else 0,
                            "trend": analyze_trend(values),
                            "data_points": len(values)
                        }
                        
                        # Add to metrics with friendly name
                        friendly_name = get_friendly_metric_name(measurement, metric_name)
                        analysis["metrics"][friendly_name] = metric_analysis
                        print(f"✅ Added legacy metric: {friendly_name}")
                        
                except Exception as e:
                    print(f"⚠️ Error processing legacy metric {measurement}-{metric_name}: {e}")
                    continue
        
        # Generate insights and recommendations
        analysis["insights"] = generate_insights(analysis["metrics"])
        analysis["recommendations"] = generate_recommendations(analysis["metrics"])
        
        print(f"✅ Analysis completed with {len(analysis['metrics'])} metrics")
        return analysis
        
    except Exception as e:
        print(f"❌ Fatal error in parse_json_performance_metrics: {e}")
        return {
            "error": "PARSE_ERROR",
            "error_message": f"Failed to parse JSON performance metrics: {str(e)}",
            "user_friendly_message": "Error occurred while processing performance data."
        }

# Add these missing functions to your fixed_mcp_protocol_web.py file:

def parse_performance_metrics(data):
    """Parse and analyze performance metrics with better error handling"""
    analysis = {
        "summary": {},
        "metrics": {},
        "insights": [],
        "recommendations": []
    }
    
    try:
        # Basic info
        analysis["summary"] = {
            "db_node_id": data.get("DBNodeId", "Unknown"),
            "db_type": data.get("DBType", "Unknown"),
            "db_version": data.get("DBVersion", "Unknown"),
            "time_range": f"{data.get('StartTime', 'Unknown')} to {data.get('EndTime', 'Unknown')}"
        }
        
        # Process performance items
        performance_items = data.get("PerformanceKeys", {}).get("PerformanceItem", [])
        
        if not performance_items:
            print("⚠️ No performance items found in data")
            return analysis
        
        for item in performance_items:
            try:
                measurement = item.get("Measurement", "")
                metric_name = item.get("MetricName", "")
                points = item.get("Points", {}).get("PerformanceItemValue", [])
                
                print(f"🔍 Processing metric: {measurement} - {metric_name} with {len(points)} points")
                
                if points:
                    # Safely convert values to float
                    values = []
                    timestamps = []
                    
                    for point in points:
                        try:
                            value = float(point.get("Value", 0))
                            timestamp = int(point.get("Timestamp", 0))
                            values.append(value)
                            timestamps.append(timestamp)
                        except (ValueError, TypeError) as e:
                            print(f"⚠️ Skipping invalid point: {point} - Error: {e}")
                            continue
                    
                    if not values:
                        print(f"⚠️ No valid values found for {measurement} - {metric_name}")
                        continue
                    
                    metric_analysis = {
                        "values": values,
                        "avg": round(statistics.mean(values), 2),
                        "min": round(min(values), 2),
                        "max": round(max(values), 2),
                        "latest": round(values[-1], 2) if values else 0,
                        "trend": analyze_trend(values),
                        "data_points": len(values)
                    }
                    
                    # Add to metrics with friendly name
                    friendly_name = get_friendly_metric_name(measurement, metric_name)
                    analysis["metrics"][friendly_name] = metric_analysis
                    print(f"✅ Added metric: {friendly_name}")
                    
            except Exception as e:
                print(f"⚠️ Error processing metric {measurement}-{metric_name}: {e}")
                continue
        
        # Generate insights and recommendations
        analysis["insights"] = generate_insights(analysis["metrics"])
        analysis["recommendations"] = generate_recommendations(analysis["metrics"])
        
        print(f"✅ Analysis completed with {len(analysis['metrics'])} metrics")
        return analysis
        
    except Exception as e:
        print(f"❌ Fatal error in parse_performance_metrics: {e}")
        return {
            "error": "PARSE_ERROR",
            "error_message": f"Failed to parse performance metrics: {str(e)}",
            "user_friendly_message": "Error occurred while processing performance data."
        }

def get_friendly_metric_name(measurement, metric_name):
    """Convert technical metric names to human-readable names"""
    name_mapping = {
        ("PolarDBDiskUsage", "mean_data_size"): "Data Storage (MB)",
        ("PolarDBDiskUsage", "mean_log_size"): "Log Storage (MB)", 
        ("PolarDBDiskUsage", "mean_sys_dir_size"): "System Directory (MB)",
        ("PolarDBDiskUsage", "mean_tmp_dir_size"): "Temporary Directory (MB)",
        ("PolarDBDiskUsage", "mean_redolog_size"): "Redo Log (MB)",
        ("PolarDBDiskUsage", "mean_binlog_size"): "Binary Log (MB)",
        ("PolarDBDiskUsage", "mean_undolog_size"): "Undo Log (MB)",
        ("PolarDBDiskUsage", "mean_other_log_size"): "Other Logs (MB)",
        ("PolarDBDiskUsage", "mean_compressed_data_size"): "Compressed Data (MB)",
        ("PolarDBCPU", "cpu_ratio"): "CPU Usage (%)",
        ("PolarDBMemory", "mem_ratio"): "Memory Usage (%)"
    }
    
    return name_mapping.get((measurement, metric_name), f"{measurement} - {metric_name}")

def analyze_trend(values):
    """Analyze if values are trending up, down, or stable"""
    if len(values) < 2:
        return "insufficient_data"
    
    try:
        # Simple trend analysis using first and last values
        first_half = values[:len(values)//2]
        second_half = values[len(values)//2:]
        
        if not first_half or not second_half:
            return "insufficient_data"
        
        first_half_avg = statistics.mean(first_half)
        second_half_avg = statistics.mean(second_half)
        
        # Handle division by zero case
        if first_half_avg == 0:
            if second_half_avg == 0:
                return "stable"  # Both are zero
            else:
                return "increasing"  # From zero to something positive
        
        diff_percent = ((second_half_avg - first_half_avg) / first_half_avg) * 100
        
        if abs(diff_percent) < 2:
            return "stable"
        elif diff_percent > 0:
            return "increasing"
        else:
            return "decreasing"
            
    except (ZeroDivisionError, ValueError, TypeError) as e:
        print(f"⚠️ Error in trend analysis: {e}")
        return "unknown"

def generate_insights(metrics):
    """Generate human-readable insights from metrics with better error handling"""
    insights = []
    
    try:
        # CPU Analysis
        if "CPU Usage (%)" in metrics:
            cpu = metrics["CPU Usage (%)"]
            if cpu["avg"] > 80:
                insights.append(f"🔴 HIGH CPU: Average CPU usage is {cpu['avg']}%, which is quite high")
            elif cpu["avg"] > 50:
                insights.append(f"🟡 MODERATE CPU: Average CPU usage is {cpu['avg']}%")
            else:
                insights.append(f"🟢 HEALTHY CPU: Average CPU usage is {cpu['avg']}%, well within normal range")
            
            if cpu["trend"] == "increasing":
                insights.append("📈 CPU usage is trending upward over the monitoring period")
        
        # Memory Analysis  
        if "Memory Usage (%)" in metrics:
            mem = metrics["Memory Usage (%)"]
            if mem["avg"] > 80:
                insights.append(f"🔴 HIGH MEMORY: Average memory usage is {mem['avg']}%")
            elif mem["avg"] > 50:
                insights.append(f"🟡 MODERATE MEMORY: Average memory usage is {mem['avg']}%")
            else:
                insights.append(f"🟢 HEALTHY MEMORY: Average memory usage is {mem['avg']}%")
        
        # Storage Analysis
        storage_metrics = [k for k in metrics.keys() if "Storage" in k or "Log" in k or "Data" in k]
        if storage_metrics:
            try:
                total_storage = sum(metrics[m]["avg"] for m in storage_metrics if "MB" in m and metrics[m]["avg"] > 0)
                if total_storage > 0:
                    insights.append(f"💾 STORAGE: Total average storage usage is approximately {total_storage:.2f} MB")
                
                # Check for log growth
                if "Log Storage (MB)" in metrics:
                    log_trend = metrics["Log Storage (MB)"]["trend"]
                    if log_trend == "increasing":
                        insights.append("📈 Log files are growing - consider log rotation policies")
            except Exception as e:
                print(f"⚠️ Error in storage analysis: {e}")
        
        if not insights:
            insights.append("📊 Performance data collected successfully")
            
    except Exception as e:
        print(f"⚠️ Error generating insights: {e}")
        insights.append("📊 Performance data available but analysis had issues")
    
    return insights

def generate_recommendations(metrics):
    """Generate actionable recommendations"""
    recommendations = []
    
    # CPU recommendations
    if "CPU Usage (%)" in metrics:
        cpu = metrics["CPU Usage (%)"]
        if cpu["avg"] > 80:
            recommendations.append("Consider scaling up the instance or optimizing queries to reduce CPU load")
        if cpu["max"] > 95:
            recommendations.append(f"CPU peaked at {cpu['max']}% - investigate workload spikes")
    
    # Memory recommendations
    if "Memory Usage (%)" in metrics:
        mem = metrics["Memory Usage (%)"]
        if mem["avg"] > 80:
            recommendations.append("Memory usage is high - consider increasing instance memory or optimizing buffer pools")
    
    # Storage recommendations
    if "Log Storage (MB)" in metrics:
        log_size = metrics["Log Storage (MB)"]["avg"]
        if log_size > 1000:
            recommendations.append(f"Log storage is {log_size} MB - implement log archiving and cleanup policies")
    
    if not recommendations:
        recommendations.append("Performance metrics look healthy - continue monitoring")
    
    return recommendations

def analyze_proxy_performance_data(performance_result):
    """Analyze proxy performance data with enhanced proxy-specific insights"""
    try:
        # Check if we have a valid result structure
        if not performance_result or 'result' not in performance_result:
            return {"error": "Invalid proxy performance result structure"}
        
        # Extract the content from the MCP result
        result_content = performance_result.get('result', {})
        content_list = result_content.get('content', [])
        
        if not content_list:
            return {"error": "No content in proxy performance result"}
        
        # Get the text content
        text_content = content_list[0].get('text', '')
        print(f"🔍 Raw proxy performance content: {text_content[:300]}...")  # DEBUG: Show first 300 chars
        
        # Parse JSON format from the enhanced server
        try:
            json_data = json.loads(text_content)
            print("✅ Successfully parsed proxy performance as JSON from enhanced server format")
            return parse_proxy_performance_json(json_data)
        except json.JSONDecodeError:
            print("⚠️ Not JSON format, trying other parsers for proxy performance...")
        
        # Check for various error patterns
        if "代理性能查询失败" in text_content or "❌" in text_content:
            error_msg = text_content.replace("❌", "").strip()
            return {
                "error": "API_ERROR",
                "error_message": error_msg,
                "error_type": "proxy_performance_error",
                "user_friendly_message": "无法获取代理性能数据，请检查集群ID、节点ID和时间范围设置。"
            }
        
        # Check for NO_DATA scenarios
        if "no_data" in text_content.lower() or "no performance data" in text_content.lower():
            return {
                "error": "NO_DATA",
                "error_message": "指定时间范围内没有代理性能数据",
                "user_friendly_message": "没有找到指定时间范围的代理性能数据，请尝试更近期的时间段。"
            }
        
        # If we get here, we couldn't identify the data format
        return {
            "error": "UNKNOWN_FORMAT",
            "error_message": f"无法识别的代理性能响应格式: {text_content[:100]}...",
            "user_friendly_message": "收到意外的代理性能数据格式。"
        }
    
    except Exception as e:
        return {
            "error": "ANALYSIS_EXCEPTION",
            "error_message": f"代理性能数据分析失败: {str(e)}",
            "user_friendly_message": "分析代理性能数据时发生意外错误。"
        }

def parse_proxy_performance_json(data):
    """Parse the enhanced proxy performance JSON format with comprehensive analysis"""
    analysis = {
        "summary": {},
        "metrics": {},
        "insights": [],
        "recommendations": [],
        "alerts": [],
        "time_info": {}
    }
    
    try:
        # Check if this is the proxy performance response format
        if data.get("performance_type") != "proxy":
            print("⚠️ Not proxy performance data, using generic parser")
            return parse_json_performance_metrics(data)
        
        # Extract basic cluster info
        cluster_info = data.get("cluster_info", {})
        time_range = data.get("time_range", {})
        performance_analysis = data.get("performance_analysis", {})
        request_info = data.get("request_info", {})
        
        # Build summary
        analysis["summary"] = {
            "cluster_id": cluster_info.get("cluster_id", "Unknown"),
            "db_type": cluster_info.get("db_type", "Unknown"),
            "db_version": cluster_info.get("db_version", "Unknown"),
            "time_range": f"{time_range.get('start', 'Unknown')} to {time_range.get('end', 'Unknown')}",
            "analysis_time": performance_analysis.get("summary", {}).get("analysis_time", "Unknown"),
            "total_metrics": performance_analysis.get("summary", {}).get("total_metrics", 0),
            "performance_type": "proxy"
        }
        
        # Extract time information
        analysis["time_info"] = {
            "original_start": time_range.get("original_start", "Unknown"),
            "original_end": time_range.get("original_end", "Unknown"),
            "api_start": time_range.get("start", "Unknown"), 
            "api_end": time_range.get("end", "Unknown"),
            "time_conversion": "Beijing time converted to UTC for API"
        }
        
        # Process enhanced metrics analysis
        metrics_analysis = performance_analysis.get("metrics_analysis", {})
        for metric_name, metric_data in metrics_analysis.items():
            analysis["metrics"][metric_name] = {
                "measurement": metric_data.get("measurement", ""),
                "metric_name": metric_data.get("metric_name", ""),
                "data_points": metric_data.get("data_points", 0),
                "average": metric_data.get("average", 0),
                "minimum": metric_data.get("minimum", 0),
                "maximum": metric_data.get("maximum", 0),
                "latest": metric_data.get("latest", 0),
                "trend": metric_data.get("trend", "unknown"),
                "variation": metric_data.get("variation", 0),
                "stability": metric_data.get("stability", "unknown")
            }
        
        # Extract insights, recommendations, and alerts
        analysis["insights"] = performance_analysis.get("performance_insights", [])
        analysis["recommendations"] = performance_analysis.get("recommendations", [])
        analysis["alerts"] = performance_analysis.get("alerts", [])
        
        # Add request information
        analysis["request_info"] = {
            "validated_key": request_info.get("validated_key", "Unknown"),
            "original_key": request_info.get("original_key", "Unknown"),
            "warnings": request_info.get("warnings", []),
            "request_id": request_info.get("request_id", "Unknown")
        }
        
        print(f"✅ Proxy performance analysis completed with {len(analysis['metrics'])} metrics")
        return analysis
        
    except Exception as e:
        print(f"❌ Fatal error in parse_proxy_performance_json: {e}")
        return {
            "error": "PARSE_ERROR",
            "error_message": f"解析代理性能JSON数据失败: {str(e)}",
            "user_friendly_message": "处理代理性能数据时发生错误。"
        }

def format_proxy_performance_analysis(analysis):
    """Format proxy performance analysis into a comprehensive readable summary"""
    
    # Handle error cases
    if "error" in analysis:
        error_type = analysis.get("error", "UNKNOWN")
        user_message = analysis.get("user_friendly_message", "发生了一个错误")
        technical_message = analysis.get("error_message", "没有详细信息")
        
        if error_type == "API_ERROR":
            return f"""❌ **代理性能数据不可用**

🚨 **问题**: API调用失败
📋 **详情**: {user_message}

🔧 **可能的解决方案**:
- 检查集群ID和节点ID是否正确
- 验证时间范围设置（推荐1-24小时）
- 确认网络连接和阿里云凭证有效
- 确保集群已启用代理服务
- 确认集群和节点处于运行状态
- 稍后重试，这可能是临时问题

🔍 **技术详情**: {technical_message[:200]}...
"""
        else:
            return f"""❌ **代理性能分析错误**

🚨 **问题**: {error_type}
📋 **详情**: {user_message}

🔍 **技术详情**: {technical_message}
"""
    
    # Handle successful analysis
    summary = analysis.get('summary', {})
    cluster_id = summary.get('cluster_id', 'Unknown')
    db_type = summary.get('db_type', 'Unknown')
    db_version = summary.get('db_version', 'Unknown')
    time_range = summary.get('time_range', 'Unknown')
    total_metrics = summary.get('total_metrics', 0)
    
    # Time information
    time_info = analysis.get('time_info', {})
    original_start = time_info.get('original_start', 'Unknown')
    original_end = time_info.get('original_end', 'Unknown')
    
    summary_text = f"""📊 **PolarDB代理性能分析报告**

🖥️ **集群信息**: {cluster_id}
🔧 **数据库引擎**: {db_type} {db_version}
⏰ **查询时间段**: {original_start} ~ {original_end} (北京时间)
📈 **代理性能指标数量**: {total_metrics} 个
🔌 **性能类型**: 代理(Proxy)性能

"""
    
    # Request information
    request_info = analysis.get('request_info', {})
    if request_info.get('warnings'):
        summary_text += f"⚠️ **处理提醒**:\n"
        for warning in request_info['warnings']:
            summary_text += f"• {warning}\n"
        summary_text += "\n"
    
    # Key metrics summary
    summary_text += f"📈 **关键代理性能指标**:\n"
    for metric_name, data in analysis['metrics'].items():
        trend_emoji = {"increasing": "📈", "decreasing": "📉", "stable": "➡️"}.get(data['trend'], "❓")
        stability_emoji = {"stable": "🟢", "variable": "🟡"}.get(data['stability'], "❓")
        
        summary_text += f"• **{metric_name}**: "
        summary_text += f"平均: {data['average']}, 最小: {data['minimum']}, 最大: {data['maximum']}, "
        summary_text += f"最新: {data['latest']} {trend_emoji} {stability_emoji}\n"
    
    # Performance insights
    insights = analysis.get('insights', [])
    if insights:
        summary_text += f"\n💡 **代理性能洞察**:\n"
        for insight in insights:
            summary_text += f"• {insight}\n"
    
    # Alerts (if any)
    alerts = analysis.get('alerts', [])
    if alerts:
        summary_text += f"\n🚨 **代理性能警报**:\n"
        for alert in alerts:
            level_emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(alert.get('level', 'info'), "📢")
            summary_text += f"• {level_emoji} **{alert.get('metric', '未知指标')}**: {alert.get('message', '无详情')}\n"
            if alert.get('recommendation'):
                summary_text += f"  💡 建议: {alert['recommendation']}\n"
    
    # Recommendations
    recommendations = analysis.get('recommendations', [])
    if recommendations:
        summary_text += f"\n🎯 **代理优化建议**:\n"
        for rec in recommendations:
            summary_text += f"• {rec}\n"
    
    # Additional information
    summary_text += f"\n📋 **请求详情**:\n"
    summary_text += f"• 查询指标: {request_info.get('validated_key', 'Unknown')}\n"
    summary_text += f"• 请求ID: {request_info.get('request_id', 'Unknown')}\n"
    
    return summary_text

def parse_llm_response(response_text):
    """Parse LLM response that might contain JSON + explanatory text"""
    try:
        # First try to parse as pure JSON
        return json.loads(response_text.strip())
    except json.JSONDecodeError:
        # If that fails, try to extract JSON from mixed content
        lines = response_text.strip().split('\n')
        json_lines = []
        in_json = False
        brace_count = 0
        
        for line in lines:
            stripped_line = line.strip()
            
            # Start capturing when we see opening brace
            if stripped_line.startswith('{'):
                in_json = True
                brace_count += line.count('{') - line.count('}')
                json_lines.append(line)
            elif in_json:
                # Stop if we hit explanatory text markers
                if any(stripped_line.startswith(marker) for marker in [
                    'Note:', 'Notes:', 'If you need', 'Please provide', 
                    'You can also', 'Additional', 'Remember', 'Important:'
                ]):
                    break
                
                # Continue collecting JSON lines
                brace_count += line.count('{') - line.count('}')
                json_lines.append(line)
                
                # Stop when braces are balanced (complete JSON)
                if brace_count == 0:
                    break
        
        if json_lines:
            json_text = '\n'.join(json_lines)
            try:
                return json.loads(json_text)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON extracted: {e}")
        
        raise ValueError("No valid JSON found in response")

# Add these functions to your fixed_mcp_protocol_web.py file

def analyze_cluster_performance_data(performance_result):
    """Analyze cluster performance data with enhanced Beijing time support and comprehensive metrics"""
    try:
        # Check if we have a valid result structure
        if not performance_result or 'result' not in performance_result:
            return {"error": "Invalid cluster performance result structure"}
        
        # Extract the content from the MCP result
        result_content = performance_result.get('result', {})
        content_list = result_content.get('content', [])
        
        if not content_list:
            return {"error": "No content in cluster performance result"}
        
        # Get the text content
        text_content = content_list[0].get('text', '')
        print(f"🔍 Raw cluster performance content: {text_content[:300]}...")  # DEBUG: Show first 300 chars
        
        # Parse JSON format from the enhanced server
        try:
            json_data = json.loads(text_content)
            print("✅ Successfully parsed cluster performance as JSON from enhanced server format")
            return parse_cluster_performance_json(json_data)
        except json.JSONDecodeError:
            print("⚠️ Not JSON format, trying other parsers for cluster performance...")
        
        # Check for various error patterns
        if "集群性能查询失败" in text_content or "❌" in text_content:
            error_msg = text_content.replace("❌", "").strip()
            return {
                "error": "API_ERROR",
                "error_message": error_msg,
                "error_type": "cluster_performance_error",
                "user_friendly_message": "无法获取集群性能数据，请检查集群ID和时间范围设置。"
            }
        
        # Check for NO_DATA scenarios
        if "no_data" in text_content.lower() or "no performance data" in text_content.lower():
            return {
                "error": "NO_DATA",
                "error_message": "指定时间范围内没有性能数据",
                "user_friendly_message": "没有找到指定时间范围的集群性能数据，请尝试更近期的时间段。"
            }
        
        # If we get here, we couldn't identify the data format
        return {
            "error": "UNKNOWN_FORMAT",
            "error_message": f"无法识别的集群性能响应格式: {text_content[:100]}...",
            "user_friendly_message": "收到意外的集群性能数据格式。"
        }
    
    except Exception as e:
        return {
            "error": "ANALYSIS_EXCEPTION",
            "error_message": f"集群性能数据分析失败: {str(e)}",
            "user_friendly_message": "分析集群性能数据时发生意外错误。"
        }

def parse_cluster_performance_json(data):
    """Parse the enhanced cluster performance JSON format with comprehensive analysis"""
    analysis = {
        "summary": {},
        "metrics": {},
        "insights": [],
        "recommendations": [],
        "alerts": [],
        "time_info": {}
    }
    
    try:
        # Extract basic cluster info
        cluster_info = data.get("cluster_info", {})
        time_range = data.get("time_range", {})
        performance_analysis = data.get("performance_analysis", {})
        request_info = data.get("request_info", {})
        
        # Build summary
        analysis["summary"] = {
            "cluster_id": cluster_info.get("cluster_id", "Unknown"),
            "db_type": cluster_info.get("db_type", "Unknown"),
            "db_version": cluster_info.get("db_version", "Unknown"),
            "time_range": f"{time_range.get('start', 'Unknown')} to {time_range.get('end', 'Unknown')}",
            "analysis_time": performance_analysis.get("summary", {}).get("analysis_time", "Unknown"),
            "total_metrics": performance_analysis.get("summary", {}).get("total_metrics", 0)
        }
        
        # Extract time information
        analysis["time_info"] = {
            "original_start": time_range.get("original_start", "Unknown"),
            "original_end": time_range.get("original_end", "Unknown"),
            "api_start": time_range.get("start", "Unknown"), 
            "api_end": time_range.get("end", "Unknown"),
            "time_conversion": "Beijing time converted to UTC for API"
        }
        
        # Process enhanced metrics analysis
        metrics_analysis = performance_analysis.get("metrics_analysis", {})
        for metric_name, metric_data in metrics_analysis.items():
            analysis["metrics"][metric_name] = {
                "measurement": metric_data.get("measurement", ""),
                "metric_name": metric_data.get("metric_name", ""),
                "data_points": metric_data.get("data_points", 0),
                "average": metric_data.get("average", 0),
                "minimum": metric_data.get("minimum", 0),
                "maximum": metric_data.get("maximum", 0),
                "latest": metric_data.get("latest", 0),
                "trend": metric_data.get("trend", "unknown"),
                "variation": metric_data.get("variation", 0),
                "stability": metric_data.get("stability", "unknown")
            }
        
        # Extract insights, recommendations, and alerts
        analysis["insights"] = performance_analysis.get("performance_insights", [])
        analysis["recommendations"] = performance_analysis.get("recommendations", [])
        analysis["alerts"] = performance_analysis.get("alerts", [])
        
        # Add request information
        analysis["request_info"] = {
            "validated_key": request_info.get("validated_key", "Unknown"),
            "original_key": request_info.get("original_key", "Unknown"),
            "warnings": request_info.get("warnings", []),
            "request_id": request_info.get("request_id", "Unknown")
        }
        
        print(f"✅ Cluster performance analysis completed with {len(analysis['metrics'])} metrics")
        return analysis
        
    except Exception as e:
        print(f"❌ Fatal error in parse_cluster_performance_json: {e}")
        return {
            "error": "PARSE_ERROR",
            "error_message": f"解析集群性能JSON数据失败: {str(e)}",
            "user_friendly_message": "处理集群性能数据时发生错误。"
        }

def format_cluster_performance_analysis(analysis):
    """Format cluster performance analysis into a comprehensive readable summary"""
    
    # Handle error cases
    if "error" in analysis:
        error_type = analysis.get("error", "UNKNOWN")
        user_message = analysis.get("user_friendly_message", "发生了一个错误")
        technical_message = analysis.get("error_message", "没有详细信息")
        
        if error_type == "API_ERROR":
            return f"""❌ **集群性能数据不可用**

🚨 **问题**: API调用失败
📋 **详情**: {user_message}

🔧 **可能的解决方案**:
- 检查集群ID是否正确
- 验证时间范围设置（推荐1-24小时）
- 确认网络连接和阿里云凭证有效
- 确保集群处于运行状态
- 稍后重试，这可能是临时问题

🔍 **技术详情**: {technical_message[:200]}...
"""
        else:
            return f"""❌ **集群性能分析错误**

🚨 **问题**: {error_type}
📋 **详情**: {user_message}

🔍 **技术详情**: {technical_message}
"""
    
    # Handle successful analysis
    summary = analysis.get('summary', {})
    cluster_id = summary.get('cluster_id', 'Unknown')
    db_type = summary.get('db_type', 'Unknown')
    db_version = summary.get('db_version', 'Unknown')
    time_range = summary.get('time_range', 'Unknown')
    total_metrics = summary.get('total_metrics', 0)
    
    # Time information
    time_info = analysis.get('time_info', {})
    original_start = time_info.get('original_start', 'Unknown')
    original_end = time_info.get('original_end', 'Unknown')
    
    summary_text = f"""📊 **PolarDB集群性能分析报告**

🖥️ **集群信息**: {cluster_id}
🔧 **数据库引擎**: {db_type} {db_version}
⏰ **查询时间段**: {original_start} ~ {original_end} (北京时间)
📈 **性能指标数量**: {total_metrics} 个

"""
    
    # Request information
    request_info = analysis.get('request_info', {})
    if request_info.get('warnings'):
        summary_text += f"⚠️ **处理提醒**:\n"
        for warning in request_info['warnings']:
            summary_text += f"• {warning}\n"
        summary_text += "\n"
    
    # Key metrics summary
    summary_text += f"📈 **关键性能指标**:\n"
    for metric_name, data in analysis['metrics'].items():
        trend_emoji = {"increasing": "📈", "decreasing": "📉", "stable": "➡️"}.get(data['trend'], "❓")
        stability_emoji = {"stable": "🟢", "variable": "🟡"}.get(data['stability'], "❓")
        
        summary_text += f"• **{metric_name}**: "
        summary_text += f"平均: {data['average']}, 最小: {data['minimum']}, 最大: {data['maximum']}, "
        summary_text += f"最新: {data['latest']} {trend_emoji} {stability_emoji}\n"
    
    # Performance insights
    insights = analysis.get('insights', [])
    if insights:
        summary_text += f"\n💡 **性能洞察**:\n"
        for insight in insights:
            summary_text += f"• {insight}\n"
    
    # Alerts (if any)
    alerts = analysis.get('alerts', [])
    if alerts:
        summary_text += f"\n🚨 **性能警报**:\n"
        for alert in alerts:
            level_emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(alert.get('level', 'info'), "📢")
            summary_text += f"• {level_emoji} **{alert.get('metric', '未知指标')}**: {alert.get('message', '无详情')}\n"
            if alert.get('recommendation'):
                summary_text += f"  💡 建议: {alert['recommendation']}\n"
    
    # Recommendations
    recommendations = analysis.get('recommendations', [])
    if recommendations:
        summary_text += f"\n🎯 **优化建议**:\n"
        for rec in recommendations:
            summary_text += f"• {rec}\n"
    
    # Additional information
    summary_text += f"\n📋 **请求详情**:\n"
    summary_text += f"• 查询指标: {request_info.get('validated_key', 'Unknown')}\n"
    summary_text += f"• 请求ID: {request_info.get('request_id', 'Unknown')}\n"
    
    return summary_text

def analyze_connectivity_result(connectivity_result):
    """Analyze connectivity test result and provide insights"""
    try:
        # Check if we have a valid result structure
        if not connectivity_result or 'result' not in connectivity_result:
            return {"error": "Invalid connectivity result structure"}
        
        # Extract the content from the MCP result
        result_content = connectivity_result.get('result', {})
        content_list = result_content.get('content', [])
        
        if not content_list:
            return {"error": "No content in connectivity result"}
        
        # Get the text content
        text_content = content_list[0].get('text', '')
        
        # Check for various patterns in the response
        if "✅ SUCCESS" in text_content:
            return {
                "status": "success",
                "result": "connected",
                "summary": "🟢 连接测试成功 - 源IP可以成功连接到数据库集群",
                "details": "网络连通性良好，IP地址已在白名单中，可以正常建立数据库连接。",
                "recommendations": [
                    "可以使用此IP地址配置应用程序连接",
                    "获取连接端点信息以完成数据库配置",
                    "确保数据库账号已创建并具有适当权限"
                ]
            }
        elif "❌ FAILED" in text_content:
            analysis = {
                "status": "failed",
                "result": "connection_failed",
                "summary": "🔴 连接测试失败",
                "details": "",
                "recommendations": []
            }
            
            # Check for specific error patterns
            if "SRC_IP_NOT_IN_USER_WHITELIST" in text_content:
                analysis["error_code"] = "SRC_IP_NOT_IN_USER_WHITELIST"
                analysis["details"] = "源IP地址不在集群访问白名单中，连接被安全策略阻止。"
                analysis["recommendations"] = [
                    "使用 polardb_modify_db_cluster_access_whitelist 将IP地址添加到白名单",
                    "检查当前白名单配置确认安全策略",
                    "添加IP后重新测试连接性",
                    "考虑使用CIDR范围而不是单个IP地址"
                ]
            else:
                analysis["details"] = "连接失败，可能由于网络问题、集群状态或其他配置问题。"
                analysis["recommendations"] = [
                    "检查集群ID是否正确且集群正在运行",
                    "验证网络连接和防火墙配置",
                    "确认集群不在维护模式",
                    "检查源IP地址格式是否正确"
                ]
            
            return analysis
        elif "❌ INVALID_CLUSTER_ID_FORMAT" in text_content:
            return {
                "status": "error",
                "result": "invalid_cluster_id",
                "summary": "🔴 集群ID格式错误",
                "details": "提供的集群ID格式无效，必须以'pc-'开头。",
                "recommendations": [
                    "使用 polardb_describe_db_clusters 查找正确的集群ID",
                    "确保使用集群ID（pc-xxx）而不是节点ID（pi-xxx）",
                    "检查集群ID拼写和格式"
                ]
            }
        elif "❌ INVALID_IP_FORMAT" in text_content:
            return {
                "status": "error", 
                "result": "invalid_ip",
                "summary": "🔴 IP地址格式错误",
                "details": "提供的IP地址格式无效，必须是有效的IPv4地址。",
                "recommendations": [
                    "使用正确的IPv4格式：xxx.xxx.xxx.xxx",
                    "确保每个段都在0-255范围内",
                    "检查IP地址拼写和格式"
                ]
            }
        else:
            # Unknown format
            return {
                "status": "unknown",
                "result": "unknown_format",
                "summary": "❓ 连接测试结果格式未知",
                "details": "收到意外的响应格式，无法解析连接测试结果。",
                "recommendations": [
                    "检查工具调用参数是否正确",
                    "验证集群和IP地址格式",
                    "重新尝试连接测试"
                ]
            }
    
    except Exception as e:
        return {
            "status": "error",
            "result": "analysis_error", 
            "summary": "❌ 连接测试分析失败",
            "details": f"分析连接测试结果时发生错误: {str(e)}",
            "recommendations": [
                "检查连接测试响应格式",
                "验证输入参数是否正确",
                "重新执行连接测试"
            ]
        }

def format_connectivity_analysis(analysis):
    """Format connectivity analysis into a readable summary"""
    
    if analysis.get("status") == "success":
        return f"""✅ **数据库连接测试成功**

{analysis.get('summary', '')}

📋 **详细信息**: {analysis.get('details', '')}

🎯 **建议操作**:
{chr(10).join(f'• {rec}' for rec in analysis.get('recommendations', []))}
"""
    
    elif analysis.get("status") == "failed":
        return f"""❌ **数据库连接测试失败**

{analysis.get('summary', '')}

📋 **失败原因**: {analysis.get('details', '')}

🔧 **解决方案**:
{chr(10).join(f'• {rec}' for rec in analysis.get('recommendations', []))}

{f"🚨 **错误代码**: {analysis.get('error_code', '')}" if analysis.get('error_code') else ''}
"""
    
    elif analysis.get("status") == "error":
        return f"""⚠️ **连接测试参数错误**

{analysis.get('summary', '')}

📋 **错误详情**: {analysis.get('details', '')}

🔧 **修正建议**:
{chr(10).join(f'• {rec}' for rec in analysis.get('recommendations', []))}
"""
    
    else:
        return f"""❓ **连接测试结果未知**

{analysis.get('summary', '')}

📋 **详情**: {analysis.get('details', '')}

💡 **建议**:
{chr(10).join(f'• {rec}' for rec in analysis.get('recommendations', []))}
"""

# Update the analyze_performance_data function to handle cluster performance
# In your fixed_mcp_protocol_web.py, update the analyze_performance_data function:

def analyze_performance_data(performance_result):
    """Enhanced analyze_performance_data function that handles both node and cluster performance"""
    try:
        # Check if we have a valid result structure
        if not performance_result or 'result' not in performance_result:
            return {"error": "Invalid performance result structure"}
        
        # Extract the content from the MCP result
        result_content = performance_result.get('result', {})
        content_list = result_content.get('content', [])
        
        if not content_list:
            return {"error": "No content in performance result"}
        
        # Get the text content
        text_content = content_list[0].get('text', '')
        print(f"🔍 Raw text content: {text_content[:200]}...")  # DEBUG: Show first 200 chars
        
        # NEW: Check for JSON format from the updated server
        try:
            json_data = json.loads(text_content)
            print("✅ Successfully parsed as JSON from new server format")
            
            # FIXED: Detect proxy vs node vs cluster performance based on JSON structure
            if json_data.get("performance_type") == "proxy":
                print("🎯 Detected proxy performance data")
                return parse_proxy_performance_json(json_data)
            elif "cluster_info" in json_data or "performance_analysis" in json_data:
                print("🎯 Detected cluster performance data")
                return parse_cluster_performance_json(json_data)
            elif "node_id" in json_data or json_data.get("status") == "success":
                print("🎯 Detected node performance data")
                return parse_json_performance_metrics(json_data)  # This handles the node format
            else:
                print("🔍 Unknown JSON structure, trying node format")
                return parse_json_performance_metrics(json_data)
                
        except json.JSONDecodeError:
            print("⚠️ Not JSON format, trying other parsers...")
        
        # Continue with existing error checking and legacy format handling...
        
        # Check for various error patterns first
        if "Error retrieving performance data:" in text_content:
            error_msg = text_content.replace("Error retrieving performance data:", "").strip()
            return {
                "error": "API_ERROR",
                "error_message": error_msg,
                "error_type": "network_timeout" if "timed out" in error_msg else "api_error",
                "user_friendly_message": "Unable to retrieve performance data due to network connectivity issues. Please try again later."
            }
        
        # Check for NO_PERFORMANCE_DATA format
        if "NO_PERFORMANCE_DATA" in text_content:
            return {
                "error": "NO_DATA",
                "error_message": "No performance data available for the specified time range",
                "user_friendly_message": "No performance data found for the requested time period. Try a more recent time range."
            }
        
        # Legacy format handling for backwards compatibility
        if "DB node performance (raw response):" in text_content:
            # Extract the dict/JSON from the response
            dict_start = text_content.find('{')
            if dict_start != -1:
                dict_str = text_content[dict_start:]
                
                # Try to parse as JSON first
                try:
                    json_data = json.loads(dict_str)
                    print("✅ Successfully parsed legacy format as JSON")
                    return parse_performance_metrics(json_data)
                except json.JSONDecodeError:
                    print("⚠️ JSON parsing failed, trying Python dict evaluation...")
                    
                    # Try to parse as Python dict using ast.literal_eval (safe evaluation)
                    try:
                        import ast
                        python_data = ast.literal_eval(dict_str)
                        print("✅ Successfully parsed as Python dict")
                        return parse_performance_metrics(python_data)
                    except (ValueError, SyntaxError) as e:
                        print(f"❌ Python dict parsing also failed: {e}")
                        
                        # Last resort: try to convert Python dict format to JSON format
                        try:
                            # Replace single quotes with double quotes and handle True/False/None
                            json_str = dict_str.replace("'", '"')
                            json_str = json_str.replace('True', 'true')
                            json_str = json_str.replace('False', 'false')
                            json_str = json_str.replace('None', 'null')
                            
                            json_data = json.loads(json_str)
                            print("✅ Successfully converted Python dict to JSON")
                            return parse_performance_metrics(json_data)
                        except json.JSONDecodeError as e:
                            return {
                                "error": "PARSE_ERROR",
                                "error_message": f"Could not parse performance data: {str(e)}",
                                "user_friendly_message": "Received malformed performance data from the API.",
                                "raw_sample": dict_str[:500] + "..." if len(dict_str) > 500 else dict_str
                            }
        
         # Check if this is connectivity test data
        if "CONNECTIVITY TEST" in text_content or "ConnCheckResult" in text_content:
            print("🎯 Detected connectivity test data, using connectivity analysis")
            return analyze_connectivity_result(performance_result)

        # If we get here, we couldn't identify the data format
        return {
            "error": "UNKNOWN_FORMAT",
            "error_message": f"Unrecognized response format: {text_content[:100]}...",
            "user_friendly_message": "Received unexpected response format from the performance API."
        }
    
    except Exception as e:
        return {
            "error": "ANALYSIS_EXCEPTION",
            "error_message": f"Analysis failed: {str(e)}",
            "user_friendly_message": "An unexpected error occurred while analyzing performance data."
        }

def format_performance_analysis(analysis):
    """Enhanced format_performance_analysis that handles both node and cluster performance"""

    # Check if this is connectivity analysis
    if "connectivity" in str(analysis).lower() or analysis.get('status') in ['success', 'failed']:
        if 'connection' in str(analysis) or 'connectivity' in str(analysis):
            return format_connectivity_analysis(analysis)

    # Check if this is proxy performance analysis
    if analysis.get('summary', {}).get('performance_type') == 'proxy':
        return format_proxy_performance_analysis(analysis)

    # Handle error cases
    if "error" in analysis:
        error_type = analysis.get("error", "UNKNOWN")
        user_message = analysis.get("user_friendly_message", "An error occurred")
        technical_message = analysis.get("error_message", "No details available")
        
        if error_type == "NETWORK_ERROR" or error_type == "API_ERROR":
            return f"""❌ **PERFORMANCE DATA UNAVAILABLE**

🚨 **Issue**: Network connectivity problem
📋 **Details**: {user_message}

🔧 **Possible Solutions**:
- Check your internet connection
- Verify your Alibaba Cloud credentials are valid
- Ensure the database node/cluster is accessible from your network
- Try again in a few minutes as this may be a temporary issue

🔍 **Technical Details**: {technical_message[:200]}...
"""
        else:
            return f"""❌ **PERFORMANCE ANALYSIS ERROR**

🚨 **Issue**: {error_type}
📋 **Details**: {user_message}

🔍 **Technical Details**: {technical_message}
"""
    
    # Check if this is cluster performance analysis
    if "cluster_id" in analysis.get('summary', {}) or "cluster_info" in analysis:
        return format_cluster_performance_analysis(analysis)
    
    # Handle node performance analysis (existing logic)
    summary = analysis.get('summary', {})
    cluster_id = summary.get('db_cluster_id', summary.get('db_node_id', 'Unknown'))
    db_type = summary.get('db_type', 'Unknown')
    db_version = summary.get('db_version', 'Unknown')
    time_range = summary.get('time_range', 'Unknown')
    
    summary_text = f"""📊 **PERFORMANCE ANALYSIS SUMMARY**

🖥️ **Database**: {cluster_id}
🔧 **Engine**: {db_type} {db_version}
⏰ **Time Period**: {time_range}

📈 **KEY METRICS**:
"""
    
    for metric_name, data in analysis['metrics'].items():
        trend_emoji = {"increasing": "📈", "decreasing": "📉", "stable": "➡️"}.get(data['trend'], "❓")
        summary_text += f"• **{metric_name}**: Avg: {data['avg']}, Min: {data['min']}, Max: {data['max']} {trend_emoji}\n"
    
    summary_text += f"\n💡 **INSIGHTS**:\n"
    for insight in analysis['insights']:
        summary_text += f"• {insight}\n"
    
    summary_text += f"\n🎯 **RECOMMENDATIONS**:\n"
    for rec in analysis['recommendations']:
        summary_text += f"• {rec}\n"
    
    return summary_text

# Update the HARDCODED_TOOLS list by replacing the existing polardb_describe_db_cluster_performance entry:

# Find and replace the existing polardb_describe_db_cluster_performance tool in HARDCODED_TOOLS with:
{
    "name": "polardb_describe_db_cluster_performance",
    "description": "获取PolarDB集群在指定时间范围内的性能指标数据，支持多种性能指标分析和北京时间自动转换。系统会自动进行性能分析并提供优化建议。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "db_cluster_id": {
                "type": "string",
                "description": "PolarDB集群ID (例如: pc-1udt379icjl5032b1)"
            },
            "key": {
                "type": "string", 
                "description": "性能指标，逗号分隔，最多5个。不提供则使用默认指标（PolarDBDiskUsage, PolarDBCPU, PolarDBMemory, PolarDBConnections, PolarDBIOSTAT）。可用指标: PolarDBDiskUsage(磁盘), PolarDBCPU(CPU), PolarDBMemory(内存), PolarDBConnections(连接), PolarDBIOSTAT(IOPS), PolarDBQPSTPS(查询统计), PolarDBNetworkTraffic(网络), PolarDBInnoDBBufferRatio(缓冲池), PolarDBInnoDBDataReadWrite(数据读写), PolarDBInnoDBBufferRequests(缓冲池请求), PolarDBInnoDBLogWrites(日志写入), PolarDBCOMDML(DML操作), PolarDBRowDML(行DML), PolarDBReplicaLag(副本延迟)"
            },
            "start_time": {
                "type": "string",
                "description": "开始时间，支持多种格式，系统会自动转换为北京时间。示例: '2025-07-10 09:00:00', '2025-07-10T01:00Z', '2025-07-10T09:00+08:00'"
            },
            "end_time": {
                "type": "string",
                "description": "结束时间，支持多种格式，系统会自动转换为北京时间。示例: '2025-07-10 10:00:00', '2025-07-10T02:00Z', '2025-07-10T10:00+08:00'"
            }
        },
        "required": ["db_cluster_id", "start_time", "end_time"]
    }
}

def create_tool_descriptions() -> str:
    """Create tool descriptions for LLM context"""
    descriptions = []
    for tool in HARDCODED_TOOLS:
        desc = f"- {tool['name']}: {tool.get('description', 'No description')}"
        if 'inputSchema' in tool and 'properties' in tool['inputSchema']:
            props = tool['inputSchema']['properties']
            required = tool['inputSchema'].get('required', [])
            params = []
            for prop_name, prop_def in props.items():
                req_marker = " (required)" if prop_name in required else " (optional)"
                params.append(f"{prop_name}{req_marker}: {prop_def.get('description', '')}")
            if params:
                desc += f"\n  Parameters: {', '.join(params)}"
        descriptions.append(desc)
    
    return "\n".join(descriptions)

# Create Flask app
app = Flask(__name__)

# Global MCP client
mcp_client = None

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/tools')
def get_tools():
    """Return hardcoded tools list"""
    print("🔍 API request for tools (using hardcoded list)")
    return jsonify({"tools": HARDCODED_TOOLS})

@app.route('/api/resources')
def get_resources():
    """Return hardcoded resources list"""
    print("🔍 API request for resources (using hardcoded list)")
    return jsonify({"resources": HARDCODED_RESOURCES})

@app.route('/api/call-tool', methods=['POST'])
def call_tool():
    """Call a tool using proper MCP protocol"""
    if not mcp_client:
        return jsonify({"error": "MCP client not initialized"})
    
    data = request.json
    tool_name = data.get('tool')
    arguments = data.get('arguments', {})
    
    print(f"🔧 Manual tool call: {tool_name} with args: {arguments}")
    
    try:
        result = mcp_client.call_tool_with_proper_protocol(tool_name, arguments)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/test-analysis')
def test_analysis():
    """Test the analysis function with sample data"""
    # Sample performance data (simplified version of your actual data)
    sample_data = {
        "DBNodeId": "pi-dj1w3rx6y52284dww",
        "DBType": "MySQL", 
        "DBVersion": "8.0",
        "StartTime": "2025-06-05T16:20:00Z",
        "EndTime": "2025-06-05T17:20:00Z",
        "PerformanceKeys": {
            "PerformanceItem": [
                {
                    "Measurement": "PolarDBCPU",
                    "MetricName": "cpu_ratio", 
                    "Points": {
                        "PerformanceItemValue": [
                            {"Timestamp": 1749140400000, "Value": "5.94"},
                            {"Timestamp": 1749140460000, "Value": "5.95"},
                            {"Timestamp": 1749140520000, "Value": "5.87"}
                        ]
                    }
                },
                {
                    "Measurement": "PolarDBMemory",
                    "MetricName": "mem_ratio",
                    "Points": {
                        "PerformanceItemValue": [
                            {"Timestamp": 1749140400000, "Value": "17.06"},
                            {"Timestamp": 1749140460000, "Value": "17.07"}, 
                            {"Timestamp": 1749140520000, "Value": "17.06"}
                        ]
                    }
                }
            ]
        }
    }
    
    analysis = parse_performance_metrics(sample_data)
    formatted = format_performance_analysis(analysis)
    
    return jsonify({
        "test_data": sample_data,
        "analysis": analysis,
        "formatted_summary": formatted
    })

@app.route('/api/ask', methods=['POST'])
def ask_natural_language():
    """Process natural language question with sequential tool execution and analysis"""
    if not mcp_client:
        return jsonify({"error": "MCP client not initialized"})
    
    data = request.json
    question = data.get('question', '')
    
    if not question:
        return jsonify({"error": "No question provided"})
    
    # Try to import anthropic
    try:
        import anthropic
    except ImportError:
        return jsonify({"error": "Anthropic package not installed. Run: pip install anthropic"})
    
    # Check for API key
    anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
    if not anthropic_api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY environment variable not set"})
    
    try:
        # Initialize Anthropic client
        anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)
        
        # Create tool descriptions for LLM
        tools_info = create_tool_descriptions()
        
        # Updated system prompt for sequential execution with correct time format
        system_prompt = f"""You are helping test an MCP (Model Context Protocol) server for PolarDB management.

Available MCP tools:
{tools_info}

CRITICAL TIME FORMAT REQUIREMENTS:
- For all time parameters (start_time, end_time): Use format "YYYY-MM-DDTHH:MMZ" (NO SECONDS)
- Example: "2025-06-05T04:25Z" (correct) vs "2025-06-05T04:25:00Z" (incorrect)
- Always use UTC timezone (Z suffix)

CRITICAL PARAMETER REQUIREMENTS:
- For performance metrics "key" parameter: Use spaces after commas
- Example: "PolarDBDiskUsage, PolarDBCPU, PolarDBMemory, PolarDBConnections, PolarDBIOSTAT" (correct)

CRITICAL: HOW TO PARSE CLUSTER RESPONSES TO FIND NODES
When you call polardb_describe_db_clusters, you get a response like this:
```
'DBCluster': [
  {{
    'DBClusterId': 'pc-6nnxi02yw7ma1fopw',
    'DBNodes': {{
      'DBNode': [
        {{'DBNodeId': 'pi-6nnp9h5z59l323jpf', 'DBNodeRole': 'Writer'}},
        {{'DBNodeId': 'pi-other-node-id', 'DBNodeRole': 'Reader'}}
      ]
    }}
  }}
]
```

TO FIND A NODE:
1. Look at EACH cluster in the 'DBCluster' array
2. For each cluster, look at 'DBNodes' -> 'DBNode' array  
3. Check each 'DBNodeId' in that array
4. If you find the target node ID, YOU'VE FOUND IT - use that cluster's 'DBClusterId'

EXAMPLE: Looking for node "pi-6nnp9h5z59l323jpf"
- Cluster 1: pc-uf6bui46gdx7m8d8z has nodes ['pi-uf6tn00bneck8wbng', 'pi-uf6600x23rdrzp595'] ❌ NOT FOUND
- Cluster 2: pc-6nnxi02yw7ma1fopw has nodes ['pi-6nnp9h5z59l323jpf'] ✅ FOUND!
- Result: Use cluster_id = "pc-6nnxi02yw7ma1fopw"

NEVER say "node not found" if you haven't carefully examined EVERY node in EVERY cluster in the response.

COMPREHENSIVE REGION SEARCH STRATEGY:
When searching for a database node (pi-xxxxx), use this systematic approach:

1. FIRST: Get all available regions using polardb_describe_regions  
2. THEN: Search through regions systematically
3. FOR EACH REGION: Call polardb_describe_db_clusters
4. CAREFULLY PARSE: Look through ALL clusters and ALL nodes in each cluster
5. WHEN FOUND: Note the cluster ID and STOP searching

CORRECT SEARCH FLOW for "Get performance for node pi-6nnp9h5z59l323jpf":
1. Call polardb_describe_regions to get ALL available regions
2. Call polardb_describe_db_clusters with region_id: "cn-hangzhou"
3. Parse response: Check every cluster's DBNodes array for "pi-6nnp9h5z59l323jpf"
4. If not found, try next region: polardb_describe_db_clusters with region_id: "cn-beijing"  
5. Parse response: Check every cluster's DBNodes array for "pi-6nnp9h5z59l323jpf"
6. If not found, try next region: polardb_describe_db_clusters with region_id: "cn-shanghai"
7. Parse response: Find "pi-6nnp9h5z59l323jpf" in cluster "pc-6nnxi02yw7ma1fopw" ✅ FOUND!
8. Use cluster_id: "pc-6nnxi02yw7ma1fopw" for performance call

CRITICAL DATABASE ID RELATIONSHIPS:
- NEVER assume cluster IDs based on node IDs - they are NOT related by simple prefix replacement
- Always look up the actual cluster information to find which cluster contains a specific node
- Parse the actual API response data carefully - don't miss nodes that are clearly present

GUIDELINES FOR DATABASE OPERATIONS:
- Search ALL regions systematically - don't assume location
- CAREFULLY parse cluster responses to find nodes
- Never guess or construct cluster IDs from node IDs  
- For performance data: Use recent 1-hour time ranges with correct format
- Current time reference: around 2025-06-05T17:30Z

GLOBAL SECURITY IP GROUP ANALYSIS:
When users ask about security configurations or IP access controls:
1. Check both local IP arrays (polardb_describe_db_cluster_access_whitelist) 
2. Check global security groups (polardb_describe_global_security_ipgroup_relation)
3. Global groups provide centralized management across multiple clusters
4. An empty GlobalSecurityIPGroupRel array means no global groups are configured
5. Both global and local IP configurations affect cluster access

COMPREHENSIVE SECURITY AUDIT WORKFLOW:
For complete security analysis:
1. Call polardb_describe_db_cluster_access_whitelist (local IP arrays)
2. Call polardb_describe_global_security_ipgroup_relation (global IP groups)  
3. Analyze both results together for complete security posture
4. Check for conflicts or redundancies between global and local settings

        CRITICAL PROXY PERFORMANCE METRICS:
        For polardb_describe_db_proxy_performance, use ONLY these proxy-specific metrics:

        CORE PROXY METRICS (recommended):
        - PolarProxy_CurrentConns (当前连接数)
        - PolarProxy_DBConns (数据库连接数) 
        - PolarProxy_DBActionOps (数据库操作次数)

        EXTENDED PROXY METRICS:
        - PolarProxy_CPU (代理CPU使用率)
        - PolarProxy_Memory (代理内存使用率)
        - PolarProxy_NetworkIn (网络输入流量)
        - PolarProxy_NetworkOut (网络输出流量)
        - PolarProxy_QPS (每秒查询数)
        - PolarProxy_TPS (每秒事务数)
        - PolarProxy_AvgResponseTime (平均响应时间)
        - PolarProxy_SlowQueries (慢查询数量)
        - PolarProxy_ConnectionPool (连接池使用情况)
        - PolarProxy_ThreadPool (线程池使用情况)

        DEFAULT if no key provided: "PolarProxy_CurrentConns, PolarProxy_DBConns, PolarProxy_DBActionOps"

        DO NOT MIX cluster/node metrics (PolarDBCPU, PolarDBMemory, etc.) with proxy metrics!

        PROXY PERFORMANCE vs NODE/CLUSTER PERFORMANCE:
        - polardb_describe_db_proxy_performance → Use PolarProxy_* metrics ONLY
        - polardb_describe_db_node_performance → Use PolarDB* metrics (PolarDBCPU, PolarDBMemory, etc.)
        - polardb_describe_db_cluster_performance → Use PolarDB* metrics (PolarDBDiskUsage, PolarDBCPU, etc.)

        Example proxy performance call:
        {{
            "tool_name": "polardb_describe_db_proxy_performance",
            "arguments": {{
                "dbcluster_id": "pc-6nnupu6o754068f16",
                "dbnode_id": "pi-6nno0x8y190703h5c", 
                "key": "PolarProxy_CurrentConns, PolarProxy_DBConns, PolarProxy_CPU",
                "start_time": "2025-07-16T17:01Z",
                "end_time": "2025-07-16T17:05Z"
            }}
        }}

RESPONSE FORMAT - respond with ONLY valid JSON:
{{
    "reasoning": "Brief explanation of what you're doing and why",
    "status": "continue" | "complete",
    "tool_call": {{
        "tool_name": "tool_name_here",
        "arguments": {{
            "param1": "value1"
        }}
    }} | null
}}

Set status to "continue" when you need to make a tool call.
Set status to "complete" with tool_call: null when the task is finished.
""" 
        
        # Track conversation state
        conversation_history = []
        results = {
            "question": question,
            "reasoning_steps": [],
            "tool_calls": [],
            "results": [],
            "final_answer": "",
            "analysis": None
        }
        
        max_iterations = 5  # Prevent infinite loops
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # Build context for LLM
            context_parts = [f"Original question: {question}"]
            
            if conversation_history:
                context_parts.append("\nPrevious tool calls and results:")
                for i, (tool_name, args, result) in enumerate(conversation_history):
                    context_parts.append(f"{i+1}. Called {tool_name} with {args}")
                    # Don't include full raw result in context to save space
                    if "isError" in str(result) and result.get("isError"):
                        context_parts.append(f"   Result: ERROR - {result}")
                    else:
                        context_parts.append(f"   Result: SUCCESS (data available)")
            
            context_parts.append(f"\nWhat should be the next step? (Iteration {iteration}/{max_iterations})")
            context = "\n".join(context_parts)
            
            # Get LLM response
            message = anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": context}
                ]
            )
            
            response_text = message.content[0].text
            print(f"🧠 LLM Response (iteration {iteration}): {response_text}")
            
            try:
                llm_response = parse_llm_response(response_text)
                
                reasoning = llm_response.get('reasoning', '')
                status = llm_response.get('status', 'continue')
                tool_call = llm_response.get('tool_call')
                error_message = llm_response.get('error_message')
                
                results["reasoning_steps"].append(f"Step {iteration}: {reasoning}")
                
                if status == "error":
                    # Task cannot be completed due to missing tools or other issues
                    results["final_answer"] = f"❌ **操作无法完成**\n\n{error_message or reasoning}\n\n请确保所需的工具已正确配置。"
                    print(f"❌ Task failed: {error_message or reasoning}")
                    break
                elif status == "complete" or not tool_call:
                    # Task is complete
                    print(f"✅ Task completed after {iteration} iterations")
                    break

                # Execute the tool call
                tool_name = tool_call.get('tool_name')
                arguments = tool_call.get('arguments', {})
                
                print(f"🤖 Iteration {iteration}: Executing {tool_name} with {arguments}")
                
                # Call the tool using proper protocol
                result = mcp_client.call_tool_with_proper_protocol(tool_name, arguments)
                
                # Store results
                results["tool_calls"].append({
                    "iteration": iteration,
                    "tool_name": tool_name,
                    "arguments": arguments
                })
                
                results["results"].append({
                    "iteration": iteration,
                    "tool_name": tool_name,
                    "result": result
                })
                
                # Add to conversation history for next iteration
                conversation_history.append((tool_name, arguments, result))
                
                # Check if this was a performance tool and analyze it
                if "performance" in tool_name.lower():
                    print(f"🔍 Analyzing performance data from {tool_name}")
                    
                    analysis = analyze_performance_data(result)
                    print(f"📊 Analysis result: {analysis}")  # DEBUG: Print analysis
                    
                    if "error" not in analysis:
                        formatted_summary = format_performance_analysis(analysis)
                        print(f"📝 Formatted summary length: {len(formatted_summary)}")  # DEBUG
                        
                        results["analysis"] = {
                            "raw_analysis": analysis,
                            "formatted_summary": formatted_summary
                        }
                        
                        print(f"✅ Performance analysis completed and added to results")
                        print(f"🔍 Results keys: {list(results.keys())}")  # DEBUG: Show what's in results
                    else:
                        print(f"❌ Analysis error: {analysis}")  # DEBUG: Show analysis errors
                
            except (json.JSONDecodeError, ValueError) as e:
                return jsonify({
                    "error": f"Failed to parse LLM response as JSON: {str(e)}",
                    "raw_response": response_text,
                    "iteration": iteration
                })
        
        # Generate final answer with analysis if available
        if conversation_history:
            final_context = f"""Based on the following tool calls and results, provide a comprehensive final answer to: "{question}"

Tool calls and results:
"""
            for i, (tool_name, args, result) in enumerate(conversation_history):
                final_context += f"{i+1}. {tool_name}({args}) -> "
                
                # FIXED: Don't truncate successful results - include full content
                if result.get("isError"):
                    final_context += f"ERROR: {str(result)[:200]}...\n"
                elif "performance" in tool_name.lower() and results.get("analysis"):
                    final_context += "Performance data analyzed successfully\n"
                else:
                    # CRITICAL FIX: Include full result content for database listings and other tools
                    if 'result' in result and 'content' in result['result']:
                        content_list = result['result']['content']
                        if content_list and len(content_list) > 0:
                            full_text = content_list[0].get('text', '')
                            final_context += f"SUCCESS: {full_text}\n"
                        else:
                            final_context += f"SUCCESS: {str(result)[:500]}...\n"
                    else:
                        final_context += f"SUCCESS: {str(result)[:500]}...\n"
            
            # Add specific instruction to use all information
            final_context += f"""

IMPORTANT INSTRUCTIONS:
- Use ALL the information provided above in your final answer
- Do NOT truncate or summarize the database details
- Include specific values like character sets, status, engine types, etc.
- Provide a complete and detailed response in Chinese
- Format the information clearly and comprehensively
"""
            
            final_message = anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,  # INCREASED from 500 to 1500 to allow longer responses
                messages=[
                    {"role": "user", "content": final_context}
                ]
            )
            
            base_answer = final_message.content[0].text
            
            # Combine base answer with analysis if available
            if results.get("analysis"):
                print(f"🎯 Adding analysis to final answer")  # DEBUG
                results["final_answer"] = f"{base_answer}\n\n{results['analysis']['formatted_summary']}"
                print(f"📄 Final answer length: {len(results['final_answer'])}")  # DEBUG
            else:
                print(f"⚠️ No analysis found in results")  # DEBUG
                results["final_answer"] = base_answer        

        print(f"🚀 Returning response with keys: {list(results.keys())}")  # DEBUG
        return jsonify(results)
        
    except Exception as e:
        return jsonify({"error": f"Error calling LLM: {str(e)}"})

def setup_and_start_mcp_server(server_path=None):
    """Setup virtual environment and start MCP server - replicates start_mcp_server.sh logic"""
    if server_path is None:
        server_path = DEFAULT_SERVER_PATH
    
    print(f"🚀 Setting up MCP server at: {server_path}")
    
    # Check if the directory exists
    if not os.path.isdir(server_path):
        raise FileNotFoundError(f"Directory '{server_path}' does not exist")
    
    original_cwd = os.getcwd()
    
    try:
        # Change to server directory
        os.chdir(server_path)
        print(f"📁 Changed to directory: {server_path}")
        
        # Create virtual environment if it doesn't exist
        if not os.path.isdir("bin"):
            print("🔨 Creating virtual environment...")
            subprocess.run([sys.executable, "-m", "venv", "."], check=True)
        
        # Determine the correct python executable path
        if os.name == 'nt':  # Windows
            python_exe = os.path.join("Scripts", "python.exe")
            pip_exe = os.path.join("Scripts", "pip.exe")
        else:  # Unix/Linux/Mac
            python_exe = os.path.join("bin", "python3")
            pip_exe = os.path.join("bin", "pip")
        
        print("⚡ Activating virtual environment and upgrading pip...")
        subprocess.run([python_exe, "-m", "pip", "install", "--upgrade", "pip"], 
                      check=True, capture_output=True)
        
        # Install requirements
        print("📦 Installing requirements...")
        if os.path.isfile("requirements.txt"):
            subprocess.run([python_exe, "-m", "pip", "install", "-r", "requirements.txt", "--upgrade"], 
                          check=True, capture_output=True)
        else:
            print("⚠️ requirements.txt not found, installing pytz manually...")
            subprocess.run([python_exe, "-m", "pip", "install", "pytz"], 
                          check=True, capture_output=True)
        
        # Verify pytz installation
        print("🔍 Verifying pytz installation...")
        try:
            subprocess.run([python_exe, "-c", "import pytz; print('pytz installed successfully')"], 
                          check=True, capture_output=True)
        except subprocess.CalledProcessError:
            print("🔧 Installing pytz...")
            subprocess.run([python_exe, "-m", "pip", "install", "pytz"], 
                          check=True, capture_output=True)
        
        print("✅ MCP server environment setup complete!")
        
        # Return the command to run the server
        return [python_exe, "server.py"]
        
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to setup MCP server environment: {e}")
    except Exception as e:
        raise RuntimeError(f"Error setting up MCP server: {e}")
    finally:
        # Always change back to original directory
        os.chdir(original_cwd)

def main():
    """Main function with integrated MCP server startup"""
    global mcp_client
    
    # Require server path as command line argument
    if len(sys.argv) < 2:
        print("❌ Error: MCP server path is required")
        print("\n🔧 Usage:")
        print(f"   python3 {sys.argv[0]} <path_to_polardb_server>")
        print(f"   Example: python3 {sys.argv[0]} /Users/panfeng/git/polardb_mcp_server/polardb-openapi-mcp-server")
        return 1
    
    server_path = sys.argv[1]
    
    print("🚀 Starting Enhanced MCP Protocol Web Interface")
    print("=" * 60)
    print(f"📁 MCP Server Path: {server_path}")
    
    try:
        # Setup and get server command
        print("🔨 Setting up MCP server environment...")
        server_command = setup_and_start_mcp_server(server_path)
        print(f"✅ Server command prepared: {' '.join(server_command)}")
        
    except Exception as e:
        print(f"❌ Failed to setup MCP server: {e}")
        print("\n🔧 Usage:")
        print(f"   python3 {sys.argv[0]} [path_to_polardb_server]")
        print(f"   Example: python3 {sys.argv[0]} /Users/panfeng/git/polardb_mcp_server/polardb-openapi-mcp-server")
        return 1
    
    print("✅ Using proper MCP protocol sequence:")
    print("   1. initialize request")
    print("   2. initialize response") 
    print("   3. initialized notification ← FIX")
    print("   4. tool call request")
    
    if not os.path.exists('index.html'):
        print("❌ index.html not found in current directory")
        print("💡 Make sure to run this script from the directory containing index.html")
        return 1
    
    # Update server command to use the full path
    full_server_command = []
    if server_command[0].startswith('/') or server_command[0].startswith('.'):
        # Absolute or relative path
        full_server_command = server_command
    else:
        # Relative to server path
        full_server_command = [os.path.join(server_path, server_command[0])] + server_command[1:]
    
    # Initialize MCP client with the prepared command
    mcp_client = FixedMCPClient([
        "/bin/bash", "-c", 
        f"cd {server_path} && {' '.join(server_command)}"
    ])
    
    print("✅ Enhanced MCP Client initialized with auto-setup")
    print("🌐 Starting web interface...")
    print(f"\n🎯 Open your browser and go to: http://localhost:4657")
    print("📋 MCP server will auto-start with proper environment!")
    print("🔧 Server environment auto-configured with requirements")
    
    try:
        app.run(debug=False, host='0.0.0.0', port=4657)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        return 0
    
    return 0

if __name__ == "__main__":
    main()

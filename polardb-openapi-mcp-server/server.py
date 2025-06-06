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
import asyncio
import sqlparse

from alibabacloud_polardb20170801.client import Client as polardb20170801Client
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_polardb20170801 import models as polardb_20170801_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_tea_util.client import Client as UtilClient

enable_write = False
enable_update = False
enable_insert = False
enable_ddl = False
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger("polardb-openapi-mcp-server")

def create_client() -> polardb20170801Client:
    """
    Initialize the Client with the credentials from the environment variables.
    @return: polardb20170801Client
    """
    # Load environment variables from .env file
    load_dotenv()

    # Retrieve Alibaba Cloud Access Key and Secret from environment variables
    access_key_id = os.getenv('ALIBABA_CLOUD_ACCESS_KEY_ID')
    access_key_secret = os.getenv('ALIBABA_CLOUD_ACCESS_KEY_SECRET')

    if not access_key_id or not access_key_secret:
        print("Missing Access Key ID or Access Key Secret.")
        return None

    # Create a Config object to store your credentials
    config = open_api_models.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        region_id='cn-hangzhou'  # Update this with your region if needed
    )
    # Set the endpoint for the PolarDB API
    config.endpoint = 'polardb.aliyuncs.com'
    return polardb20170801Client(config)

# Initialize server
app = Server("polardb-mysql-mcp-server")

@app.list_resources()
async def list_resources() -> list[Resource]:
    try:
        return [
            Resource(
                uri=f"polardb-mysql://regions",
                name="get_regions",
                description="List all available regions for Alibaba Cloud PolarDB",
                mimeType="text/plain"
            ),
            Resource(
                uri=f"polardb-mysql://clusters",
                name="get_clusters",
                description="List all PolarDB clusters across all regions",
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
            uriTemplate=f"polardb-mysql://{{region_id}}/clusters",
            name="region_clusters",
            description="get all PolarDB clusters in a specific region",
            mimeType="text/plain"
        ),
        ResourceTemplate(
            uriTemplate=f"polardb-mysql://classes/{{region_id}}/{{db_type}}",
            name="region_db_type_classes",
            description="get all PolarDB classes specifications for a specific region and database type",
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

        if len(parts) == 1 and parts[0] == "regions":
            # List all regions
            return await get_polardb_regions()

        elif len(parts) == 1 and parts[0] == "clusters":
            # List all clusters across all regions
            return await get_all_polardb_clusters()

        elif len(parts) == 2 and parts[1] == "clusters":
            # List clusters in a specific region
            region_id = parts[0]
            return await get_polardb_clusters(region_id)

        else:
            logger.error(f"Invalid URI: {uri_str}")
            raise ValueError(f"Invalid URI: {uri_str}")

    else:
        logger.error(f"Invalid URI scheme: {uri_str}")
        raise ValueError(f"Invalid URI scheme: {uri_str}")

# PolarDB API helper functions
async def get_polardb_regions() -> str:
    """Get all available PolarDB regions"""
    client = create_client()
    if not client:
        return "Failed to create PolarDB client. Please check your credentials."

    try:
        # Create the request model for DescribeRegions
        describe_regions_request = polardb_20170801_models.DescribeRegionsRequest()
        runtime = util_models.RuntimeOptions()

        # Call the API to get the regions list
        response = client.describe_regions_with_options(describe_regions_request, runtime)

        # Format the response
        if response.body and hasattr(response.body, 'regions') and response.body.regions:
            regions_info = []
            for region in response.body.regions.region:
                regions_info.append(f"{region.region_id}: {region.local_name}")

            return "\n".join(regions_info)
        else:
            return "No regions found or empty response"

    except Exception as e:
        logger.error(f"Error describing PolarDB regions: {str(e)}")
        return f"Error retrieving regions: {str(e)}"

async def get_polardb_clusters(region_id: str) -> str:
    """Get all PolarDB clusters in a specific region"""
    client = create_client()
    if not client:
        return "Failed to create PolarDB client. Please check your credentials."

    try:
        # Create request for describing DB clusters
        request = polardb_20170801_models.DescribeDBClustersRequest(
            region_id=region_id
        )
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_db_clusters_with_options(request, runtime)

        # Format the response
        if response.body and hasattr(response.body, 'items') and response.body.items:
            clusters_info = []
            for cluster in response.body.items.db_cluster:
                cluster_info = (
                    f"Cluster ID: {cluster.db_cluster_id}\n"
                    f"Description: {cluster.db_cluster_description}\n"
                    f"Status: {cluster.db_cluster_status}\n"
                    f"Engine: {cluster.engine} {cluster.db_version}\n"
                    f"Created: {cluster.create_time}\n"
                    f"----------------------------------"
                )
                clusters_info.append(cluster_info)

            return "\n".join(clusters_info)
        else:
            return f"No PolarDB clusters found in region {region_id}"

    except Exception as e:
        logger.error(f"Error describing PolarDB clusters: {str(e)}")
        return f"Error retrieving clusters: {str(e)}"

async def get_all_polardb_clusters() -> str:
    """Get all PolarDB clusters across all regions"""
    # First get all regions
    regions_text = await get_polardb_regions()
    regions = []

    for line in regions_text.split("\n"):
        if line and ":" in line:
            region_id = line.split(":")[0].strip()
            regions.append(region_id)

    if not regions:
        return "No regions found"

    # Get clusters for each region
    all_clusters = []
    for region_id in regions:
        clusters = await get_polardb_clusters(region_id)
        if clusters and "No PolarDB clusters found" not in clusters:
            all_clusters.append(f"=== Region: {region_id} ===")
            all_clusters.append(clusters)

    if not all_clusters:
        return "No PolarDB clusters found across all regions"

    return "\n".join(all_clusters)

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available PolarDB MySQL tools."""
    logger.info("Listing tools...")
    return [
        Tool(
            name="polardb_describe_regions",
            description="List all available regions for Alibaba Cloud PolarDB",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="polardb_describe_db_clusters",
            description="List all PolarDB clusters in a specific region",
            inputSchema={
                "type": "object",
                "properties": {
                    "region_id": {
                        "type": "string",
                        "description": "Region ID to list clusters from (e.g., cn-hangzhou)"
                    }
                },
                "required": ["region_id"]
            }
        ),
        Tool(
            name="polardb_describe_db_cluster",
            description="Get detailed information about a specific PolarDB cluster",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_cluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster"
                    }
                },
                "required": ["region_id", "db_cluster_id"]
            }
        ),
        Tool(
            name="polardb_describe_available_resources",
            description="List available resources for creating PolarDB clusters",
            inputSchema={
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
        ),
        Tool(
           name="polardb_create_cluster",
            description="Create a new PolarDB cluster",
            inputSchema={
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
        ),
        Tool(
            name="polardb_describe_db_node_parameters",
            description="Get configuration parameters for a specific PolarDB database node",
            inputSchema={
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
        ),
        Tool(
            name="polardb_modify_db_node_parameters",
            description="Modify configuration parameters for PolarDB database nodes",
            inputSchema={
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
        ),
        Tool(
            name="polardb_describe_slow_log_records",
            description="Get slow log records for a specific PolarDB cluster within a time range",
            inputSchema={
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
        ),
        Tool(
            name="polardb_describe_db_node_performance",
            description="Get performance metrics for a specific PolarDB database node within a time range",
            inputSchema={
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
        ),
        Tool(
            name="polardb_describe_db_cluster_performance",
            description="Get performance metrics for a specific PolarDB cluster within a time range",
            inputSchema={
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
        )
    ]

def polardb_describe_regions() -> list[TextContent]:
    """List all available regions for Alibaba Cloud PolarDB"""
    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    # Create the request model for DescribeRegions
    describe_regions_request = polardb_20170801_models.DescribeRegionsRequest()
    runtime = util_models.RuntimeOptions()

    try:
        # Call the API to get the regions list
        response = client.describe_regions_with_options(describe_regions_request, runtime)

        # Format the response
        if response.body and hasattr(response.body, 'regions') and response.body.regions:
            regions_info = []
            for region in response.body.regions.region:
                # Extract zone IDs from the Zones.Zone list
                zone_ids = []
                if hasattr(region, 'zones') and region.zones and hasattr(region.zones, 'zone'):
                    for zone in region.zones.zone:
                        if hasattr(zone, 'zone_id'):
                            zone_ids.append(zone.zone_id)

                regions_info.append(f"Region ID: {region.region_id}, Zones: {', '.join(zone_ids)}")
            return [TextContent(type="text", text="\n".join(regions_info))]
        else:
            return [TextContent(type="text", text="No regions found or empty response")]

    except Exception as e:
        logger.error(f"Error describing PolarDB regions: {str(e)}")
        return [TextContent(type="text", text=f"Error retrieving regions: {str(e)}")]

def polardb_describe_db_clusters(arguments: dict) -> list[TextContent]:
    """List all PolarDB clusters in a specific region"""
    region_id = arguments.get("region_id")
    if not region_id:
        return [TextContent(type="text", text="Region ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    # Create request for describing DB clusters
    request = polardb_20170801_models.DescribeDBClustersRequest(
        region_id=region_id
    )
    runtime = util_models.RuntimeOptions()

    try:
        # Call the API
        response = client.describe_dbclusters_with_options(request, runtime)
        response_dict = None

        # 尝试转换响应为字典
        try:
            import json
            response_dict = json.loads(str(response.to_map()))
        except:
            pass

        clusters_info = []

        # 如果成功转换为字典，使用字典方式访问
        if response_dict and 'body' in response_dict:
            body = response_dict['body']
            if 'Items' in body and 'DBCluster' in body['Items']:
                clusters = body['Items']['DBCluster']
                for cluster in clusters:
                    cluster_info = (
                        f"Cluster ID: {cluster.get('DBClusterId', 'N/A')}\n"
                        f"Description: {cluster.get('DBClusterDescription', 'N/A')}\n"
                        f"Status: {cluster.get('DBClusterStatus', 'N/A')}\n"
                        f"Engine: {cluster.get('DBType', 'N/A')} {cluster.get('DBVersion', 'N/A')}\n"
                        f"Created: {cluster.get('CreateTime', 'N/A')}\n"
                        f"----------------------------------"
                    )
                    clusters_info.append(cluster_info)
        # 如果无法转换为字典，尝试使用对象方式访问
        elif hasattr(response, 'body') and hasattr(response.body, 'Items'):
            items = response.body.Items
            if hasattr(items, 'DBCluster') and items.DBCluster:
                for cluster in items.DBCluster:
                    try:
                        cluster_info = (
                            f"Cluster ID: {getattr(cluster, 'DBClusterId', 'N/A')}\n"
                            f"Description: {getattr(cluster, 'DBClusterDescription', 'N/A')}\n"
                            f"Status: {getattr(cluster, 'DBClusterStatus', 'N/A')}\n"
                            f"Engine: {getattr(cluster, 'DBType', 'N/A')} {getattr(cluster, 'DBVersion', 'N/A')}\n"
                            f"Created: {getattr(cluster, 'CreateTime', 'N/A')}\n"
                            f"----------------------------------"
                        )
                        clusters_info.append(cluster_info)
                    except Exception as e:
                        clusters_info.append(f"Error processing cluster: {str(e)}")

        if clusters_info:
            return [TextContent(type="text", text="\n".join(clusters_info))]
        else:
            # 如果没有找到集群，返回原始响应数据以供调试
            debug_info = f"No PolarDB clusters found in region {region_id}\n"
            if response_dict:
                debug_info += f"Response body: {response_dict}"
            else:
                debug_info += f"Response: {response}"
            return [TextContent(type="text", text=debug_info)]

    except Exception as e:
        return [TextContent(type="text", text=f"Error retrieving clusters: {str(e)}")]

def polardb_describe_db_cluster(arguments: dict) -> list[TextContent]:
    """Get detailed information about a specific PolarDB cluster"""
    db_cluster_id = arguments.get("db_cluster_id")
    if not db_cluster_id:
        return [TextContent(type="text", text="DB Cluster ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    # Create request for describing a specific DB cluster
    request = polardb_20170801_models.DescribeDBClusterAttributeRequest(
        dbcluster_id=db_cluster_id
    )
    runtime = util_models.RuntimeOptions()

    try:
        # Call the API
        response = client.describe_dbcluster_attribute_with_options(request, runtime)
        response_dict = None

        # Try to convert response to dictionary
        try:
            import json
            response_dict = json.loads(str(response.to_map()))
        except:
            pass

        # Initialize cluster_info list
        cluster_info = []

        # If successfully converted to dictionary, use dictionary access
        if response_dict and 'body' in response_dict:
            body = response_dict['body']

            # Basic cluster information
            cluster_info.extend([
                f"Cluster ID: {body.get('DBClusterId', 'N/A')}",
                f"Description: {body.get('DBClusterDescription', 'N/A')}",
                f"Status: {body.get('DBClusterStatus', 'N/A')}",
                f"Engine: {body.get('Engine', 'N/A')} {body.get('DBVersion', 'N/A')}",
                f"Created: {body.get('CreationTime', 'N/A')}",
                f"Expire Time: {body.get('ExpireTime', 'N/A')}",
                f"Payment Type: {body.get('PayType', 'N/A')}",
                f"Region ID: {body.get('RegionId', 'N/A')}",
                f"Zone IDs: {body.get('ZoneIds', 'N/A')}"
            ])

            # Storage information
            storage_used = body.get('StorageUsed', 'N/A')
            if storage_used != 'N/A':
                try:
                    storage_used_mb = float(storage_used) / 1024 / 1024
                    cluster_info.append(f"Storage Usage: {storage_used} bytes ({storage_used_mb:.2f} MB)")
                except (ValueError, TypeError):
                    cluster_info.append(f"Storage Usage: {storage_used}")
            else:
                cluster_info.append(f"Storage Usage: {storage_used}")

            cluster_info.extend([
                f"Storage Type: {body.get('StorageType', 'N/A')}",
                f"VPC ID: {body.get('VPCId', 'N/A')}",
                f"VSwitch ID: {body.get('VSwitchId', 'N/A')}"
            ])

            # Node information
            if 'DBNodes' in body and body['DBNodes']:
                cluster_info.append("\nDB Nodes:")

                # Handle different types of node data structure
                nodes = body['DBNodes']
                if not isinstance(nodes, list):
                    # If it's not a list, it might be a dict with a list inside
                    if isinstance(nodes, dict) and 'DBNode' in nodes:
                        nodes = nodes['DBNode']
                    else:
                        nodes = [nodes]

                for node in nodes:
                    node_info = [
                        f"  Node ID: {node.get('DBNodeId', 'N/A')}",
                        f"  Description: {node.get('DBNodeDescription', 'N/A')}",
                        f"  Class: {node.get('DBNodeClass', 'N/A')}",
                        f"  Role: {node.get('DBNodeRole', 'N/A')}",
                        f"  Status: {node.get('DBNodeStatus', 'N/A')}",
                        f"  CPU Cores: {node.get('CpuCores', 'N/A')}",
                        f"  Memory Size: {node.get('MemorySize', 'N/A')} MB",
                        f"  Created: {node.get('CreationTime', 'N/A')}",
                        f"  Zone ID: {node.get('ZoneId', 'N/A')}",
                        f"  Max Connections: {node.get('MaxConnections', 'N/A')}",
                        f"  Max IOPS: {node.get('MaxIOPS', 'N/A')}",
                        f"  Hot Replica Mode: {node.get('HotReplicaMode', 'N/A')}",
                        f"  IMCI Switch: {node.get('ImciSwitch', 'N/A')}"
                    ]
                    cluster_info.append("\n".join(node_info))
                    cluster_info.append("  ----------------------------------")

            # Additional cluster information
            cluster_info.append("\nAdditional Information:")
            cluster_info.extend([
                f"  Architecture: {body.get('Architecture', 'N/A')}",
                f"  Auto Upgrade Minor Version: {body.get('AutoUpgradeMinorVersion', 'N/A')}",
                f"  Network Type: {body.get('DBClusterNetworkType', 'N/A')}",
                f"  Deletion Lock: {body.get('DeletionLock', 'N/A')}",
                f"  Lock Mode: {body.get('LockMode', 'N/A')}",
                f"  Hot Standby Cluster: {body.get('HotStandbyCluster', 'N/A')}",
                f"  Resource Group ID: {body.get('ResourceGroupId', 'N/A')}",
                f"  Category: {body.get('Category', 'N/A')}",
                f"  Sub Category: {body.get('SubCategory', 'N/A')}"
            ])
        # If cannot convert to dictionary, use object attribute access
        elif hasattr(response, 'body'):
            attr = response.body

            # Direct access via attributes (fallback method)
            try:
                # Basic cluster information - try accessing attributes directly
                cluster_info.extend([
                    f"Cluster ID: {getattr(attr, 'DBClusterId', 'N/A')}",
                    f"Description: {getattr(attr, 'DBClusterDescription', 'N/A')}",
                    f"Status: {getattr(attr, 'DBClusterStatus', 'N/A')}",
                    f"Engine: {getattr(attr, 'Engine', 'N/A')} {getattr(attr, 'DBVersion', 'N/A')}",
                    f"Created: {getattr(attr, 'CreationTime', 'N/A')}",
                    f"Expire Time: {getattr(attr, 'ExpireTime', 'N/A')}",
                    f"Payment Type: {getattr(attr, 'PayType', 'N/A')}",
                    f"Region ID: {getattr(attr, 'RegionId', 'N/A')}",
                    f"Zone IDs: {getattr(attr, 'ZoneIds', 'N/A')}"
                ])

                # Add full response body for debugging
                cluster_info.append("\nDebug - Full Response Body:")
                cluster_info.append(str(attr))
            except Exception as attr_error:
                cluster_info.append(f"Error accessing attributes: {str(attr_error)}")
                # Add raw response for debugging
                cluster_info.append("\nDebug - Raw Response:")
                cluster_info.append(str(response))
        else:
            return [TextContent(type="text", text=f"No details found for cluster {db_cluster_id}")]

        return [TextContent(type="text", text="\n".join(cluster_info))]

    except Exception as e:
        logger.error(f"Error describing PolarDB cluster: {str(e)}")
        return [TextContent(type="text", text=f"Error retrieving cluster details: {str(e)}")]

def polardb_describe_available_resources(arguments: dict = None) -> list[TextContent]:
    """List available resources for creating PolarDB clusters"""
    arguments = arguments or {}

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing available resources
        request = polardb_20170801_models.DescribeDBClusterAvailableResourcesRequest()

        # Set default PayType if not provided
        request.pay_type = arguments.get("pay_type", "Postpaid")

        # Set optional parameters if provided
        if "region_id" in arguments and arguments["region_id"]:
            request.region_id = arguments["region_id"]
        if "zone_id" in arguments and arguments["zone_id"]:
            request.zone_id = arguments["zone_id"]
        if "db_type" in arguments and arguments["db_type"]:
            request.db_type = arguments["db_type"]
        if "db_version" in arguments and arguments["db_version"]:
            request.db_version = arguments["db_version"]

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbcluster_available_resources_with_options(request, runtime)

        # Format the response
        if response.body and hasattr(response.body, 'available_zones') and response.body.available_zones:
            zones_info = []

            for zone in response.body.available_zones:
                zone_info = [f"Zone: {zone.zone_id}, Region: {zone.region_id}"]

                if hasattr(zone, 'supported_engines') and zone.supported_engines:
                    for engine in zone.supported_engines:
                        engine_info = [f"  Engine: {engine.engine}"]

                        if hasattr(engine, 'available_resources') and engine.available_resources:
                            resources = []
                            for resource in engine.available_resources:
                                resources.append(f"    {resource.category}: {resource.dbnode_class}")

                            if resources:
                                engine_info.append("\n".join(resources))
                        else:
                            engine_info.append("    No available resources")

                        zone_info.append("\n".join(engine_info))
                else:
                    zone_info.append("  No supported engines")

                zones_info.append("\n".join(zone_info))
                zones_info.append("----------------------------------")

            return [TextContent(type="text", text="\n".join(zones_info))]
        else:
            msg = "No PolarDB available resources found"
            if "region_id" in arguments and arguments["region_id"]:
                msg += f" in region {arguments['region_id']}"
            if "zone_id" in arguments and arguments["zone_id"]:
                msg += f" for zone {arguments['zone_id']}"
            if "db_type" in arguments and arguments["db_type"]:
                msg += f" for DB type {arguments['db_type']}"
            return [TextContent(type="text", text=msg)]

    except Exception as e:
        logger.error(f"Error describing PolarDB available resources: {str(e)}")
        return [TextContent(type="text", text=f"Error retrieving available resources: {str(e)}")]

def polardb_describe_db_node_parameters(arguments: dict) -> list[TextContent]:
    """Get configuration parameters for a specific PolarDB database node"""
    dbnode_id = arguments.get("dbnode_id")
    db_cluster_id = arguments.get("db_cluster_id")

    if not dbnode_id:
        return [TextContent(type="text", text="Database node ID is required")]

    if not db_cluster_id:
        return [TextContent(type="text", text="DB cluster ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing DB node parameters
        request = polardb_20170801_models.DescribeDBNodesParametersRequest(
            dbnode_ids=dbnode_id,
            dbcluster_id=db_cluster_id
        )
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbnodes_parameters_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            try:
                # Try to parse the response as JSON for better formatting
                import json
                formatted_response = json.dumps(response.body.to_map(), indent=2)
                return [TextContent(type="text", text=f"Parameters for DB node {dbnode_id}:\n{formatted_response}")]
            except Exception:
                # Fallback to string representation if JSON conversion fails
                return [TextContent(type="text", text=f"Parameters for DB node {dbnode_id}:\n{str(response.body)}")]
        else:
            return [TextContent(type="text", text=f"No parameters found for DB node {dbnode_id} in cluster {db_cluster_id}")]

    except Exception as e:
        logger.error(f"Error describing PolarDB node parameters: {str(e)}")
        return [TextContent(type="text", text=f"Error retrieving parameters: {str(e)}")]

def polardb_modify_db_node_parameters(arguments: dict) -> list[TextContent]:
    """Modify configuration parameters for PolarDB database nodes"""
    db_cluster_id = arguments.get("db_cluster_id")
    dbnode_ids = arguments.get("dbnode_ids")
    parameters = arguments.get("parameters")

    if not db_cluster_id:
        return [TextContent(type="text", text="DB cluster ID is required")]
    if not dbnode_ids:
        return [TextContent(type="text", text="Database node IDs are required")]
    if not parameters:
        return [TextContent(type="text", text="Parameters are required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for modifying DB node parameters
        request = polardb_20170801_models.ModifyDBNodesParametersRequest(
            parameters=parameters,
            dbcluster_id=db_cluster_id,
            dbnode_ids=dbnode_ids
        )
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.modify_dbnodes_parameters_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            result = f"Parameters modified successfully for nodes {dbnode_ids} in cluster {db_cluster_id}.\n"
            result += f"Request ID: {getattr(response.body, 'RequestId', 'N/A')}"

            # Check if there's a TaskId in the response
            task_id = getattr(response.body, 'TaskId', None)
            if task_id:
                result += f"\nTask ID: {task_id}"

            return [TextContent(type="text", text=result)]
        else:
            return [TextContent(type="text", text=f"No response received from the API. The operation may have failed.")]

    except Exception as e:
        logger.error(f"Error modifying PolarDB node parameters: {str(e)}")
        return [TextContent(type="text", text=f"Error modifying parameters: {str(e)}")]

# Add this function to your code to handle creating PolarDB clusters
def polardb_create_cluster(arguments: dict) -> list[TextContent]:
    """Create a new PolarDB cluster"""
    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for creating a new PolarDB cluster
        request = polardb_20170801_models.CreateDBClusterRequest()

        # Required parameters
        request.region_id = arguments.get("region_id", "cn-hangzhou")
        request.dbtype = arguments.get("dbtype", "MySQL")
        request.dbversion = arguments.get("dbversion", "8.0")
        request.dbnode_class = arguments.get("dbnode_class", "polar.mysql.g2.medium")
        request.pay_type = arguments.get("pay_type", "Postpaid")

        # StorageSpace parameter (required to avoid the error you encountered)
        storage_space = arguments.get("storage_space", 50)
        # Convert to int if it's a string
        if isinstance(storage_space, str) and storage_space.isdigit():
            storage_space = int(storage_space)
        request.storage_space = storage_space

        # Optional parameters
        if "zone_id" in arguments:
            request.zone_id = arguments["zone_id"]
        if "vpc_id" in arguments:
            request.vpcid = arguments["vpc_id"]
        if "vswitch_id" in arguments:
            request.vswitch_id = arguments["vswitch_id"]
        if "tde_status" in arguments:
            request.tde_status = arguments["tde_status"]
        if "db_cluster_description" in arguments:
            request.db_cluster_description = arguments["db_cluster_description"]
        if "resource_group_id" in arguments:
            request.resource_group_id = arguments["resource_group_id"]
        if "period" in arguments:
            request.period = arguments["period"]
        if "used_time" in arguments:
            request.used_time = arguments["used_time"]
        if "client_token" in arguments:
            request.client_token = arguments["client_token"]

        # Add runtime options
        runtime = util_models.RuntimeOptions()

        # Call the API to create the cluster
        response = client.create_dbcluster_with_options(request, runtime)

        # Format and return the successful response
        if response.body:
            result = (
                f"PolarDB cluster created successfully!\n"
                f"Cluster ID: {getattr(response.body, 'DBClusterId', 'N/A')}\n"
                f"Order ID: {getattr(response.body, 'OrderId', 'N/A')}\n"
                f"Request ID: {getattr(response.body, 'RequestId', 'N/A')}\n"
                f"Resource Group ID: {getattr(response.body, 'ResourceGroupId', 'N/A')}"
            )
            return [TextContent(type="text", text=result)]
        else:
            return [TextContent(type="text", text="Cluster creation response was empty. Please check the console to verify creation.")]

    except Exception as e:
        logger.error(f"Error creating PolarDB cluster: {str(e)}")
        return [TextContent(type="text", text=f"Error creating PolarDB cluster: {str(e)}")]

def polardb_describe_slow_log_records(arguments: dict) -> list[TextContent]:
    """Get slow log records for a specific PolarDB cluster within a time range"""
    region_id = arguments.get("region_id")
    db_cluster_id = arguments.get("db_cluster_id")
    start_time = arguments.get("start_time")
    end_time = arguments.get("end_time")

    # Validate required parameters
    if not region_id:
        return [TextContent(type="text", text="Region ID is required")]
    if not db_cluster_id:
        return [TextContent(type="text", text="DB Cluster ID is required")]
    if not start_time:
        return [TextContent(type="text", text="Start time is required")]
    if not end_time:
        return [TextContent(type="text", text="End time is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing slow log records
        request = polardb_20170801_models.DescribeSlowLogRecordsRequest(
            region_id=region_id,
            dbcluster_id=db_cluster_id,
            start_time=start_time,
            end_time=end_time
        )

        # Set optional parameters if provided
        if "node_id" in arguments and arguments["node_id"]:
            request.node_id = arguments["node_id"]
        if "dbname" in arguments and arguments["dbname"]:
            request.dbname = arguments["dbname"]
        if "page_size" in arguments and arguments["page_size"]:
            request.page_size = arguments["page_size"]
        if "page_number" in arguments and arguments["page_number"]:
            request.page_number = arguments["page_number"]
        if "sqlhash" in arguments and arguments["sqlhash"]:
            request.sqlhash = arguments["sqlhash"]

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_slow_log_records_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            try:
                # Try to convert response to dictionary for better parsing
                import json
                response_dict = json.loads(str(response.to_map()))
 
                if 'body' in response_dict:
                    body = response_dict['body']

                    # Format header information
                    result_lines = [
                        f"Slow Log Records for Cluster: {db_cluster_id}",
                        f"Region: {region_id}"
                    ]

                    # Add node ID if specified
                    if "node_id" in arguments and arguments["node_id"]:
                        result_lines.append(f"Node ID: {arguments['node_id']}")

                    result_lines.extend([
                        f"Time Range: {start_time} to {end_time}",
                        f"Total Records: {body.get('TotalRecordCount', 'N/A')}",
                        f"Page Number: {body.get('PageNumber', 'N/A')}",
                        f"Page Size: {body.get('PageRecordCount', 'N/A')}",
                        "=" * 80
                    ])

                    # Parse slow log items
                    if 'Items' in body and 'SlowLogRecord' in body['Items']:
                        slow_logs = body['Items']['SlowLogRecord']

                        # Handle case where slow_logs might not be a list
                        if not isinstance(slow_logs, list):
                            slow_logs = [slow_logs]

                        for i, log in enumerate(slow_logs, 1):
                            log_info = [
                                f"\n--- Slow Log Record #{i} ---",
                                f"Create Time: {log.get('CreateTime', 'N/A')}",
                                f"Database Name: {log.get('DBName', 'N/A')}",
                                f"DB Node ID: {log.get('DBNodeId', 'N/A')}",
                                f"Max Execution Time: {log.get('MaxExecutionTime', 'N/A')} seconds",
                                f"Max Lock Time: {log.get('MaxLockTime', 'N/A')} seconds",
                                f"Parse Max Row Count: {log.get('ParseMaxRowCount', 'N/A')}",
                                f"Parse Total Row Counts: {log.get('ParseTotalRowCounts', 'N/A')}",
                                f"Return Max Row Count: {log.get('ReturnMaxRowCount', 'N/A')}",
                                f"Return Total Row Counts: {log.get('ReturnTotalRowCounts', 'N/A')}",
                                f"SQL Hash: {log.get('SQLHash', 'N/A')}",
                                f"SQL Text: {log.get('SQLText', 'N/A')}",
                                f"Total Execution Counts: {log.get('TotalExecutionCounts', 'N/A')}",
                                f"Total Execution Times: {log.get('TotalExecutionTimes', 'N/A')} seconds",
                                f"Total Lock Times: {log.get('TotalLockTimes', 'N/A')} seconds"
                            ]
                            result_lines.extend(log_info)
                            result_lines.append("-" * 60)

                        return [TextContent(type="text", text="\n".join(result_lines))]
                    else:
                        result_lines.append("No slow log records found in the specified time range.")
                        return [TextContent(type="text", text="\n".join(result_lines))]
                else:
                    # Fallback: use string representation
                    return [TextContent(type="text", text=f"Slow log records response:\n{str(response.body)}")]

            except Exception as parse_error:
                logger.error(f"Error parsing slow log response: {str(parse_error)}")
                # Fallback to raw response
                return [TextContent(type="text", text=f"Slow log records (raw response):\n{str(response.body)}")]
        else:
            return [TextContent(type="text", text=f"No slow log records found for cluster {db_cluster_id} in the specified time range.")]

    except Exception as e:
        logger.error(f"Error describing slow log records: {str(e)}")
        if hasattr(e, 'message'):
            error_msg = f"Error retrieving slow log records: {e.message}"
            if hasattr(e, 'data') and e.data and e.data.get("Recommend"):
                error_msg += f"\nRecommendation: {e.data.get('Recommend')}"
        else:
            error_msg = f"Error retrieving slow log records: {str(e)}"

        return [TextContent(type="text", text=error_msg)]

def polardb_describe_db_node_performance(arguments: dict) -> list[TextContent]:
    """Get performance metrics for a specific PolarDB database node within a time range"""
    dbnode_id = arguments.get("dbnode_id")
    key = arguments.get("key")
    start_time = arguments.get("start_time")
    end_time = arguments.get("end_time")
    db_cluster_id = arguments.get("db_cluster_id")

    # Validate required parameters
    if not dbnode_id:
        return [TextContent(type="text", text="Database node ID is required")]
    if not key:
        return [TextContent(type="text", text="Performance key is required")]
    if not start_time:
        return [TextContent(type="text", text="Start time is required")]
    if not end_time:
        return [TextContent(type="text", text="End time is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing DB node performance
        request = polardb_20170801_models.DescribeDBNodePerformanceRequest(
            dbnode_id=dbnode_id,
            key=key,
            start_time=start_time,
            end_time=end_time
        )

        # Add cluster ID if provided (some API versions may require this)
        if db_cluster_id:
            # Note: Check if your API version supports db_cluster_id parameter
            # If not supported, you can remove this part
            try:
                request.db_cluster_id = db_cluster_id
            except AttributeError:
                # Ignore if the parameter is not supported in this API version
                pass

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbnode_performance_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            try:
                # Try to convert response to dictionary for better parsing
                import json
                response_dict = json.loads(str(response.to_map()))

                if 'body' in response_dict:
                    body = response_dict['body']

                    # Format header information
                    result_lines = [
                        f"DB Node Performance Report",
                        f"Node ID: {body.get('DBNodeId', dbnode_id)}",
                        f"DB Type: {body.get('DBType', 'N/A')}",
                        f"DB Version: {body.get('DBVersion', 'N/A')}",
                        f"Time Range: {body.get('StartTime', start_time)} to {body.get('EndTime', end_time)}",
                        f"Request ID: {body.get('RequestId', 'N/A')}",
                        "=" * 80
                    ]

                    # Parse performance data
                    if 'PerformanceKeys' in body and 'PerformanceItem' in body['PerformanceKeys']:
                        performance_items = body['PerformanceKeys']['PerformanceItem']

                        # Handle case where performance_items might not be a list
                        if not isinstance(performance_items, list):
                            performance_items = [performance_items]

                        for item in performance_items:
                            metric_name = item.get('MetricName', 'N/A')
                            measurement = item.get('Measurement', 'N/A')

                            result_lines.extend([
                                f"\n--- Performance Metric: {measurement} ---",
                                f"Metric Name: {metric_name}"
                            ])

                            # Parse performance data points
                            if 'Points' in item and 'PerformanceItemValue' in item['Points']:
                                points = item['Points']['PerformanceItemValue']

                                # Handle case where points might not be a list
                                if not isinstance(points, list):
                                    points = [points]

                                result_lines.append(f"Data Points ({len(points)} total):")

                                # Sort points by timestamp for better readability
                                try:
                                    points_sorted = sorted(points, key=lambda x: x.get('Timestamp', 0))
                                except (TypeError, KeyError):
                                    points_sorted = points

                                # Display data points
                                for i, point in enumerate(points_sorted):
                                    timestamp = point.get('Timestamp', 'N/A')
                                    value = point.get('Value', 'N/A')

                                    # Convert timestamp to readable format if it's a valid Unix timestamp
                                    readable_time = 'N/A'
                                    if timestamp != 'N/A':
                                        try:
                                            # Convert from milliseconds to seconds
                                            timestamp_seconds = int(timestamp) / 1000
                                            from datetime import datetime
                                            readable_time = datetime.fromtimestamp(timestamp_seconds).strftime('%Y-%m-%d %H:%M:%S UTC')
                                        except (ValueError, TypeError):
                                            readable_time = str(timestamp)

                                    result_lines.append(f"  {i+1:3d}. {readable_time} | Value: {value}")

                                # Calculate some basic statistics if there are multiple points
                                if len(points_sorted) > 1:
                                    try:
                                        numeric_values = [float(p.get('Value', 0)) for p in points_sorted if p.get('Value', '').replace('.', '').replace('-', '').isdigit()]
                                        if numeric_values:
                                            min_val = min(numeric_values)
                                            max_val = max(numeric_values)
                                            avg_val = sum(numeric_values) / len(numeric_values)
                                            result_lines.extend([
                                                f"  Statistics: Min={min_val:.2f}, Max={max_val:.2f}, Avg={avg_val:.2f}"
                                            ])
                                    except (ValueError, TypeError):
                                        # Skip statistics if values are not numeric
                                        pass
                            else:
                                result_lines.append("  No performance data points found")

                            result_lines.append("-" * 60)

                        return [TextContent(type="text", text="\n".join(result_lines))]
                    else:
                        result_lines.append("No performance data found for the specified parameters.")
                        return [TextContent(type="text", text="\n".join(result_lines))]
                else:
                    # Fallback: use string representation
                    return [TextContent(type="text", text=f"DB node performance response:\n{str(response.body)}")]

            except Exception as parse_error:
                logger.error(f"Error parsing performance response: {str(parse_error)}")
                # Fallback to raw response
                return [TextContent(type="text", text=f"DB node performance (raw response):\n{str(response.body)}")]
        else:
            return [TextContent(type="text", text=f"No performance data found for node {dbnode_id} in the specified time range.")]

    except Exception as e:
        logger.error(f"Error describing DB node performance: {str(e)}")
        if hasattr(e, 'message'):
            error_msg = f"Error retrieving performance data: {e.message}"
            if hasattr(e, 'data') and e.data and e.data.get("Recommend"):
                error_msg += f"\nRecommendation: {e.data.get('Recommend')}"
        else:
            error_msg = f"Error retrieving performance data: {str(e)}"

        return [TextContent(type="text", text=error_msg)]

def polardb_describe_db_cluster_performance(arguments: dict) -> list[TextContent]:
    """Get performance metrics for a specific PolarDB cluster within a time range"""
    db_cluster_id = arguments.get("db_cluster_id")
    key = arguments.get("key")
    start_time = arguments.get("start_time")
    end_time = arguments.get("end_time")

    # Validate required parameters
    if not db_cluster_id:
        return [TextContent(type="text", text="Database cluster ID is required")]
    if not key:
        return [TextContent(type="text", text="Performance key is required")]
    if not start_time:
        return [TextContent(type="text", text="Start time is required")]
    if not end_time:
        return [TextContent(type="text", text="End time is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing DB cluster performance
        request = polardb_20170801_models.DescribeDBClusterPerformanceRequest(
            dbcluster_id=db_cluster_id,
            key=key,
            start_time=start_time,
            end_time=end_time
        )

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbcluster_performance_with_options(request, runtime)

        # Format the response (reuse the same logic as node performance)
        if hasattr(response, 'body') and response.body:
            try:
                # Try to convert response to dictionary for better parsing
                import json
                response_dict = json.loads(str(response.to_map()))

                if 'body' in response_dict:
                    body = response_dict['body']

                    # Format header information
                    result_lines = [
                        f"DB Cluster Performance Report",
                        f"Cluster ID: {body.get('DBClusterId', db_cluster_id)}",
                        f"DB Type: {body.get('DBType', 'N/A')}",
                        f"DB Version: {body.get('DBVersion', 'N/A')}",
                        f"Time Range: {body.get('StartTime', start_time)} to {body.get('EndTime', end_time)}",
                        f"Request ID: {body.get('RequestId', 'N/A')}",
                        "=" * 80
                    ]

                    # Parse performance data
                    if 'PerformanceKeys' in body and 'PerformanceItem' in body['PerformanceKeys']:
                        performance_items = body['PerformanceKeys']['PerformanceItem']

                        # Handle case where performance_items might not be a list
                        if not isinstance(performance_items, list):
                            performance_items = [performance_items]

                        for item in performance_items:
                            metric_name = item.get('MetricName', 'N/A')
                            measurement = item.get('Measurement', 'N/A')

                            result_lines.extend([
                                f"\n--- Performance Metric: {measurement} ---",
                                f"Metric Name: {metric_name}"
                            ])

                            # Parse performance data points
                            if 'Points' in item and 'PerformanceItemValue' in item['Points']:
                                points = item['Points']['PerformanceItemValue']

                                # Handle case where points might not be a list
                                if not isinstance(points, list):
                                    points = [points]

                                result_lines.append(f"Data Points ({len(points)} total):")

                                # Sort points by timestamp for better readability
                                try:
                                    points_sorted = sorted(points, key=lambda x: x.get('Timestamp', 0))
                                except (TypeError, KeyError):
                                    points_sorted = points

                                # Display data points
                                for i, point in enumerate(points_sorted):
                                    timestamp = point.get('Timestamp', 'N/A')
                                    value = point.get('Value', 'N/A')

                                    # Convert timestamp to readable format if it's a valid Unix timestamp
                                    readable_time = 'N/A'
                                    if timestamp != 'N/A':
                                        try:
                                            # Convert from milliseconds to seconds
                                            timestamp_seconds = int(timestamp) / 1000
                                            from datetime import datetime
                                            readable_time = datetime.fromtimestamp(timestamp_seconds).strftime('%Y-%m-%d %H:%M:%S UTC')
                                        except (ValueError, TypeError):
                                            readable_time = str(timestamp)

                                    result_lines.append(f"  {i+1:3d}. {readable_time} | Value: {value}")

                                # Calculate some basic statistics if there are multiple points
                                if len(points_sorted) > 1:
                                    try:
                                        numeric_values = [float(p.get('Value', 0)) for p in points_sorted if p.get('Value', '').replace('.', '').replace('-', '').isdigit()]
                                        if numeric_values:
                                            min_val = min(numeric_values)
                                            max_val = max(numeric_values)
                                            avg_val = sum(numeric_values) / len(numeric_values)
                                            result_lines.extend([
                                                f"  Statistics: Min={min_val:.2f}, Max={max_val:.2f}, Avg={avg_val:.2f}"
                                            ])
                                    except (ValueError, TypeError):
                                        # Skip statistics if values are not numeric
                                        pass
                            else:
                                result_lines.append("  No performance data points found")

                            result_lines.append("-" * 60)

                        return [TextContent(type="text", text="\n".join(result_lines))]
                    else:
                        result_lines.append("No performance data found for the specified parameters.")
                        return [TextContent(type="text", text="\n".join(result_lines))]
                else:
                    # Fallback: use string representation
                    return [TextContent(type="text", text=f"DB cluster performance response:\n{str(response.body)}")]

            except Exception as parse_error:
                logger.error(f"Error parsing cluster performance response: {str(parse_error)}")
                # Fallback to raw response
                return [TextContent(type="text", text=f"DB cluster performance (raw response):\n{str(response.body)}")]
        else:
            return [TextContent(type="text", text=f"No performance data found for cluster {db_cluster_id} in the specified time range.")]

    except Exception as e:
        logger.error(f"Error describing DB cluster performance: {str(e)}")
        if hasattr(e, 'message'):
            error_msg = f"Error retrieving cluster performance data: {e.message}"
            if hasattr(e, 'data') and e.data and e.data.get("Recommend"):
                error_msg += f"\nRecommendation: {e.data.get('Recommend')}"
        else:
            error_msg = f"Error retrieving cluster performance data: {str(e)}"

        return [TextContent(type="text", text=error_msg)]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info(f"Calling tool: {name} with arguments: {arguments}")

    if name == "polardb_describe_regions":
        return polardb_describe_regions()
    elif name == "polardb_describe_db_clusters":
        return polardb_describe_db_clusters(arguments)
    elif name == "polardb_describe_db_cluster":
        return polardb_describe_db_cluster(arguments)
    elif name == "polardb_describe_available_resources":
        return polardb_describe_available_resources(arguments)
    elif name == "polardb_create_cluster":
        return polardb_create_cluster(arguments)
    elif name == "polardb_describe_db_node_parameters":
        return polardb_describe_db_node_parameters(arguments)
    elif name == "polardb_modify_db_node_parameters":
        return polardb_modify_db_node_parameters(arguments)
    elif name == "polardb_describe_slow_log_records":
        return polardb_describe_slow_log_records(arguments)
    elif name == "polardb_describe_db_node_performance":
        return polardb_describe_db_node_performance(arguments)
    elif name == "polardb_describe_db_cluster_performance":
        return polardb_describe_db_cluster_performance(arguments)
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

    logger.info("Starting PolarDB OpenAPI MCP server with stdio mode...") 
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

def main():
    load_dotenv()

    if os.getenv("RUN_MODE")=="stdio":
        asyncio.run(stdio_main())
    else:
        bind_host = os.getenv("SSE_BIND_HOST")
        bind_port = int(os.getenv("SSE_BIND_PORT"))
        sse_main(bind_host,bind_port)

if __name__ == "__main__":
    main()

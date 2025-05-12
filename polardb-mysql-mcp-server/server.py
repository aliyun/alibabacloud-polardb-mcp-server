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
            ),
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
            ),
            Resource(
                uri=f"polardb-mysql://classes",
                name="get_classes",
                description="List all available PolarDB instance classes/specifications",
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
        ),
        ResourceTemplate(
            uriTemplate=f"polardb-mysql://{{region_id}}/clusters",
            name="region_clusters",
            description="get all PolarDB clusters in a specific region",
            mimeType="text/plain"
        ),
        ResourceTemplate(
            uriTemplate=f"polardb-mysql://classes/{{db_type}}",
            name="db_type_classes",
            description="get all PolarDB classes specifications for a specific database type (MySQL, PostgreSQL, etc.)",
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

        elif len(parts) == 1 and parts[0] == "classes":
            # List all instance classes across all regions
            return await get_polardb_classes()

        elif len(parts) == 2 and parts[0] == "classes":
            # List instance classes for a specific DB type
            db_type = parts[1]
            return await get_polardb_classes(db_type=db_type)

        elif len(parts) == 3 and parts[0] == "classes":
            # List instance classes for a specific region and DB type
            region_id = parts[1]
            db_type = parts[2]
            return await get_polardb_classes(region_id=region_id, db_type=db_type)

        # Handle original polardb-mysql resources
        elif len(parts) == 1 and parts[0] == "tables":
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
            resource_type = parts[1]
            try:
                with connect(**config) as conn:
                    with conn.cursor() as cursor:
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
            except Error as e:
                logger.error(f"Database error reading resource: {str(e)}")
                raise RuntimeError(f"Database error: {str(e)}")

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

async def get_polardb_classes(region_id: str = None, db_type: str = None) -> str:
    """Get all PolarDB instance classes/specifications"""
    client = create_client()
    if not client:
        return "Failed to create PolarDB client. Please check your credentials."

    try:
        # Create request for describing DB classes
        request = polardb_20170801_models.DescribeClassListRequest()
        
        # Add CommodityCode parameter with polardb_sub as default value
        request.commodity_code = "polardb_sub"

        # Set optional parameters if provided
        if region_id:
            request.region_id = region_id
        if db_type:
            request.db_type = db_type

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_class_list_with_options(request, runtime)

        # Format the response
        if response.body and hasattr(response.body, 'items') and response.body.items:
            classes_info = []

            # Add header row
            header = "ClassCode, ClassTypeLevel, ClassGroup, CPU, Memory, MaxConnections, MaxStorageCapacity, MaxIOPS, Price"
            classes_info.append(header)

            for class_item in response.body.items:
                # Build IOPS info
                iops_info = ""
                if hasattr(class_item, 'psl4_max_iops') and class_item.psl4_max_iops:
                    iops_info = f"PSL4:{class_item.psl4_max_iops}"
                elif hasattr(class_item, 'pl1_max_iops') and class_item.pl1_max_iops:
                    iops_info = f"PL1:{class_item.pl1_max_iops}"

                # Format price from cents to yuan for readability
                price = "N/A"
                if hasattr(class_item, 'reference_price') and class_item.reference_price:
                    try:
                        price_yuan = int(class_item.reference_price) / 100
                        price = f"{price_yuan:.2f} Yuan"
                    except (ValueError, TypeError):
                        price = class_item.reference_price

                # Build the class info line
                class_info = (
                    f"{class_item.class_code}, "
                    f"{getattr(class_item, 'class_type_level', 'N/A')}, "
                    f"{getattr(class_item, 'class_group', 'N/A')}, "
                    f"{getattr(class_item, 'cpu', 'N/A')}, "
                    f"{getattr(class_item, 'memory_class', 'N/A')}, "
                    f"{getattr(class_item, 'max_connections', 'N/A')}, "
                    f"{getattr(class_item, 'max_storage_capacity', 'N/A')}, "
                    f"{iops_info}, "
                    f"{price}"
                )
                classes_info.append(class_info)

            return "\n".join(classes_info)
        else:
            msg = "No PolarDB instance classes found"
            if region_id:
                msg += f" in region {region_id}"
            if db_type:
                msg += f" for DB type {db_type}"
            return msg

    except Exception as e:
        logger.error(f"Error describing PolarDB classes: {str(e)}")
        return f"Error retrieving instance classes: {str(e)}"

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
                    "model": {  # Add a property name here
                        "type": "json",
                        "description": """ 
                        各字段意义如下
                        model_name:模型名称
                        model_class:模型算法,可以如下取值
                            * lightgbm(LightGBM算法)
                            * deepfm(DeepFM算法))
                            * kmeans(K均值聚类算法（K-Means))
                            * randomforestreg(随机森林回归算法（Random Forest Regression))
                            * gbrt(梯度提升回归树算法（GBRT))
                            * gbdt(决策树算法（GBDT))
                            * linearreg(线性回归算法（Linear Regression))
                            * svr(支持向量回归算法（SVR))
                            * bst(BST算法)
                        table_reference：输入特征表名称
                        x_cols: 模型输入列(table_reference中的列),以逗号分隔
                        y_cols: 模型输出列(table_reference中的列),以逗号分隔
                        完整的例子如下: {"model_name":"gbdt_test","model_class":"gbdt","x_cols":"test_feature1,test_feature2","y_cols":"test_label","table_name":"testfile"}
                        """
                    }
                },
                "required": ["model"]
            }
        ),
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
            name="polardb_describe_class_list",
            description="List all available PolarDB instance class specifications",
            inputSchema={
                "type": "object",
                "properties": {
                    "region_id": {
                        "type": "string",
                        "description": "Region ID to list classes from (e.g., cn-hangzhou)"
                    },
                    "db_type": {
                        "type": "string",
                        "description": "Database type (e.g., MySQL, PostgreSQL)"
                    },
                    "db_version": {
                        "type": "string",
                        "description": "Database version"
                    },
                    "pay_type": {
                        "type": "string",
                        "description": "Payment type (e.g., Prepaid, Postpaid)"
                    },
                    "class_group": {
                        "type": "string",
                        "description": "Class group (e.g., Beginner, Exclusive package)"
                    },
                    "commodity_code": {
                        "type": "string",
                        "description": "Commodity code for the PolarDB product (default: polardb_sub)"
                    }
                },
                "required": []
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
        )
    ]

def polar4ai_create_models(model: dict) -> list[TextContent]:
    """
    使用polar4ai语法，创建模型
    """
    config = get_db_config()
    #config['compress']=True
    logger.info(str(model))
    logger.info(f"Reading polar4ai_create_models")
    try:
        with connect(**config) as conn:
            with conn.cursor() as cursor:
                query_str = "/*polar4ai*/CREATE MODEL "+str(model['model_name'])+" WITH (model_class = \'"+str(model['model_class'])+"\',x_cols = \'"+str(model['x_cols'])+"\',y_cols=\'"+str(model['y_cols'])+"\')AS (SELECT * FROM "+str(model['table_name'])+");"
                cursor.execute(query_str)
                logger.info("create model ok")
                return [TextContent(type="text", text=f"创建{str(model['model_name'])}模型成功")]
                
    except Error as e:
        logger.error(f"Database error polar4ai : {str(e)}")
        return [TextContent(type="text", text=f"创建{str(model['model_name'])}模型失败")]


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
    global enable_write,enable_update,enable_insert,enable_ddl
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

def polardb_describe_class_list(arguments: dict = None) -> list[TextContent]:
    """List all available PolarDB instance class specifications"""
    arguments = arguments or {}
    
    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing DB classes
        request = polardb_20170801_models.DescribeClassListRequest()
        
        # Add CommodityCode parameter with polardb_sub as default value
        request.commodity_code = "polardb_sub"

        # Set optional parameters if provided
        if "region_id" in arguments and arguments["region_id"]:
            request.region_id = arguments["region_id"]
        if "db_type" in arguments and arguments["db_type"]:
            request.db_type = arguments["db_type"]
        if "db_version" in arguments and arguments["db_version"]:
            request.db_version = arguments["db_version"]
        if "pay_type" in arguments and arguments["pay_type"]:
            request.pay_type = arguments["pay_type"]
        if "class_group" in arguments and arguments["class_group"]:
            request.class_group = arguments["class_group"]
        # Allow overriding the default CommodityCode if provided
        if "commodity_code" in arguments and arguments["commodity_code"]:
            request.commodity_code = arguments["commodity_code"]

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_class_list_with_options(request, runtime)

        # Format the response
        if response.body and hasattr(response.body, 'items') and response.body.items:
            classes_info = []

            # Add header row
            header = "ClassCode, ClassTypeLevel, ClassGroup, CPU, Memory, MaxConnections, MaxStorageCapacity, MaxIOPS, Price"
            classes_info.append(header)

            for class_item in response.body.items:
                # Build IOPS info
                iops_info = ""
                if hasattr(class_item, 'psl4_max_iops') and class_item.psl4_max_iops:
                    iops_info = f"PSL4:{class_item.psl4_max_iops}"
                elif hasattr(class_item, 'pl1_max_iops') and class_item.pl1_max_iops:
                    iops_info = f"PL1:{class_item.pl1_max_iops}"

                # Format price from cents to yuan for readability
                price = "N/A"
                if hasattr(class_item, 'reference_price') and class_item.reference_price:
                    try:
                        price_yuan = int(class_item.reference_price) / 100
                        price = f"{price_yuan:.2f} Yuan"
                    except (ValueError, TypeError):
                        price = class_item.reference_price

                # Build the class info line
                class_info = (
                    f"{class_item.class_code}, "
                    f"{getattr(class_item, 'class_type_level', 'N/A')}, "
                    f"{getattr(class_item, 'class_group', 'N/A')}, "
                    f"{getattr(class_item, 'cpu', 'N/A')}, "
                    f"{getattr(class_item, 'memory_class', 'N/A')}, "
                    f"{getattr(class_item, 'max_connections', 'N/A')}, "
                    f"{getattr(class_item, 'max_storage_capacity', 'N/A')}, "
                    f"{iops_info}, "
                    f"{price}"
                )
                classes_info.append(class_info)

            return [TextContent(type="text", text="\n".join(classes_info))]
        else:
            msg = "No PolarDB instance classes found"
            if "region_id" in arguments and arguments["region_id"]:
                msg += f" in region {arguments['region_id']}"
            if "db_type" in arguments and arguments["db_type"]:
                msg += f" for DB type {arguments['db_type']}"
            return [TextContent(type="text", text=msg)]

    except Exception as e:
        logger.error(f"Error describing PolarDB classes: {str(e)}")
        return [TextContent(type="text", text=f"Error retrieving instance classes: {str(e)}")]

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
@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info(f"Calling tool: {name} with arguments: {arguments}")
    if name == "execute_sql":
        return execute_sql(arguments)
    elif name == "polar4ai_create_models":
        # Extract the query_dict from arguments
        query_dict = arguments.get("model")
        if query_dict is None:
            raise ValueError("Missing 'query_dict' in arguments")
        return polar4ai_create_models(query_dict)
    elif name == "polardb_describe_regions":
        return polardb_describe_regions()
    elif name == "polardb_describe_db_clusters":
        return polardb_describe_db_clusters(arguments)
    elif name == "polardb_describe_db_cluster":
        return polardb_describe_db_cluster(arguments)
    elif name == "polardb_describe_class_list":
        return polardb_describe_class_list(arguments)
    elif name == "polardb_describe_available_resources":
        return polardb_describe_available_resources(arguments)
    elif name == "polardb_create_cluster":
        return polardb_create_cluster(arguments)
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
    global enable_write,enable_update,enable_insert,enable_ddl
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

import pytest
import os
from unittest.mock import AsyncMock, patch, MagicMock
from mcp.types import Resource, Tool, TextContent, ResourceTemplate
from mysql.connector import Error
from dotenv import load_dotenv
import asyncio
import time
import logging
import ast
logger = logging.getLogger("test-polardb-mysql-mcp-server")
from polardb_mysql_mcp_server.server import ( 
    get_sql_operation_type,
    get_db_config,
    exec_sql,
    polar4ai_update_index_for_text_2_sql,
    polar4ai_text_2_sql,
    polar4ai_text_2_chart,
    polar4ai_import_doc,
    polar4ai_search_doc
)

# Fixtures for environment variables
@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(env_path)
    for key, value in os.environ.items():
        if key.startswith("POLARDB_MYSQL_"):
            monkeypatch.setenv(key, value)

    
def test_exec_sql():
    logging.info("start run test_exec_sql")
    config = get_db_config()
    rows, ok = exec_sql(config,"select 1000;")
    assert ok
    assert rows[0][0] == 1000
    logging.info(" end run test_exec_sql")

def test_get_sql_operation_type():
    assert get_sql_operation_type("INSERT INTO test VALUES (1)") == "INSERT"
    assert get_sql_operation_type("UPDATE test SET col=1") == "UPDATE"
    assert get_sql_operation_type("DELETE FROM test") == "DELETE"
    assert get_sql_operation_type("CREATE TABLE test (id INT)") == "DDL"
    assert get_sql_operation_type("SELECT * FROM test") == "OTHER"


def prepare_data(config,table_name):
    table_students = table_name
    create_table_sql = f"""
        CREATE TABLE {table_students} (
            student_id VARCHAR(20) PRIMARY KEY COMMENT '学号，主键，唯一标识学生',
            student_name VARCHAR(50) NOT NULL COMMENT '学生姓名',
            total_score DECIMAL(5,2) NOT NULL COMMENT '学生总分（例如：95.5）',
            class_name VARCHAR(50) COMMENT '学生所在班级名称'
        ) COMMENT='学生成绩表，记录学生的总分及班级信息';
    """
    insert_table_sql = f"""
    INSERT INTO {table_students} (student_id, student_name, total_score, class_name) VALUES
    ('2023A0101', '张三', 92.50, '高一（1）班'),
    ('2023A0102', '李四', 88.00, '高一（1）班'),
    ('2023A0103', '王五', 75.75, '高一（2）班'),
    ('2023A0104', '赵六', 95.25, '高一（2）班'),
    ('2023A0105', '陈雨', 82.00, '高二（1）班'),
    ('2023A0106', '刘洋', 78.50, '高二（1）班'),
    ('2023A0107', '周婷', 90.00, '高二（2）班'),
    ('2023A0108', '吴昊', 84.75, '高二（2）班'),
    ('2023A0109', '郑浩', 68.25, '高三（1）班'),
    ('2023A0110', '王芳', 93.50, '高三（1）班');
    """
    rows, ok = exec_sql(config, create_table_sql)
    assert ok
    rows, ok = exec_sql(config, insert_table_sql)
    assert ok

def clear_data(config,index_table_name, table_name):
    exec_sql(config, f"/*polar4ai*/ drop table {index_table_name};")
    exec_sql(config, f"drop table {table_name};")


def test_polar4ai_update_index_for_text_2_sql1():
    logging.info("start run test_polar4ai_update_index_for_text_2_sql1")
    arguments = {
        "force_update": True
    }
    # before test
    config = get_db_config()
    index_table_name = "test_schema_index1";
    table_students = "test_polar4ai_students1";
    prepare_data(config,table_students)
    polar4ai_update_index_for_text_2_sql(arguments, index_table_name)
    # sleep 5 seconds
    time.sleep(5)
    rows, ok = exec_sql(config, f"/*polar4ai*/select count(*) from {index_table_name}")
    assert ok
    assert int(rows[0][0]) > 0
    clear_data(config, index_table_name, table_students)
    logging.info("end run test_polar4ai_update_index_for_text_2_sql1")

def test_polar4ai_update_index_for_text_2_sql2():
    logging.info("start run test_polar4ai_update_index_for_text_2_sql2")
    arguments = {
        "force_update": False
    }
    # before test
    config = get_db_config()
    index_table_name = "test_schema_index1";
    table_students = "test_polar4ai_students1";
    prepare_data(config,table_students)
    polar4ai_update_index_for_text_2_sql(arguments, index_table_name)
    # sleep 5 seconds
    time.sleep(5)
    rows, ok = exec_sql(config, f"/*polar4ai*/select count(*) from {index_table_name}")
    assert ok
    assert int(rows[0][0]) > 0
    clear_data(config, index_table_name, table_students)
    logging.info("end run test_polar4ai_update_index_for_text_2_sql2")

def test_polar4ai_text_2_sql():
    logging.info("start run test_polar4ai_text_2_sql")
    arguments = {
        "force_update": True
    }
    # before test
    config = get_db_config()
    index_table_name = "test_schema_index1";
    table_students = "test_polar4ai_students1";
    prepare_data(config,table_students)
    polar4ai_update_index_for_text_2_sql(arguments, index_table_name)
    # sleep 5 seconds
    time.sleep(5)
    rows, ok = exec_sql(config, f"/*polar4ai*/select count(*) from {index_table_name}")
    assert ok
    assert int(rows[0][0]) > 0
    arguments1 = {
        "text": "获取各班级平均分"
    }
    result = polar4ai_text_2_sql(arguments1, index_table_name)
    logging.info(f"result:{result}")
    #clear data
    clear_data(config, index_table_name, table_students)
    logging.info("end run test_polar4ai_text_2_sql")

def test_polar4ai_text_2_chart():
    logging.info("start run test_polar4ai_text_2_sql")
    arguments = {
        "force_update": True
    }
    # before test
    config = get_db_config()
    index_table_name = "test_schema_index1";
    table_students = "test_polar4ai_students1";
    prepare_data(config,table_students)
    polar4ai_update_index_for_text_2_sql(arguments, index_table_name)
    # sleep 5 seconds
    time.sleep(5)
    rows, ok = exec_sql(config, f"/*polar4ai*/select count(*) from {index_table_name}")
    assert ok
    assert int(rows[0][0]) > 0
    arguments1 = {
        "text": "获取各班级平均分"
    }
    result = polar4ai_text_2_chart(arguments1, index_table_name)
    logging.info(f"result:{result}")
    #clear data
    clear_data(config, index_table_name, table_students)
    logging.info("end run test_polar4ai_text_2_sql")

 
def test_polar4ai_search_doc():
    default_table="default_knowledge_base"
    table_name = "test_default_knowledge_base"
    arguments_import1 = {
        "dir": './tests/test_doc',
        "table_name":table_name
    }
    arguments_import2 = {
        "dir": './tests/test_doc'
    }
    polar4ai_import_doc(arguments_import1)
    polar4ai_import_doc(arguments_import2)
    polar4ai_import_doc(arguments_import2)
    arguments_search1 = {
        "text": '负载均衡策略',
        "table_name":table_name,
    }
    arguments_search2 = {
       "text": '负载均衡策略',
       "count":6
    }
    result = polar4ai_search_doc(arguments_search1)
    result_text = result[0].text
    data_list = ast.literal_eval(result_text)
    assert len(data_list) ==5
    result= polar4ai_search_doc(arguments_search2)
    result_text = result[0].text
    data_list = ast.literal_eval(result_text)
    assert len(data_list) == 6
    # clear data
    sql1 = f"drop table {default_table}"
    sql2 = f"drop table {table_name}"
    config = get_db_config()
    rows, ok = exec_sql(config, sql1)
    assert ok
    rows, ok = exec_sql(config, sql2)
    assert ok


from langchain.text_splitter import MarkdownTextSplitter
import mammoth
from mysql.connector import connect, Error
import logging
import os
import re
import time
import json
logger = logging.getLogger("polardb-mysql-mcp-server")
DEFAULT_TABLE_NAME = "default_knowledge_base"

_IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*$')


def _validate_identifier(name, kind="identifier"):
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid {kind}: {name!r}")
    return name


def _quote_identifier(name, kind="identifier"):
    safe = _validate_identifier(name, kind)
    return "`" + safe.replace("`", "``") + "`"


def _escape_sql_string(value):
    if not isinstance(value, str):
        raise ValueError("expected string")
    if "\x00" in value:
        raise ValueError("NUL byte not allowed in SQL string")
    return (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\x1a", "\\Z")
    )


_VECTOR_RE = re.compile(r'^[\[\]\d.,eE+\-\s]+$')
class DocImport:
    def __init__(self,db_config,chunk_size_ =500,chunk_overlap_=50):
        self.text_splitter = MarkdownTextSplitter(chunk_size=chunk_size_, chunk_overlap=chunk_overlap_)
        self.config = db_config
    def split_documents(self,file_path):
        texts = self.text_splitter.split_text(self.doc_to_markdown(file_path))
        return texts
    def _convert_image(self,image):
        return []
    def doc_to_markdown(self,file_path) -> str:
        if file_path.endswith(".docx"):
            with open(file_path, "rb") as doc_file:
                result = mammoth.convert_to_markdown(doc_file, convert_image=self._convert_image)
                markdown_text = result.value
                return markdown_text
        else:
            with open(file_path, 'r', encoding='utf-8') as doc_file:
                contents = doc_file.read()
                return contents

    def text_to_vect(self, text):
        safe_text = _escape_sql_string(text)
        query_sql = f"/*polar4ai*/SELECT * FROM predict(model _polar4ai_text2vec, SELECT '{safe_text}') with();"
        rows, ok = self.exec_sql(query_sql)
        if ok:
            if len(rows) != 1:
                logger.error(f"executing SQL '{query_sql}' with more than one rows({len(rows)})")
                return ""
            else:
                vec = rows[0][0]
                return vec
        else:
            return ""    
    def exec_sql(self, sql):
        rows=[]
        try:
            with connect(**self.config) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql)
                    if cursor.description is not None:
                        return cursor.fetchall(),True
                    else:
                        conn.commit()
                        return rows,True
        except Error as e:
            logger.error(f"Error executing SQL '{sql}': {e}")
            return rows,False

    def get_all_docxs(self, dir):
        result = []
        files_and_dirs = os.listdir(dir)
        for file_or_dir in files_and_dirs:
            file_path = os.path.join(dir, file_or_dir)
            if os.path.isfile(file_path) and (file_or_dir.endswith('docx') or file_or_dir.endswith('md')):
                result.append((file_path, file_or_dir))
        return result

    def text_deal(self, text):
        text = text.replace('\'','"')
        text = text.replace('\\"', '"')
        text = text.replace('\\','\\\\')
        text = text.replace('\\\'', '"') 
        text = text.replace("/*","/.")
        text = text.replace("*/","./")
        return text
                  
    def import_doc(self, dir, table='') -> str:
        if table == '':
            table_name = DEFAULT_TABLE_NAME
        else:
            table_name = table
        try:
            _validate_identifier(table_name, "table_name")
        except ValueError as e:
            logger.error(f"Invalid table_name '{table_name}': {e}")
            return f"Invalid table_name '{table_name}'"
        logger.info(f"table_name:{table_name}")
        quoted_table = _quote_identifier(table_name, "table_name")
        create_table_sql = f"""
            create table if not exists {quoted_table}(
            id int unsigned auto_increment,
            chunk_content text, 
            file_name varchar(256),
            vecs vector(768), 
            primary key(id)
            )comment 'columnar=1';
        """
        rows, ok = self.exec_sql(create_table_sql)
        if not ok:
            logger.error(f"Error creating table '{table_name}'")
            return  f"Error creating table '{table_name}'"
        docs = self.get_all_docxs(dir)
        entry_count = 0
        file_count = 0
        for doc in docs:
            file_count += 1
            file_path, file_name = doc
            texts = self.split_documents(file_path)
            for text in texts:
                text = self.text_deal(text)
                vec = self.text_to_vect(text)
                if vec != "":
                    if not _VECTOR_RE.match(vec):
                        logger.error("Refusing to insert non-numeric vector literal")
                        continue
                    safe_text = _escape_sql_string(text)
                    safe_file = _escape_sql_string(file_name)
                    insert_sql = (
                        f"insert into {quoted_table} (chunk_content, file_name, vecs) "
                        f"values ('{safe_text}', '{safe_file}', string_to_vector(\"{vec}\"))"
                    )
                    rows, ok = self.exec_sql(insert_sql)
                    if not ok:
                        logger.error(f"Error inserting into table '{table_name}'")
                    else:
                        entry_count += 1
        logger.info(f"success import {entry_count} entries with {file_count} files to table({table_name})")
        return f"success import {entry_count} entries with {file_count} files"
    
    def query_knowledge(self, text: str,count=5,table=''):
        text = self.text_deal(text)
        vec = self.text_to_vect(text)
        if table=='':
            table_name = DEFAULT_TABLE_NAME
        else:
            table_name = table
        try:
            _validate_identifier(table_name, "table_name")
        except ValueError as e:
            logger.error(f"Invalid table_name '{table_name}': {e}")
            return []
        try:
            count = int(count)
        except (TypeError, ValueError):
            logger.error(f"Invalid count {count!r}, falling back to 5")
            count = 5
        if count <= 0 or count > 1000:
            count = 5
        if vec == "" or not _VECTOR_RE.match(vec):
            logger.error("No usable vector for query")
            return []
        quoted_table = _quote_identifier(table_name, "table_name")
        query_sql = (
            f"/*force_imci*/ select file_name,chunk_content, "
            f"distance(string_to_vector(\"{vec}\"), vecs, \"COSINE\") as d "
            f"from {quoted_table} order by d limit {count};"
        )
        rows, ok = self.exec_sql(query_sql)
        result = []
        if ok:
            for row in rows:
                result.append({"file_name": row[0], "content": row[1]})
        return result
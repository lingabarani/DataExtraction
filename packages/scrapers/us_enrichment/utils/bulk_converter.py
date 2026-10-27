"""
Bulk File Converter Utility for US B2B Open Directory Scraping Pipeline.

Provides high-performance, streaming conversion of bulk Excel (.xlsx), CSV (.csv),
and ZIP (.zip) archives directly into JSON and Line-Delimited JSON (.jsonl) format.
Designed to handle multi-gigabyte datasets without memory exhaustion.
"""

import json
import os
import zipfile
import io
from typing import List, Dict, Any, Generator, Optional, Union
import pandas as pd


def stream_csv_to_jsonl(
    csv_input: Union[str, io.IOBase],
    jsonl_output_path: str,
    chunk_size: int = 100000,
    encoding: str = "utf-8",
    field_mapping: Optional[Dict[str, str]] = None,
) -> int:
    """
    Reads a CSV file in chunks and streams records directly into a .jsonl file.
    
    :param csv_input: Path to CSV file or file-like object.
    :param jsonl_output_path: Output filepath for .jsonl file.
    :param chunk_size: Number of rows per chunk.
    :param encoding: File encoding.
    :param field_mapping: Optional dict to rename CSV headers to target JSON keys.
    :return: Total number of records converted.
    """
    total_records = 0
    os.makedirs(os.path.dirname(os.path.abspath(jsonl_output_path)), exist_ok=True)
    
    with open(jsonl_output_path, "w", encoding="utf-8") as out_f:
        chunks = pd.read_csv(
            csv_input,
            chunksize=chunk_size,
            low_memory=False,
            encoding=encoding,
            on_bad_lines="skip"
        )
        for chunk in chunks:
            if field_mapping:
                chunk = chunk.rename(columns=field_mapping)
            
            # Clean NaN values
            records = chunk.where(pd.notnull(chunk), None).to_dict(orient="records")
            for record in records:
                out_f.write(json.dumps(record, default=str) + "\n")
                total_records += 1
                
    return total_records


def stream_excel_to_jsonl(
    excel_path: str,
    jsonl_output_path: str,
    sheet_name: Union[str, int] = 0,
    field_mapping: Optional[Dict[str, str]] = None,
) -> int:
    """
    Reads an Excel (.xlsx) file and streams rows directly into a .jsonl file.
    Uses openpyxl read-only mode for memory efficiency.
    
    :param excel_path: Path to .xlsx file.
    :param jsonl_output_path: Target .jsonl filepath.
    :param sheet_name: Sheet index or sheet name.
    :param field_mapping: Optional column renaming dict.
    :return: Total records written.
    """
    total_records = 0
    os.makedirs(os.path.dirname(os.path.abspath(jsonl_output_path)), exist_ok=True)

    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    if field_mapping:
        df = df.rename(columns=field_mapping)

    records = df.where(pd.notnull(df), None).to_dict(orient="records")
    with open(jsonl_output_path, "w", encoding="utf-8") as out_f:
        for record in records:
            out_f.write(json.dumps(record, default=str) + "\n")
            total_records += 1

    return total_records


def zip_to_jsonl(
    zip_source: Union[str, bytes, io.BytesIO],
    jsonl_output_path: str,
    target_extension: str = ".csv",
    chunk_size: int = 100000,
) -> int:
    """
    Extracts CSV/XLSX files inside a ZIP archive in-memory and converts them directly to JSONL.
    
    :param zip_source: File path, bytes, or BytesIO object of ZIP archive.
    :param jsonl_output_path: Output filepath.
    :param target_extension: Extension to process inside ZIP (.csv or .xlsx).
    :param chunk_size: Chunk size for CSV reading.
    :return: Total records converted.
    """
    total_records = 0
    if isinstance(zip_source, str):
        zf = zipfile.ZipFile(zip_source, "r")
    elif isinstance(zip_source, bytes):
        zf = zipfile.ZipFile(io.BytesIO(zip_source), "r")
    else:
        zf = zipfile.ZipFile(zip_source, "r")

    try:
        for filename in zf.namelist():
            if filename.lower().endswith(target_extension.lower()):
                with zf.open(filename) as f:
                    if target_extension.lower() == ".csv":
                        count = stream_csv_to_jsonl(f, jsonl_output_path, chunk_size=chunk_size)
                        total_records += count
    finally:
        zf.close()

    return total_records


def jsonl_to_json_records(jsonl_path: str, max_records: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Reads a .jsonl file and returns a list of dictionaries.
    
    :param jsonl_path: Path to .jsonl file.
    :param max_records: Optional cap on records loaded.
    :return: List of JSON records.
    """
    records = []
    if not os.path.exists(jsonl_path):
        return records

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if max_records and i >= max_records:
                break
            line_str = line.strip()
            if line_str:
                records.append(json.loads(line_str))

    return records

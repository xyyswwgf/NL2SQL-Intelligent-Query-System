"""
================================================================================
CSV 导入引擎 — 解析、类型推断、建表、批量写入
================================================================================

核心功能:
  - 支持多行合并表头（Excel 合并单元格场景）
  - 支持跳过末尾非数据行（汇总、签字行等）
  - 自动编码检测（UTF-8 / GBK / GB2312）
  - 自动分隔符检测（逗号 / 制表符）
  - 智能类型推断 + 用户手动覆盖
  - 自定义主键列

安全设计:
  - 所有 SQL 由服务端构造，不经过 sql_guard
  - 列名和表名经过清理 + backtick 包裹
  - 数据值通过 PyMySQL executemany 参数化传递
================================================================================
"""

import csv
import io
import re
import datetime
import logging
from backend.database import execute_ddl, execute_insert

logger = logging.getLogger("nl2sql.csv_importer")

# ---------------------------------------------------------------------------
_NULL_MARKERS = {"", "null", "none", "na", "n/a", "-", "nil", "无", "空", "/"}
_MAX_COLUMN_NAME_LEN = 64
_MIN_VARCHAR_LEN = 100
_MAX_VARCHAR_LEN = 2000
_UTF8MB4_BYTE_FACTOR = 4

# 非数据行的特征（用于自动检测尾部行）
_FOOTER_KEYWORDS = ["合计", "总计", "签字", "审核", "日期", "院长", "公章", "备注", "说明"]


# ═══════════════════════════════════════════════════════════════
# 1. CSV 解析
# ═══════════════════════════════════════════════════════════════

def parse_csv(
    file_bytes: bytes,
    has_header: bool = True,
    header_row: int = 1,
    data_start_row: int | None = None,
    skip_trailing_rows: int = 0,
    combine_header_rows: int = 1,
) -> tuple[list[str], list[list[str]]]:
    """解析 CSV 原始字节 → (表头列表, 数据行列表)"""
    if data_start_row is None:
        data_start_row = header_row + combine_header_rows if has_header else 1

    # ── 编码检测 ──
    text = None
    for enc in ["utf-8", "gbk", "gb2312", "latin-1"]:
        try:
            text = file_bytes.decode(enc)
            logger.info("CSV 编码: %s", enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise ValueError("无法识别 CSV 文件编码，请确保为 UTF-8 或 GBK 编码。")

    if text and text[0] == "﻿":
        text = text[1:]
    if not text.strip():
        raise ValueError("CSV 文件为空。")

    # ── 解析 ──
    delimiter = _detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    all_lines = list(reader)
    # 使用逻辑行号（csv.reader 已处理好引号内的换行）
    # 过滤空行后的逻辑行，1-based 编号
    logical_rows = [row for row in all_lines if any(c.strip() for c in row)]
    if not logical_rows:
        raise ValueError("CSV 文件没有有效内容。")

    total_rows = len(logical_rows)

    # ── 跳过末尾行 ──
    if skip_trailing_rows > 0:
        if skip_trailing_rows >= total_rows:
            raise ValueError(f"跳过末尾行数({skip_trailing_rows})≥总行数({total_rows})")
        logical_rows = logical_rows[:total_rows - skip_trailing_rows]
        total_rows = len(logical_rows)

    # ── 自动检测表头行 ──
    if has_header and header_row <= 0:
        header_row = auto_detect_header_row(logical_rows)
        logger.info("自动检测表头行: %d", header_row)

    # ── 提取表头 ──
    if has_header:
        h_idx = header_row - 1  # 转0-based
        if h_idx + combine_header_rows > total_rows:
            raise ValueError(f"表头行范围超出总行数({total_rows})，请调整行号设置。")

        if combine_header_rows == 1:
            headers = logical_rows[h_idx]
        else:
            header_rows = logical_rows[h_idx:h_idx + combine_header_rows]
            max_c = max((len(r) for r in header_rows), default=0)
            headers = []
            for ci in range(max_c):
                parts = []
                for row in header_rows:
                    v = row[ci].strip() if ci < len(row) else ""
                    if v and v not in parts:
                        parts.append(v)
                headers.append("-".join(parts) if parts else f"列{ci + 1}")
            logger.info("合并%d行表头→%d列", combine_header_rows, len(headers))

        d_idx = max(data_start_row - 1, h_idx + combine_header_rows)
        if d_idx >= total_rows:
            raise ValueError(f"数据起始行 {data_start_row} 超出范围({total_rows})")
        rows = logical_rows[d_idx:]
    else:
        max_c = max((len(row) for row in logical_rows), default=0)
        headers = [f"col_{i + 1}" for i in range(max_c)]
        rows = logical_rows[data_start_row - 1:]

    if not rows:
        raise ValueError("没有找到数据行，请检查「列名所在行」和「数据起始行」设置。")

    max_cols = len(headers)
    rows = [_pad_row(row, max_cols) for row in rows]

    logger.info("CSV解析: %d列 %d行 (表头=%d~%d 数据起始=%d 跳末尾=%d)",
                max_cols, len(rows), header_row, header_row + combine_header_rows - 1,
                data_start_row, skip_trailing_rows)
    return headers, rows


def _detect_delimiter(text: str) -> str:
    sample = "\n".join(text.strip().split("\n")[:10])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except Exception:
        counts = {d: sample.count(d) for d in [",", "\t", ";", "|"]}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else ","


def _pad_row(row: list[str], target_len: int) -> list[str]:
    if len(row) < target_len:
        return row + [""] * (target_len - len(row))
    return row[:target_len]


def auto_detect_trailing_rows(rows: list[list[str]], threshold: float = 0.5) -> int:
    """自动检测末尾非数据行数量（基于关键词匹配）"""
    if len(rows) < 3:
        return 0
    n = 0
    for row in reversed(rows[-10:]):
        row_text = "".join(str(c) for c in row)
        matches = sum(1 for kw in _FOOTER_KEYWORDS if kw in row_text)
        if matches >= 2 or (matches >= 1 and len([c for c in row if c.strip()]) <= 3):
            n += 1
        else:
            break
    return min(n, 10)


def auto_detect_header_row(logical_rows: list[list[str]]) -> int:
    """自动检测表头所在逻辑行号（1-based）"""
    # 策略：找第一个包含「序号」或「学号」或「姓名」等常见表头关键词的行
    _header_keywords = ["序号", "学号", "姓名", "编号", "ID", "id", "代码", "日期"]
    for i, row in enumerate(logical_rows[:15]):
        row_text = " ".join(str(c)[:20] for c in row if c.strip())
        matches = sum(1 for kw in _header_keywords if kw in row_text)
        # 同时检查第一列是否为数字（表头行第一列通常是文本如"序号"）
        first_col = row[0].strip() if row else ""
        is_text_header = first_col and not first_col.replace(".", "").replace("-", "").isdigit()
        if matches >= 2 or (matches >= 1 and is_text_header):
            return i + 1  # 1-based
    return 1  # 默认第一行


# ═══════════════════════════════════════════════════════════════
# 2. 列名规范化
# ═══════════════════════════════════════════════════════════════

def sanitize_column_name(raw: str, used_names: set | None = None) -> str:
    if used_names is None:
        used_names = set()
    name = raw.strip()
    name = re.sub(r"[\x00-\x1f`]", "", name)
    name = name.replace("　", " ")
    name = re.sub(r" {2,}", " ", name).strip()
    if not name:
        name = f"column_{len(used_names) + 1}"
    if name[0].isdigit():
        name = "col_" + name
    if len(name) > _MAX_COLUMN_NAME_LEN:
        name = name[:_MAX_COLUMN_NAME_LEN].rstrip()
    original = name
    counter = 2
    while name.lower() in {n.lower() for n in used_names}:
        suffix = f"_{counter}"
        max_base = _MAX_COLUMN_NAME_LEN - len(suffix)
        name = original[:max_base].rstrip() + suffix
        counter += 1
    used_names.add(name)
    return name


# ═══════════════════════════════════════════════════════════════
# 3. 表名推导
# ═══════════════════════════════════════════════════════════════

def derive_table_name(filename: str) -> str:
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    name = re.sub(r"[\x00-\x1f`]", "", name)
    name = name.replace("　", " ")
    name = re.sub(r" {2,}", " ", name).strip()
    if not name:
        name = "imported"
    if not name.lower().startswith("csv_"):
        name = "csv_" + name
    if len(name) > _MAX_COLUMN_NAME_LEN:
        name = name[:_MAX_COLUMN_NAME_LEN].rstrip()
    return name


# ═══════════════════════════════════════════════════════════════
# 4. 类型推断
# ═══════════════════════════════════════════════════════════════

def infer_column_types(headers: list[str], rows: list[list[str]], overrides: dict | None = None) -> list[dict]:
    if overrides is None:
        overrides = {}
    if not rows:
        return [{"name": h, "type": overrides.get(h, f"VARCHAR({_MIN_VARCHAR_LEN})"),
                 "nullable": True, "max_len": _MIN_VARCHAR_LEN} for h in headers]

    results = []
    for col_idx, col_name in enumerate(headers):
        if col_name in overrides:
            results.append({"name": col_name, "type": overrides[col_name], "nullable": True, "max_len": _MIN_VARCHAR_LEN})
            continue

        values = [row[col_idx] if col_idx < len(row) else "" for row in rows]
        non_null = [v for v in values if v.strip().lower() not in _NULL_MARKERS]
        has_null = len(non_null) < len(values)
        max_blen = max((len(v.encode("utf-8")) for v in non_null), default=0)

        if not non_null:
            results.append({"name": col_name, "type": f"VARCHAR({_MIN_VARCHAR_LEN})", "nullable": True, "max_len": _MIN_VARCHAR_LEN})
            continue

        is_int, max_int_val = _try_int(non_null)
        if is_int:
            int_type = "BIGINT" if max_int_val > 2_147_483_647 else "INT"
            results.append({"name": col_name, "type": int_type, "nullable": has_null, "max_len": max_blen})
        elif (dt := _try_decimal(non_null)):
            results.append({"name": col_name, "type": dt, "nullable": has_null, "max_len": max_blen})
        elif _try_date(non_null):
            results.append({"name": col_name, "type": "DATE", "nullable": has_null, "max_len": max_blen})
        elif _try_datetime(non_null):
            results.append({"name": col_name, "type": "DATETIME", "nullable": has_null, "max_len": max_blen})
        else:
            vlen = max(int(max_blen * _UTF8MB4_BYTE_FACTOR * 0.8), _MIN_VARCHAR_LEN)
            vlen = min(vlen, _MAX_VARCHAR_LEN)
            results.append({"name": col_name, "type": f"VARCHAR({vlen})", "nullable": has_null, "max_len": vlen})

    return results


def _try_int(vals):
    """尝试 INT / BIGINT"""
    max_val = 0
    try:
        for v in vals:
            iv = int(v)
            max_val = max(max_val, abs(iv))
        return True, max_val
    except (ValueError, TypeError):
        return False, 0

def _try_decimal(vals):
    mi, mf = 0, 0
    try:
        for v in vals:
            s = v.strip()
            float(s)
            if "." in s:
                ip, fp = s.split(".", 1)
                mi = max(mi, len(ip.lstrip("-")))
                mf = max(mf, len(fp))
            else:
                mi = max(mi, len(s.lstrip("-")))
        p = min(mi + mf, 18)
        s = min(mf, 4)
        return f"DECIMAL({max(p,1)},{s})"
    except (ValueError, TypeError):
        return None

def _try_date(vals):
    pat = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for v in vals:
        v = v.strip()
        if not pat.match(v): return False
        try:
            datetime.date.fromisoformat(v)
        except ValueError:
            return False
    return True

def _try_datetime(vals):
    pats = [r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$"]
    for v in vals:
        if not any(re.match(p, v.strip()) for p in pats): return False
    return True


# ═══════════════════════════════════════════════════════════════
# 5. 建表 & 写入
# ═══════════════════════════════════════════════════════════════

def create_table(table_name: str, columns: list[dict], primary_key_column: str | None = None) -> None:
    col_defs = []
    pk_added = False
    if primary_key_column and any(c["name"] == primary_key_column for c in columns):
        for col in columns:
            nc = "NOT NULL" if col["name"] == primary_key_column else "DEFAULT NULL"
            pk = "PRIMARY KEY" if col["name"] == primary_key_column else ""
            col_defs.append(f"`{col['name']}` {col['type']} {nc} {pk} COMMENT '导入列'".strip())
        pk_added = True
    else:
        col_defs.append("`_id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '自动行号'")
        for col in columns:
            null_clause = "DEFAULT NULL" if col.get("nullable", True) else "NOT NULL"
            col_defs.append(f"`{col['name']}` {col['type']} {null_clause} COMMENT '导入列'")

    if not pk_added:
        col_defs.append("`_imported_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '导入时间'")

    ddl = f"CREATE TABLE `{table_name}` (\n  " + ",\n  ".join(col_defs) + \
          f"\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='CSV导入表'"
    logger.info("DDL: %s", ddl[:300])
    execute_ddl(ddl)


def insert_rows(table_name: str, headers: list[str], rows: list[list[str]], batch_size: int = 500) -> int:
    if not rows:
        return 0
    ph = ", ".join(["%s"] * len(headers))
    cs = ", ".join(f"`{h}`" for h in headers)
    sql = f"INSERT INTO `{table_name}` ({cs}) VALUES ({ph})"
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        params = [tuple(row) for row in batch]
        total += execute_insert(sql, params)
        logger.info("已插入 %d/%d 行 → %s", total, len(rows), table_name)
    return total

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import dataclasses
import re
import sys
import zlib
from typing import Any, Iterable, Iterator, Optional


@dataclasses.dataclass(frozen=True)
class PDFRef:
    obj: int
    gen: int


@dataclasses.dataclass(frozen=True)
class PDFStream:
    dictionary: dict[str, Any]
    data: bytes


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    value: Any


WHITESPACE = b" \t\r\n\x0c\x00"
DELIMITERS = b"()<>[]{}/%"


def _is_delimiter(byte: int) -> bool:
    return byte in DELIMITERS or byte in WHITESPACE


def _decode_pdf_name(raw: bytes) -> str:
    # PDF name objects may contain #XX hex escapes.
    out = bytearray()
    i = 0
    while i < len(raw):
        if raw[i : i + 1] == b"#" and i + 2 < len(raw):
            try:
                out.append(int(raw[i + 1 : i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out.append(raw[i])
        i += 1
    return out.decode("latin1", errors="replace")


def _read_literal_string(data: bytes, start: int) -> tuple[bytes, int]:
    # Starts at '(' and returns (decoded_bytes, next_index).
    i = start + 1
    depth = 1
    out = bytearray()
    while i < len(data) and depth > 0:
        b = data[i]
        if b == 0x5C:  # backslash
            i += 1
            if i >= len(data):
                break
            esc = data[i]
            if esc in b"nrtbf":
                out.append(
                    {
                        ord("n"): 0x0A,
                        ord("r"): 0x0D,
                        ord("t"): 0x09,
                        ord("b"): 0x08,
                        ord("f"): 0x0C,
                    }[esc]
                )
                i += 1
                continue
            if esc in b"\\()":
                out.append(esc)
                i += 1
                continue
            if 0x30 <= esc <= 0x37:  # octal escape
                j = i
                oct_digits = bytearray()
                while j < len(data) and len(oct_digits) < 3 and 0x30 <= data[j] <= 0x37:
                    oct_digits.append(data[j])
                    j += 1
                try:
                    out.append(int(oct_digits.decode("ascii"), 8) & 0xFF)
                except ValueError:
                    pass
                i = j
                continue
            # Unknown escape: treat the escaped char literally.
            out.append(esc)
            i += 1
            continue

        if b == 0x28:  # '('
            depth += 1
            out.append(b)
            i += 1
            continue
        if b == 0x29:  # ')'
            depth -= 1
            if depth == 0:
                i += 1
                break
            out.append(b)
            i += 1
            continue

        out.append(b)
        i += 1
    return bytes(out), i


def _read_hex_string(data: bytes, start: int) -> tuple[bytes, int]:
    # Starts at '<' (not '<<') and returns (decoded_bytes, next_index)
    i = start + 1
    hex_chars = bytearray()
    while i < len(data):
        b = data[i]
        if b == 0x3E:  # '>'
            i += 1
            break
        if b in WHITESPACE:
            i += 1
            continue
        hex_chars.append(b)
        i += 1
    if len(hex_chars) % 2 == 1:
        hex_chars.append(ord("0"))
    try:
        return bytes.fromhex(hex_chars.decode("ascii")), i
    except ValueError:
        return b"", i


def tokenize(data: bytes) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(data):
        b = data[i]
        if b in WHITESPACE:
            i += 1
            continue
        if b == 0x25:  # '%': comment
            while i < len(data) and data[i] not in b"\r\n":
                i += 1
            continue
        if data[i : i + 2] == b"<<":
            tokens.append(Token("DICT_START", None))
            i += 2
            continue
        if data[i : i + 2] == b">>":
            tokens.append(Token("DICT_END", None))
            i += 2
            continue
        if b == 0x5B:  # '['
            tokens.append(Token("ARRAY_START", None))
            i += 1
            continue
        if b == 0x5D:  # ']'
            tokens.append(Token("ARRAY_END", None))
            i += 1
            continue
        if b == 0x28:  # '('
            s, j = _read_literal_string(data, i)
            tokens.append(Token("STRING", s))
            i = j
            continue
        if b == 0x3C and data[i : i + 2] != b"<<":  # '<' hex string
            s, j = _read_hex_string(data, i)
            tokens.append(Token("HEXSTRING", s))
            i = j
            continue
        if b == 0x2F:  # '/'
            j = i + 1
            while j < len(data) and not _is_delimiter(data[j]):
                j += 1
            tokens.append(Token("NAME", _decode_pdf_name(data[i + 1 : j])))
            i = j
            continue

        # number, boolean, null, keyword/operator
        j = i
        while j < len(data) and not _is_delimiter(data[j]):
            j += 1
        word = data[i:j]
        if word == b"true":
            tokens.append(Token("BOOL", True))
        elif word == b"false":
            tokens.append(Token("BOOL", False))
        elif word == b"null":
            tokens.append(Token("NULL", None))
        else:
            try:
                if b"." in word or b"e" in word or b"E" in word:
                    tokens.append(Token("NUMBER", float(word.decode("ascii"))))
                else:
                    tokens.append(Token("NUMBER", int(word.decode("ascii"))))
            except ValueError:
                tokens.append(Token("KEYWORD", word.decode("latin1", errors="replace")))
        i = j
    return tokens


class ParseError(Exception):
    pass


def _parse_object(tokens: list[Token], pos: int) -> tuple[Any, int]:
    if pos >= len(tokens):
        raise ParseError("unexpected end of tokens")
    t = tokens[pos]
    if t.kind == "DICT_START":
        out: dict[str, Any] = {}
        pos += 1
        while pos < len(tokens) and tokens[pos].kind != "DICT_END":
            key_tok = tokens[pos]
            if key_tok.kind != "NAME":
                raise ParseError(f"expected dict key NAME, got {key_tok.kind}")
            pos += 1
            val, pos = _parse_object_or_ref(tokens, pos)
            out[key_tok.value] = val
        if pos >= len(tokens) or tokens[pos].kind != "DICT_END":
            raise ParseError("unterminated dict")
        return out, pos + 1
    if t.kind == "ARRAY_START":
        out_list: list[Any] = []
        pos += 1
        while pos < len(tokens) and tokens[pos].kind != "ARRAY_END":
            val, pos = _parse_object_or_ref(tokens, pos)
            out_list.append(val)
        if pos >= len(tokens) or tokens[pos].kind != "ARRAY_END":
            raise ParseError("unterminated array")
        return out_list, pos + 1
    if t.kind in ("STRING", "HEXSTRING", "NAME", "NUMBER", "BOOL", "NULL"):
        return t.value, pos + 1
    if t.kind == "KEYWORD":
        return t.value, pos + 1
    raise ParseError(f"unhandled token kind: {t.kind}")


def _parse_object_or_ref(tokens: list[Token], pos: int) -> tuple[Any, int]:
    # Indirect reference: <int> <int> R
    if (
        pos + 2 < len(tokens)
        and tokens[pos].kind == "NUMBER"
        and isinstance(tokens[pos].value, int)
        and tokens[pos + 1].kind == "NUMBER"
        and isinstance(tokens[pos + 1].value, int)
        and tokens[pos + 2].kind == "KEYWORD"
        and tokens[pos + 2].value == "R"
    ):
        return PDFRef(tokens[pos].value, tokens[pos + 1].value), pos + 3
    return _parse_object(tokens, pos)


def parse_pdf_value(data: bytes) -> Any:
    toks = tokenize(data)
    if not toks:
        return None
    obj, pos = _parse_object_or_ref(toks, 0)
    if pos != len(toks):
        # Some objects contain multiple top-level tokens; return the first and ignore the rest.
        return obj
    return obj


OBJ_HEADER_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
STREAM_RE = re.compile(rb"\bstream\b\r?\n")


def extract_indirect_object_bodies(pdf_bytes: bytes) -> dict[tuple[int, int], bytes]:
    out: dict[tuple[int, int], bytes] = {}
    for m in OBJ_HEADER_RE.finditer(pdf_bytes):
        obj = int(m.group(1))
        gen = int(m.group(2))
        start = m.end()
        end = pdf_bytes.find(b"endobj", start)
        if end == -1:
            continue
        out[(obj, gen)] = pdf_bytes[start:end].strip()
    return out


def parse_indirect_object_body(body: bytes) -> Any:
    m = STREAM_RE.search(body)
    if m and b"endstream" in body:
        header = body[: m.start()].strip()
        endstream = body.find(b"endstream", m.end())
        stream_data = body[m.end() : endstream]
        header_obj = parse_pdf_value(header)
        header_dict: dict[str, Any] = header_obj if isinstance(header_obj, dict) else {}
        return PDFStream(dictionary=header_dict, data=stream_data)
    return parse_pdf_value(body)


def _asciihex_decode(data: bytes) -> bytes:
    filtered = bytearray()
    for b in data:
        if b in WHITESPACE:
            continue
        if b == 0x3E:  # '>' end marker
            break
        filtered.append(b)
    if len(filtered) % 2 == 1:
        filtered.append(ord("0"))
    try:
        return bytes.fromhex(filtered.decode("ascii"))
    except ValueError:
        return b""


def decode_stream(stream: PDFStream) -> bytes:
    data = stream.data
    filters = stream.dictionary.get("Filter")
    if filters is None:
        return data

    filter_list: list[str]
    if isinstance(filters, str):
        filter_list = [filters]
    elif isinstance(filters, list):
        filter_list = [f for f in filters if isinstance(f, str)]
    else:
        filter_list = []

    for f in filter_list:
        if f == "FlateDecode":
            try:
                data = zlib.decompress(data)
            except zlib.error:
                data = zlib.decompress(data, wbits=-15)
        elif f == "ASCII85Decode":
            data = base64.a85decode(data, adobe=True)
        elif f == "ASCIIHexDecode":
            data = _asciihex_decode(data)
        else:
            # Unknown filter: return best-effort.
            return data
    return data


def _obj_dict(obj: Any) -> Optional[dict[str, Any]]:
    if isinstance(obj, PDFStream):
        return obj.dictionary
    if isinstance(obj, dict):
        return obj
    return None


def _resolve(obj: Any, objects: dict[tuple[int, int], Any], depth: int = 0) -> Any:
    if depth > 50:
        return obj
    if isinstance(obj, PDFRef):
        resolved = objects.get((obj.obj, obj.gen)) or objects.get((obj.obj, 0))
        if resolved is None:
            return obj
        return _resolve(resolved, objects, depth + 1)
    return obj


def _deep_merge(parent: Any, child: Any) -> Any:
    if parent is None:
        return child
    if child is None:
        return parent
    if isinstance(parent, dict) and isinstance(child, dict):
        merged = dict(parent)
        for k, v in child.items():
            merged[k] = _deep_merge(parent.get(k), v)
        return merged
    return child


def _parse_all_objects(pdf_bytes: bytes) -> dict[tuple[int, int], Any]:
    bodies = extract_indirect_object_bodies(pdf_bytes)
    objects: dict[tuple[int, int], Any] = {}
    for key, body in bodies.items():
        try:
            objects[key] = parse_indirect_object_body(body)
        except Exception:
            continue

    # Expand object streams (ObjStm).
    objstm_refs: list[tuple[int, int]] = []
    for key, obj in objects.items():
        d = _obj_dict(obj)
        if not d:
            continue
        if d.get("Type") == "ObjStm":
            objstm_refs.append(key)

    for key in objstm_refs:
        obj = objects.get(key)
        if not isinstance(obj, PDFStream):
            continue
        d = obj.dictionary
        n = d.get("N")
        first = d.get("First")
        if not isinstance(n, int) or not isinstance(first, int):
            continue
        try:
            decoded = decode_stream(obj)
        except Exception:
            continue
        header = decoded[:first].strip().split()
        if len(header) < 2 * n:
            continue
        pairs: list[tuple[int, int]] = []
        ok = True
        for i in range(n):
            try:
                objnum = int(header[2 * i].decode("ascii"))
                offset = int(header[2 * i + 1].decode("ascii"))
                pairs.append((objnum, offset))
            except Exception:
                ok = False
                break
        if not ok:
            continue

        for idx, (objnum, offset) in enumerate(pairs):
            start = first + offset
            end = first + (pairs[idx + 1][1] if idx + 1 < len(pairs) else len(decoded) - first)
            raw_obj = decoded[start:end].strip()
            if not raw_obj:
                continue
            try:
                objects[(objnum, 0)] = parse_pdf_value(raw_obj)
            except Exception:
                continue
    return objects


def _find_catalog(objects: dict[tuple[int, int], Any]) -> Optional[dict[str, Any]]:
    for obj in objects.values():
        d = _obj_dict(obj)
        if d and d.get("Type") == "Catalog":
            return d
    return None


def _collect_pages(
    node: Any,
    objects: dict[tuple[int, int], Any],
    inherited_resources: Optional[dict[str, Any]] = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    resolved = _resolve(node, objects)
    d = _obj_dict(resolved)
    if not d:
        return []

    resources_obj = d.get("Resources")
    resources_dict: Optional[dict[str, Any]] = None
    if resources_obj is not None:
        resources_resolved = _resolve(resources_obj, objects)
        resources_dict = resources_resolved if isinstance(resources_resolved, dict) else None
    merged_resources = _deep_merge(inherited_resources, resources_dict)

    if d.get("Type") == "Page":
        return [(d, merged_resources or {})]

    if d.get("Type") != "Pages":
        return []

    kids = d.get("Kids", [])
    if not isinstance(kids, list):
        return []

    pages: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for kid in kids:
        pages.extend(_collect_pages(kid, objects, merged_resources))
    return pages


def _utf16be_to_str(data: bytes) -> str:
    if len(data) % 2 == 1:
        data = data + b"\x00"
    return data.decode("utf-16-be", errors="replace")


def _parse_tounicode_cmap(cmap_bytes: bytes) -> dict[bytes, str]:
    text = cmap_bytes.decode("latin1", errors="ignore")
    text = re.sub(r"%.*", "", text)
    mapping: dict[bytes, str] = {}

    for bfchar_block in re.finditer(r"beginbfchar(.*?)endbfchar", text, re.S):
        for m in re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", bfchar_block.group(1)):
            src = bytes.fromhex(m.group(1))
            dst = _utf16be_to_str(bytes.fromhex(m.group(2)))
            mapping[src] = dst

    for bfrange_block in re.finditer(r"beginbfrange(.*?)endbfrange", text, re.S):
        block = bfrange_block.group(1)
        # Array form: <start> <end> [<u1> <u2> ...]
        for m in re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", block, re.S):
            start_hex, end_hex, arr = m.group(1), m.group(2), m.group(3)
            start_code = int(start_hex, 16)
            end_code = int(end_hex, 16)
            code_len = len(bytes.fromhex(start_hex))
            dests = re.findall(r"<([0-9A-Fa-f]+)>", arr)
            for i, dst_hex in enumerate(dests):
                code = start_code + i
                if code > end_code:
                    break
                src = int(code).to_bytes(code_len, "big")
                mapping[src] = _utf16be_to_str(bytes.fromhex(dst_hex))

        # Sequential form: <start> <end> <dstStart>
        for m in re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            start_hex, end_hex, dst_hex = m.group(1), m.group(2), m.group(3)
            start_code = int(start_hex, 16)
            end_code = int(end_hex, 16)
            code_len = len(bytes.fromhex(start_hex))
            dst_bytes = bytes.fromhex(dst_hex)
            if len(dst_bytes) % 2 != 0:
                continue
            if len(dst_bytes) != 2:
                # Multi-codepoint strings exist, but are rare here; skip for simplicity.
                continue
            dst_start = int.from_bytes(dst_bytes, "big")
            for i in range(end_code - start_code + 1):
                src = int(start_code + i).to_bytes(code_len, "big")
                mapping[src] = chr(dst_start + i)

    return mapping


@dataclasses.dataclass(frozen=True)
class CMap:
    mapping: dict[bytes, str]
    max_key_len: int


def _build_font_cmaps(
    resources: dict[str, Any], objects: dict[tuple[int, int], Any]
) -> dict[str, CMap]:
    res_fonts_obj = resources.get("Font")
    res_fonts = _resolve(res_fonts_obj, objects)
    if not isinstance(res_fonts, dict):
        return {}

    out: dict[str, CMap] = {}
    for font_name, font_ref in res_fonts.items():
        font_obj = _resolve(font_ref, objects)
        font_dict = _obj_dict(font_obj) or {}

        tounicode_ref = font_dict.get("ToUnicode")
        if isinstance(tounicode_ref, PDFRef):
            tounicode_obj = _resolve(tounicode_ref, objects)
            if isinstance(tounicode_obj, PDFStream):
                try:
                    cmap_bytes = decode_stream(tounicode_obj)
                except Exception:
                    cmap_bytes = b""
                mapping = _parse_tounicode_cmap(cmap_bytes) if cmap_bytes else {}
                max_len = max((len(k) for k in mapping), default=1)
                out[font_name] = CMap(mapping=mapping, max_key_len=max_len)
                continue

        # Try descendant fonts (Type0).
        desc = font_dict.get("DescendantFonts")
        if isinstance(desc, list) and desc:
            desc_dict = _obj_dict(_resolve(desc[0], objects)) or {}
            tounicode_ref = desc_dict.get("ToUnicode")
            if isinstance(tounicode_ref, PDFRef):
                tounicode_obj = _resolve(tounicode_ref, objects)
                if isinstance(tounicode_obj, PDFStream):
                    try:
                        cmap_bytes = decode_stream(tounicode_obj)
                    except Exception:
                        cmap_bytes = b""
                    mapping = _parse_tounicode_cmap(cmap_bytes) if cmap_bytes else {}
                    max_len = max((len(k) for k in mapping), default=1)
                    out[font_name] = CMap(mapping=mapping, max_key_len=max_len)
    return out


def _decode_text_bytes(raw: bytes, cmap: Optional[CMap]) -> str:
    if not raw:
        return ""
    if cmap is None or not cmap.mapping:
        return raw.decode("latin1", errors="replace")

    out: list[str] = []
    i = 0
    while i < len(raw):
        matched = False
        for ln in range(min(cmap.max_key_len, len(raw) - i), 0, -1):
            chunk = raw[i : i + ln]
            s = cmap.mapping.get(chunk)
            if s is not None:
                out.append(s)
                i += ln
                matched = True
                break
        if not matched:
            out.append(raw[i : i + 1].decode("latin1", errors="replace"))
            i += 1
    return "".join(out)


TEXT_OPERATORS_NEWLINE = {"T*", "TD"}


def extract_page_text(
    page: dict[str, Any],
    resources: dict[str, Any],
    objects: dict[tuple[int, int], Any],
) -> str:
    cmaps = _build_font_cmaps(resources, objects)
    current_font: Optional[str] = None

    contents = page.get("Contents")
    content_refs: list[Any]
    if isinstance(contents, list):
        content_refs = contents
    elif contents is None:
        content_refs = []
    else:
        content_refs = [contents]

    streams: list[PDFStream] = []
    for ref in content_refs:
        obj = _resolve(ref, objects)
        if isinstance(obj, PDFStream):
            streams.append(obj)

    out_lines: list[str] = []
    current_line: list[str] = []

    def flush_line() -> None:
        nonlocal current_line
        if current_line:
            out_lines.append("".join(current_line).replace("\x00", "").strip())
            current_line = []

    in_text = False
    for s in streams:
        try:
            data = decode_stream(s)
        except Exception:
            continue
        toks = tokenize(data)
        operands: list[Any] = []
        i = 0
        while i < len(toks):
            t = toks[i]
            if t.kind in ("ARRAY_START", "DICT_START"):
                try:
                    obj, j = _parse_object(toks, i)
                except Exception:
                    i += 1
                    continue
                operands.append(obj)
                i = j
                continue
            if t.kind in ("STRING", "HEXSTRING", "NAME", "NUMBER", "BOOL", "NULL"):
                operands.append(t.value)
                i += 1
                continue
            if t.kind != "KEYWORD":
                i += 1
                continue

            op = t.value
            if op == "BT":
                in_text = True
                operands.clear()
                i += 1
                continue
            if op == "ET":
                in_text = False
                operands.clear()
                flush_line()
                i += 1
                continue

            if not in_text:
                operands.clear()
                i += 1
                continue

            if op == "Tf" and len(operands) >= 2:
                font = operands[-2]
                if isinstance(font, str):
                    current_font = font
            elif op in ("Td", "TD", "T*"):
                flush_line()
            elif op == "'" and operands:
                flush_line()
                raw = operands[-1]
                if isinstance(raw, (bytes, bytearray)):
                    current_line.append(_decode_text_bytes(bytes(raw), cmaps.get(current_font or "")))
            elif op == '"' and operands:
                flush_line()
                raw = operands[-1]
                if isinstance(raw, (bytes, bytearray)):
                    current_line.append(_decode_text_bytes(bytes(raw), cmaps.get(current_font or "")))
            elif op == "Tj" and operands:
                raw = operands[-1]
                if isinstance(raw, (bytes, bytearray)):
                    current_line.append(_decode_text_bytes(bytes(raw), cmaps.get(current_font or "")))
            elif op == "TJ" and operands:
                arr = operands[-1]
                if isinstance(arr, list):
                    for item in arr:
                        if isinstance(item, (bytes, bytearray)):
                            current_line.append(
                                _decode_text_bytes(bytes(item), cmaps.get(current_font or ""))
                            )
                        elif isinstance(item, (int, float)) and item < -200:
                            current_line.append(" ")
            elif op in TEXT_OPERATORS_NEWLINE:
                flush_line()

            operands.clear()
            i += 1

    flush_line()
    return "\n".join([ln for ln in out_lines if ln])


def extract_pdf_text(pdf_path: str) -> list[str]:
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    objects = _parse_all_objects(pdf_bytes)
    catalog = _find_catalog(objects)
    if not catalog:
        return []

    pages_root = catalog.get("Pages")
    pages = _collect_pages(pages_root, objects)
    page_texts: list[str] = []
    for page, resources in pages:
        page_texts.append(extract_page_text(page, resources, objects))
    return page_texts


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Best-effort PDF text extractor (no external deps).")
    parser.add_argument("pdf", help="Path to input PDF.")
    parser.add_argument("--out", help="Write extracted text to this file (default: stdout).")
    parser.add_argument("--max-pages", type=int, default=0, help="Limit pages extracted (0 = all).")
    args = parser.parse_args(argv)

    pages = extract_pdf_text(args.pdf)
    if args.max_pages > 0:
        pages = pages[: args.max_pages]

    rendered = []
    for idx, text in enumerate(pages, start=1):
        rendered.append(f"===== Page {idx} =====\n{text}".strip())
    final = "\n\n".join(rendered).strip() + "\n"

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(final)
        return 0

    sys.stdout.write(final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

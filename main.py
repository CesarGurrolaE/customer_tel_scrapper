#!/usr/bin/env python3
"""
consulta_soms_por_telefono.py

Consulta un endpoint SOMS (GET) por teléfono (lada + telefono) a partir de un archivo
(txt o csv) y genera un CSV con resultados.

Características:
- Input flexible: TXT (1 por línea) o CSV (columna configurable)
- Parámetros por CLI: base-url, idUsuario, input, output, log, etc.
- Normalización de teléfono:
  * 11 dígitos: OK
  * 10 dígitos: antepone '0' => 11
  * <10 o >11: inválido
- Extracción configurable:
  * id_cliente: DatosSOMS.IdCliente
  * nombre: Nombre1 Nombre2 Ap-Pat Ap-Mat
  * ambos
- Log detallado de requests y errores.
"""

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DIGITS_RE = re.compile(r"\d+")

# ----------------------------
# Helpers: teléfono
# ----------------------------

def only_digits(s: str) -> str:
    if not s:
        return ""
    return "".join(DIGITS_RE.findall(s))

def normalize_phone_to_11(phone_digits: str) -> Optional[str]:
    """
    - 11 dígitos: OK
    - 10 dígitos: '0' + 10 => 11
    - otros: inválido
    """
    if len(phone_digits) == 11:
        return phone_digits
    if len(phone_digits) == 10:
        return "0" + phone_digits
    return None

def split_lada_telefono(phone_digits: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Recibe dígitos (sin espacios/guiones).
    Regla:
      - normaliza a 11
      - lada = primeros 3
      - telefono = últimos 8
    """
    normalized = normalize_phone_to_11(phone_digits)
    if not normalized:
        return (None, None, None)
    return (normalized[:3], normalized[3:], normalized)

# ----------------------------
# Helpers: URL
# ----------------------------

def build_url(base_url: str, id_usuario: str, lada: str, telefono: str) -> str:
    params = {
        "lada": lada,
        "telefono": telefono,
        "idUsuario": id_usuario,
        "nombre": "",
        "evento": "",
        "estado": "",
        "calle": "",
        "colonia": "",
        "cp": "",
    }
    return "{}?{}".format(base_url, urlencode(params))

# ----------------------------
# Helpers: extracción
# ----------------------------

def normalize_spaces(s: str) -> str:
    return " ".join((s or "").split()).strip()

def build_full_name(datos: Dict) -> str:
    """
    Nombre1 Nombre2 Ap-Pat Ap-Mat
    Ej: Ligia Caballero Flores
    """
    nombre1 = normalize_spaces(datos.get("Nombre1", ""))
    nombre2 = normalize_spaces(datos.get("Nombre2", ""))
    ap_pat = normalize_spaces(datos.get("Ap-Pat", ""))
    ap_mat = normalize_spaces(datos.get("Ap-Mat", ""))

    parts = [p for p in [nombre1, nombre2, ap_pat, ap_mat] if p]
    return " ".join(parts)

def extract_clientes(payload: Dict) -> List[Dict]:
    """
    Devuelve lista de dicts DatosSOMS.
    """
    bcr = payload.get("BusquedaClienteResponse") or {}
    clientes = bcr.get("Clientes") or []
    if not isinstance(clientes, list):
        return []
    out = []
    for c in clientes:
        if not isinstance(c, dict):
            continue
        datos = c.get("DatosSOMS") or {}
        if isinstance(datos, dict):
            out.append(datos)
    return out

def extract_idclientes(payload: Dict) -> List[str]:
    ids = []
    seen = set()
    for datos in extract_clientes(payload):
        cid = normalize_spaces(datos.get("IdCliente", ""))
        if cid and cid not in seen:
            ids.append(cid)
            seen.add(cid)
    return ids

def extract_names(payload: Dict) -> List[str]:
    names = []
    seen = set()
    for datos in extract_clientes(payload):
        n = build_full_name(datos)
        key = n.lower()
        if n and key not in seen:
            names.append(n)
            seen.add(key)
    return names

# ----------------------------
# Input readers
# ----------------------------

def detect_input_kind(path: Path, force_kind: Optional[str]) -> str:
    """
    Retorna 'txt' o 'csv'.
    - Si force_kind se pasa, respeta.
    - Si no, decide por extensión.
    """
    if force_kind:
        return force_kind.lower()
    ext = path.suffix.lower()
    if ext in (".csv",):
        return "csv"
    return "txt"

def read_inputs_from_txt(path: Path) -> List[str]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return [l.strip() for l in lines if l.strip()]

def read_inputs_from_csv(path: Path, phone_field: str) -> List[str]:
    out = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        if phone_field not in headers:
            raise ValueError("No existe la columna '{}' en CSV. Headers: {}".format(phone_field, headers))
        for row in reader:
            val = (row.get(phone_field) or "").strip()
            if val:
                out.append(val)
    return out

# ----------------------------
# CLI
# ----------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Consulta SOMS por teléfono desde TXT/CSV y exporta resultados a CSV."
    )
    ap.add_argument("--base-url", required=True, help="URL base del endpoint (QA o PROD)")
    ap.add_argument("--id-usuario", required=True, help="idUsuario para el query param")
    ap.add_argument("--input", required=True, help="Archivo input (TXT 1 por línea o CSV)")
    ap.add_argument("--input-kind", choices=["txt", "csv"], default=None,
                    help="Forzar tipo de input (si no, se infiere por extensión)")
    ap.add_argument("--phone-field", default="valor_medio_contacto",
                    help="Nombre de columna si input es CSV (default: valor_medio_contacto)")

    ap.add_argument("--extract", choices=["id_cliente", "nombre", "ambos"], default="id_cliente",
                    help="Qué extraer del JSON (default: id_cliente)")

    ap.add_argument("--output", default="output.csv", help="Archivo CSV de salida (default: output.csv)")
    ap.add_argument("--log", default="log_requests.csv", help="Archivo de log (default: log_requests.csv)")

    ap.add_argument("--sleep", type=int, default=20, help="Sleep entre requests (seg) (default: 20)")
    ap.add_argument("--timeout", type=int, default=30, help="Timeout por request (seg) (default: 30)")

    ap.add_argument("--verify-tls", action="store_true",
                    help="Habilita verificación TLS (por defecto está deshabilitada)")
    ap.add_argument("--max", type=int, default=0,
                    help="Procesar solo N teléfonos (0 = todos). Útil para pruebas")

    return ap.parse_args()

# ----------------------------
# Main
# ----------------------------

def main() -> None:
    args = parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit("No existe input: {}".format(input_path))

    kind = detect_input_kind(input_path, args.input_kind)

    if kind == "csv":
        inputs = read_inputs_from_csv(input_path, args.phone_field)
    else:
        inputs = read_inputs_from_txt(input_path)

    if not inputs:
        raise SystemExit("No se encontraron teléfonos en el input.")

    if args.max and args.max > 0:
        inputs = inputs[: args.max]

    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    # Define headers de output según extract
    out_fields = ["telefono_entrada", "telefono_11", "lada", "telefono_8"]
    if args.extract in ("id_cliente", "ambos"):
        out_fields.append("id_cliente")
    if args.extract in ("nombre", "ambos"):
        out_fields.append("nombre_completo")

    log_fields = [
        "telefono_raw",
        "telefono_digits",
        "telefono_11",
        "lada",
        "telefono_8",
        "request_url",
        "http_status",
        "ok",
        "extraidos",
        "error",
    ]

    with open(args.output, "w", newline="", encoding="utf-8") as f_out, open(
        args.log, "w", newline="", encoding="utf-8"
    ) as f_log:
        out_writer = csv.DictWriter(f_out, fieldnames=out_fields)
        out_writer.writeheader()

        log_writer = csv.DictWriter(f_log, fieldnames=log_fields)
        log_writer.writeheader()

        for idx, raw_phone in enumerate(inputs, start=1):
            phone_digits = only_digits(raw_phone)
            lada, tel8, phone11 = split_lada_telefono(phone_digits)

            log_row = {
                "telefono_raw": raw_phone,
                "telefono_digits": phone_digits,
                "telefono_11": phone11 or "",
                "lada": lada or "",
                "telefono_8": tel8 or "",
                "request_url": "",
                "http_status": "",
                "ok": "0",
                "extraidos": "",
                "error": "",
            }

            if not lada or not tel8 or not phone11:
                if len(phone_digits) < 10:
                    log_row["error"] = "SKIPPED: telefono invalido (<10 digitos)"
                elif len(phone_digits) in (10, 11):
                    log_row["error"] = "SKIPPED: telefono invalido (no se pudo normalizar)"
                else:
                    log_row["error"] = "SKIPPED: telefono invalido (>11 digitos)"
                log_writer.writerow(log_row)
                continue

            url = build_url(args.base_url, args.id_usuario, lada, tel8)
            log_row["request_url"] = url
            print("[{}] {} -> GET {}".format(idx, phone11, url), flush=True)

            try:
                resp = session.get(url, timeout=args.timeout, verify=args.verify_tls)
                log_row["http_status"] = str(resp.status_code)

                if not resp.ok:
                    log_row["error"] = (resp.text or "")[:200]
                    log_writer.writerow(log_row)
                    time.sleep(args.sleep)
                    continue

                try:
                    payload = resp.json()
                except json.JSONDecodeError:
                    log_row["error"] = "Respuesta no es JSON"
                    log_writer.writerow(log_row)
                    time.sleep(args.sleep)
                    continue

                extracted_items: List[Dict[str, str]] = []

                ids: List[str] = []
                names: List[str] = []
                if args.extract in ("id_cliente", "ambos"):
                    ids = extract_idclientes(payload)
                if args.extract in ("nombre", "ambos"):
                    names = extract_names(payload)

                # Escribe filas:
                # - Si ambos: cruzamos por índice si tienen misma longitud; si no, emitimos combinaciones seguras.
                # - Si solo uno: una fila por item.
                if args.extract == "id_cliente":
                    for cid in ids:
                        extracted_items.append({"id_cliente": cid})
                elif args.extract == "nombre":
                    for n in names:
                        extracted_items.append({"nombre_completo": n})
                else:  # ambos
                    # caso común: misma cantidad (1 y 1)
                    if len(ids) == len(names) and len(ids) > 0:
                        for cid, n in zip(ids, names):
                            extracted_items.append({"id_cliente": cid, "nombre_completo": n})
                    else:
                        # fallback: todas las combinaciones (si hay mismatch), o lo que exista
                        if ids and names:
                            for cid in ids:
                                for n in names:
                                    extracted_items.append({"id_cliente": cid, "nombre_completo": n})
                        elif ids:
                            for cid in ids:
                                extracted_items.append({"id_cliente": cid, "nombre_completo": ""})
                        elif names:
                            for n in names:
                                extracted_items.append({"id_cliente": "", "nombre_completo": n})

                if not extracted_items:
                    # No hubo clientes en respuesta, aún así loguea OK y sin extraídos
                    log_row["ok"] = "1"
                    log_row["extraidos"] = ""
                    log_writer.writerow(log_row)
                    time.sleep(args.sleep)
                    continue

                for item in extracted_items:
                    out_row = {
                        "telefono_entrada": raw_phone,
                        "telefono_11": phone11,
                        "lada": lada,
                        "telefono_8": tel8,
                    }
                    out_row.update(item)
                    out_writer.writerow(out_row)

                log_row["ok"] = "1"
                # resumen corto en log
                if args.extract == "id_cliente":
                    log_row["extraidos"] = "|".join(ids)
                elif args.extract == "nombre":
                    log_row["extraidos"] = "|".join(names)
                else:
                    # ambos
                    pairs = []
                    for it in extracted_items[:10]:
                        pairs.append("{}::{}".format(it.get("id_cliente", ""), it.get("nombre_completo", "")))
                    log_row["extraidos"] = "|".join(pairs)
                log_writer.writerow(log_row)

            except requests.RequestException as e:
                log_row["error"] = "{}: {}".format(e.__class__.__name__, e)
                log_writer.writerow(log_row)

            time.sleep(args.sleep)

            if idx % 25 == 0:
                print("Procesados {} teléfonos...".format(idx))

    print("Listo: {} (output) y {} (log)".format(args.output, args.log))


if __name__ == "__main__":
    main()

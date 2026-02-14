# consulta-soms-por-telefono

CLI en Python para consultar un endpoint de **SOMS** por **teléfono** (LADA + teléfono) a partir de un archivo **TXT/CSV** y exportar un **CSV** con resultados (por ejemplo `id_cliente`, `nombre_completo` o ambos), sin tener que editar el script.

---

## ¿Qué problema resuelve?

Cuando tienes un insumo con teléfonos (por ejemplo, de remisiones o registros) y necesitas **consultar SOMS** para recuperar datos como:

- `IdCliente`
- Nombre completo (`Nombre1 Nombre2 Ap-Pat Ap-Mat`)

Este script automatiza:

1. Leer teléfonos desde **TXT** (1 por línea) o **CSV** (columna configurable).
2. Normalizar el teléfono:
   - **11 dígitos**: OK
   - **10 dígitos**: agrega `0` al inicio para formar 11
   - **<10 / >11**: inválido (se registra en log y se omite)
3. Partir en:
   - `lada` = **primeros 3**
   - `telefono` = **últimos 8**
4. Hacer `GET` al endpoint (QA o PROD) con `idUsuario`.
5. Parsear JSON de respuesta y extraer `id_cliente`, `nombre_completo` o ambos.
6. Generar:
   - **output CSV** con los matches
   - **log CSV** con status, URL, errores, etc.

---

## Requisitos

- Python **3.9+**
- Paquetes:
  - `requests`

Instalación rápida:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip requests
```

> Nota macOS: si ves warning de `urllib3` por LibreSSL, no rompe el script; es solo aviso del runtime.

---

## Archivos de entrada

### Opción A: TXT
Un teléfono por línea (puede traer espacios/guiones, el script se queda con dígitos):

```
9811111111
(614) 02-22222
05511223344
```

### Opción B: CSV
Necesitas indicar la columna con `--phone-field` (por default: `valor_medio_contacto`).

Ejemplo:

```csv
valor_medio_contacto
9811111111
05511223344
```

---

## Uso

### 1) TXT (QA), extraer `id_cliente` (default)
```bash
python3 consulta_soms_por_telefono.py \
  --base-url "https://QA_HOST/sellerapp-middleware/api/v1/broker/soms/customersV2" \
  --id-usuario "" \
  --input telefonos.txt \
  --extract id_cliente \
  --output telefono_idcliente.csv \
  --log log_requests.csv \
  --sleep 5 \
  --timeout 30
```

### 2) CSV (PROD), columna `valor_medio_contacto`
```bash
python3 consulta_soms_por_telefono.py \
  --base-url "https://PROD_HOST/sellerapp-middleware/api/v1/broker/soms/customersV2" \
  --id-usuario "" \
  --input INSUMO_CONSULTA.csv \
  --input-kind csv \
  --phone-field valor_medio_contacto \
  --extract id_cliente \
  --output out_prod.csv
```

### 3) Probar rápido con 10 teléfonos
```bash
python3 consulta_soms_por_telefono.py \
  --base-url "https://QA_HOST/..." \
  --id-usuario "" \
  --input telefonos.txt \
  --max 10 \
  --sleep 1
```

### 4) Extraer `nombre` o `ambos`
```bash
# nombre
python3 consulta_soms_por_telefono.py ... --extract nombre --output telefono_nombre.csv

# ambos
python3 consulta_soms_por_telefono.py ... --extract ambos --output telefono_id_nombre.csv
```

---

## Parámetros (CLI)

| Parámetro | Requerido | Default | Descripción |
|---|---:|---|---|
| `--base-url` | ✅ | — | URL base del endpoint (QA o PROD) |
| `--id-usuario` | ✅ | — | `idUsuario` para el query param |
| `--input` | ✅ | — | Archivo input (TXT o CSV) |
| `--input-kind` | ❌ | inferido | Forzar `txt` o `csv` |
| `--phone-field` | ❌ | `valor_medio_contacto` | Columna de teléfono si input es CSV |
| `--extract` | ❌ | `id_cliente` | `id_cliente` / `nombre` / `ambos` |
| `--output` | ❌ | `output.csv` | Archivo CSV de salida |
| `--log` | ❌ | `log_requests.csv` | Log detallado de requests |
| `--sleep` | ❌ | `20` | Pausa entre requests (seg) |
| `--timeout` | ❌ | `30` | Timeout por request (seg) |
| `--verify-tls` | ❌ | off | Habilita verificación TLS (por defecto deshabilitada) |
| `--max` | ❌ | `0` | Procesa solo N teléfonos (0 = todos) |

---

## Salida

### Output CSV (`--output`)
Incluye siempre:
- `telefono_entrada`
- `telefono_11`
- `lada`
- `telefono_8`

Y además según `--extract`:
- `id_cliente`
- `nombre_completo`
- o ambos

Ejemplo (`--extract id_cliente`):

```csv
telefono_entrada,telefono_11,lada,telefono_8,id_cliente
9831268365,09831268365,098,31268365,0069657104
```

### Log CSV (`--log`)
Registra por teléfono:
- `http_status`, `ok`, `request_url`, y `error` si falló
- `extraidos` con un resumen de lo que encontró

---

## JSON esperado (referencia)

El script busca datos en:

```json
{
  "BusquedaClienteResponse": {
    "Clientes": [
      {
        "DatosSOMS": {
          "IdCliente": "1198957334",
          "Nombre1": "Ligia",
          "Nombre2": "",
          "Ap-Pat": "Flores",
          "Ap-Mat": "Flores"
        }
      }
    ]
  }
}
```

---

## Buenas prácticas

- Empieza con `--max 10` y `--sleep 1` para validar.
- En PROD usa `--sleep` más alto para no saturar.
- Si el endpoint tiene rate limit, sube `--sleep` y/o baja paralelismo (este script es secuencial).

---

## Limitaciones conocidas

- Si el endpoint devuelve múltiples clientes para el mismo teléfono:
  - `--extract id_cliente` genera una fila por `IdCliente`
  - `--extract nombre` genera una fila por nombre
  - `--extract ambos` intenta emparejar por índice; si no coincide, genera combinaciones seguras.

---

## Soporte / Extensiones sugeridas

Ideas para siguiente iteración:
- `--retries` con backoff
- cache local para evitar reconsultas del mismo teléfono
- `--headers` / `--auth` si el endpoint requiere auth adicional

"""
AEGIS — Validación segura de archivos subidos.

Implementa validación de magic bytes en puro Python (sin dependencias externas):
- Verifica que los primeros 4 bytes del contenido sean %PDF (0x25 0x50 0x44 0x46)
- Sanitiza el nombre del archivo eliminando cualquier carácter que permita
  Path Traversal, inyección de null bytes o colisiones de nombres en disco.

El filename sanitizado se usa exclusivamente para el path en disco (ya prefijado
con UUID4), nunca se expone directamente al usuario en la respuesta.
"""

import re
import unicodedata
from fastapi import HTTPException, status


# Magic bytes de PDF: b'%PDF'
_PDF_MAGIC = b"%PDF"


def validate_pdf_magic_bytes(content: bytes) -> None:
    """
    Verifica que el contenido sea un PDF real comprobando los magic bytes.

    Lee únicamente los primeros 4 bytes del buffer, por lo que es O(1) en
    tiempo y no requiere cargar el archivo completo en memoria.

    Raises:
        HTTPException 400 si el contenido no comienza con %PDF.
    """
    if not content[:4] == _PDF_MAGIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "El archivo no es un PDF válido. "
                "Se detectó un tipo de archivo diferente al declarado."
            ),
        )


def sanitize_filename(filename: str) -> str:
    """
    Devuelve una versión segura del nombre de archivo.

    Transformaciones aplicadas (en orden):
    1. Normalización Unicode NFKD → elimina caracteres compuestos raros.
    2. Encode ASCII ignorando caracteres no-ASCII → elimina Unicode especial.
    3. Elimina null bytes y caracteres de control.
    4. Reemplaza separadores de path (/ y \\) con guiones.
    5. Elimina el prefijo de disco Windows (e.g. 'C:').
    6. Sustituye cualquier carácter que no sea alnum, punto, guion o guion bajo.
    7. Colapsa guiones/espacios múltiples consecutivos.
    8. Trunca a 200 caracteres para evitar filenames excesivamente largos.
    9. Si el resultado queda vacío, devuelve 'file.pdf' como fallback.

    Args:
        filename: Nombre original del archivo tal como lo envía el cliente.

    Returns:
        Nombre de archivo sanitizado, seguro para uso en paths del servidor.
    """
    # 1. Normalización Unicode
    normalized = unicodedata.normalize("NFKD", filename)

    # 2. Solo ASCII
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")

    # 3. Eliminar null bytes y control chars
    ascii_name = re.sub(r"[\x00-\x1f\x7f]", "", ascii_name)

    # 4. Separadores de path → guiones
    ascii_name = ascii_name.replace("/", "-").replace("\\", "-")

    # 5. Eliminar prefijo de disco Windows (C:, D:, etc.)
    ascii_name = re.sub(r"^[a-zA-Z]:", "", ascii_name)

    # 5b. Colapsar secuencias de puntos (path traversal: ../../)
    ascii_name = re.sub(r"\.{2,}", "", ascii_name)

    # 6. Solo caracteres seguros: alnum, punto, guion, guion_bajo, espacio
    ascii_name = re.sub(r"[^\w.\- ]", "_", ascii_name)

    # 7. Colapsar múltiples guiones/espacios
    ascii_name = re.sub(r"[-_ ]{2,}", "_", ascii_name).strip("_. -")

    # 8. Truncar
    ascii_name = ascii_name[:200]

    # 9. Fallback
    return ascii_name if ascii_name else "file.pdf"

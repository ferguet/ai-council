"""
Extraccion de texto de los archivos que se adjuntan al Chat Grupal.

Idea: no guardamos el binario en ningun sitio permanente (Render free no
tiene disco persistente y no hay almacenamiento de objetos configurado). En
su lugar, en el momento de la subida extraemos el texto util del archivo y
ese texto pasa a formar parte del mensaje de la conversacion, tal cual un
mensaje mas: así entra en el contexto que cada IA ve al responder, sin tener
que tocar el motor de orquestacion ni el formato de prompt.

Formatos con extraccion de texto real: PDF, Word (.docx), Excel/CSV, texto
plano y codigo fuente, y ZIP (se listan los miembros y se extrae texto de
los que sean legibles). Imagenes, video, audio, PowerPoint y formatos
binarios no soportados se degradan con elegancia: se comparten igualmente
(nombre + tamano visibles para el usuario y las IA) pero sin contenido
extraido, dejandolo claro en el propio texto.
"""
from __future__ import annotations

import csv
import io
import zipfile

_MAX_CHARS = 6000            # tope de texto extraido por archivo (evita prompts gigantes)
_MAX_ZIP_MEMBERS = 25         # cuantos ficheros de un zip se intentan leer como maximo
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".css", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php",
    ".sh", ".sql", ".ini", ".cfg", ".toml", ".env",
}


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) > _MAX_CHARS:
        return text[:_MAX_CHARS] + "\n[...truncado, el archivo sigue...]"
    return text


def _extract_plain_text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
        if sum(len(p) for p in parts) > _MAX_CHARS:
            break
    return "\n".join(parts)


def _extract_docx(content: bytes) -> str:
    import docx
    doc = docx.Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_xlsx(content: bytes) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    lines: list[str] = []
    for sheet in wb.worksheets:
        lines.append(f"--- hoja: {sheet.title} ---")
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i > 200:
                lines.append("[...mas filas omitidas...]")
                break
            lines.append(", ".join("" if v is None else str(v) for v in row))
        if sum(len(l) for l in lines) > _MAX_CHARS:
            break
    return "\n".join(lines)


def _extract_csv(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    lines = [", ".join(row) for row in reader]
    return "\n".join(lines)


def _extract_zip(content: bytes) -> str:
    lines: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = zf.namelist()
        lines.append(f"Archivo comprimido con {len(names)} elementos:")
        lines.extend(f"- {n}" for n in names[:80])
        if len(names) > 80:
            lines.append(f"[...y {len(names) - 80} mas...]")
        read = 0
        for name in names:
            if read >= _MAX_ZIP_MEMBERS or name.endswith("/"):
                continue
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in _TEXT_EXTENSIONS:
                continue
            try:
                data = zf.read(name)
            except Exception:
                continue
            read += 1
            snippet = data.decode("utf-8", errors="replace")[:800]
            lines.append(f"\n--- contenido de {name} (primeras lineas) ---\n{snippet}")
            if sum(len(l) for l in lines) > _MAX_CHARS:
                break
    return "\n".join(lines)


def kind_for(filename: str) -> str:
    """Categoria simple del archivo, para elegir icono en el frontend."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in {".pdf"}:
        return "pdf"
    if ext in {".doc", ".docx"}:
        return "word"
    if ext in {".xls", ".xlsx", ".csv", ".tsv"}:
        return "excel"
    if ext in {".ppt", ".pptx"}:
        return "powerpoint"
    if ext in {".zip", ".rar", ".7z", ".tar", ".gz"}:
        return "zip"
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}:
        return "image"
    if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        return "video"
    if ext in {".mp3", ".wav", ".ogg", ".m4a", ".flac"}:
        return "audio"
    code_ext = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".hpp",
        ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".sql",
    }
    if ext in code_ext:
        return "code"
    if ext in _TEXT_EXTENSIONS:
        return "text"
    return "file"


def extract_text(filename: str, content: bytes) -> str | None:
    """Devuelve el texto extraido del archivo, o None si el tipo no se
    puede leer como texto (imagen, video, audio, formatos binarios raros).
    Nunca lanza: cualquier fallo de parseo se trata como "no extraible"."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    try:
        if ext == ".pdf":
            return _truncate(_extract_pdf(content))
        if ext == ".docx":
            return _truncate(_extract_docx(content))
        if ext in {".xlsx"}:
            return _truncate(_extract_xlsx(content))
        if ext in {".csv", ".tsv"}:
            return _truncate(_extract_csv(content))
        if ext == ".zip":
            return _truncate(_extract_zip(content))
        if ext in _TEXT_EXTENSIONS:
            return _truncate(_extract_plain_text(content))
    except Exception as exc:  # el archivo puede venir corrupto o con un formato inesperado
        return f"(no se pudo leer el contenido: {exc})"
    return None  # tipo no soportado para extraccion (imagen, video, audio, .doc, .ppt, ...)

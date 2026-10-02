"""BibTeX Cleaner: local bibliography workspace. Run with ``py app.py``."""

import argparse
import csv
import os
import re
import threading
import time
import unicodedata
import webbrowser
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

import bibtexparser
import requests
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter, SortingStrategy
from flask import Flask, jsonify, request

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

CROSSREF_API = "https://api.crossref.org/works"
ARXIV_SEARCH_API = "https://export.arxiv.org/api/query"
HEADERS = {"User-Agent": "BibTeXCleaner/2.0"}
ATOM = {"a": "http://www.w3.org/2005/Atom"}
_arxiv_lock = threading.Lock()
_arxiv_last_request = 0.0
BOOL_OPTIONS = {
    "clean_whitespace", "remove_empty", "remove_duplicates", "enclose_braces",
    "sort_fields", "generate_keys", "find_dois", "lowercase_fields",
}
DEFAULTS = {"clean_whitespace": True, "remove_empty": True, "sort_fields": True}


def normalize_text(text):
    text = unicodedata.normalize("NFKD", re.sub(r"[{}]", "", text))
    return " ".join(text.encode("ascii", "ignore").decode().lower().split())


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def extract_arxiv_id(text):
    text = re.sub(r"[{}]", "", text or "")
    match = re.search(
        r"(?<![\w.])(\d{4}\.\d{4,5}|[a-z][a-z.\-]+/\d{7})(?:v\d+)?(?!\w)",
        re.sub(r"10\.48550/arxiv\.", "", text, flags=re.I), re.I,
    )
    return match.group(1) if match else None


def is_arxiv_entry(entry):
    for field in ("eprint", "arxivid", "url", "journal", "note", "howpublished"):
        value = entry.get(field, "")
        # Bare identifiers are meaningful only in identifier fields.
        if field not in ("eprint", "arxivid") and "arxiv" not in value.lower():
            continue
        identifier = extract_arxiv_id(value)
        if identifier:
            return identifier, field
    return None, None


def arxiv_id_to_doi(identifier):
    return f"10.48550/arXiv.{identifier}"


def first_surname(author):
    first = re.split(r"\s+and\s+", author, maxsplit=1)[0].strip()
    return first.split(",")[0] if "," in first else (first.split()[-1] if first else "")


def search_arxiv_by_title(title, author=""):
    global _arxiv_last_request
    if not title.strip():
        return None, "Sin título para buscar en arXiv."
    query = 'ti:"' + re.sub(r'[{}"]', "", title) + '"'
    if author:
        query += ' AND au:"' + re.sub(r'[{}"]', "", first_surname(author)) + '"'
    try:
        # arXiv asks clients to leave at least three seconds between calls.
        with _arxiv_lock:
            time.sleep(max(0, 3 - (time.monotonic() - _arxiv_last_request)))
            _arxiv_last_request = time.monotonic()
            response = requests.get(ARXIV_SEARCH_API, params={
                "search_query": query, "max_results": 3, "sortBy": "relevance",
            }, headers=HEADERS, timeout=8)
        response.raise_for_status()
        for item in ET.fromstring(response.content).findall("a:entry", ATOM):
            candidate = item.findtext("a:title", default="", namespaces=ATOM)
            if similarity(normalize_text(title), normalize_text(candidate)) > 0.90:
                identifier = extract_arxiv_id(item.findtext("a:id", default="", namespaces=ATOM))
                if identifier:
                    return identifier, "Coincidencia de título en arXiv."
        return None, "Sin coincidencia suficiente en arXiv."
    except (requests.RequestException, ET.ParseError, ValueError):
        return None, "No se pudo consultar arXiv; inténtalo más tarde."


def find_doi_crossref_inner(title, author=""):
    if not title.strip():
        return None, "Sin título para buscar en Crossref."
    params = {"query.title": normalize_text(title), "rows": 5, "select": "DOI,title,author"}
    if author:
        params["query.author"] = normalize_text(first_surname(author))
    try:
        response = requests.get(CROSSREF_API, params=params, headers=HEADERS, timeout=8)
        response.raise_for_status()
        for item in response.json().get("message", {}).get("items", []):
            titles = item.get("title") or []
            if not titles or not item.get("DOI"):
                continue
            score = similarity(normalize_text(title), normalize_text(titles[0]))
            families = [normalize_text(a.get("family", "")) for a in item.get("author", [])]
            surname = normalize_text(first_surname(author))
            if score > 0.90 and (not surname or surname in families):
                return item["DOI"], f"Coincidencia de título {score:.0%} en Crossref."
        return None, "Sin coincidencia suficiente en Crossref."
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        return None, "No se pudo consultar Crossref; inténtalo más tarde."


def find_doi_for_entry(entry):
    identifier, field = is_arxiv_entry(entry)
    if identifier:
        return arxiv_id_to_doi(identifier), "arxiv_field", f"Identificador arXiv en {field}."
    title, author = entry.get("title", ""), entry.get("author", "")
    messages = []
    if entry.get("ENTRYTYPE") in ("misc", "unpublished", "techreport"):
        identifier, message = search_arxiv_by_title(title, author)
        if identifier:
            return arxiv_id_to_doi(identifier), "arxiv_search", message
        messages.append(message)
    doi, message = find_doi_crossref_inner(title, author)
    messages.append(message)
    return doi, "crossref" if doi else None, " ".join(messages)


def clean_field_value(value):
    return re.sub(r"\s+", " ", value).strip()


def canonical_doi(value):
    value = re.sub(r"[{}]", "", value).strip().lower()
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)


def generate_citation_key(entry):
    surname = re.sub(r"[^a-zA-Z]", "", normalize_text(first_surname(entry.get("author", ""))))
    year = re.search(r"\d{4}", entry.get("year", ""))
    words = re.findall(r"[a-z]+", normalize_text(entry.get("title", "")))
    stop = {"a", "an", "the", "of", "in", "on", "for", "and", "or", "to", "with", "from", "by", "at"}
    word = next((word for word in words if word not in stop), "untitled")
    return f"{surname.capitalize() or 'Unknown'}{year.group() if year else 'XXXX'}{word.capitalize()}"


def validate_options(options):
    if not isinstance(options, dict):
        raise ValueError("Las opciones deben ser un objeto.")
    result = {**DEFAULTS, **options}
    for key in BOOL_OPTIONS:
        if key in result and not isinstance(result[key], bool):
            raise ValueError(f"La opción {key} debe ser verdadera o falsa.")
    for key in ("remove_fields", "add_fields", "sort_by"):
        if key in result and not isinstance(result[key], str):
            raise ValueError(f"La opción {key} debe ser texto.")
    if result.get("sort_by", "none") not in ("none", "ID", "year", "author", "title"):
        raise ValueError("El criterio de orden no es válido.")
    return result


def parse_added_fields(raw):
    fields = {}
    for item in next(csv.reader([raw], skipinitialspace=True)):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError("Usa campo=valor para añadir campos.")
        key, value = (part.strip() for part in item.split("=", 1))
        key = key.lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", key) or key in ("id", "entrytype"):
            raise ValueError(f"No se puede añadir el campo «{key}».")
        # Verify values before inserting raw BibTeX delimiters into the export.
        depth = 0
        for char in re.sub(r"\\.", "", value):
            depth += (char == "{") - (char == "}")
            if depth < 0:
                break
        if depth:
            raise ValueError("Las llaves de los campos añadidos deben estar equilibradas.")
        fields[key] = value
    return fields


def process_bibtex(bib_content, options):
    try:
        options = validate_options(options)
        added = parse_added_fields(options.get("add_fields", ""))
        parser = BibTexParser(common_strings=True)
        parser.ignore_nonstandard_types = False
        bib_db = bibtexparser.loads(bib_content, parser=parser)
        if not bib_db.entries:
            raise ValueError("No se encontraron referencias válidas. Revisa el formato BibTeX.")
        # bibtexparser can silently interpret malformed entries as comments.
        if any(re.search(r"^\s*@(?!(?:comment)\b)\w+\s*[{(]", comment, re.I | re.M)
               for comment in bib_db.comments):
            raise ValueError("Hay una entrada incompleta o mal formada. Revisa las llaves y comas.")
    except Exception as error:
        return None, f"No se pudo leer el BibTeX: {error}", [], []

    original_count = len(bib_db.entries)
    log, doi_results, entries = [], [], []
    removed = {field.strip().lower() for field in options.get("remove_fields", "").split(",")}
    seen_keys, seen_dois, aliases = {}, {}, {}
    duplicates = 0
    for original in bib_db.entries:
        entry = original.copy()
        key = entry["ID"]
        # Deduplicate before changing keys or deleting DOI metadata.
        doi = canonical_doi(entry.get("doi", ""))
        match = seen_keys.get(key) or (seen_dois.get(doi) if doi else None)
        if options.get("remove_duplicates") and match:
            duplicates += 1
            aliases[key] = match
            log.append(f"[{key}] Duplicado eliminado; se conserva {match}.")
            continue
        seen_keys[key] = key
        if doi:
            seen_dois[doi] = key
        if options.get("find_dois") and not doi and "doi" not in removed:
            found, method, message = find_doi_for_entry(entry)
            if found:
                entry["doi"] = found
            doi_results.append({"key": key, "doi": found, "method": method,
                                "status": "found" if found else "not_found", "msg": message})
            log.append(f"[{key}] {message}" + (f" DOI: {found}" if found else ""))
        for field in list(entry):
            if field in ("ID", "ENTRYTYPE"):
                continue
            if field.lower() in removed or (options.get("remove_empty") and not entry[field].strip()):
                del entry[field]
                log.append(f"[{key}] Campo eliminado: {field}.")
            elif options.get("clean_whitespace"):
                cleaned = clean_field_value(entry[field])
                if cleaned != entry[field]:
                    entry[field] = cleaned
                    log.append(f"[{key}] Espacios normalizados: {field}.")
        for field, value in added.items():
            if field not in entry:
                entry[field] = value
                log.append(f"[{key}] Campo añadido: {field}.")
        if not any(field not in ("ID", "ENTRYTYPE") for field in entry):
            return None, f"La referencia «{key}» quedaría sin campos. Conserva al menos uno.", [], []
        entries.append(entry)

    key_map, used = {}, set()
    if options.get("generate_keys"):
        for entry in entries:
            old = entry["ID"]
            base = generate_citation_key(entry)
            new, suffix = base, 2
            while new in used:
                new, suffix = f"{base}{suffix}", suffix + 1
            used.add(new)
            key_map.setdefault(old, new)
            entry["ID"] = new
            if new != old:
                log.append(f"[{old}] Nueva clave: {new}.")
    if options.get("generate_keys") or aliases:
        for entry in entries:
            if "crossref" in entry:
                old = entry["crossref"]
                target = aliases.get(old, old)
                entry["crossref"] = key_map.get(target, target)

    if options.get("enclose_braces"):
        for entry in entries:
            # Extra braces protect title casing; bracing authors/DOIs changes their meaning.
            value = entry.get("title", "")
            if value and not (value.startswith("{") and value.endswith("}")):
                entry["title"] = "{" + value + "}"
    sort_by = options.get("sort_by", "none")
    if sort_by != "none":
        entries.sort(key=lambda entry: normalize_text(entry.get(sort_by, "")))
        log.append(f"Referencias ordenadas por {sort_by}.")
    bib_db.entries = entries
    writer = BibTexWriter()
    writer.indent = "  "
    writer.add_trailing_comma = True
    writer.order_entries_by = None
    writer.display_order = [] if options.get("sort_fields") else [
        "author", "title", "journal", "booktitle", "year", "volume", "number", "pages", "doi", "url",
    ]
    writer.display_order_sorting = SortingStrategy.ALPHABETICAL_ASC
    output = bibtexparser.dumps(bib_db, writer)
    stats = {"total_entries": original_count, "output_entries": len(entries),
             "duplicates_removed": duplicates,
             "dois_found": sum(result["status"] == "found" for result in doi_results),
             "dois_searched": len(doi_results)}
    return output, stats, log, doi_results


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/health")
def health():
    return jsonify(status="ok", version="2.0.0")


@app.post("/clean")
def clean():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Envía un objeto JSON válido."), 400
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return jsonify(error="Pega o importa contenido BibTeX antes de continuar."), 400
    result, stats, log, doi_results = process_bibtex(content, data.get("options", {}))
    if result is None:
        return jsonify(error=stats), 400
    return jsonify(output=result, stats=stats, log=log, doi_results=doi_results)


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="El archivo supera el límite de 5 MB."), 413


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5050")))
    cli.add_argument("--open", action="store_true", help="Abrir la aplicación en el navegador")
    args = cli.parse_args()
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    app.run(host="127.0.0.1", port=args.port, debug=False)

# BibTeX Cleaner

Un espacio de trabajo local para limpiar, organizar y completar bibliografías BibTeX. Interfaz clara en español, entrada y resultado en paralelo, opciones por pestañas y exportación a `.bib`.

## Ejecutar en Windows

Requiere Python 3.10 o posterior. Desde la carpeta del proyecto:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py --open
```

Abre [http://127.0.0.1:5050](http://127.0.0.1:5050). Si las dependencias ya están instaladas en tu Python, basta con `py app.py --open`. Detén la aplicación con Ctrl+C en su terminal. Para usar otro puerto: `py app.py --port 5051 --open`.

En macOS o Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py --open
```

El servidor escucha solo en tu equipo y se inicia sin depuración. Está pensado para uso local, no para exponerlo directamente a Internet.

## Uso

1. Importa o arrastra un archivo `.bib` al editor Original; también puedes pegar texto o cargar el ejemplo.
2. Ajusta las pestañas **Limpieza**, **Campos** y **DOI**.
3. Pulsa **Limpiar bibliografía** o Ctrl/⌘+Enter.
4. Revisa el resultado y la actividad. Copia o descarga el archivo limpio.

En escritorio, la distribución se ajusta a la ventana y los textos largos se desplazan dentro de sus editores. En pantallas estrechas, los paneles se apilan; el desplazamiento permite mantener controles y texto legibles. Las opciones pueden desplazarse en ventanas especialmente bajas o con zoom alto.

### Reglas de limpieza

- Espacios, campos vacíos y campos en orden alfabético activados por defecto.
- Duplicados opcionales: conserva la primera referencia que tenga la misma clave o DOI existente. Los prefijos `doi:`, `https://doi.org/` y las diferencias de mayúsculas no impiden reconocer un DOI duplicado. No fusiona los campos de referencias duplicadas.
- La opción **Mantener orden original** respeta la secuencia de entrada. Los demás criterios son ascendentes.
- Sin orden A–Z, los campos siguen un orden bibliográfico: autor, título, revista/congreso, año y resto de metadatos.
- Las claves generadas tienen sufijos numéricos cuando coinciden. Las referencias internas `crossref` se actualizan. Si activas esta opción, también debes actualizar las citas de tus documentos LaTeX; la app solo modifica el `.bib`.
- **Proteger mayúsculas** añade llaves adicionales únicamente al título. Los autores, DOI y referencias internas mantienen su significado.
- Los nombres de campo se normalizan a minúsculas por el lector BibTeX. Los valores y comandos LaTeX se conservan, salvo las transformaciones elegidas. Las macros `@string` se resuelven al leer.
- Añadir campos no sobrescribe campos presentes. Usa `language=spanish, note=preprint`. Si el valor contiene comas, encierra el par completo: `"note=uno, dos"`.
- El límite de importación es 4 MB; el servidor acepta hasta 5 MB de JSON.
- Si cambias el original o la configuración, vuelve a limpiar antes de exportar. Un fallo no permite descargar resultados de una ejecución anterior.

### DOI y conexión

La limpieza básica funciona sin Internet y no guarda las bibliografías en disco. Las fuentes y estilos de la interfaz son locales.

La búsqueda de DOI está desactivada inicialmente. Al activarla, los identificadores arXiv existentes se convierten sin consulta externa. Para el resto, se envían el título y el autor a arXiv o Crossref. El servicio arXiv deja al menos tres segundos entre solicitudes y cada consulta tiene un tiempo de espera limitado; bibliografías grandes pueden tardar varios minutos. Los fallos externos quedan registrados y no impiden exportar el resto de la limpieza. Revisa siempre las coincidencias: una similitud de título no garantiza identidad bibliográfica.

Referencias de implementación: [API de arXiv](https://info.arxiv.org/help/api/user-manual.html), [BibTeXParser](https://bibtexparser.readthedocs.io/en/v1.4.0/bibtexparser.html).

## Comprobar funcionamiento

```powershell
py -m unittest discover -s tests -v
```

Las pruebas verifican errores de entrada, conservación de datos, orden, duplicados, claves, referencias internas y respuestas simuladas de los proveedores DOI, sin depender de Internet. GitHub Actions ejecuta la misma suite con Python 3.10 y 3.14.

## Estructura

```text
app.py                 Servidor Flask y limpieza BibTeX
static/index.html      Interfaz
static/styles.css      Tema claro y distribución adaptable
static/app.js          Importación, opciones y exportación
tests/test_app.py      Pruebas de regresión
requirements.txt      Dependencias reproducibles
```

## Subir a GitHub

Este proyecto no incluye credenciales ni un destino remoto. Crea un repositorio vacío en tu cuenta y, desde esta carpeta, conecta la URL que te proporcione GitHub:

```sh
git remote add origin URL_DE_TU_REPOSITORIO
git push -u origin main
```

Si recibiste la carpeta como ZIP sin historial, ejecuta antes `git init -b main`, `git add .` y `git commit -m "Release BibTeX Cleaner 2.0"`. El entorno virtual, copias locales, registros y archivos temporales están excluidos mediante `.gitignore`.

# Guía de uso del generador CSV de Last.fm

Esta guía explica cómo crear un catálogo de artistas y géneros para un sistema de recomendaciones. El programa usa únicamente la biblioteca estándar de Python y la API de Last.fm.

## 1. Preparar el entorno

1. Instala Python 3.9 o posterior.
2. Solicita una [clave de API de Last.fm](https://www.last.fm/api/account/create).
3. Abre una terminal en la carpeta del proyecto y configura la clave:

```bash
export LASTFM_API_KEY="tu_clave_de_api"
```

La clave se lee desde la variable de entorno; no se guarda en los CSV. No hace falta instalar paquetes con `pip`.

## 2. Generar un catálogo básico

```bash
python3 generate_csv.py --genres "rock,pop,jazz" --per-genre 20 --output data
```

El programa escribe cuatro archivos en `data/`. Si omites `--genres`, usa `rock,pop,jazz,hip-hop,electronic`. Los nombres son **etiquetas de Last.fm**, no categorías de un catálogo cerrado: puedes elegir otras, como `metal`, `folk` o `ambient`.

## 3. Ajustar la selección

### Excluir artistas muy populares

```bash
python3 generate_csv.py --genres "rock,jazz" --per-genre 20 \
  --max-listeners 500000 --max-playcount 10000000 \
  --scan-per-genre 300 --output data
```

Se excluye un artista si supera cualquiera de los límites indicados. Los límites incluyen el valor exacto: con `--max-listeners 500000`, un artista con 500 000 oyentes puede entrar. Si Last.fm no proporciona una métrica necesaria, se omite.

Al activar un límite de popularidad, la búsqueda empieza por defecto en la **página 5** de artistas de cada género. Así se evitan las primeras 200 posiciones. Puedes cambiar el punto de partida con `--start-page 10` o volver al principio con `--start-page 1`. Las páginas están ordenadas por uso de la etiqueta, no por número de oyentes, por lo que el filtro de popularidad se comprueba después con la ficha de cada candidato.

### Limitar por país de escucha

```bash
python3 generate_csv.py --genres "rock,jazz" --country Spain \
  --country-scan 1000 --per-genre 20 --output data
```

`--country` acepta un nombre de país como `Spain` o `France`. El programa cruza los artistas de los géneros elegidos con el ranking de artistas escuchados en ese país. `--country-scan` indica cuántos artistas de ese ranking se consideran; su valor por defecto es 500.

**País de escucha no significa país de origen.** Un artista de cualquier país puede aparecer en el ranking de España. Además, los límites `--max-listeners` y `--max-playcount` usan estadísticas globales de Last.fm, no estadísticas limitadas al país.

### Combinar filtros

```bash
python3 generate_csv.py --genres "rock,indie" --country Spain \
  --country-scan 1000 --per-genre 20 --scan-per-genre 300 \
  --max-listeners 500000 --start-page 5 \
  --similar-limit 10 --output data
```

Cuantos más filtros combines, menos artistas pueden coincidir. Si obtienes pocos resultados, aumenta `--scan-per-genre` o `--country-scan`, o ajusta `--start-page` y los límites de popularidad. Aumentar el recorrido también incrementa las peticiones a la API.

## 4. Opciones del comando

| Opción | Función | Valor por defecto |
| --- | --- | --- |
| `--genres` | Etiquetas separadas por comas | `rock,pop,jazz,hip-hop,electronic` |
| `--country` | País donde se escucha al artista | Sin filtro |
| `--country-scan` | Artistas del ranking del país usados para el cruce | `500` |
| `--per-genre` | Objetivo de artistas aceptados por género | `20` |
| `--max-listeners` | Máximo de oyentes globales | Sin límite |
| `--max-playcount` | Máximo de reproducciones globales | Sin límite |
| `--scan-per-genre` | Candidatos revisados por género | Igual a `--per-genre` sin filtros; diez veces ese valor con filtros |
| `--start-page` | Primera página de artistas por género | `1` sin límite de popularidad; `5` con él |
| `--similar-limit` | Artistas similares solicitados por artista; `0` desactiva esta consulta | `10` |
| `--delay` | Pausa mínima entre peticiones, en segundos | `0.25` |
| `--output` | Carpeta de salida | `data` |

Para ver la ayuda integrada:

```bash
python3 generate_csv.py --help
```

## 5. Archivos generados

Todos los CSV se escriben en UTF-8 con BOM, para facilitar su apertura en Excel. Si ya existen, se reemplazan después de completar la descarga.

| Archivo | Columnas | Uso |
| --- | --- | --- |
| `artists.csv` | `artist_id,name,mbid,url,listeners,playcount` | Catálogo de artistas y popularidad global |
| `genres.csv` | `genre_id,name` | Etiquetas elegidas como géneros |
| `artist_genres.csv` | `artist_id,genre_id,tag_count,source` | Relación artista–género; `tag_count` puede estar vacío |
| `artist_similar.csv` | `artist_id,similar_artist_id,match_score` | Similitudes dirigidas entre artistas incluidos en el catálogo |

`artist_id` usa el MBID cuando existe y, si falta, el nombre normalizado. `match_score` procede de Last.fm y está entre 0 y 1. Una relación de similitud solo se guarda si **ambos** artistas están en `artists.csv`; por eso `artist_similar.csv` puede contener solo la cabecera en catálogos pequeños.

## 6. Problemas habituales

- **«Falta LASTFM_API_KEY»**: configura la variable en la misma terminal donde ejecutas el programa.
- **Pocos artistas o CSV vacíos**: reduce `--start-page`, aumenta `--scan-per-genre` o `--country-scan`, o relaja los límites de popularidad. Algunos géneros y países tienen pocas coincidencias en los rankings consultados.
- **Límite de peticiones**: el script reintenta los errores temporales. Si se repiten, aumenta la pausa, por ejemplo `--delay 1`.
- **Artistas sin el país de origen esperado**: `--country` representa el país de escucha, no el origen del artista.

Consulta las [condiciones de uso de la API de Last.fm](https://www.last.fm/api/tos) antes de ampliar el volumen de descarga o utilizar los datos con fines académicos o comerciales.

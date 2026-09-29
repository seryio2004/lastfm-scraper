# Generador de CSV con Last.fm

Genera un catálogo inicial para un recomendador basado en artistas y géneros. En Last.fm los géneros se representan mediante **etiquetas** creadas por usuarios; por eso eliges qué etiquetas tratar como géneros.

[Guía de uso detallada](GUIA_USO.md).

## Uso

Necesitas Python 3.9 o posterior y una [clave de API de Last.fm](https://www.last.fm/api/account/create). Las consultas usadas son públicas y no necesitan autenticación de usuario.

```bash
export LASTFM_API_KEY="tu_clave"
python3 generate_csv.py --genres "rock,pop,jazz,hip-hop,electronic" --per-genre 20 --output data
```

La clave se lee del entorno; no se escribe en los CSV. El script espera al menos 0,25 segundos entre peticiones y reintenta errores temporales o límites de peticiones. Puedes ajustar la pausa con `--delay 1`. Para omitir las consultas de artistas similares usa `--similar-limit 0`.

## Excluir artistas muy populares

Puedes fijar un máximo de oyentes, de reproducciones o ambos. Los valores se obtienen de `artist.getInfo`; el límite es inclusivo. Si falta una métrica necesaria para el filtro, el artista se omite.

```bash
python3 generate_csv.py --genres "rock,jazz" --per-genre 20 \
  --max-listeners 500000 --max-playcount 10000000 \
  --start-page 5 --scan-per-genre 300 --output data
```

Con algún filtro de popularidad, el programa empieza **por defecto en la página 5** de `tag.getTopArtists`, evitando consultar las fichas de los primeros 200 artistas de cada género. Sin filtros empieza en la página 1. Puedes cambiarlo con `--start-page`: un valor mayor se aleja más de los primeros puestos; `--start-page 1` permite incluirlos si lo necesitas. Last.fm ordena esa lista por número de etiquetas, no por oyentes, así que saltar páginas es una aproximación. Los límites de oyentes y reproducciones siguen comprobándose con `artist.getInfo` para cada candidato examinado.

`--per-genre` indica cuántos artistas válidos se buscan por género. Para encontrarlos, el programa revisa hasta `--scan-per-genre` candidatos a partir de la página inicial. Si activas un filtro de popularidad o de país y no indicas ese valor, revisa hasta diez veces `--per-genre`; sin filtros, revisa solo `--per-genre`. Un límite muy estricto, o una página inicial demasiado avanzada, puede producir menos artistas de los solicitados: ajusta `--start-page`, `--scan-per-genre` o el umbral. Buscar más candidatos aumenta las peticiones a la API.

## Limitar por país de escucha

`--country` cruza los candidatos de cada género con el ranking de artistas escuchados en un país. El nombre del país debe seguir el formato aceptado por Last.fm, por ejemplo `Spain` o `France`.

```bash
python3 generate_csv.py --genres "rock,jazz" --country Spain \
  --country-scan 1000 --per-genre 20 --output data
```

`--country-scan` controla cuántos artistas del ranking geográfico se consideran; por defecto son 500. El cruce se hace antes de llamar a `artist.getInfo`, por lo que se evitan consultas individuales de artistas que no aparecen en ese ranking. Un valor bajo puede dejar pocos resultados para géneros específicos; aumentarlo añade peticiones paginadas al ranking. Puedes combinarlo con `--max-listeners`, `--max-playcount` y `--start-page`.

**Este criterio indica popularidad entre oyentes de un país, no el país de origen del artista.** Last.fm ofrece `geo.getTopArtists` para el primer caso, pero no un filtro documentado por origen en los métodos usados aquí.

## Archivos

| Archivo | Contenido |
| --- | --- |
| `artists.csv` | `artist_id`, nombre, MBID, URL, oyentes y reproducciones |
| `genres.csv` | Identificador y nombre de cada etiqueta seleccionada |
| `artist_genres.csv` | Relación artista–género, recuento de etiquetas cuando Last.fm lo proporciona y origen de la relación |
| `artist_similar.csv` | Similitudes dirigidas entre artistas del catálogo, con puntuación de 0 a 1 |

Los identificadores de artista usan el MBID cuando existe y, si falta, el nombre normalizado. Las relaciones de similitud solo incluyen artistas que figuran en `artists.csv`. `tag_count` queda vacío cuando la relación procede de `tag.getTopArtists` pero no aparece en `artist.getTopTags`. Los CSV se guardan en UTF-8 con BOM para facilitar su apertura en Excel.

El script sobrescribe los cuatro archivos del directorio de salida tras completar la descarga. Si falla una consulta, no reemplaza los CSV existentes. El conjunto de artistas depende de los géneros elegidos y del orden de popularidad de Last.fm, así que no representa un catálogo musical completo.

Consulta la [documentación de la API](https://www.last.fm/api) y sus [condiciones de uso](https://www.last.fm/api/tos) antes de ampliar el volumen de datos o usarlo con fines académicos o comerciales.

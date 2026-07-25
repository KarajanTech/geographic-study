# Technical Architecture

## 1. Principios

- empezar con una arquitectura modular y sencilla;
- usar raster 2.5D antes de introducir 3D completo;
- separar cálculo geoespacial, optimización y presentación;
- cachear operaciones costosas;
- mantener trazabilidad de CRS, resolución y parámetros;
- evitar microservicios prematuros.

## 2. Arquitectura inicial

```text
Next.js frontend
      |
      | HTTP / WebSocket
      v
FastAPI API
      |
      +---- Project service
      +---- Dataset service
      +---- Candidate service
      +---- Viewshed service
      +---- Optimization service
      +---- Export service
      |
      +---- PostgreSQL / PostGIS
      +---- Object storage
      +---- Worker queue
```

Para desarrollo local, el object storage puede ser un volumen Docker. Posteriormente puede sustituirse por S3 compatible.

## 3. Estructura recomendada del repositorio

```text
sentinel-planner/
├── apps/
│   ├── api/
│   │   ├── app/
│   │   │   ├── api/
│   │   │   ├── core/
│   │   │   ├── db/
│   │   │   ├── geo/
│   │   │   ├── optimization/
│   │   │   ├── services/
│   │   │   └── workers/
│   │   └── tests/
│   └── web/
│       ├── app/
│       ├── components/
│       ├── lib/
│       └── types/
├── packages/
│   └── shared-schemas/
├── data/
│   ├── raw/
│   ├── processed/
│   └── outputs/
├── docs/
├── docker-compose.yml
├── Makefile
└── README.md
```

## 4. Entidades principales

### Project

```text
id
name
description
area_geometry
analysis_crs
created_at
updated_at
```

### Dataset

```text
id
project_id
type
source_uri
crs
resolution_x
resolution_y
bounds
checksum
metadata
```

Tipos:

- DEM
- DSM
- vegetation
- roads
- exclusions
- priorities
- existing_sites

### AnalysisRun

```text
id
project_id
status
algorithm_version
parameters
random_seed
started_at
finished_at
metrics
error
```

### CandidateSite

```text
id
analysis_run_id
geometry
elevation
slope
access_score
site_cost
is_allowed
filter_reasons
```

### Viewshed

```text
candidate_site_id
observer_height
target_height
max_distance
raster_uri
bitset_uri
visible_cell_count
weighted_visible_score
```

### OptimizationSolution

```text
id
analysis_run_id
solver
selected_candidate_ids
coverage_ratio
weighted_coverage_ratio
redundancy_metrics
total_cost
objective_value
runtime_seconds
```

## 5. Pipeline geoespacial

### 5.1 Validación

- comprobar que el GeoTIFF tiene CRS;
- comprobar nodata;
- comprobar resolución;
- comprobar intersección con el área de estudio;
- registrar checksum;
- rechazar datos geográficamente incompatibles.

### 5.2 CRS

Nunca realizar cálculos de distancia directamente en EPSG:4326.

El sistema debe:

1. detectar el centroide del área;
2. escoger un CRS proyectado apropiado;
3. reproyectar todas las capas;
4. guardar el CRS de análisis.

Para España, UTM suele ser una opción adecuada según la zona.

### 5.3 Recorte

Todos los rasters deben recortarse al área de estudio más un buffer igual al alcance máximo.

### 5.4 Generación de derivados

A partir del DEM:

- slope raster;
- aspect raster;
- local prominence;
- hillshade para visualización.

### 5.5 DSM inicial

Si no existe DSM:

```text
surface = DEM + vegetation_height
```

La vegetación puede introducirse como raster o como reglas por clase de suelo.

## 6. Generación de candidatos

Versión inicial:

1. crear una malla regular;
2. muestrear elevación y pendiente;
3. descartar nodata;
4. descartar pendientes excesivas;
5. descartar zonas excluidas;
6. aplicar separación mínima;
7. ordenar por elevación relativa o prominencia.

Estrategias posteriores:

- máximos locales;
- líneas de cresta;
- torres existentes;
- proximidad a carreteras;
- clustering de candidatos equivalentes.

## 7. Motor de viewshed

Interfaz conceptual:

```python
class ViewshedEngine:
    def compute(
        self,
        surface_raster: Path,
        observer_x: float,
        observer_y: float,
        observer_height_m: float,
        target_height_m: float,
        max_distance_m: float,
    ) -> ViewshedResult:
        ...
```

Implementación inicial recomendada:

- GDAL viewshed;
- resultado binario;
- máscara al área de estudio;
- conversión opcional a bitset;
- caché por hash de parámetros.

Clave de caché:

```text
hash(
  surface_checksum,
  observer_coordinates,
  observer_height,
  target_height,
  max_distance,
  curvature_setting
)
```

## 8. Representación eficiente

No guardar la matriz completa como JSON.

Opciones:

- GeoTIFF comprimido;
- NumPy packed bits;
- Roaring Bitmap;
- arrays booleanos comprimidos.

Para el MVP:

```python
packed = numpy.packbits(visibility_mask.flatten())
```

La cobertura combinada puede calcularse con operaciones binarias.

## 9. Optimización

### 9.1 Greedy

Primera implementación obligatoria:

```text
seleccionar el candidato con mayor ganancia marginal ponderada
repetir hasta alcanzar el límite o el objetivo
```

Debe soportar:

- área uniforme;
- pesos por celda;
- costes diferentes;
- candidatos bloqueados;
- candidatos obligatorios.

### 9.2 CP-SAT

Añadir después del greedy.

El greedy proporciona:

- solución inicial;
- upper bound práctico;
- warm start conceptual;
- respuesta rápida para interfaz.

CP-SAT se utiliza para:

- minimizar unidades;
- cumplir cobertura mínima;
- imponer redundancia;
- incorporar presupuestos;
- resolver restricciones discretas.

### 9.3 Multiobjetivo

No implementar hasta que las métricas básicas sean estables.

## 10. API propuesta

### Proyectos

```text
POST   /projects
GET    /projects/{id}
PATCH  /projects/{id}
```

### Datasets

```text
POST   /projects/{id}/datasets
GET    /projects/{id}/datasets
POST   /datasets/{id}/validate
```

### Análisis

```text
POST   /projects/{id}/analysis-runs
GET    /analysis-runs/{id}
GET    /analysis-runs/{id}/status
GET    /analysis-runs/{id}/candidates
GET    /analysis-runs/{id}/solutions
```

### Exportación

```text
GET /solutions/{id}/export.geojson
GET /solutions/{id}/export.csv
GET /solutions/{id}/coverage.tif
```

## 11. Frontend

Pantallas del MVP:

### Project setup

- nombre;
- polígono;
- carga de DEM;
- parámetros generales.

### Analysis configuration

- resolución;
- altura del poste;
- altura objetivo;
- alcance;
- pendiente máxima;
- separación de candidatos;
- objetivo de cobertura;
- número máximo de Sentinel.

### Results

- mapa base;
- DEM sombreado;
- candidatos;
- Sentinel elegidos;
- cobertura;
- puntos ciegos;
- métricas;
- tabla de Sentinel;
- exportaciones.

## 12. Tests críticos

- reproyección conserva geometría aproximadamente;
- recorte produce límites correctos;
- una superficie plana genera cobertura circular limitada por alcance;
- una barrera elevada crea sombra;
- el greedy nunca disminuye cobertura acumulada;
- una celda cubierta por dos candidatos tiene redundancia dos;
- candidatos excluidos nunca aparecen en la solución;
- la misma semilla genera el mismo resultado;
- las exportaciones conservan CRS y coordenadas.

## 13. Seguridad y robustez

- limitar tamaño de archivos;
- validar extensiones y MIME;
- aislar rutas de archivos;
- no ejecutar comandos construidos directamente desde input;
- usar directorios temporales por ejecución;
- limpiar temporales;
- registrar fallos de GDAL;
- definir timeouts para workers.

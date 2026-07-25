# Sentinel Planner

Sistema geoespacial para optimizar automáticamente la ubicación de torres o postes Sentinel destinados a vigilancia temprana de incendios forestales.

## Objetivo

Dado un territorio real, el sistema debe determinar:

- cuántos Sentinel son necesarios;
- dónde deben colocarse;
- qué superficie queda cubierta;
- qué zonas permanecen ocultas;
- qué nivel de redundancia existe;
- cuánto cuesta cada configuración;
- qué mejora marginal aporta cada Sentinel adicional.

El objetivo principal es maximizar la cobertura de vigilancia y el riesgo cubierto utilizando el menor número posible de Sentinel.

## Principio de funcionamiento

El sistema combina:

1. datos geográficos reales;
2. modelos digitales de elevación;
3. vegetación y obstáculos;
4. cálculo de línea de visión;
5. generación de ubicaciones candidatas;
6. optimización combinatoria;
7. visualización 2D y 3D.

Pipeline principal:

```text
Área geográfica
    ↓
DEM / DSM / vegetación / carreteras
    ↓
Generación y filtrado de candidatos
    ↓
Viewshed de cada candidato
    ↓
Matriz candidato-celda
    ↓
Optimización de cobertura
    ↓
Mapa, métricas y exportación
```

## Alcance del MVP

El primer MVP debe permitir:

- cargar o dibujar un polígono de estudio;
- cargar un DEM GeoTIFF;
- generar posiciones candidatas;
- calcular la visibilidad desde cada candidato;
- seleccionar automáticamente las mejores posiciones;
- configurar altura del poste, alcance y cobertura objetivo;
- mostrar Sentinel seleccionados, cobertura y puntos ciegos;
- exportar resultados a GeoJSON y CSV.

El MVP no debe intentar inicialmente:

- simular árboles individuales;
- hacer fotorealismo 3D;
- predecir físicamente la propagación del humo;
- incorporar meteorología en tiempo real;
- usar aprendizaje automático sin necesidad;
- resolver todo el planeta en una única ejecución.

## Stack recomendado

### Backend geoespacial

- Python 3.12
- FastAPI
- GDAL
- Rasterio
- GeoPandas
- Shapely
- PyProj
- NumPy
- SciPy
- OR-Tools
- PostgreSQL
- PostGIS

### Frontend

- Next.js
- TypeScript
- MapLibre GL JS
- deck.gl, opcional para capas grandes
- CesiumJS, solamente en una fase posterior

### Desarrollo local

- Docker Compose
- pytest
- Ruff
- mypy
- pre-commit
- GitHub Actions

## Puesta en marcha

Requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js >= 20, Docker y Make.
No hace falta instalar GDAL: `rasterio` incluye sus propios binarios.

```bash
cp .env.example .env     # ajustar al menos POSTGRES_PASSWORD
make install             # dependencias de Python y de Node
make dev                 # base de datos + API + frontend con Docker Compose
make db-upgrade          # aplicar migraciones
```

- Frontend: <http://localhost:3000>
- Documentación de la API: <http://localhost:8000/api/v1/docs>
- Estado del servicio: <http://localhost:8000/api/v1/health>

Comandos de trabajo:

```bash
make check        # formato, lint, tipos y tests, lo mismo que ejecuta CI
make test         # pytest
make schemas      # regenerar OpenAPI y los tipos TypeScript compartidos
make sample-dem   # generar un DEM sintético en data/raw
make help         # todos los comandos
```

El detalle está en [`docs/development.md`](docs/development.md).

## Estado del proyecto

**Fase actual: Phase 1 — ingesta geoespacial (completada).**

- **Phase 0:** monorepo, API, PostGIS con migraciones, frontend tipado, contrato
  OpenAPI compartido, tests, lint, tipos y CI.
- **Phase 1:** creación de proyectos con área de estudio en GeoJSON, selección
  automática de CRS métrico proyectado (ETRS89/UTM en Europa, WGS84/UTM fuera),
  carga de DEM GeoTIFF con validación, reproyección, recorte con buffer de
  alcance, hillshade, previsualización y visualización en el frontend.

Todavía no hay generación de candidatos, viewshed ni optimización: llegan en las
fases 2 a 4 de [`ROADMAP.md`](ROADMAP.md).

Prueba rápida del pipeline completo:

```bash
make up && make db-upgrade
make demo-project        # crea un proyecto e ingiere un DEM sintético
```

Después, abrir <http://localhost:3000/projects>.

## Documentación del repositorio

- `PRODUCT_SPEC.md`: comportamiento funcional y criterios de producto.
- `ARCHITECTURE.md`: arquitectura técnica, modelos de datos y APIs.
- `ROADMAP.md`: fases de desarrollo y criterios de aceptación.
- `AGENT_INSTRUCTIONS.md`: instrucciones para Codex, Claude Code u otro agente.
- `docs/development.md`: guía de desarrollo, comandos y convenciones.
- `docs/data-sources.md`: de dónde obtener un DEM real.
- `docs/adr/`: decisiones de arquitectura registradas.

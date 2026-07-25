# Development Roadmap

## Estrategia general

Construir verticalmente. Cada fase debe terminar con una demostración funcional, no solo con infraestructura.

No avanzar a 3D, riesgo, costes complejos o inteligencia artificial hasta que el pipeline básico de terreno, viewshed y optimización esté validado.

---

# Phase 0: Repository and engineering foundation

## Objetivo

Crear un repositorio reproducible y preparado para iterar.

## Tareas

- crear monorepo;
- configurar Python, FastAPI y Next.js;
- configurar Docker Compose;
- añadir PostgreSQL y PostGIS;
- añadir Ruff, mypy, pytest y pre-commit;
- añadir lint y tests a GitHub Actions;
- definir gestión de configuración;
- crear estructura de documentación;
- incluir un pequeño DEM de prueba o script para obtenerlo;
- crear Makefile con comandos básicos.

## Entregables

- `make dev`;
- `make test`;
- API health endpoint;
- frontend cargando;
- base de datos accesible;
- CI en verde.

## Criterios de aceptación

- una persona nueva puede levantar el proyecto siguiendo el README;
- tests y lint se ejecutan localmente y en CI;
- no existen secretos dentro del repositorio.

---

# Phase 1: Geospatial ingestion

## Objetivo

Cargar, validar, recortar y reproyectar un DEM real.

## Tareas

- endpoint para crear proyecto;
- carga de polígono GeoJSON;
- carga de GeoTIFF;
- lectura de metadata;
- validación de CRS y nodata;
- selección de CRS proyectado;
- reproyección;
- recorte con buffer;
- creación de hillshade;
- almacenamiento de metadata y archivos derivados.

## Entregables

- proyecto con área de estudio;
- DEM procesado;
- endpoint de metadata;
- visualización del raster en frontend.

## Criterios de aceptación

- el sistema rechaza GeoTIFF sin georreferenciación;
- el sistema guarda resolución, bounds, CRS y checksum;
- el área de estudio se visualiza correctamente;
- los cálculos utilizan unidades métricas.

---

# Phase 2: Candidate generation

## Objetivo

Generar y filtrar posiciones potenciales.

## Tareas

- generar malla regular;
- calcular elevación;
- calcular pendiente;
- aplicar pendiente máxima;
- aplicar máscara de exclusión;
- aplicar separación mínima;
- calcular elevación relativa local;
- guardar candidatos en PostGIS;
- mostrarlos en el mapa;
- permitir candidatos obligatorios y bloqueados.

## Entregables

- capa de candidatos;
- tabla con atributos;
- configuración reproducible.

## Criterios de aceptación

- ningún candidato está fuera del área;
- ningún candidato viola restricciones duras;
- el número de candidatos cambia de manera coherente al modificar la separación;
- el mismo input produce los mismos candidatos.

---

# Phase 3: Viewshed engine

## Objetivo

Calcular la visibilidad real desde cada candidato.

## Tareas

- integrar GDAL viewshed;
- soportar altura del observador;
- soportar altura objetivo;
- soportar alcance máximo;
- recortar resultados;
- guardar GeoTIFF de cobertura;
- guardar representación compacta;
- añadir caché;
- ejecutar en worker;
- mostrar viewshed individual al seleccionar un candidato.

## Entregables

- cálculo de viewshed por candidato;
- endpoint de progreso;
- visualización de cobertura individual.

## Criterios de aceptación

- terreno plano produce comportamiento esperado;
- una montaña bloquea correctamente la visibilidad;
- cambiar la altura objetivo modifica la cobertura;
- repetir un cálculo idéntico utiliza la caché;
- un fallo en un candidato no destruye toda la ejecución.

---

# Phase 4: Greedy optimizer

## Objetivo

Seleccionar automáticamente posiciones que maximizan cobertura.

## Tareas

- construir matriz candidato-celda;
- implementar greedy maximum coverage;
- soportar número máximo de Sentinel;
- soportar cobertura objetivo;
- calcular ganancia marginal;
- calcular superficie visible;
- calcular superficie oculta;
- devolver orden de selección;
- guardar métricas por iteración.

## Entregables

- solución automática;
- tabla ordenada de Sentinel;
- curva unidades-cobertura;
- mapa de cobertura acumulada.

## Criterios de aceptación

- la cobertura acumulada nunca disminuye;
- ningún candidato se selecciona dos veces;
- el algoritmo se detiene correctamente;
- los resultados son reproducibles;
- se puede resolver una zona de demostración con cientos de candidatos.

---

# Phase 5: Usable MVP interface

## Objetivo

Convertir el motor técnico en una herramienta utilizable.

## Tareas

- flujo de creación de proyecto;
- dibujo de polígono;
- carga de DEM;
- formulario de parámetros;
- lanzamiento de análisis;
- progreso;
- mapa de resultados;
- métricas principales;
- tabla de posiciones;
- exportación GeoJSON;
- exportación CSV;
- gestión básica de errores.

## Entregables

Una demo completa:

```text
crear proyecto
→ cargar zona
→ configurar análisis
→ ejecutar
→ visualizar solución
→ exportar
```

## Criterios de aceptación

- el usuario completa todo el flujo sin terminal;
- los errores son comprensibles;
- la configuración queda asociada a la solución;
- las posiciones exportadas coinciden con el mapa.

---

# Phase 6: Risk-weighted coverage

## Objetivo

Optimizar riesgo cubierto, no solo superficie.

## Tareas

- permitir raster de pesos;
- normalizar pesos;
- incorporar zonas prioritarias;
- calcular cobertura ponderada;
- mostrar cobertura física y ponderada;
- permitir editar pesos;
- añadir presets de riesgo.

## Criterios de aceptación

- aumentar el peso de una zona puede cambiar la solución;
- cobertura física y ponderada se reportan separadamente;
- los pesos utilizados quedan guardados.

---

# Phase 7: Installation constraints and cost

## Objetivo

Producir soluciones desplegables, no solo geométricas.

## Tareas

- importar carreteras;
- calcular distancia al acceso;
- coste base por Sentinel;
- coste variable por emplazamiento;
- exclusiones por propiedad o protección;
- conectividad;
- exposición solar;
- optimización por presupuesto;
- curva coste-cobertura.

## Criterios de aceptación

- un candidato inaccesible puede penalizarse o excluirse;
- el sistema puede maximizar cobertura bajo presupuesto;
- el coste total es explicable por componentes.

---

# Phase 8: Redundancy and exact optimization

## Objetivo

Soportar redes robustas y restricciones complejas.

## Tareas

- calcular multiplicidad de cobertura;
- objetivos de cobertura doble;
- zonas con redundancia obligatoria;
- integrar OR-Tools CP-SAT;
- comparar greedy y solución exacta o mejorada;
- límites de tiempo del solver;
- fallback automático a greedy.

## Criterios de aceptación

- las zonas críticas cumplen la redundancia indicada;
- el solver respeta presupuesto y número máximo;
- el sistema devuelve una solución aunque CP-SAT alcance timeout.

---

# Phase 9: Vegetation and DSM

## Objetivo

Reducir el optimismo del modelo de terreno desnudo.

## Tareas

- aceptar DSM;
- aceptar canopy height model;
- reglas de altura por uso de suelo;
- combinar terreno y vegetación;
- comparar escenarios DEM y DSM;
- registrar incertidumbre de datos.

## Criterios de aceptación

- un bosque alto puede reducir visibilidad;
- el usuario conoce qué modelo de superficie se utilizó;
- los resultados permiten comparar con y sin vegetación.

---

# Phase 10: 3D and commercial reporting

## Objetivo

Mejorar presentación, análisis y utilidad comercial.

## Tareas

- visualización 3D con Cesium;
- perfil de elevación;
- cono o frustum aproximado del sensor;
- informe PDF;
- escenarios comparables;
- branding Karajan;
- resumen ejecutivo;
- estimación de unidades y coste.

## Criterios de aceptación

- el informe reproduce métricas del sistema;
- las coordenadas del informe coinciden con los datos exportados;
- el 3D es una capa visual y no altera el cálculo científico.

---

# Backlog posterior

- degradación probabilística por distancia;
- visibilidad atmosférica;
- orientación solar;
- meteorología;
- múltiples tipos de Sentinel;
- PTZ scheduling;
- triangulación;
- localización de humo desde varias cámaras;
- simulación de fallo de nodos;
- optimización de comunicaciones;
- integración con Cortex;
- planificación de mantenimiento;
- análisis nacional por lotes;
- procesamiento distribuido;
- active learning basado en validación de campo.

---

# Orden recomendado para agentes

El agente debe ejecutar una fase cada vez.

Para cada fase:

1. leer todos los documentos;
2. proponer un plan técnico breve;
3. implementar una vertical funcional;
4. añadir tests;
5. ejecutar lint, types y tests;
6. documentar decisiones;
7. no comenzar la siguiente fase hasta cumplir los criterios de aceptación.

La primera meta comercial es completar Phase 0 a Phase 5.

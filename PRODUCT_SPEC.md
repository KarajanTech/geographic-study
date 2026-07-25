# Product Specification

## 1. Problema

La planificación manual de una red de cámaras forestales suele basarse en círculos de alcance, intuición local o posiciones históricas. Esto no considera correctamente:

- montañas y crestas;
- valles y zonas ocultas;
- vegetación;
- altura del poste;
- altura a la que aparece el humo;
- accesibilidad;
- coste de instalación;
- solapamiento entre cámaras;
- criticidad desigual del territorio.

Sentinel Planner debe convertir esta planificación en un proceso geoespacial reproducible, cuantitativo y optimizable.

## 2. Usuarios

Usuarios principales:

- equipo técnico de Karajan;
- administraciones forestales;
- cuerpos de bomberos;
- operadores de parques naturales;
- ingenierías medioambientales;
- distribuidores e instaladores de Sentinel.

## 3. Casos de uso

### Caso A: número mínimo de Sentinel

El usuario define una cobertura mínima, por ejemplo 95 %. El sistema devuelve el menor número de posiciones que alcanza ese objetivo.

### Caso B: presupuesto fijo

El usuario define un máximo de unidades o un presupuesto. El sistema maximiza la cobertura posible.

### Caso C: posiciones preexistentes

El usuario introduce torres, edificios o postes disponibles. El sistema elige cuáles utilizar.

### Caso D: cobertura redundante

El usuario exige que ciertas zonas sean visibles desde dos o más Sentinel.

### Caso E: comparación de escenarios

El usuario compara diferentes alturas de poste, alcances ópticos o presupuestos.

## 4. Entradas

Entradas mínimas:

- polígono del área de estudio;
- DEM GeoTIFF;
- altura del observador;
- altura del objetivo;
- alcance máximo;
- separación mínima entre candidatos;
- porcentaje de cobertura objetivo;
- número máximo de Sentinel.

Entradas opcionales:

- DSM o modelo de vegetación;
- edificios;
- carreteras y pistas;
- torres existentes;
- parcelas excluidas;
- zonas prioritarias;
- mapa de riesgo;
- coste por ubicación;
- conectividad celular;
- exposición solar;
- pendiente máxima;
- redundancia mínima.

## 5. Salidas

Resultados mínimos:

- posiciones Sentinel seleccionadas;
- cobertura total;
- superficie no cubierta;
- mapa de cobertura;
- número de Sentinel;
- cobertura marginal por Sentinel;
- lista de coordenadas;
- exportación GeoJSON;
- exportación CSV.

Resultados posteriores:

- cobertura ponderada por riesgo;
- cobertura doble y triple;
- coste total;
- frontera coste-cobertura;
- informe PDF;
- visualización 3D;
- perfiles de elevación.

## 6. Definición de cobertura

El sistema debe distinguir:

### Cobertura geométrica del terreno

Una celda es visible si existe línea de visión directa desde el Sentinel hasta la altura objetivo de la celda.

### Cobertura de humo

Una celda puede considerarse cubierta si una columna de humo a una altura configurable es visible, aunque el suelo no lo sea.

Alturas recomendadas:

- 0 m;
- 5 m;
- 10 m;
- 20 m;
- 50 m.

### Cobertura operativa

En fases posteriores, la cobertura puede incluir una función de degradación por distancia.

Ejemplo:

```text
0-3 km:    calidad 1.00
3-5 km:    calidad 0.95
5-8 km:    calidad 0.80
8-12 km:   calidad 0.55
12-15 km:  calidad 0.30
```

Estos valores deben ser configurables y no codificarse como verdades físicas.

## 7. Funciones objetivo

### Minimizar unidades

```text
minimizar número de Sentinel
sujeto a cobertura >= objetivo
```

### Maximizar cobertura

```text
maximizar cobertura ponderada
sujeto a número de Sentinel <= límite
```

### Minimizar coste

```text
minimizar coste de instalación
sujeto a cobertura y redundancia mínimas
```

### Multiobjetivo

```text
score =
  cobertura ponderada
  - penalización por coste
  - penalización por puntos ciegos
  + recompensa por redundancia
```

Los pesos deben ser configurables.

## 8. Requisitos funcionales del MVP

### RF-01

El usuario puede cargar un DEM GeoTIFF.

### RF-02

El usuario puede cargar o dibujar un polígono de estudio.

### RF-03

El backend reproyecta los datos a un CRS métrico apropiado.

### RF-04

El sistema genera candidatos sobre una malla configurable.

### RF-05

El sistema filtra candidatos por pendiente, máscara y separación.

### RF-06

El sistema calcula un viewshed para cada candidato.

### RF-07

El sistema guarda cada viewshed de forma compacta.

### RF-08

El sistema ejecuta un algoritmo greedy de maximum coverage.

### RF-09

El sistema permite fijar número máximo de Sentinel o cobertura objetivo.

### RF-10

El frontend muestra candidatos, seleccionados, cobertura y zonas ocultas.

### RF-11

El sistema exporta las posiciones seleccionadas.

### RF-12

Cada ejecución guarda configuración, métricas y versión del algoritmo.

## 9. Requisitos no funcionales

- resultados reproducibles;
- unidades explícitas;
- coordenadas y CRS explícitos;
- logs estructurados;
- tareas pesadas ejecutables en background worker;
- caché de viewsheds;
- tests unitarios de geometría y optimización;
- ningún algoritmo debe depender de estado global;
- los datos originales no deben modificarse;
- cada resultado debe guardar su procedencia.

## 10. Criterio de éxito del MVP

El MVP será aceptable cuando pueda:

1. procesar un área de prueba real;
2. generar al menos 100 candidatos;
3. calcular su cobertura;
4. seleccionar una solución razonable;
5. visualizarla en un mapa;
6. demostrar que añadir Sentinel nunca reduce la cobertura;
7. exportar las posiciones y métricas;
8. reproducir el mismo resultado con la misma configuración y semilla.

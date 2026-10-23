# Original User Request

## Initial Request — 2026-10-21T01:38:13Z

Auditoría integral, certificación de calidad rigurosa, pruebas de estrés y optimización del sistema de gestión para restaurante "Pollo Apanado" (Punto de Venta táctil para tablet, trazabilidad de despiece, cronómetros de cocina, inventario multinivel, cuadre de caja y empaquetado Docker), implementando un ciclo iterativo de agentes ejecutores y agentes auditores adversarios con autoridad de rechazo y re-ejecución.

Working directory: `c:\Users\Alejandro\Desktop\POLLO APANADO`
Integrity mode: development

## Requirements

### R1. Auditoría y Robustez del Punto de Venta Táctil (Tablet)
Validar que la interfaz de mostrador opere sin fricción ni retrasos: comanda interactiva con controles de aumento, disminución y eliminación de ítems, selección obligatoria de presa para el Almuerzo Completo ($16.000 COP) con verificación de existencias en vivo, cálculo exacto de cambio en efectivo y pagos digitales (Nequi/Daviplata y Datáfono).

### R2. Trazabilidad Matemática de Despiece e Inventario Multinivel
Comprobar que la regla de despiece (`1 Pollo Crudo` ➔ `2 Pechugas + 2 Muslos + 2 Contramuslos + 2 Alas + raciones de Caldo`) y el consumo de gaseosas, porciones e insumos secos no presenten derivas ni descuadres matemáticos entre bodega, cocina y vitrina.

### R3. Precisión de Cronómetros de Cocina y Algoritmo de Horas Pico
Verificar la funcionalidad de los temporizadores de salmuera y adobo con parámetros configurables, y validar que el recomendador de fritura anticipe correctamente las tandas de pollo frito basadas en la curva horaria de demanda.

### R4. Integridad del Cuadre de Caja y Métricas de Socios
Auditar el arqueo financiero diario por método de pago, el cálculo de márgenes brutos y la comparación automática contra el punto de equilibrio diario ($258.462 COP/día), garantizando que las alertas de compras a proveedores se disparen ante stocks críticos.

### R5. Suite de Pruebas Automatizadas, Resiliencia y Docker
Crear y ejecutar una suite exhaustiva de pruebas unitarias y de estrés de concurrencia. Validar el manejo seguro de transacciones en SQLite (modo WAL), la persistencia del archivo de datos y la reproducibilidad del despliegue en contenedor Docker.

## Acceptance Criteria

### Integridad Operativa y Pruebas Automatizadas
- [ ] La suite de pruebas automatizadas (`pytest`) cubre el 100% de los flujos críticos (despiece, venta en mostrador, selección de presa, reversión de venta, cuadre de caja) pasando con cero errores.
- [ ] Prueba de estrés de concurrencia: simular al menos 50 transacciones rápidas consecutivas verificando que no existan bloqueos de base de datos (`database is locked`) ni descuadres en el inventario final.
- [ ] Verificación de inventario cerrado: `Stock Inicial + Entradas por Despiece - Ventas Registradas = Stock Final Físico` con discrepancia cero.

### Auditoría Adversaria y Certificación de Código
- [ ] Un agente auditor independiente revisa el código fuente, endpoints y frontend, emitiendo un reporte formal de calidad.
- [ ] Si se identifican fallos de validación, vulnerabilidades o inconsistencias, el ciclo se re-ejecuta automáticamente hasta cumplir el estándar de producción.
- [ ] El contenedor Docker compila y levanta limpiamente con volúmenes persistentes funcionales.


## 2026-10-21T04:39:26Z

Implementación, auditoría y certificación de un sistema de arqueo de caja ultra-explícito (con apertura de base inicial, separación de efectivo físico vs. transferencias digitales y dinero esperado al cierre) y un módulo de seguridad antifraude con PIN de Administrador/Socio para erradicar el robo por anulaciones de ventas, complementado con auditoría de discrepancias entre inventario físico y teórico.

Working directory: `c:\Users\Alejandro\Desktop\POLLO APANADO`
Integrity mode: development

## Requirements

### R1. Ciclo de Caja con Base Inicial y Arqueo Cierre Explícito
Implementar la apertura de turno donde el cajero declara la Base Inicial de efectivo (ej. $100.000 COP para dar cambio). Al cierre de jornada, el sistema debe emitir una planilla comprensible que calcule:
`Efectivo Final Esperado en Cajón = Base Inicial + Ventas en Efectivo - Gastos Menores Autorizados`.
Separar con total claridad el efectivo físico en caja, las transferencias en Nequi/Daviplata y los vouchers de datáfono para que tanto el dueño como el empleado entiendan el cuadre con exactitud.

### R2. Desglose Exhaustivo de Presas, Combos y Dinero Recaudado
El informe de cierre debe listar explícitamente:
- Presas vendidas: cuántas Pechugas, Muslos, Contramuslos y Alas se despacharon (individuales y dentro de combos) y su valor equivalente en dinero ($ COP).
- Combos y Almuerzos: cantidad de 1/4 de pollo, 1/2 pollo, pollos enteros y almuerzos ejecutivos con su valor recaudado.
- Porciones sueltas (caldo, arroz, frijol, papas, arepas) y unidades de gaseosas (Postobón y Coca-Cola) con su dinero respectivo.

### R3. Módulo Antifraude con PIN de Administrador y Bitácora Forense
Erradicar la trampa de anulaciones de ventas para sustraer efectivo:
1. **Bloqueo por PIN:** La anulación de cualquier venta queda estrictamente bloqueada para el cajero común; solo puede autorizarse mediante el PIN de seguridad de Administrador/Socio.
2. **Bitácora Forense Inmutable:** Toda anulación guarda permanentemente la fecha, hora, segundo exacto, motivo y usuario autorizador.
3. **Sección de Alerta en Cierre:** El informe de caja incluye un recuadro en rojo con la auditoría de ventas anuladas, el dinero que fue revertido y las presas exactas que debieron reingresar a la vitrina.

### R4. Arqueo Físico de Vitrina y Reporte de Discrepancias
Al cierre de turno, el cajero debe ingresar el conteo físico real de presas en vitrina. El sistema contrasta automáticamente:
`Discrepancia / Merma = Conteo Físico Real - Stock Teórico del Sistema`.
Si hay ventas anuladas pero las presas no están físicamente en vitrina, el sistema genera una alerta inmediata de posible sustracción no autorizada.

### R5. Suite de Pruebas Automatizadas y Auditoría de Seguridad
Desarrollar pruebas automatizadas con `pytest` que validen:
- Rechazo de anulaciones sin PIN o con PIN incorrecto (HTTP 401/403).
- Aprobación de anulación solo con PIN válido y registro inmutable en bitácora.
- Cálculo matemático exacto de `Base Inicial + Ventas = Efectivo en Cajón`.
- Detección de discrepancias en el conteo físico de inventario.

## Acceptance Criteria

### Integridad de Caja y Desglose
- [ ] La apertura de caja registra la base inicial en base de datos y la refleja en la fórmula de arqueo de cierre.
- [ ] El informe de cierre muestra el desglose completo de presas, combos, porciones y bebidas con sus cantidades y subtotales en COP sumando con exactitud al 100%.
- [ ] El dinero esperado en cajón calcula `Base Inicial + Ventas Efectivo` con cero descuadre matemático.

### Seguridad Antifraude y Bitácora
- [ ] Cualquier petición de anulación sin PIN de administrador es rechazada con código de error HTTP 403.
- [ ] Con PIN válido, la anulación se ejecuta, reingresa el inventario y se registra en la tabla forense de auditoría.
- [ ] El reporte de cierre expone de forma visible todas las ventas anuladas del día con su dinero y presas asociadas.
- [ ] El formulario de cierre físico detecta y alerta discrepancias entre presas contadas vs. teóricas.


## 2026-10-22T01:24:23Z

Corrección integral del bug visual de la comanda en el Punto de Venta táctil (POS) e implementación de un módulo dedicado de Entrada de Mercancía de Proveedores y Conciliación de Inventario Inicial para el sistema Pollo Apanado.

Working directory: `c:\Users\Alejandro\Desktop\POLLO APANADO`
Integrity mode: development

## Requirements

### R1. Corrección del Renderizado Reactivo del Ticket/Comanda en Mostrador
Solucionar el fallo en la interfaz del mostrador donde el ticket no refleja visualmente los nuevos ítems agregados, ni los incrementos/decrementos en las cantidades, a pesar de que el valor monetario total sí se acumula internamente. Asegurar que cada toque sobre cualquier producto (presas solas, combos, almuerzos, porciones, gaseosas) o sobre los controles de aumentar (+), disminuir (-) o eliminar (🗑️) actualice de forma inmediata, fluida y sin excepciones de JavaScript el listado visual del pedido en curso.

### R2. Módulo de Entrada de Mercancía y Recepción de Proveedores
Implementar una vista y formulario táctil para registrar la llegada de insumos de proveedores (pollos enteros crudos para bodega, gaseosas para nevera, bultos de harina, canecas de aceite, arepas, etc.).
- Debe capturar: Proveedor, Número de Factura o Remisión, Producto/Insumo recibido, Cantidad ingresada y Costo total/unitario.
- Al confirmar, debe sumar automáticamente las unidades al stock real existente (`Stock Actual = Stock Previo + Entrada Proveedor`).
- Debe persistir una bitácora auditable de compras/recepciones para trazabilidad histórica.

### R3. Panel de Conteo Inicial de Inventario y Conciliación Diaria
Disponer de una interfaz clara donde el dueño o administrador pueda:
- Visualizar y establecer el inventario de apertura del día (con cuánto stock de pollos, gaseosas e insumos se arrancó la jornada).
- Consultar la conciliación en tiempo real: `Stock Físico Esperado = Stock Inicial + Entradas de Proveedores - Consumo/Ventas`.

### R4. Suite de Pruebas Automatizadas y Auditoría E2E
Desarrollar pruebas automatizadas con `pytest` y validaciones en navegador que certifiquen:
- Adición consecutiva de múltiples ítems heterogéneos al carrito sin errores de JavaScript en la consola.
- Integridad de la comanda en pantalla reflejando exactamente cada ítem con su respectivo subtotal y cantidad.
- Adición correcta de inventario por proveedor y actualización de existencias en base de datos.
- Conciliación matemática de stock sin derivas.

## Acceptance Criteria

### Interfaz del Punto de Venta (POS)
- [ ] Al seleccionar múltiples productos diferentes sucesivamente (ej. Contramuslo solo + Pechuga sola), todos aparecen listados individualmente en el ticket lateral derecho con sus nombres, presas, cantidades y subtotales.
- [ ] Los botones táctiles de aumentar (+) y disminuir (-) actualizan visualmente el número de unidades y el subtotal de la fila al instante sin congelar la comanda.
- [ ] Al vaciar la comanda o completar la venta, el ticket vuelve a su estado inicial limpio de forma correcta.

### Gestión de Proveedores e Inventario
- [ ] Existe un botón o sección accesible ("Entrada de Mercancía / Proveedores") para cargar recepciones de insumos.
- [ ] Registrar una compra de proveedores incrementa inmediatamente el stock disponible en bodega/nevera y genera el registro en la tabla de recepciones.
- [ ] El sistema muestra con exactitud el inventario con el que inició el turno y el balance acumulado de entradas.
- [ ] La suite de pruebas de `pytest` pasa al 100% con cero errores y cero regresiones.

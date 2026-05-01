# Renfe Notifier Bot - Guía avanzada de funcionalidades, instalación y uso

> **Versión 2.1** (Mayo 2026) — Nuevas mejoras UX: selector paginado de trenes, búsqueda predictiva de estaciones, flujo inteligente "otra consulta"

## 1. ¿Qué hace este bot?

Este bot de Telegram consulta disponibilidad de trenes en Renfe y te permite:

- Hacer una **búsqueda puntual** con validación inteligente de estaciones y búsqueda predictiva.
- **4 modos de búsqueda**: hora concreta, primer tren disponible, último disponible, o todas las opciones con selector paginado (4 trenes/página).
- **Seguimiento automático cada 30 segundos**: si no hay plazas, el bot busca automáticamente y te notifica al instante cuando hay disponibilidad.
- Validar estaciones con corrección de errores tipográficos y búsqueda predictiva por prefijo y prioridad de ciudad.
- Activar búsqueda por **Plaza H disponible**.
- **Recuperación inteligente**: si no hay trenes, vuelves a elegir modo, cambiar fecha, o menú principal.
- **Flujo "otra consulta" inteligente**: reutiliza automáticamente estaciones y/o fecha según tu preferencia.
- Control de acceso: solo usuarios autorizados.

---

## 2. Funcionalidades principales

### 2.1 Flujo de conversación del usuario (v2.1)

Al usar `/start`, el bot abre un menú principal con:

1. **Realizar búsqueda** (nueva)
2. **Ver seguimientos activos** (nuevo)

#### Flujo "Realizar búsqueda"

1. Pide estación de origen (con búsqueda predictiva: conforme escribes se filtran por prefijo y prioridad).
2. Pide estación de destino (misma búsqueda predictiva).
3. Pide fecha (calendario restrictivo: hoy hasta +2 meses).
4. Pregunta si quieres buscar con **Plaza H disponible**.
5. **Pregunta modo de búsqueda** (actualizado en v2.1):
   - **Hora concreta**: selecciona el tren por número
   - **Primer tren disponible**: busca el más temprano con plazas
   - **Último tren disponible**: busca el más tardío con plazas
   - **Todas las opciones**: **selector paginado inline** (4 trenes/página con navegación ⬅️/➡️)

**Si hay plazas disponibles:**
- Muestra: `"Felicidades! El tren del día DD/MM/YYYY ORIGEN (HH:MM) - DESTINO(HH:MM) tiene plazas disponibles."`
- Pregunta: `"¿Quieres hacer alguna consulta adicional? (SI/NO)"` **(v2.1 - NUEVO FLUJO)**
  - **SÍ** → `"¿Deseas usar las mismas estaciones de origen y destino? (SI/NO)"`
    - **SÍ** → `"¿Deseas usar la misma fecha? (SI/NO)"`
      - **SÍ** → Salta a Plaza H (reutiliza ambas → búsqueda rápida)
      - **NO** → Pide nueva fecha → Plaza H
    - **NO** → Pide selector origen/destino (sin pedir fecha, asume la misma) → Plaza H
  - **NO** → Limpia chat completamente, vuelve a menú principal

**Si NO hay plazas disponibles:**
1. Muestra: `"Lo lamentamos, El tren ... NO tiene plazas disponibles."`
2. Pregunta: `"¿Quieres hacer un seguimiento? (SI/NO)"`
   - **SI**: Se activa seguimiento cada 30s. Te notificará cuando haya plazas. Duración: 1 mes o hasta salida del tren (lo que ocurra antes).
   - **NO**: Acceso a **menú de recuperación**:
     - Volver a opciones de búsqueda
     - Cambiar fecha
     - Volver al menú principal

#### Flujo "Ver seguimientos activos"

1. Lista los seguimientos activos con números.
2. Pregunta si quieres eliminar alguno.
3. Si sí, selecciona por número y se borra.

---

## 🆕 v2.1 NUEVAS FUNCIONALIDADES

### 2.2a Búsqueda predictiva de estaciones (v2.1)

Conforme escribes en el selector de estaciones:

- **Prefijo exacto** (ej: escribes "S" y aparece Sevilla antes de otras) → +8 puntos
- **Palabras que empiezan** con tu búsqueda (ej: escribes "Puerta" y aparece "Madrid-Puerta de Atocha") → +5 puntos
- **Umbral mínimo reducido a 2 caracteres** (ej: "Ma" → todos los Madriles)
- **Desempate por prioridad de ciudad**: ciudades importantes (Madrid, Barcelona) aparecen primero

**Ejemplo práctico:**
- Escribes: `"S"`
- Resultados ordenados:
  1. Sevilla-Santa Justa ⭐ (empieza con S, prioridad 7)
  2. Santander ⭐ (empieza con S, prioridad 9)
  3. Soria (empieza con S, prioridad menor)
  4. Sahagún (no empieza con S, solo contiene S)

---

### 2.2b Selector paginado de trenes (v2.1) - Modo "Todas las opciones"

En modo **"Todas las opciones"**, ver todos los trenes disponibles de forma paginada:

- **4 trenes por página** en teclado inline
- **Navegación intuitiva**: `⬅️ Anterior | Página X/Y | ➡️ Siguiente`
- **Botón especial**: "Todos los trenes 🌐" (para seguir todos a la vez)
- Selecciona el tren tocando su botón

**Vista típica:**
```
Trenes Madrid-Atocha → Barcelona-Sants (30/04/2026):
[06:30 ✓] [07:00 ✓] [08:00 ✗] [09:00 ✓]
[⬅️ Prev] [Página 1/3] [Next ➡️]
[Todos los trenes 🌐]
```

---

### 2.2c Flujo "otra consulta" inteligente (v2.1)

Cuando seleccionas un tren con disponibilidad, el bot pregunta:

**"¿Quieres hacer otra consulta? (SI/NO)"**

**Si SÍ**, flujo smart de 2 preguntas:

1. **"¿Mismas estaciones de origen y destino?"**
   - SÍ → va a pregunta 2
   - NO → pide selector origen/destino (sin pedir fecha)

2. **"¿Misma fecha?"** (solo si respondiste SÍ a pregunta 1, o saltado si respondiste NO)
   - SÍ → **Salta directo a Plaza H** (búsqueda express)
   - NO → pide **calendario para nueva fecha** → Plaza H

**Matriz de 4 caminos:**

| ¿Mismas estaciones? | ¿Misma fecha? | Resultado |
|:---:|:---:|---|
| **SÍ** | **SÍ** | ✅ Plaza H directo (reutiliza TODO) |
| **SÍ** | **NO** | 📅 Calendario → Plaza H |
| **NO** | **SÍ** | 🏢 Selector origen/destino → Plaza H |
| **NO** | **NO** | 🏠 Vuelve a menú principal |

**Bonus:** Chat limpiado automáticamente al iniciar cada búsqueda adicional → mejor UX.

---

## 2.3 Búsqueda por Plaza H

Si eliges **Plaza H disponible**:

- El bot manda la búsqueda a Renfe con `plazaH=true`.
- Intenta activar elementos del DOM relacionados:
  - Botón **"Más opciones de búsqueda"**
  - Checkbox **"Plaza H disponible"**
- Detecta automáticamente resultados **"Solo plazas H"** como válidos cuando buscas con Plaza H.

---

## 2.4 Seguimiento automático cada 30 segundos (Nuevo v2.0)

Cuando seleccionas un tren sin plazas y confirmas seguimiento:

- **El bot busca cada 30 segundos** de forma invisible.
- **Solo te notifica si encuentra plazas** en ese tren.
- **Duración**: automática hasta el mínimo entre:
  - 1 mes desde creación
  - Fecha + hora de salida del tren

**Ciclo de vida:**
1. Creas seguimiento con confirmación SI
2. Bot busca cada 30s en segundo plano
3. Si hay plazas → **Notificación inmediata** + se borra seguimiento
4. Si pasa 1 mes sin disponibilidad → Bot te pregunta si prolongar 1 mes más
5. Si llega fecha/hora de salida → Bot te notifica que se borró (tren ya salió)

---

## 2.5 Recuperación inteligente tras "no hay trenes" (Nuevo v2.0)

Si no hay disponibilidad y rechazas hacer seguimiento:

**Menú de recuperación** con 3 opciones:
1. **Volver a opciones de búsqueda**: elige otro modo (hora concreta / primer / último / todas)
2. **Cambiar fecha**: vuelves al calendario para otra fecha
3. **Volver al menú principal**: vuelves a `/start`

Esto evita perder contexto y facilita ajustes rápidos.

---

## 2.6 Manejo de errores y trazas de depuración

Cuando hay fallo al consultar Renfe, el bot guarda automáticamente:

- **Captura**: `data/debug.png`
- **HTML de la página**: `data/debug.html`

Ayuda a diagnosticar cambios de HTML/IDs/selectores en Renfe.

---

## 3. Arquitectura del proyecto (v2.1)

### Carpetas/archivos clave:

- **`python/renfebot.py`**: Orquestación del bot (async con `Application` de PTB v20+), registro de handlers, Job Queue de seguimientos cada 30s.
- **`python/conversations.py`**: Estados conversacionales (ConvStates enum), flujo async, validaciones, nuevos estados ADDITIONAL_SAME_STATIONS y ADDITIONAL_SAME_DATE (v2.1).
- **`python/renfechecker.py`**: Scraping Selenium (v4) con hardening anti-stale:
  - Método `_submit_payload_to_dom_form()`: rellenado atómico sin referencias stale
  - 3 intentos con retry automático
  - Fallback a POST manual si DOM no estable
- **`python/dbmanager.py`**: Persistencia SQLite:
  - Tabla `users`: userid, username, auth
  - Tabla `followups`: seguimientos activos (id, userid, ruta, fecha, hora, plaza_h, estado, expiración)
  - Métodos: crear, listar, extender, borrar seguimientos
- **`python/texts.py`**: Textos (emojis) y teclados. Contiene nuevas opciones: RECOVERY_OPTIONS, modos búsqueda, TRAIN_PICKER_*, ASK_ADDITIONAL_* (v2.1).
- **`python/bot_data.py`**: Configuración (TOKEN, ADMIN_ID).
- **`python/telegramcalendarkeyboard/telegramcalendar.py`**: Calendario inline async con restricciones min/max fechas.
- **`docker-compose.yml` + `Dockerfile`**: Stack: Python 3.12, Firefox ESR, geckodriver latest.
- **`secrets/bot_data.py`**: Credenciales (NO commitar).
- **`data/`**: Base de datos SQLite + artefactos debug (PNG/HTML).
- **`data/stations.json`**: Catálogo de ~1300 estaciones de Renfe (JSON con prioridades).

---

## 4. Instalación

### 4.1 Opción recomendada: Docker Compose

#### Requisitos

- Docker
- Docker Compose (v2)

#### Pasos

1. Crea el archivo `secrets/bot_data.py`:

```python
TOKEN = "TU_TOKEN_DE_BOTFATHER"
ADMIN_ID = 123456789
```

2. Levanta el servicio:

```bash
docker compose up --build -d
```

3. Verifica logs:

```bash
docker compose logs -f renfe-notifier-bot
```

4. Parar servicio:

```bash
docker compose down
```

### Qué hace cada comando

| Comando | Qué hace |
|---|---|
| `docker compose up --build -d` | Construye imagen y levanta el bot en segundo plano. |
| `docker compose logs -f renfe-notifier-bot` | Muestra logs en tiempo real del servicio. |
| `docker compose restart renfe-notifier-bot` | Reinicia solo el contenedor del bot. |
| `docker compose down` | Detiene y elimina contenedor/red del compose. |

---

## 4.2 Opción manual (sin Docker)

> Recomendado para entornos Linux. Requiere Firefox + geckodriver configurados.

### Requisitos técnicos

- **Python 3.12** (mínimo 3.10; preferiblemente 3.12+)
- **Firefox ESR** (última versión)
- **geckodriver** (v0.36.0 o latest)
- **Dependencias Python** (latest estables, sin pines):
  - `python-telegram-bot` (v20+, async)
  - `selenium` (v4+)
  - `pyvirtualdisplay`
  - `emoji`
  - `urllib3`
  - `requests`
  - `certifi`

### Instalación de dependencias Python

```bash
pip install --upgrade \
  python-telegram-bot \
  selenium \
  pyvirtualdisplay \
  emoji \
  urllib3 \
  requests \
  certifi
```

### Ejecutar bot manualmente

```bash
python python/renfebot.py --database data/renfebot.db
```

### Qué hace este comando

- Arranca el bot de Telegram (async con Application v2.0).
- Carga token/admin desde `python/bot_data.py`.
- Usa la base de datos SQLite indicada en `--database`.
- Registra Job Queue para búsquedas de seguimiento cada 30s.

---

## 5. Uso del bot (usuario final)

## Comandos Telegram para usuario

| Comando | Uso |
|---|---|
| `/start` | Inicia conversación y menú principal. |
| `/cancel` | Cancela la conversación actual. |

## Recomendaciones de uso

- Escribe estaciones de forma aproximada si no recuerdas nombre exacto; el bot sugiere alternativas.
- Para búsqueda precisa, usa opción **un tren en concreto** y horas exactas.
- Activa **Plaza H** solo cuando necesites esa disponibilidad específica.
- Usa **"otra consulta"** para búsquedas rápidas reutilizando estaciones o fecha.

---

## 6. Comandos administrativos

Cuando un usuario no autorizado intenta usar el bot, el admin recibe atajos de teclado.

| Comando | Qué hace |
|---|---|
| `/admin ALLOW <userid> <username>` | Autoriza al usuario. |
| `/admin NOTALLOW <userid> <username>` | Revoca autorización al usuario. |

**Ejemplo:**

```text
/admin ALLOW 123456789 Juan
/admin NOTALLOW 123456789 Juan
```

---

## 7. Ciclo de vida de un seguimiento (Nuevo v2.0)

**Escenario**: usuario selecciona tren sin plazas y confirma seguimiento.

```
T=0     → Seguimiento creado (fecha_salida, duración = 1 mes O fecha_salida, lo que sea antes)
T=30s   → Bot busca (Job Queue)
T=60s   → Bot busca
...
T=N días → Bot busca cada 30s
Si Disponible → Notificación + se borra seguimiento
Si Expira (1 mes) → Bot notifica "¿Prolongar?" → Espera SI/NO
  SI  → Prolongación 1 mes más (o hasta fecha_salida, lo que sea antes)
  NO  → Se borra seguimiento
Si Llega fecha_salida → Bot notifica "Tren salió, se borró seguimiento"
```

---

## 8. CLI interna de comprobación (debug técnico)

Existe un modo script para comprobar rutas fuera de Telegram:

```bash
python python/renfechecker.py -o "SEVILLA-SANTA JUSTA" -d "MADRID-PUERTA DE ATOCHA" -f "30/04/2026"
```

### Parámetros

| Parámetro | Significado |
|---|---|
| `-o`, `--origen` | Estación de origen |
| `-d`, `--destino` | Estación de destino |
| `-f`, `--fecha` | Fecha de viaje (`DD/MM/YYYY`) |

---

## 9. Solución de problemas (troubleshooting) (v2.1)

### 9.1 El bot no responde en Telegram

- Revisa token en `secrets/bot_data.py`.
- Revisa logs con `docker compose logs -f renfe-notifier-bot`.
- Verifica que el contenedor está corriendo: `docker compose ps`.

### 9.2 Fallos de Selenium / Renfe cambió HTML

Ahora mucho más robusto (v2.1):

- El bot **reintenta 3 veces automáticamente** si hay `StaleElementReferenceException`.
- Fallback a POST manual si el DOM no es estable.
- Revisa `data/debug.html` y `data/debug.png` si el error persiste.
- Verifica selectores de formulario (`buscarTren.do`, `currenLocation`, `plazaH`).

### 9.3 No se encuentran trenes

- Puede ser ausencia real de disponibilidad para esa fecha/ruta.
- Si buscas tren concreto, revisa formato numérico de selección.
- Si usas Plaza H, desactívala para contrastar disponibilidad general.

### 9.4 No recibo notificación de seguimiento

- Verifica que el seguimiento se creó (lista en `/start` → "Ver seguimientos").
- Revisa logs: `check_followups` debería ejecutarse cada 30s.
- Confirma que hay plazas disponibles (el bot solo notifica si DISPONIBLE=true).
- Si duración expiró (1 mes), el bot envía "¿Prolongar?" pero espera tu respuesta con `/start`.

### 9.5 Selector paginado de trenes no aparece

- Solo aparece en modo **"Todas las opciones"**.
- En modo "Hora concreta", debes escribir el número del tren manualmente.
- Revisa logs si hay error al renderizar el picker inline.

### 9.6 Búsqueda predictiva de estaciones no filtra bien

- Verifica que escribes caracteres válidos (sin acentos especiales en tiempo real; el bot normaliza).
- Umbral mínimo es 2 caracteres.
- Si falta una estación, revisa `data/stations.json` (estructura: `{"nombre_estación": {"nmroPrioridad": N}}`).

---

## 10. Notas operativas importantes (v2.1)

### Cambios principales desde v2.0

1. **Búsqueda predictiva de estaciones**: Ahora prioriza por prefijo exacto y prioridad de ciudad.
2. **Selector paginado de trenes**: En modo "Todas las opciones", visualiza 4 trenes/página con navegación.
3. **Flujo "otra consulta" inteligente**: Pregunta sobre reutilización de estaciones/fecha, con limpieza de chat automática.
4. **Matriz de 4 caminos**: Evita pasos innecesarios según la combinación de respuestas.

### Cambios principales desde v1.0

1. **Async/await en toda la aplicación**: Handlers, calendarios, búsquedas de seguimiento ahora async.
2. **Python-telegram-bot v20+**: Usa `Application` (de `Updater`), `filters.TEXT` (de `Filters.text`).
3. **Seguimiento cada 30s visible**: Job Queue async que busca continuamente, notifica solo si hay cambios.
4. **Selenium v4 hardened**: Retry automático, fallback POST ante stale elements.
5. **4 modos búsqueda**: hora concreta, primer/último tren, todas las opciones (con pagination).
6. **Recuperación inteligente**: Menú tras "no hay trenes" para ajustar opciones.

### Notas de operación

- La base de datos persiste en el volumen `./data`.
- Las credenciales van fuera del código, en `secrets/bot_data.py`.
- Job Queue de 30s corre en segundo plano (invisible al usuario).
- Seguimientos se almacenan en tabla `followups` con estados (active, awaiting_extension, expired).
- Limpieza best effort de chat en cada transición a menú principal o al iniciar búsqueda adicional.
- Búsqueda predictiva recalcula scores en tiempo real según tokens (2+ caracteres).

### Performance

- Búsqueda de estaciones: O(1347) con fuzzy matching optimizado + predicción.
- Scraping Renfe: ~5-15s (depende de disponibilidad).
- Job Queue: 30s entre intentos de búsqueda (configurable en `renfebot.py`).
- Paginación de trenes: O(1) acceso a página (inline keyboard renderizado on-demand).

### Escalabilidad

- SQLite es simple pero suficiente para cientos de usuarios.
- Si crece > 1000 usuarios, considera migrar a PostgreSQL.
- Job Queue actual es serial; para >500 seguimientos simultáneos, considera worker pool.
- Búsqueda predictiva está optimizada para ~1300 estaciones; si adds más catálogos, considera índices de trie.

---

**Última actualización**: Mayo 2026 (v2.1 — Selector paginado + búsqueda predictiva + flujo "otra consulta")

# 🚂 Renfe Notifier Bot

> ⭐ **Fork mejorado** de [0electricista/renfe-web-monitor](https://github.com/0electricista/renfe-web-monitor), que a su vez es fork de [emartinez-dev/renfe-bot](https://github.com/emartinez-dev/renfe-bot)

Un bot de Telegram **inteligente y eficiente** para consultar disponibilidad de trenes en [Renfe](https://www.renfe.com/es/es) con validación avanzada de estaciones, búsqueda flexible y **seguimiento automático cada 30 segundos** cuando no hay plazas disponibles.

## ✨ Características principales

- **📍 Validación inteligente de estaciones**: Cargadas desde un catálogo de **+1300 estaciones reales**. Si escribes mal, el bot sugiere las 3 opciones más probables. **Búsqueda predictiva**: conforme escribes se indexan estaciones por coincidencia de prefijo y prioridad de ciudad.
- **🔄 Múltiples modos de búsqueda**: Hora concreta, primer tren, último tren, o todas las opciones disponibles. **Selector paginado de trenes** (4 por página) en modo "todas las opciones".
- **♿ Filtro Plaza H**: Búsqueda de plazas especiales para personas con movilidad reducida.
- **⏰ Seguimiento automático**: Si no hay plazas, el bot busca cada 30 segundos y te notifica al instante cuando hay disponibilidad.
- **📅 Calendario inteligente**: Selecciona fechas de viaje con restricciones (no antes de hoy, máximo 2 meses adelante).
- **🔁 Flujo "otra consulta" inteligente**: Reutiliza automáticamente estaciones y/o fecha. Menú contextual que se adapta a tu respuesta (mismas estaciones → mismo lugar; misma fecha → saltea calendario). **Limpieza automática de chat** entre búsquedas.
- **🔐 Control de acceso**: Solo usuarios autorizados pueden usar el bot. Gestión simple de permisos.
- **🌙 Interfaz conversacional limpia**: Limpieza automática de chat para mejor experiencia.

---

## 📋 Flujo de uso

```
/start
  ↓
┌─ Opción: Realizar búsqueda / Ver seguimientos activos
│
├─ BÚSQUEDA NUEVA
│   ├─ Estación origen (validación inteligente con ranking por prefijo)
│   ├─ Estación destino (validación inteligente con ranking por prefijo)
│   ├─ Fecha viaje (calendario restrictivo)
│   ├─ ¿Plaza H disponible?
│   ├─ Modo: Hora concreta / Primer tren / Último tren / Todas
│   │   ├─ Modo "Todas" → Selector paginado (4 trenes/página, navegación ⬅️/➡️)
│   │
│   ├─ [Tren DISPONIBLE] → Notificación + ¿Otra consulta?
│   │   ├─ SÍ → ¿Mismas estaciones? (SÍ/NO)
│   │   │   ├─ SÍ → ¿Misma fecha? (SÍ/NO)
│   │   │   │   ├─ SÍ → Plaza H (sin pedir estaciones/fecha)
│   │   │   │   └─ NO → Calendario (nueva fecha) → Plaza H
│   │   │   └─ NO → Selector origen/destino (sin pedir fecha) → Plaza H
│   │   └─ NO → Limpia chat, vuelve a menú principal
│   │
│   └─ [Tren NO DISPONIBLE]
│       ├─ ¿Hacer seguimiento? (SI/NO)
│       ├─ SI → Búsqueda cada 30s (hasta 1 mes o salida del tren)
│       └─ NO → Menú de recuperación
│           ├─ Volver a opciones de búsqueda
│           ├─ Cambiar fecha
│           └─ Volver al menú principal
│
└─ VER SEGUIMIENTOS
    ├─ Listar seguimientos activos
    └─ ¿Eliminar alguno? (SI/NO)
```

---

## 🚀 Instalación

### Requisitos previos

- **Docker** y **Docker Compose** (recomendado)
- O bien: **Python 3.12+**, **Firefox ESR**, **geckodriver** (instalación manual)
- **Token de Telegram** (crear con [@BotFather](https://t.me/botfather))

### Opción 1: Docker Compose (Recomendado)

1. **Clona el repositorio**:
   ```bash
   git clone https://github.com/tuusuario/renfe-notifier-bot.git
   cd renfe-notifier-bot
   ```

2. **Configura el token del bot**:
   ```bash
   mkdir -p secrets
   cat > secrets/bot_data.py << 'EOF'
   TOKEN = "TU_TOKEN_DE_BOTFATHER"
   ADMIN_ID = 123456789  # Tu ID de usuario (obtén con /start si lo configuras)
   EOF
   ```

3. **Levanta el servicio**:
   ```bash
   docker compose up --build -d
   ```

4. **Verifica los logs**:
   ```bash
   docker compose logs -f renfe-notifier-bot
   ```

### Opción 2: Instalación manual

1. **Requisitos del sistema** (Ubuntu/Debian):
   ```bash
   sudo apt-get update && sudo apt-get install -y \
     python3.12 python3.12-venv python3-pip \
     firefox-esr wget ca-certificates xvfb
   ```

2. **Geckodriver**:
   ```bash
   GECKODRIVER_VERSION=0.36.0
   wget -q "https://github.com/mozilla/geckodriver/releases/download/v${GECKODRIVER_VERSION}/geckodriver-v${GECKODRIVER_VERSION}-linux64.tar.gz"
   tar -xzf "geckodriver-v${GECKODRIVER_VERSION}-linux64.tar.gz" -C /usr/local/bin
   rm "geckodriver-v${GECKODRIVER_VERSION}-linux64.tar.gz"
   ```

3. **Python virtual environment**:
   ```bash
   python3.12 -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   ```

4. **Dependencias Python**:
   ```bash
   pip install --upgrade pip setuptools wheel
   pip install -r requirements.txt  # Si existe
   # O bien:
    pip install --upgrade \
      python-telegram-bot \
      selenium \
      pyvirtualdisplay \
      emoji \
      json5 \
      requests
   ```

5. **Configura el bot** (crear `python/bot_data.py`):
   ```python
   TOKEN = "TU_TOKEN_DE_BOTFATHER"
   ADMIN_ID = 123456789
   ```

6. **Inicia el bot**:
   ```bash
   python python/renfebot.py --database /path/to/renfebot.db
   ```

---

## ⚙️ Configuración

### `secrets/bot_data.py`

```python
TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"  # Token de Telegram
ADMIN_ID = 987654321                                   # Tu ID (obtén de /start)
```

**Cómo obtener tu ID de usuario**:
1. Inicia el bot con `/start`
2. Mira los logs: verás un mensaje de solicitud de acceso con tu ID
3. Úsalo en `ADMIN_ID`

### Base de datos

La base de datos SQLite se crea automáticamente en:
- **Docker**: `/data/renfebot.db`
- **Manual**: especificada con `--database` (default: `/mnt/shared/renfebot.db`)

---

## 📖 Guía de uso

Consulta la **[Guía Avanzada](./GUIA_AVANZADA.md)** para:
- Descripción completa de cada comando
- Ejemplos de flujo conversacional
- Casos de uso y estrategias
- Troubleshooting

---

## 🏗️ Arquitectura

```
renfe-notifier-bot/
├── python/
│   ├── renfebot.py                    # Orquestación del bot (async + Job Queue)
│   ├── conversations.py               # Estados y flujo conversacional
│   ├── renfechecker.py               # Scraping Renfe (Selenium con hardening)
│   ├── dbmanager.py                  # SQLite: usuarios, seguimientos
│   ├── texts.py                      # Textos y teclados
│   ├── bot_data.py                   # Configuración (token, admin)
│   └── telegramcalendarkeyboard/     # Calendario inline personalizado
├── data/
│   ├── stations.json                 # Catálogo de +1300 estaciones
│   └── renfebot.db                   # BD SQLite (creada automáticamente)
├── secrets/
│   └── bot_data.py                   # Credenciales (NO commitar)
├── Dockerfile                        # Image: Python 3.12 + Firefox ESR + geckodriver
├── docker-compose.yml                # Orquestación (volúmenes compartidos)
├── README.md                         # Este archivo
└── GUIA_AVANZADA.md                  # Documentación extendida
```

### Tecnologías

- **Bot framework**: `python-telegram-bot` (v20+, async/await)
- **Scraping**: `selenium` (v4+) con Firefox
- **Display**: `pyvirtualdisplay` (X11 virtual display)
- **BD**: `sqlite3` (nativa, sin dependencias)
- **Emojis**: `emoji` library
- **Parser DWR**: `json5` (parseo de respuesta backend Renfe)

---

## 🔧 Desarrollo

### Build local de imagen Docker

```bash
docker build -t renfe-notifier-bot:latest .
```

### Compilación de Python (validación)

```bash
python -m py_compile python/*.py python/telegramcalendarkeyboard/*.py
```

### Estructura de estados conversacionales

Los estados definidos en `ConvStates` (enum):
- `OPTION`: Selección de acción principal
- `STATION`: Entrada de estación origen/destino
- `STATION_GROUP_CHOICE`: Desambiguación de ciudades (e.g., MADRID (TODAS))
- `DATE`: Selección de fecha (calendario)
- `PLAZA_H`: Filtro de plazas especiales
- `SEARCH_MODE`: Modo de búsqueda (específico, primer, último, todos)
- `TRAIN_SELECT`: Selección numérica de tren + selector paginado inline (modo "todas")
- `FOLLOWUP_CONFIRM`: Confirmación de seguimiento
- `RECOVERY_ACTION`: Recuperación tras no disponibilidad
- `ADDITIONAL_QUERY`: ¿Hacer otra búsqueda? (v2.1 - nuevo)
- `ADDITIONAL_SAME_STATIONS`: ¿Reutilizar estaciones origen/destino? (v2.1 - nuevo)
- `ADDITIONAL_SAME_DATE`: ¿Reutilizar fecha? (v2.1 - nuevo)
- `EXTEND_DECISION`: Ampliación de seguimiento pasado 1 mes

---

## 🐛 Troubleshooting

### El bot no responde

1. **Verifica que esté corriendo**:
   ```bash
   docker compose ps
   # O: ps aux | grep renfebot
   ```

2. **Mira los logs**:
   ```bash
   docker compose logs renfe-notifier-bot -f
   ```

3. **Comprueba el token**:
   - Asegúrate de que `TOKEN` en `secrets/bot_data.py` es correcto
   - Verifica que el archivo existe y está en el contenedor (volumen montado)

### Error: "StaleElementReferenceException"

Si ves este error en logs (ahora es raro):
- Se debe a que el DOM de Renfe cambió durante el rellenado del formulario
- El bot **reintenta automáticamente 3 veces** con fallback a POST manual
- Si persiste: verifica que Renfe no cambió su estructura HTML

### Error: "Estación no encontrada"

1. El catálogo `data/stations.json` se cargó correctamente
2. El bot sugiere las 3 opciones más similares
3. Si la estación sigue sin aparecer:
   - Revisa `data/stations.json` (estructura: `{"nombre_estación": {"nmroPrioridad": N}}`)
   - Asegúrate de que el nombre coincide con el de Renfe

### La búsqueda tarda mucho

- Renfe es lento (especialmente en horas pico)
- El timeout está configurado a 60s
- Si timeout: revisa que Firefox + Selenium estén funcionando

### Las notificaciones de seguimiento no llegan

1. Verifica que el seguimiento se creó:
   - Comando `/admin` (solo para admin) ver DB
2. Comprueba el Job Queue:
   - Logs mostrarán `check_followups` cada 30s
3. Asegúrate de que hay plazas disponibles:
   - El bot solo notifica si **DISPONIBLE=true** en el tren

---

## 📝 Logs

### Ubicación

- **Docker**: `docker compose logs renfe-notifier-bot`
- **Manual**: stdout (terminal donde ejecutaste `renfebot.py`)

### Niveles

- `DEBUG`: Flujo conversacional, acciones del bot
- `INFO`: Cambios de estado
- `WARNING`: Timeouts, DOM changes
- `ERROR`: Excepciones en scraping, fallos críticos

### Debug HTML/Screenshot

Si hay error de Renfe, el bot guarda automáticamente:
- `/data/debug.html` (página HTML)
- `/data/debug.png` (screenshot)

---

## 🔐 Seguridad y privacidad

### Notas importantes

1. **Token del bot**: NUNCA lo commitees en git. Usa `secrets/bot_data.py` y `.gitignore`.
2. **Base de datos**: Contiene IDs de usuarios y datos de seguimiento. Protégela.
3. **ADMIN_ID**: Solo el admin puede autorizar usuarios nuevos.
4. **Credenciales Renfe**: El bot NO almacena credenciales (es navegación anónima).

### Recomendaciones

- Ejecuta en servidor privado (no expuesto a internet directamente)
- Usa volúmenes Docker con permisos restrictivos (`chmod 600 secrets/`)
- Haz backups regulares de `/data/renfebot.db`

---

## 📄 Licencia

Este proyecto está bajo licencia [MIT](./LICENSE) (si existe).

---

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor:

1. Fork el repositorio
2. Crea una rama para tu feature (`git checkout -b feature/NuevaFuncionalidad`)
3. Commit tus cambios (`git commit -am 'Agrega nueva funcionalidad'`)
4. Push a la rama (`git push origin feature/NuevaFuncionalidad`)
5. Abre un Pull Request

---

## 📞 Soporte

Si encuentras problemas:

1. **Revisa [GUIA_AVANZADA.md](./GUIA_AVANZADA.md)** para casos de uso detallados
2. **Consulta [Troubleshooting](#troubleshooting)** en este README
3. **Abre una issue** con:
   - Descripción del problema
   - Logs relevantes (sin tokens sensibles)
   - Pasos para reproducir

---

## 📊 Estado del proyecto

| Componente | Estado | Notas |
|---|---|---|
| Bot base (Telegram) | ✅ Completo | Async, Python 3.12 |
| Scraping Renfe | ✅ Completo | Selenium 4 con hardening anti-stale |
| Validación estaciones | ✅ Completo | +1300 estaciones, búsqueda predictiva por prefijo |
| Modos búsqueda | ✅ Completo | 4 modos + hora concreta + selector paginado (4/página) |
| Selector paginado trenes | ✅ Completo | Modo "todas opciones" con navegación ⬅️/➡️ |
| Plaza H | ✅ Completo | Detecta "solo plazas H" automáticamente |
| Seguimiento 30s | ✅ Completo | Job Queue async cada 30 segundos |
| Calendario | ✅ Completo | Inline, restricciones min/max fechas |
| Flujo "otra consulta" | ✅ Completo | Reutiliza estaciones/fecha, limpieza de chat |
| Control acceso | ✅ Completo | Admin autoriza usuarios nuevos |
| Docker | ✅ Completo | Python 3.12, Firefox ESR, geckodriver |
| Documentación | ✅ Completo | README + GUIA_AVANZADA.md + PLAN_MEJORAS_UX_V3.md |

---

**Última actualización**: Mayo 2026  
**Versión**: 2.1 (Selector paginado + búsqueda predictiva + flujo inteligente "otra consulta")

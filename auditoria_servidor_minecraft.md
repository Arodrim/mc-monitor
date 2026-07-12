# Auditoría Técnica de Infraestructura — Servidor Doméstico de Minecraft

**Fecha:** 2026-07-11
**Alcance:** Disponibilidad, red, sistema operativo, servidor de juego, seguridad y observabilidad.
**Contexto disparador:** Incidente de resolución DNS dinámica (Dynu) que dejó el servidor inaccesible para jugadores externos tras un cambio de IP pública del ISP (Antel), a pesar de que el servicio parecía "sano" localmente.

---

## 1. Resumen ejecutivo

El servidor cumple su función básica —Paper 1.21.8 sobre Debian 12, gestionado por systemd, con port forwarding y DNS dinámico vía Dynu— pero la arquitectura actual es **frágil por diseño**, no por mala suerte puntual. El incidente reportado (Dynu no actualizó el registro tras un cambio de IP del ISP) no fue un evento aislado: es el síntoma de un problema estructural más amplio: **no existe una capa de verificación end-to-end** que confirme que un jugador externo real puede conectarse. Todos los chequeos actuales (`ping`, `Test-NetConnection`, "el servicio está activo") validan capas de red o de proceso, pero ninguno valida la experiencia real del usuario final.

Esto es la causa raíz común a la mayoría de los escenarios de falla planteados: **la infraestructura mide "¿está encendido?" en vez de "¿funciona de punta a punta?"**.

Puntos clave:

- Hay un **único punto de fallo en cascada de tres eslabones** (ISP asigna IP → Dynu detecta el cambio → Dynu publica el registro) y **ningún eslabón se verifica de forma independiente** desde fuera de la red doméstica.
- El servidor depende 100% de un enlace residencial único, sin redundancia de conectividad ni de energía.
- No hay evidencia de un pipeline de backups verificado (backup ≠ backup restaurable).
- La superficie de ataque hacia SSH y el puerto de juego no está descrita con controles compensatorios explícitos (Fail2Ban, listas de bloqueo, rate limiting).
- La observabilidad existente (si la hay) monitorea el proceso, no el servicio percibido por el jugador.

Ninguno de estos problemas requiere hardware nuevo ni un proveedor cloud: se resuelven con configuración, scripts de verificación externos y disciplina de monitoreo. El roadmap al final prioriza exactamente eso.

---

## 2. Análisis de causa raíz del incidente reportado

Reconstrucción de la cadena de fallo:

1. Antel reasignó la IP pública (`186.53.219.38` → `186.50.5.43`), algo esperable en una conexión residencial sin IP fija.
2. El agente/cliente de actualización de Dynu **no propagó el cambio a tiempo** (o no se ejecutó, o falló silenciosamente).
3. El registro DNS de `minecraft-tomas.xubi.org` siguió apuntando a la IP vieja.
4. El jugador remoto resolvía el hostname correctamente (`ping` funcionaba) porque el DNS *sí* respondía — solo que con el dato incorrecto.
5. `Test-NetConnection` a 25565 devolvía `True` porque, muy probablemente, **el router del jugador o un salto intermedio respondía en la IP vieja** (podía ser un ISP con NAT de carrier, otro dispositivo, o el propio Antel reasignando esa IP a otro cliente que casualmente tenía un puerto abierto) — esto es clave y hay que verificarlo, porque "el TCP handshake funciona pero el juego no conecta" también puede significar que **la IP vieja ya pertenece a otro abonado de Antel**, lo cual es un escenario más grave que un simple DNS desactualizado.
6. El cliente de Minecraft, que sí completa el protocolo de aplicación (handshake + login), fue el único punto donde el fallo se manifestó de forma inequívoca.

**Conclusión crítica:** un chequeo de "¿responde el puerto?" no es suficiente para detectar este tipo de incidente, porque puede dar falso positivo si la IP vieja quedó reasignada a otro host con algún puerto abierto. La única prueba confiable es un **handshake real del protocolo de Minecraft** (Server List Ping) ejecutado desde una red externa a la doméstica, resolviendo el hostname público, no una IP cacheada.

---

## 3. Hallazgos críticos (requieren atención inmediata)

### C1. No hay verificación externa de resolución DNS vs. IP real del servidor
No se evidencia un chequeo que compare periódicamente "IP pública actual del servidor" contra "IP que resuelve el hostname de Dynu". Esto es exactamente lo que causó el incidente y **puede volver a pasar mañana** de la misma forma. Sin este control, cualquier fallo del agente de Dynu (crash, IP no cambiada, rate limit de Dynu, cambio de credenciales, expiración del hostname free) queda invisible hasta que un jugador se queja.

### C2. Los chequeos de salud existentes validan la capa equivocada
"El servicio systemd está activo" y "el puerto responde a un socket TCP" no prueban que el juego sea jugable. Un mundo corrupto, un hilo colgado, un accept() saturado, o exactamente el escenario del incidente (DNS apuntando a otro host) pueden coexistir con "systemctl status: active (running)".

### C3. Dependencia de un único enlace residencial sin plan de contingencia de conectividad
No hay mención de una ruta secundaria (failover 4G/5G, segundo ISP, VPN a un VPS barato como relay). Si Antel tiene una caída de horas, el servicio cae completo sin alternativa, y no hay forma de que la comunidad sepa "por qué" sin un canal externo (ver C4).

### C4. Canal de comunicación de estado depende de la misma infraestructura que falla
Si el servidor/router/Internet doméstico cae, probablemente también caiga cualquier bot de Telegram/Discord alojado localmente para avisar "el server está caído". Se necesita que las alertas se generen **desde afuera** (un monitor externo tipo Uptime Kuma en un VPS gratuito, UptimeRobot, Healthchecks.io) para que "silencio total" también dispare alerta.

### C5. Estado real de los backups no verificado (no confirmado, pero no evidenciado)
No se menciona verificación de integridad ni restauración de prueba. Un backup que nunca se restaura es, estadísticamente, un backup que no existe cuando se lo necesita. Esto entra como crítico porque la corrupción de mundo es uno de los escenarios de mayor impacto y menor tiempo de detección.

---

## 4. Riesgos altos

### R-A1. Cadena DNS dinámico sin redundancia de proveedor
Un único proveedor DDNS (Dynu) es un punto único de fallo. Si Dynu tiene un incidente de plataforma, cambia su API, o suspende la cuenta gratuita, el hostname deja de resolver correctamente y no hay plan B (segundo proveedor, TTL corto documentado, registro A secundario).

### R-A2. IPv4 CGNAT / reasignación de IP no monitoreada como evento de red
No queda claro si Antel entrega IP pública dedicada o si existe riesgo de CGNAT (Carrier-Grade NAT), lo cual haría **imposible** el port forwarding tradicional. Si hoy funciona pero la IP puede cambiar sin aviso (como ocurrió), hay que asumir que el ISP no garantiza estabilidad, y diseñar en consecuencia (ver roadmap).

### R-A3. Ausencia de IPv6 como respaldo
No se menciona soporte IPv6. IPv6 evita NAT y port forwarding por completo si el ISP y el router lo soportan, y sería una vía de conexión alternativa independiente de los problemas de IPv4/CGNAT. Hoy es una oportunidad no explotada, mañana puede ser el único camino si Antel migra a CGNAT.

### R-A4. Seguridad SSH sin controles compensatorios confirmados
No hay evidencia de Fail2Ban, autenticación por clave únicamente (deshabilitar password auth), cambio de puerto, o restricción por IP/VPN para el acceso administrativo. El servidor está expuesto a Internet (port forwarding activo), así que SSH es un vector de ataque de fuerza bruta constante si el puerto 22 también está expuesto.

### R-A5. `online-mode=false` sin controles adicionales documentados
Ya usan AuthMe, lo cual es correcto para mitigar la suplantación de identidad en modo offline. Pero offline-mode también implica: sin verificación de Mojang, el servidor es más vulnerable a bots de conexión masiva y a ataques de "fake ping" para reconocimiento. Hay que confirmar que existe protección adicional (rate limiting de conexiones, whitelist si aplica, protección contra flood de logins).

### R-A6. Falta de límites de recursos y protección ante saturación (RAM/disco)
No se evidencia una política de rotación de logs, cuotas de disco, ni límites de memoria por systemd (`MemoryMax`) o por el propio JVM con manejo de OOM. Un mundo que crece sin límite (chunks nunca purgados, `entities` acumulándose) puede llenar el disco silenciosamente durante semanas — coincide con el escenario de "backup fallando en silencio".

### R-A7. Ausencia de UPS / protección ante corte de energía
No se menciona una UPS. Un corte de energía durante una escritura de mundo (guardado de chunk) es una de las causas más comunes de corrupción de mundo en servidores caseros. Esto conecta directamente con el escenario "se corrompe el mundo" y con la necesidad de `save-off`/`save-all` controlado antes de cualquier apagado, y journaling en modo seguro en el sistema de archivos.

---

## 5. Riesgos medios

### R-M1. Certificados/HTTPS si existe algún panel web (Dynmap, panel de administración)
Si hay algún servicio web expuesto (mapa, panel), no se menciona gestión de certificados (Let's Encrypt + renovación automática). Un certificado vencido no tumba Minecraft, pero sí cualquier herramienta de administración remota basada en HTTPS.

### R-M2. Automatizaciones (cron/systemd timers) sin verificación de éxito
No se confirma que los scripts de renovación de IP, backups o reinicios registren su resultado (exit code, logging, alerta en caso de fallo). Un cron que "corre" pero falla silenciosamente (por ejemplo, un `curl` a la API de Dynu que empieza a devolver 401 por credenciales vencidas) es indistinguible de uno que nunca corrió, sin logging explícito.

### R-M3. Gestión de usuarios y permisos en el servidor Linux
No hay detalle sobre si Minecraft corre bajo un usuario dedicado sin privilegios de root, con `sudo` restringido, y con el sistema de archivos del mundo separado del resto del sistema (permisos, cuota, montaje independiente). Ejecutar el proceso de Java como usuario dedicado no-root es una práctica básica que hay que confirmar explícitamente.

### R-M4. Latencia y calidad del enlace no monitoreada
No hay métricas de latencia/jitter/pérdida de paquetes hacia el exterior. Un enlace residencial saturado (por ejemplo, por otro dispositivo del hogar) puede degradar la experiencia sin que ningún chequeo binario ("¿está arriba o abajo?") lo detecte.

### R-M5. Gestión de plugins/mods sin proceso de actualización controlado
No se menciona un proceso de staging antes de actualizar plugins en producción. Un plugin desactualizado tras un update de Paper (1.21.8) puede romper el arranque o corromper datos de jugadores.

---

## 6. Riesgos bajos

- Ausencia de documentación centralizada (runbook) de "qué hacer si pasa X" — bajo impacto técnico pero alto impacto en tiempo de recuperación (RTO) si quien administra el servidor no está disponible.
- Falta de versión de MOTD/mensaje de mantenimiento cuando el servidor está caído a propósito (mejora de experiencia, no de disponibilidad).
- No confirmado si existe control de versión (git) para configuración del servidor (`server.properties`, plugins config, scripts) — bajo riesgo pero facilita rollback rápido.

---

## 7. Oportunidades de mejora

- **Monitor de "verdad" externo**: un script en un VPS gratuito (Oracle Cloud Free Tier, un Raspberry Pi en otra red, o un servicio como Healthchecks.io) que cada 1–5 minutos resuelva el hostname público y haga un Server List Ping real, comparando la IP resuelta contra la IP pública real del servidor (obtenida vía `curl ifconfig.me` desde el propio host casero, publicada en un pequeño endpoint).
- **Segundo proveedor DDNS** como respaldo, o migrar a un proveedor con API estable y webhook de confirmación de actualización.
- **IPv6 dual-stack** como ruta de conexión alternativa.
- **UPS de bajo costo** con `apcupsd`/`nut` para apagado ordenado (`save-all`, `save-off`, `stop`) ante corte de energía.
- **Fail2Ban** para SSH y, si aplica, para el puerto de Minecraft (patrones de fuerza bruta de login).
- **Backups 3-2-1** con verificación de integridad automática (checksum) y **restauración de prueba periódica** (no solo "el archivo se generó").
- **Alertas multicanal**: Telegram como principal, pero con un canal secundario (email) para el caso de que el bot de Telegram falle o el token expire.
- **Límites de recursos systemd** (`MemoryMax`, `CPUQuota`) y rotación de logs (`logrotate`/`journald` con límites).
- **Runbook** documentado con los escenarios de este informe y los pasos de remediación.

---

## 8. Análisis de escenarios de falla

| Escenario | Detección | Impacto | Controles actuales (según lo reportado) | Controles faltantes | Reducción de RTO | Reducción de recurrencia |
|---|---|---|---|---|---|---|
| **Dynu deja de actualizar la IP** (ocurrió) | Ninguna automática hoy; se detectó por reporte de jugador | Alto: server inaccesible pero "parece sano" | Actualización automática de IP (falló) | Chequeo externo IP-real vs IP-DNS cada pocos minutos + alerta | De horas/días a minutos | Segundo proveedor DDNS + logging de cada actualización con verificación de éxito |
| **El script de actualización deja de ejecutarse** | No evidenciado | Alto, igual al anterior | Cron/systemd timer (asumido) | Alerta tipo "dead man's switch" (ej. Healthchecks.io) si el script no reporta éxito en X minutos | Minutos si hay dead-man-switch | Logging + reintentos + alerta en fallo, no solo en éxito |
| **Cambia la IP pública de madrugada** | Depende del intervalo del chequeo de IP | Medio-alto si nadie juega de madrugada, alto si sí | Igual que arriba | Igual que arriba | Minutos con monitoreo externo | Reducir TTL DNS + polling más frecuente |
| **El router reinicia inesperadamente** | Caída de ping/puerto desde monitor externo | Medio, usualmente breve | Desconocido si hay monitoreo de disponibilidad básica | Monitor de uptime (Uptime Kuma/similar) con alerta | Minutos | UPS + configuración de router para reconexión automática rápida |
| **El ISP asigna una IP distinta** | Igual al caso Dynu | Alto (es la causa raíz del incidente) | Ver C1 | Ver C1 | Minutos con chequeo activo | DHCP con IP reservada del lado ISP si está disponible, o aceptar el cambio y automatizar mejor la detección |
| **El firewall pierde una regla** | Monitor externo detecta puerto cerrado | Alto | Desconocido | Chequeo periódico de puerto + `iptables`/`nftables` persistente vía systemd, no manual | Minutos | Persistencia de reglas garantizada (`netfilter-persistent` o equivalente) + revisión tras cada actualización de sistema |
| **El puerto 25565 deja de estar abierto** | Monitor externo de puerto | Alto | Chequeo manual esporádico (implícito) | Monitor automático continuo | Minutos | Validar UPnP/NAT-PMP no interfiera, fijar reglas estáticas |
| **El disco comienza a fallar** | SMART, logs de I/O errors | Crítico (corrupción de datos) | No evidenciado | Monitoreo SMART (`smartd`) + alertas | Depende de backups verificados | Reemplazo proactivo, RAID1 si el hardware lo permite |
| **Se llena el almacenamiento** | Monitor de espacio en disco | Alto (crashes, corrupción de escritura) | No evidenciado | Alertas al 80/90% de uso + rotación de logs + límites de world size | Minutos si hay alerta temprana | Logrotate, poda de chunks/backups viejos automatizada |
| **Servidor se queda sin RAM** | OOM killer en logs, monitor de memoria | Alto (proceso Java matado abruptamente) | Desconocido si hay `-Xmx` bien calculado | Límites systemd + alertas de memoria + swap de emergencia bien configurado (no como sustituto de RAM) | Minutos con reinicio automático + alerta | Ajustar heap de JVM, revisar plugins con memory leaks |
| **Docker deja de iniciar un contenedor** (si aplica) | Systemd/monitor detecta contenedor no corriendo | Alto | Depende de si usan Docker (no confirmado) | `Restart=always` en systemd/docker-compose + alerta de reinicio repetido | Segundos a minutos | Healthcheck de contenedor + logs centralizados |
| **El proceso de Minecraft se bloquea (hang)** | Server List Ping falla aunque el proceso siga "activo" | Alto, es el escenario más peligroso porque `systemctl status` puede mentir | No evidenciado chequeo de aplicación | Watchdog que haga ping de protocolo real, no solo verificar el PID | Minutos con watchdog + auto-restart | Revisar causas (deadlocks de plugins, GC pauses largas → tuning de JVM/G1GC) |
| **Se corrompe el mundo** | Errores en logs al cargar chunks, crash al iniciar | Crítico | No evidenciado backup verificado | Backups automáticos + verificación de integridad + restauración de prueba periódica | Depende 100% de la calidad del backup | UPS + `save-off` antes de operaciones de I/O + apagado ordenado |
| **Se pierde Internet varias horas** | Monitor externo (obviamente no detecta nada desde adentro) | Alto | No hay redundancia de conectividad | Failover 4G/5G o aviso claro a la comunidad vía canal externo | No mitigable sin conectividad redundante | Backup de conectividad si es viable económicamente |
| **Se corta la energía** | UPS con notificación, o simplemente el server desaparece | Crítico si corrompe el mundo | No evidenciada UPS | UPS + apagado ordenado automático | Minutos tras que vuelve la energía, con auto-arranque | UPS resuelve tanto detección como prevención de corrupción |
| **Certificado HTTPS expira** (si hay panel web) | Alertas de expiración, o el navegador avisa | Bajo-medio | No evidenciado | Renovación automática (Let's Encrypt + certbot timer) + alerta si falla renovación | Automático si está bien configurado | Automatizar completamente, no depender de renovación manual |
| **Backup falla silenciosamente semanas** | Nada, hasta que se necesita restaurar | Crítico | No evidenciada verificación | Checksum + alerta si el backup no crece/cambia + restauración de prueba mensual | El daño ya está hecho si no se detecta antes de necesitarlo | Automatizar verificación, no solo generación |
| **Uptime Kuma deja de funcionar** (si existe) | Nada si es el único monitor | Alto (pierdes visibilidad total) | Depende de si está en la misma red que puede caer | Monitor secundario externo e independiente (otro proveedor/red) | Minutos si hay redundancia de monitoreo | Nunca depender de un solo monitor en la misma infraestructura que vigila |
| **Telegram deja de enviar alertas** | Nada si es el único canal | Alto (incidentes invisibles) | Un solo canal (implícito) | Canal secundario (email, otro bot, webhook a un segundo servicio) | Minutos con canal redundante | Probar el canal de alertas periódicamente (alerta de prueba programada) |
| **Jugador reporta no poder conectar con server "encendido"** | Reporte manual del usuario (como ya ocurrió) | Alto en confianza de la comunidad | Ninguno automático | Server List Ping automatizado desde fuera, exactamente lo que habría detectado el incidente original | Minutos en vez de depender de que un jugador avise | Resolver C1 elimina la causa raíz de este escenario específico |

---

## 9. Roadmap priorizado (Riesgo × Impacto × Esfuerzo)

| # | Prioridad | Acción | Justificación | Riesgo mitigado | Dificultad | Tiempo estimado | Beneficio esperado |
|---|---|---|---|---|---|---|---|
| 1 | 🔴 Crítica | Monitor externo con Server List Ping real + comparación IP pública vs IP resuelta por DNS | Ataca directamente la causa raíz del incidente ya ocurrido | C1, C2, R-A1 (parcial) | Baja | 2–4 horas | Detección en minutos en vez de depender de un jugador |
| 2 | 🔴 Crítica | Alertas "dead man's switch" para scripts de actualización de IP y backups | Detecta fallos silenciosos de automatización, no solo fallos de ejecución exitosa | C1, R-M2, backups silenciosos | Baja | 1–2 horas | Visibilidad de "el script dejó de correr", no solo "el script falló" |
| 3 | 🔴 Crítica | Verificación de backups: checksum + restauración de prueba mensual | Un backup no verificado es un riesgo crítico latente | C5, corrupción de mundo | Media | 1 día inicial + mantenimiento mensual | Confianza real en la recuperación ante desastre |
| 4 | 🟠 Alta | Segundo canal de alertas independiente de Telegram | Evita punto único de fallo en la notificación de incidentes | C4 | Baja | 1 hora | Alertas siguen llegando aunque falle un canal |
| 5 | 🟠 Alta | UPS + apagado ordenado (`save-off`/`save-all`) ante corte de energía | Previene corrupción de mundo, la falla de mayor impacto y peor RTO | R-A7, corrupción de mundo | Media | Compra + 2–3 horas de configuración | Elimina la causa más común de mundos corruptos en setups caseros |
| 6 | 🟠 Alta | Fail2Ban + hardening SSH (solo clave, sin password, puerto no estándar opcional) | El servidor está expuesto a Internet; SSH es el vector de mayor impacto si se compromete | R-A4 | Baja | 1–2 horas | Reduce drásticamente ataques de fuerza bruta exitosos |
| 7 | 🟡 Media | Habilitar IPv6 dual-stack como ruta alternativa | Elimina dependencia de NAT/port forwarding si el ISP lo soporta | R-A3, R-A2 | Media | Depende del router/ISP, 2–4 horas | Ruta de conexión resiliente ante problemas de IPv4 |
| 8 | 🟡 Media | Segundo proveedor DDNS o mejora de resiliencia del actual | Reduce dependencia de un único proveedor externo | R-A1 | Baja-media | 2–3 horas | Continuidad si Dynu tiene un incidente de plataforma |
| 9 | 🟡 Media | Límites de recursos systemd (memoria, CPU) + monitoreo de disco/SMART | Previene degradación silenciosa por saturación de recursos | R-A6 | Media | 3–4 horas | Evita crashes por OOM y corrupción por disco lleno |
| 10 | 🟢 Baja | Runbook documentado de incidentes | Reduce el tiempo de recuperación cuando el administrador no está disponible o está bajo presión | Todos (transversal) | Baja | 2–3 horas | RTO más corto y consistente independientemente de quién responda |
| 11 | 🟢 Baja | Control de versiones (git) para configuración del servidor | Facilita rollback ante cambios problemáticos | R-M5 | Baja | 1 hora | Recuperación rápida de configuraciones rotas |
| 12 | 🟢 Baja | Renovación automática de certificados si existe panel web | Impacto acotado a herramientas de administración | R-M1 | Baja | 1 hora | Elimina un mantenimiento manual olvidable |

---

## 10. Cierre

El incidente de Dynu no fue mala suerte: fue la infraestructura mostrando su punto más débil de la manera más visible posible — un jugador tuvo que reportarlo. La buena noticia es que **el 80% del riesgo identificado se resuelve sin gastar dinero**, solo con scripts de verificación externos y disciplina de alertas. La UPS es la única inversión de hardware que realmente recomiendo priorizar, porque es la única forma efectiva de prevenir corrupción de mundo ante cortes de energía, que es el escenario de peor combinación de impacto y dificultad de recuperación de todo este informe.

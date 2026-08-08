# Laberinto Clínico

Proyecto de app de razonamiento diagnóstico

Documento de definición. Aquí no se programa nada todavía: se decide qué es,
cómo funciona y por qué, para que cuando empecemos no haya que rehacer cosas.

---

## 1. Qué es

Una herramienta de estudio para pensar como piensa un médico: metes datos
clínicos poco a poco y ves, **en cada paso**, qué sistemas y qué patologías
siguen en juego y cuáles se han caído — y sobre todo **por qué** se han caído.

Lo importante no es el resultado final. Es el camino. Si la app solo dijera
"esto es una meningitis", no serviría para aprender nada. Lo que enseña es ver
cómo, al añadir un dato, tres posibilidades se apagan y una sube.

## 2. Qué NO es

- **No es una herramienta de diagnóstico real.** Es material de estudio. Esto
  irá escrito en la propia pantalla, no escondido en un aviso legal. Un alumno
  puede usarla para entrenar; nadie debe usarla con un paciente delante.
- **No sustituye a las guías clínicas.** Es un mapa mental, no una fuente.
- **No da certezas.** Da posibilidades ordenadas, con su razón al lado.

---

## 3. Cómo se usa (el flujo)

1. **Entras con lo que sea.** No hay orden obligatorio ni campos obligatorios.
   Puedes empezar por "varón, 68 años, cefalea brusca" o por un solo síntoma.
2. **La pantalla se parte en dos**: a la izquierda lo que vas metiendo, a la
   derecha los sistemas y las patologías vivas.
3. **Cada dato nuevo recalcula todo** al instante. Los sistemas cambian de
   color. Las patologías suben, bajan o se tachan.
4. **Todo lo tachado sigue visible**, en gris y con el motivo. Nada desaparece
   de la pantalla: si algo se ha descartado, quieres saber qué lo mató.
5. **La app te sugiere qué preguntar.** En vez de esperar a que adivines el
   dato clave, te propone las 2-3 preguntas que más discriminan ahora mismo
   ("¿fiebre?", "¿instauración brusca o progresiva?"). Esto es la parte que
   más se parece a tener un adjunto al lado.
6. **Abres cualquier patología** y ves su ficha completa (sección 4).

---

## 4. Los campos de cada patología

Estos son los campos que pediste, más los dos que añadiste después:

| Campo | Qué contiene |
|---|---|
| **Nombre** | La patología |
| **Sistema** | A qué sistema pertenece (puede ser más de uno) |
| **Edad / Sexo** | Franja típica, y si hay predominio por sexo |
| **Genética** | Herencia, mutaciones asociadas, antecedentes familiares que pesan |
| **Clínica** | Qué presenta — y **por qué lo presenta** (el mecanismo, no la lista) |
| **Diagnóstico** | Qué se pide, **por qué se pide eso concretamente**, y **qué esperas ver** |
| **Tratamiento** | Qué se hace, **qué esperas conseguir con ello** |
| **Efectos secundarios** | Lo que puede salir mal del tratamiento |
| **Lo que la descarta** | Hallazgos incompatibles: si aparece esto, esta patología se cae |

El "por qué" es la mitad del valor. Una lista de síntomas la tienes en
cualquier manual; lo que no tienes es el mecanismo explicado en dos líneas
justo cuando lo estás usando.

---

## 5. Cómo funciona el descarte y el porcentaje

Esta es la decisión más delicada del proyecto, así que la explico entera.

### El problema

Si le pido a una IA "dame el porcentaje de probabilidad", se lo inventa. Dirá
"72%" con total seguridad y ese número no significa absolutamente nada. En
medicina eso no es un detalle estético: es peligroso, porque un número falso
con dos decimales parece más fiable que un "probable" honesto.

### La solución

**El porcentaje lo calcula el código, no la IA.** Y con reglas que tú puedes
ver.

Cada patología tiene una lista de hallazgos con un peso:

- **Típico** (+3): casi siempre está presente
- **Frecuente** (+2): aparece a menudo
- **Posible** (+1): compatible, no característico
- **Atípico** (−2): raro en esta patología, resta
- **Incompatible** (−100): la mata. Descarte directo.

Metes un dato → el código suma los pesos de cada patología → las ordena → el
porcentaje que ves es **su peso relativo frente a las demás que siguen vivas**.

### Cómo se enseña (esto es lo que pediste)

Al lado de cada patología, el motivo en texto plano:

> **Meningitis bacteriana — 41%**
> ↑ fiebre (típico) · ↑ rigidez de nuca (típico) · ↑ instauración horas (frecuente)
>
> **Hemorragia subaracnoidea — 12%** *(bajando)*
> ↑ cefalea brusca (típico) · ↓ fiebre (atípico)
>
> ~~**Migraña** — descartada~~
> ✗ fiebre + rigidez de nuca son incompatibles

Y lo mismo a nivel de sistema: un sistema se apaga cuando todas sus patologías
se han caído, y puedes ver cuál fue el dato que lo apagó.

### Lo que el porcentaje NO es

Va a estar escrito en la pantalla, no en la letra pequeña: **no es una
probabilidad clínica real**. Es un peso de coincidencia con el patrón típico
de cada patología en la base. Sirve para ordenar y para estudiar. No sirve
para decidir nada sobre un paciente.

Prefiero un número honesto y limitado a uno bonito y falso.

---

## 6. De dónde sale el contenido (modelo híbrido)

Elegiste híbrido, y es lo correcto aquí. Se reparte así:

**Parte fija y revisada (la que decide):**
- Qué patologías existen y de qué sistema son
- Sus hallazgos y el peso de cada uno
- Qué las descarta
- Edad, sexo, genética

Esto es lo que mueve los colores y los porcentajes. Tiene que ser estable:
si cambia de una sesión a otra, la app no vale para estudiar. Se construye
una vez y se corrige cuando detectes un fallo.

**Parte generada por IA (la que explica):**
- El "por qué" de la clínica
- El "por qué esta prueba" y "qué esperas ver"
- El "qué esperas del tratamiento"
- Comparaciones entre dos patologías parecidas, cuando lo pidas

La IA **siempre trabaja sobre la ficha fija como referencia**, no inventando
de cero. Y lo que genera se guarda: la segunda vez que abras esa patología no
se vuelve a pedir, ya está escrito. Así no cambia el texto cada vez que
entras, y no se gasta tiempo ni cupo repitiendo trabajo.

**Cómo se construye la base sin que te lleve un año:** la IA propone la ficha
inicial de cada patología en el formato correcto, y tú la revisas y corriges.
Redactar de cero es lento; corregir es rápido. Nada entra en la base sin que
tú le hayas dado el visto bueno.

---

## 7. Alcance inicial

Empezamos por los tres que dijiste:

- **Neurología**
- **Oncohematología**
- **Infecciosas**

Es una buena combinación, y no por casualidad: se solapan mucho en la clínica
inicial (fiebre, astenia, síndrome constitucional, focalidad) y ahí es donde
el descarte tiene gracia de verdad. Con tres sistemas que se pisan, la app
enseña algo. Con tres que no se parecen en nada, sería un buscador.

Objetivo de la primera versión: **entre 12 y 15 patologías por sistema**, las
que de verdad entran en el diferencial habitual. Ampliar después es solo
añadir fichas: no hay que tocar el motor.

---

## 8. Dónde vive

**Dentro de ai-council**, como Clases y Documentos. Lo he decidido yo porque
me lo dejaste a mí y es claramente lo más sencillo: ya tienes resuelto el
servidor, el guardado en base de datos, el reparto por dispositivo, la PWA
instalable en el móvil, el estilo visual y el sistema de proveedores de IA con
sus respaldos. Empezar de cero sería rehacer todo eso para ganar nada.

En la práctica:

- `frontend/clinica.html` — la app
- `backend/app/api/clinica.py` — el motor de descarte y las llamadas a la IA
- `backend/app/api/clinica_base.py` — la base de patologías
- Icono, manifest y entrada en el service worker, como las otras dos

---

## 9. La pantalla

Móvil primero (es donde se estudia de verdad), pero que funcione en PC.

```
┌─────────────────────────────────────┐
│  DATOS                              │
│  [+ añadir dato]                    │
│  · varón, 68 años                   │
│  · cefalea brusca            [x]    │
│  · fiebre 38.5               [x]    │
├─────────────────────────────────────┤
│  ¿QUÉ PREGUNTO AHORA?               │
│  [rigidez de nuca] [focalidad]      │
├─────────────────────────────────────┤
│  SISTEMAS                           │
│  ● Infecciosas      en juego        │
│  ● Neurología       en juego        │
│  ○ Oncohemato       poco probable   │
├─────────────────────────────────────┤
│  POSIBILIDADES                      │
│  Meningitis bacteriana        41% ▲ │
│  Encefalitis viral            23%   │
│  HSA                          12% ▼ │
│  ─────────────────────────────────  │
│  Migraña            descartada ✗    │
└─────────────────────────────────────┘
```

Colores de sistema: verde en juego · ámbar poco probable · gris descartado.
Cada patología se despliega tocándola y muestra su ficha completa.

---

## 10. Riesgos, dichos en voz alta

- **La base puede tener errores.** Si una ficha está mal, la app enseña algo
  mal con toda la confianza del mundo. Por eso la base la validas tú y por eso
  hay que poder corregir una ficha rápido cuando detectes un fallo.
- **Simplifica la realidad.** Un paciente real no encaja en pesos fijos. La
  app entrena el patrón típico; la excepción sigue siendo cosa tuya.
- **Puede crear falsa seguridad.** Es el riesgo de fondo de todo esto, y la
  razón de que el aviso vaya en pantalla y no escondido.
- **Compartirla con compañeros multiplica el impacto de un error.** Antes de
  pasarla a nadie, la base tiene que estar revisada.

---

## 11. Fases

1. **Motor y base mínima** — pesos, descarte, porcentaje, con 3-4 patologías
   de prueba. Sin diseño. Solo comprobar que el razonamiento funciona.
2. **Pantalla** — la de la sección 9, funcionando en móvil.
3. **Base real** — las ~40 patologías de los tres sistemas, generadas y
   revisadas por ti.
4. **Fichas explicadas** — la parte de IA: los "por qué", guardados.
5. **Sugerencia de preguntas** — qué dato discrimina más ahora.
6. **Extras** — guardar casos, modo examen (te da una clínica y aciertas o no),
   comparar dos patologías.

Cada fase es usable por sí sola. Si paramos en la 3, ya tienes algo que sirve.

---

## 12. Decisiones cerradas

1. **Nombre:** Laberinto Clínico. Ficheros: `clinica.html`, `clinica.py`.
2. **Entrada de datos: lista, no texto libre.** Eliges los hallazgos de un
   catálogo cerrado, agrupados por bloques (generales, neurológicos,
   infecciosos, analítica...) y con buscador para no tener que bajar cien
   líneas. Es la decisión correcta: si el hallazgo que eliges es exactamente
   el mismo que está en la ficha, el motor no tiene que adivinar nada y el
   descarte es fiable al 100%. Con texto libre habría que interpretar, y ahí
   es donde empiezan los fallos silenciosos.
   Más adelante se puede añadir texto libre encima, que traduzca al hallazgo
   de la lista más parecido. Pero la lista sigue siendo la base.
3. **Casos guardados: sí.** Guardas el caso con un nombre y vuelves a él con
   todos los datos metidos. Mismo sistema que las clases guardadas: base de
   datos, separado por dispositivo.
4. **Modo examen: más adelante** (fase 6).

---

## 13. Cómo gastar poco

El coste no está en construir la app: está en las llamadas a la IA. Reparto:

**Lo que NO gasta nada (la mayor parte del uso diario):**
El motor de descarte, los porcentajes, los colores y la sugerencia de qué
preguntar son **código puro**, sin IA. Un alumno puede pasarse una hora
navegando casos sin que se haga una sola llamada. Esto es a propósito, no
casualidad: es la razón de que el porcentaje lo calcule el código.

**Lo que gasta una vez y no vuelve a gastar:**
Los "por qué" de cada ficha se generan una vez, se guardan en la base de
datos y ya no se piden nunca más. Cuarenta patologías son cuarenta llamadas
en toda la vida de la app, no cuarenta por sesión.

**Cómo construir la base sin gastar cupo de aquí:**
Ahora tienes Qwen 7B corriendo en el Acer, gratis e ilimitado. Para redactar
el primer borrador de las fichas en formato fijo —que luego revisas tú— es
más que suficiente: es trabajo de rellenar plantilla, no de razonar. Lo caro
sería pedírmelo a mí cuarenta veces.

**En producción:** las llamadas van por la cadena que ya tienes montada
(Gemini → GLM → Groq → Cerebras), todas con capa gratuita. Coste real: cero.

**Sobre delegar en subagentes:** no ahorra, al contrario. Cada subagente
arranca sin contexto y hay que volver a explicárselo todo, así que sale más
caro que hacerlo aquí. El ahorro de verdad está en las tres cosas de arriba:
que el motor no use IA, que lo generado se guarde, y que el trabajo bruto lo
haga el modelo local.

# Desplegar la Ciudad Virtual gratis (Render + Supabase)

Estos pasos los tienes que hacer tú desde tu PC (crear cuentas y hacer login
no lo puedo hacer yo). Te dejo cada comando listo para copiar y pegar.

## 0. Borra la carpeta `.git` que quedó a medias

Al preparar esto se quedó un `.git` incompleto dentro de `Desktop\ai-council`
por un fallo técnico al escribir desde mi entorno. Bórrala tú antes de
empezar: abre `Desktop\ai-council` en el Explorador, borra la carpeta
`.git` (puede estar oculta — activa "Ver > Elementos ocultos" si no la ves).

## 1. Sube el proyecto a GitHub

1. Si no tienes cuenta, créala gratis en https://github.com/signup
2. Ve a https://github.com/new, ponle un nombre (p.ej. `ai-council`), déjalo
   en **Private** o **Public** como prefieras, y NO marques "Add a
   README" (ya tenemos archivos). Pulsa "Create repository".
3. En el Explorador, entra en `Desktop\ai-council`, botón derecho →
   "Abrir en Terminal", y pega esto (cambia la URL por la que te da GitHub
   en el paso anterior):

```powershell
git init
git add -A
git commit -m "Ciudad Virtual: primera version"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/ai-council.git
git push -u origin main
```

Si es la primera vez que usas git en este PC, te pedirá iniciar sesión en
GitHub desde el navegador — sigue las instrucciones que aparezcan.

## 2. Crea la base de datos gratis en Supabase

1. Crea cuenta gratis en https://supabase.com (sin tarjeta).
2. "New project" → ponle nombre, elige una contraseña para la base de
   datos (guárdala, la necesitarás) y la región más cercana.
3. Cuando el proyecto esté listo: Project Settings → Database →
   "Connection string" → pestaña **URI**. Copia esa cadena (empieza por
   `postgresql://postgres:...`). Sustituye `[YOUR-PASSWORD]` por la
   contraseña que pusiste. Esto es tu `DATABASE_URL`.

## 3. Despliega en Render

1. Crea cuenta gratis en https://render.com (puedes usar tu cuenta de
   GitHub para registrarte, así queda conectado directamente).
2. Dashboard → "New" → "Blueprint".
3. Conecta el repositorio `ai-council` que subiste en el paso 1. Render
   detecta el archivo `render.yaml` solo y te muestra el servicio
   `ai-council` listo para crear.
4. Antes de confirmar, te pedirá rellenar las variables marcadas como
   privadas. Rellena al menos:
   - `DATABASE_URL` → la cadena de Supabase del paso 2.
   - `GEMINI_API_KEY` y `GROQ_API_KEY` → las que ya tienes en tu `.env`
     local (ábrelo con el Bloc de notas para copiarlas).
   - El resto (`DEEPSEEK_API_KEY`, `GLM_API_KEY`, `OPENAI_API_KEY`,
     `ANTHROPIC_API_KEY`) puedes dejarlas en blanco por ahora.
5. Pulsa "Apply" / "Create Web Service". La primera build tarda unos
   minutos. Cuando termine, Render te da una URL tipo
   `https://ai-council.onrender.com`.
6. Abre esa URL: verás `index.html`, con el enlace a la Ciudad Virtual.

## Cómo funciona una vez desplegado

- El servicio se duerme tras ~15 min sin visitas y tarda unos segundos en
  despertar con la siguiente visita — normal en el plan gratuito.
- Mientras está despierto, la ciudad avanza sola en segundo plano.
- El estado (ciudadanos, proyectos, relaciones, eventos) vive en Supabase,
  así que dormirse y despertar NO borra nada.
- Si Supabase pasa más de 7 días seguidos sin ninguna consulta, pausa el
  proyecto solo — se reactiva con un clic desde tu panel de Supabase.

## Actualizar el código más adelante

Cuando quieras subir cambios nuevos:

```powershell
git add -A
git commit -m "Describe aqui el cambio"
git push
```

Render vuelve a desplegar solo en cuanto detecta el push.

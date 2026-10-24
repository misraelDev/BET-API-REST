# Instalación

## Requisitos

- Python 3.12 o superior (probado con 3.12.6; la imagen Docker usa 3.13).
- MongoDB accesible desde el backend.
- PowerShell (los comandos de esta guía son para Windows).

## Pasos

```powershell
cd C:\Users\Misrael\Documents\WEBS\BET\BET-API-REST

# 1. Crear el entorno virtual
python -m venv .venv

# 2. Instalar dependencias
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Crear el archivo de configuración
Copy-Item .env.example .env
```

Después edita `.env` con los valores de tu entorno. Nunca publiques ese archivo.

> El entorno virtual **siempre** debe crearse en `.venv` dentro de la carpeta del
> proyecto. Todos los comandos usan `.\.venv\Scripts\python.exe`.

## Verificar la instalación

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip --version
.\.venv\Scripts\python.exe -c "import fastapi, uvicorn; print(fastapi.__version__, uvicorn.__version__)"
```

Si los tres comandos responden sin error, el entorno está listo.

## Siguiente paso

- [Configurar las variables de entorno](CONFIGURACION.md)
- [Iniciar la API](EJECUCION.md)

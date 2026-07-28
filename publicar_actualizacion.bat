@echo off
cd /d "%~dp0"

echo === Actualizando datos y calibrando (puede tardar varios minutos)... ===
python ejecutar_todo.py --actualizar-datos --calibrar
if errorlevel 1 goto :error

echo.
echo === Publicando en GitHub... ===
git add dashboard.html
git commit -m "Actualizar dashboard"
if errorlevel 1 (
    echo No habia cambios nuevos para publicar ^(o el commit fallo^), no se hace push.
    goto :end
)

git push
if errorlevel 1 goto :error

echo.
echo Listo. Dashboard actualizado y publicado en GitHub Pages.
goto :end

:error
echo.
echo Hubo un error en algun paso. Revisa el mensaje de arriba antes de reintentar.

:end
pause

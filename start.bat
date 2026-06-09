@echo off
setlocal enabledelayedexpansion
set "ROOT_DIR=%~dp0"
set "SERVER_DIR=%ROOT_DIR%server"
set "CLIENT_DIR=%ROOT_DIR%client"
pushd "%ROOT_DIR%"

if not exist "%SERVER_DIR%\requirements.txt" (
    echo ERROR: Could not find "%SERVER_DIR%\requirements.txt".
    echo Please run this script from the Lorecard project folder.
    pause
    exit /b 1
)

if not exist "%CLIENT_DIR%\package.json" (
    echo ERROR: Could not find "%CLIENT_DIR%\package.json".
    echo Please run this script from the Lorecard project folder.
    pause
    exit /b 1
)

echo ===========================================
echo  Lorecard - Startup Script
echo ===========================================
echo.

REM --- 1. Environment Configuration (.env file) ---
echo [1/8] Environment Configuration
set "ENV_FILE=%SERVER_DIR%\.env"

REM Ensure the .env file exists
if not exist "%ENV_FILE%" (
    echo. > "%ENV_FILE%"
    echo      Created empty %ENV_FILE%.
)

REM --- Handle APP_SECRET_KEY ---
findstr /b "APP_SECRET_KEY=" "%ENV_FILE%" >nul || (
    echo.
    echo      Encryption key not found. This is required to secure your credentials.
    echo      Please enter a secret phrase.
    set /p "SECRET_KEY=Secret Phrase: "
    if not defined SECRET_KEY (
        echo ERROR: Secret phrase cannot be empty.
        pause
        exit /b 1
    )
    echo APP_SECRET_KEY=!SECRET_KEY!>>"%ENV_FILE%"
    echo      Secret phrase saved to %ENV_FILE%.
)

REM --- Handle DATABASE_TYPE ---
findstr /b "DATABASE_TYPE=" "%ENV_FILE%" >nul || (
    echo.
    CHOICE /C 12 /N /M "Which database would you like to use? [1] PostgreSQL [2] SQLite (default): "
    if errorlevel 2 ( set "DATABASE_TYPE=sqlite" ) else ( set "DATABASE_TYPE=postgres" )
    echo DATABASE_TYPE=!DATABASE_TYPE!>>"%ENV_FILE%"
    echo      Database choice saved to %ENV_FILE%.
)

REM Read DATABASE_TYPE for use in this script
for /f "tokens=1,* delims==" %%a in ('findstr /b "DATABASE_TYPE=" "%ENV_FILE%"') do ( set "DATABASE_TYPE=%%b" )

REM --- Handle PORT ---
findstr /b "PORT=" "%ENV_FILE%" >nul || (
    echo.
    set /p "PORT=Enter the port to run the server on (default: 3000): "
    if not defined PORT ( set "PORT=3000" )
    echo PORT=!PORT!>>"%ENV_FILE%"
    echo      Port saved to %ENV_FILE%.
)

REM Read PORT for use in this script
for /f "tokens=1,* delims==" %%a in ('findstr /b "PORT=" "%ENV_FILE%"') do ( set "PORT=%%b" )
echo.

REM --- 2. Start Docker if needed ---
echo [2/8] Docker Check
if /I "%DATABASE_TYPE%"=="postgres" (
    echo      PostgreSQL selected. Checking Docker and starting container...
    where docker >nul 2>nul || (echo ERROR: Docker is not found. It is required for PostgreSQL.& pause & exit /b 1)
    where docker-compose >nul 2>nul && (set "DOCKER_CMD=docker-compose") || (set "DOCKER_CMD=docker compose")
    pushd "%SERVER_DIR%" && !DOCKER_CMD! up -d
    if errorlevel 1 (popd & echo ERROR: Failed to start PostgreSQL container.& pause & exit /b 1)
    popd
    echo      PostgreSQL container started successfully.
) else (
    echo      Using SQLite, no Docker required.
)
echo.

REM --- 3. Check for Git and pull latest changes ---
echo [3/8] Checking for updates...
git pull || (echo ERROR: Failed to pull updates from Git.& pause & exit /b 1)
echo      Done.
echo.

REM --- 4. Check for prerequisites: pnpm and uv ---
echo [4/8] Checking prerequisites...
where pnpm >nul 2>nul || (echo ERROR: pnpm is not installed or not in your PATH.& pause & exit /b 1)
where uv >nul 2>nul || (echo ERROR: uv is not installed or not in your PATH.& pause & exit /b 1)
echo      pnpm and uv found.
echo.

REM --- 5. Setup Python virtual environment ---
echo [5/8] Setting up Python environment...
if not exist "%SERVER_DIR%\.venv" (
    echo      Virtual environment not found. Creating with Python 3.10...
    pushd "%SERVER_DIR%" && uv venv --python 3.10
    if errorlevel 1 (popd & echo ERROR: Failed to create venv. Is Python 3.10 installed?& pause & exit /b 1)
    popd
)
pushd "%SERVER_DIR%" && uv pip install -r requirements.txt
if errorlevel 1 (popd & echo ERROR: Failed to install Python dependencies.& pause & exit /b 1)
popd
echo      Python dependencies are up to date.
echo.

REM --- 6. Install client dependencies ---
echo [6/8] Installing client dependencies...
call pnpm install --prefix "%CLIENT_DIR%"
if errorlevel 1 (
    echo ERROR: Failed to install client dependencies.
    pause
    exit /b 1
)
echo      Client dependencies installed.
echo.

REM --- 7. Build the client application ---
echo [7/8] Building client application...
call pnpm --prefix "%CLIENT_DIR%" build
if errorlevel 1 (
    echo ERROR: Failed to build the client application.
    pause
    exit /b 1
)
echo      Client build complete.
echo.

REM --- 7.5. Set Application Version from Git ---
echo [7.5/8] Detecting application version...
set "APP_VERSION=development"
for /f "tokens=*" %%g in ('git describe --tags --always') do (set "APP_VERSION=%%g")
echo      Version detected: !APP_VERSION!
echo.

REM --- 8. Start the server ---
echo [8/8] Starting the server...
echo      Using %DATABASE_TYPE% database and running on port %PORT%.
echo      Open the app at: http://127.0.0.1:%PORT%
echo.
set "OPEN_BROWSER=Y"
set /p "OPEN_BROWSER=Open the app in your browser now? [Y/n]: "
if /I "!OPEN_BROWSER!"=="N" (
    echo      Browser launch skipped.
) else (
    start "" "http://127.0.0.1:%PORT%"
)
echo.
pushd "%SERVER_DIR%" && uv run python src/main.py
set "SERVER_EXIT=%ERRORLEVEL%"
popd

if not "%SERVER_EXIT%"=="0" (
    echo.
    echo ERROR: Lorecard server exited with code %SERVER_EXIT%.
    pause
    exit /b %SERVER_EXIT%
)

endlocal

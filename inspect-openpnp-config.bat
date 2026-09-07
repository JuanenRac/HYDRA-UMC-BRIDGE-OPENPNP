@echo off
REM =============================================================================
REM HYDRA-UMC-BRIDGE-OPENPNP - Read-only OpenPnP configuration inspection
REM Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
REM GPL-3.0-or-later - see LICENSE
REM =============================================================================
setlocal
cd /d "%~dp0"
echo *******************************************************************************
echo * HYDRA-UMC-BRIDGE-OPENPNP - READ-ONLY OPENPNP PROFILE INSPECTION           *
echo * 1. Parse a saved machine.xml.  2. Print non-sensitive component counts.   *
echo * No OpenPnP launch, serial-port access, motion, feeder action or write.    *
echo *******************************************************************************
if "%~1"=="" (
  echo Usage: inspect-openpnp-config.bat ^<path-to-machine.xml^>
  echo Example: inspect-openpnp-config.bat "C:\OpenPnP\machine.xml"
  pause
  exit /b 2
)
where py >nul 2>&1
if errorlevel 1 (python tools\inspect_openpnp_config.py --config "%~1") else (py -3 tools\inspect_openpnp_config.py --config "%~1")
set "RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %RESULT%

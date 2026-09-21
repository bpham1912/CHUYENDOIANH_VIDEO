@echo off
title Bo chuyen doi phuong tien da nang

echo =======================================================
echo          BO CHUYEN DOI PHUONG TIEN DA NANG HANG LOAT
echo =======================================================
echo.

rem Kiem tra Python
python --version >nul 2>&1
if errorlevel 1 goto NOPYTHON

rem Kiem tra thu muc .venv
if exist .venv goto VENVEXIST

echo [1/3] Dang khoi tao moi truong ao (.venv)...
python -m venv .venv
if errorlevel 1 goto VENVERROR

:VENVEXIST
echo [2/3] Dang kich hoat moi truong ao va cai dat thu vien...
call .venv\Scripts\activate.bat
if errorlevel 1 goto ACTIVATEERROR

python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto INSTALLERROR

echo [3/3] Dang khoi chay ung dung...
echo.
python converter.py
if errorlevel 1 goto RUNERROR

echo.
echo [INFO] Ung dung da dong thanh cong.
goto END

:NOPYTHON
echo [ERROR] Khong tim thay Python tren he thong!
echo Vui long tai va cai dat Python tu trang chu: https://www.python.org/
echo Luu y: Tich chon "Add Python to PATH" khi cai dat.
goto END

:VENVERROR
echo [ERROR] Khong the tao moi truong ao .venv!
goto END

:ACTIVATEERROR
echo [ERROR] Khong the kich hoat moi truong ao .venv!
goto END

:INSTALLERROR
echo [ERROR] Khong the cai dat cac thu vien can thiet!
goto END

:RUNERROR
echo [ERROR] Ung dung gap loi khi khoi chay!
goto END

:END
echo.
pause

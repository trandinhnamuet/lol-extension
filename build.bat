@echo off
rem Build lai "LOL Spell Timer.exe" vao thu muc dist\
cd /d "%~dp0"
py -3.12 tools\make_icon.py || goto :error
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "LOL Spell Timer" ^
  --icon "%~dp0assets\icon.ico" ^
  --add-data "%~dp0assets\icon.ico;assets" ^
  --version-file "%~dp0tools\version_info.txt" ^
  --workpath build --specpath build ^
  spell_timer.py || goto :error
echo.
echo Xong: dist\LOL Spell Timer.exe
goto :eof

:error
echo Build loi!
pause

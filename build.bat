@echo off
rem Build lai "LOL Spell Timer.exe" vao thu muc dist\
rem Can: pip install pyinstaller pillow numpy onnxruntime pyaudiowpatch mss opencv-python-headless
cd /d "%~dp0"
set PY=py -3
%PY% -c "import sys" 2>nul || set PY=python
%PY% tools\make_icon.py || goto :error
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "LOL Spell Timer" ^
  --icon "%~dp0assets\icon.ico" ^
  --version-file "%~dp0tools\version_info.txt" ^
  --add-data "%~dp0models\flash_cnn.onnx;models" --add-data "%~dp0models\ignite_cnn.onnx;models" ^
  --hidden-import pyaudiowpatch --hidden-import onnxruntime --hidden-import mss --hidden-import cv2 ^
  --collect-binaries onnxruntime ^
  --exclude-module torch --exclude-module torchvision --exclude-module torchaudio --exclude-module scipy ^
  --exclude-module matplotlib --exclude-module onnx --exclude-module PIL --exclude-module pandas --exclude-module sympy ^
  --exclude-module IPython --exclude-module psutil --exclude-module onnxruntime.training ^
  --workpath build --specpath build ^
  spell_timer.py || goto :error
echo.
echo Xong: dist\LOL Spell Timer.exe
goto :eof

:error
echo Build loi!
pause

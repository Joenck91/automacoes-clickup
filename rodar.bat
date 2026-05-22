@echo off
call "%~dp0.venv\Scripts\activate.bat"
streamlit run "%~dp0app.py"

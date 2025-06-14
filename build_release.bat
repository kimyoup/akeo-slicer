@echo off
chcp 65001 > nul
echo ========================================
echo 악어슬라이서 v1.0.2 빌드 시작
echo ========================================

:: 가상환경 활성화 (있다면)
if exist "venv\Scripts\activate.bat" (
    echo 가상환경 활성화 중...
    call venv\Scripts\activate.bat
)

:: 필요한 패키지 설치
echo.
echo 필요한 패키지 설치 중...
pip install pyinstaller pillow psd-tools requests

:: 이전 빌드 결과 정리
echo.
echo 이전 빌드 결과 정리 중...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build

:: PyInstaller로 빌드
echo.
echo PyInstaller로 실행 파일 생성 중...
pyinstaller akeo_slicer.spec

:: 빌드 결과 확인
if exist "dist\akeo_slicer.exe" (
    echo.
    echo ========================================
    echo ✅ 빌드 성공!
    echo ========================================
    echo 실행 파일: dist\akeo_slicer.exe
    
    :: 파일 크기 확인
    for %%I in (dist\akeo_slicer.exe) do echo 파일 크기: %%~zI bytes
    
    :: 배포 폴더 생성
    echo.
    echo 배포 패키지 생성 중...
    if not exist "release" mkdir release
    copy "dist\akeo_slicer.exe" "release\"
    
    :: README 파일 생성
    echo 악어슬라이서 v1.0.2 > release\README.txt
    echo. >> release\README.txt
    echo 이미지 분할/합치기/크기조정 도구 >> release\README.txt
    echo. >> release\README.txt
    echo 사용법: >> release\README.txt
    echo 1. akeo_slicer.exe 실행 >> release\README.txt
    echo 2. 원하는 기능 탭 선택 >> release\README.txt
    echo 3. 이미지 폴더 선택 후 처리 >> release\README.txt
    echo. >> release\README.txt
    echo 지원 형식: JPG, PNG, WebP, PSD, PSB >> release\README.txt
    echo. >> release\README.txt
    echo 문의: AkeoStudio >> release\README.txt
    
    echo ✅ 배포 패키지 준비 완료: release 폴더
    echo.
    echo 다음 단계:
    echo 1. release\akeo_slicer.exe 테스트
    echo 2. GitHub에 업로드
    echo 3. 구글 드라이브에 업로드
    
) else (
    echo.
    echo ❌ 빌드 실패!
    echo dist\akeo_slicer.exe 파일이 생성되지 않았습니다.
    echo 오류 로그를 확인해주세요.
)

echo.
pause 
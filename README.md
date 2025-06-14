# 🐊 악어슬라이서 (AkeoSlicer) v1.0.2

> 이미지 분할/합치기/크기조정을 위한 올인원 도구

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
![Version](https://img.shields.io/badge/version-1.0.2-green.svg)

## ✨ 주요 기능

### 🔪 이미지 분할
- **수동 분할**: 마우스 클릭으로 원하는 위치에서 분할
- **자동 분할**: 일정 간격 또는 개수로 자동 분할
- **미리보기**: 실시간 분할 위치 확인
- **사용자 정의 파일명**: 원하는 형식으로 파일명 설정

### 🔄 이미지 합치기
- **세로 결합**: 여러 이미지를 세로로 연결
- **중앙 정렬**: 자동 중앙 정렬로 깔끔한 결과
- **대용량 지원**: 21억 픽셀까지 처리 가능
- **미리보기**: 합치기 전 결과 미리 확인

### 📏 이미지 크기 조정
- **비율 유지**: 가로세로 비율 자동 유지
- **고품질 리샘플링**: LANCZOS 알고리즘 사용
- **일괄 처리**: 폴더 내 모든 이미지 한번에 처리
- **DPI 보존**: 원본 DPI 정보 유지

### 🚀 자동 업데이트
- **GitHub 연동**: 새 버전 자동 확인
- **원클릭 업데이트**: 자동 다운로드 및 설치
- **백그라운드 확인**: 프로그램 시작 시 자동 확인

## 📁 지원 형식

- **입력**: JPG, PNG, WebP, PSD, PSB
- **출력**: JPG, PNG (품질 설정 가능)

## 🖥️ 시스템 요구사항

- **OS**: Windows 10 이상
- **메모리**: 4GB 이상 권장
- **저장공간**: 500MB 이상

## 📥 다운로드

### 최신 버전 다운로드
[**🔽 akeo_slicer.exe 다운로드**](https://github.com/YOUR_USERNAME/akeo-slicer/releases/latest)

### 설치 방법
1. 위 링크에서 `akeo_slicer.exe` 다운로드
2. 원하는 폴더에 저장
3. 실행 파일 더블클릭으로 실행

## 🚀 사용법

### 1. 이미지 분할
1. **분할** 탭 선택
2. **📂 찾기** 버튼으로 이미지 폴더 선택
3. 각 이미지별로 분할 설정
4. **미리보기**로 분할 위치 확인
5. **분할 시작** 클릭

### 2. 이미지 합치기
1. **합치기** 탭 선택
2. **📂 찾기** 버튼으로 합칠 이미지 폴더 선택
3. **📄 파일 목록**에서 순서 조정
4. **🎯 자동생성**으로 파일명 설정
5. **🔄 합치기** 클릭

### 3. 이미지 크기 조정
1. **크기조정** 탭 선택
2. **📂 찾기** 버튼으로 이미지 폴더 선택
3. 목표 가로 크기 입력
4. 품질 설정 선택
5. **📏 크기 조정** 클릭

## 🛠️ 개발자 정보

### 빌드 방법
```bash
# 의존성 설치
pip install -r requirements.txt

# 실행 파일 빌드
build_release.bat
```

### 프로젝트 구조
```
akeo-slicer/
├── akeo_slicer.py          # 메인 소스코드
├── akeo_slicer.spec        # PyInstaller 설정
├── version_info.txt        # 버전 정보
├── requirements.txt        # 의존성 패키지
├── build_release.bat       # 빌드 스크립트
└── README.md              # 이 파일
```

## 📝 업데이트 로그

### v1.0.2 (2024-01-XX)
- ✅ 자동 업데이트 시스템 추가
- ✅ 메모리 최적화 및 캐싱 시스템
- ✅ 대용량 이미지 스트리밍 처리
- ✅ UI/UX 개선 및 가이드 메시지 추가
- ✅ 드래그 앤 드롭 기능 제거 (안정성 향상)

### v1.0.1 (2024-01-XX)
- ✅ PSD/PSB 파일 지원 추가
- ✅ 미리보기 기능 개선
- ✅ 에러 처리 강화

### v1.0.0 (2024-01-XX)
- ✅ 초기 릴리스
- ✅ 기본 분할/합치기/크기조정 기능

## 📄 라이선스

MIT License - 자유롭게 사용, 수정, 배포 가능

## 🤝 기여하기

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📞 문의

- **개발자**: AkeoStudio
- **이슈 리포트**: [GitHub Issues](https://github.com/YOUR_USERNAME/akeo-slicer/issues)

---

⭐ 이 프로젝트가 도움이 되었다면 Star를 눌러주세요! 
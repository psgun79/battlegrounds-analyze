# Windows 배포 관리

GitHub: https://github.com/psgun79/battlegrounds-analyze

## 로컬 빌드

Windows x64와 Python 3.11 이상이 필요합니다. 공식 릴리스 자동 빌드는 Python 3.14 x64를 사용합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install '.[dev,windows-build]'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/build_windows.py
.\.venv\Scripts\python.exe scripts/smoke_windows.py release-dist/battlegrounds-review-logger-0.4.2-windows-x64.zip
```

`release-dist`에 버전별 ZIP과 `.zip.sha256`이 생성됩니다. 배포 ZIP은 빌드 결과와 명시된 문서·라이선스만 포함합니다. 작업 폴더, 개인 경기 로그, 카드 캐시, `.venv`는 복사하지 않습니다.

빌드는 PyInstaller의 onedir 방식으로 Python 런타임을 포함합니다. `bg-review.exe`와 `_internal` 폴더는 함께 배포해야 합니다. 인자를 주지 않으면 한국어 콘솔 메뉴, 인자를 주면 기존 CLI를 실행합니다. GUI 설치 프로그램이나 자동 업데이트는 포함하지 않습니다.

`smoke_windows.py`는 ZIP의 체크섬을 확인하고 임시 한글/공백 경로에 압축 해제합니다. Python을 PATH에서 제외하고 별도 임시 AppData에서 메뉴, 설정 백업, 가상 경기 재생, 검증, 내보내기, watch, 복구를 검사합니다. 사용자의 실제 게임 설정은 변경하지 않습니다. 이는 별도 물리 PC의 실게임 검증을 대체하지 않습니다.

## GitHub 자동 배포

1. `pyproject.toml`과 `bg_review/__init__.py`의 버전을 함께 변경합니다.
2. `docs/release-notes.md`의 다운로드 이름과 변경 사항을 갱신합니다.
3. 변경 사항을 커밋하고 `main`에 push합니다.
4. 버전과 같은 `v` 태그를 생성하여 push합니다.

```powershell
git tag -a v0.4.2 -m 'Windows portable release 0.4.2'
git push origin v0.4.2
```

`Windows release` 워크플로가 테스트 → Windows ZIP 빌드 → 압축 해제 후 실행 검증 → GitHub Release 게시를 수행합니다. 태그와 코드 버전이 다르면 게시 전에 실패합니다. 소스 저장소의 `dist`와 `release-dist`는 Git에서 제외하고, 실행 파일은 Release 첨부 파일로 배포합니다.

Actions에서 `Windows release`를 수동 실행하면 검증된 다운로드용 artifact만 생성합니다. 브랜치를 선택한 수동 실행은 Release를 게시하지 않습니다. 태그를 선택하면 해당 태그에 게시하므로 이미 게시한 버전에는 새 태그를 사용하세요. 기존 Release가 있으면 덮어쓰지 않고 실패합니다.

저장소에서 GitHub Actions가 허용되어 있어야 합니다. 배포 작업에만 `contents: write` 권한을 부여합니다. 기본 Tests 워크플로는 Python 3.11/3.14 호환성 검증을 수행합니다.

## 업데이트와 기록

사용자는 새 ZIP을 별도 폴더에 압축 해제하고 실행하면 됩니다. 기록과 카드 캐시는 `%LOCALAPPDATA%\BattlegroundsReview`에 있으므로 버전 폴더를 바꿔도 유지됩니다. 기존 로거는 종료한 뒤 새 버전을 실행하세요.

Python과 PyInstaller의 라이선스는 ZIP의 `licenses` 폴더에 들어갑니다. 코드 서명 인증서는 설정되지 않았으며 Windows가 알 수 없는 게시자로 표시할 수 있습니다.

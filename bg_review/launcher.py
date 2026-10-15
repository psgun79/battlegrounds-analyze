"""Interactive console entry point for the portable Windows distribution."""
import os
import sys

from . import __version__
from .cli import default_output, main as cli_main


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args:
        return cli_main(args)
    try:
        while True:
            print(f"\n전장 복기 로거 v{__version__}")
            print("1. 기록 시작 (종료: Ctrl+C)")
            print("2. 처음 사용: 게임 로그 설정 (설정 후 하스스톤 재시작)")
            print("3. 복기 파일 폴더 열기")
            print("4. 설치 / 로그 위치 확인")
            print("Q. 종료")
            choice = input("선택: ").strip().lower()
            if choice in ("q", "0"):
                return 0
            try:
                if choice == "1":
                    root = input("로그 위치 (자동 검색은 Enter, 직접 지정 시 Logs 폴더 경로): ").strip().strip('"')
                    command = ["watch"]
                    if root:
                        command.extend(["--log-root", root])
                    cli_main(command)
                elif choice == "2":
                    cli_main(["configure-logging"])
                elif choice == "3":
                    output = default_output()
                    output.mkdir(parents=True, exist_ok=True)
                    os.startfile(str(output))
                elif choice == "4":
                    cli_main(["doctor"])
                else:
                    print("1~4 또는 Q를 입력하세요.")
            except (OSError, ValueError) as exc:
                print(f"실행하지 못했습니다: {exc}")
    except (EOFError, KeyboardInterrupt):
        print("\n로거를 종료합니다.")
        return 0

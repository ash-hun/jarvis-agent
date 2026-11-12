"""[infra] `python -m jarvis.infra` 진입. 모듈을 직접 실행하면 로거 이름이 __main__ 이 돼 jarvis 핸들러를 못 탄다."""

from jarvis.infra.infra_cli import main

main()

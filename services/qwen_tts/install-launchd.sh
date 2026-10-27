#!/bin/sh
# 로그인할 때 합성 서버가 뜨고, 죽으면 다시 뜨게 launchd 에 등록한다. 다시 실행하면 같은 상태로 맞춘다.
# launchd 가 띄운 프로그램은 macOS 개인정보 보호 때문에 Desktop, Documents 아래 파일을 못 연다(Operation not permitted).
# 그래서 서버를 ~/.jarvis/qwen-tts 로 복사하고 그 자리에 환경을 만들어 등록한다. 서버를 고치면 이 스크립트를 다시 실행한다.
# 지우려면: launchctl bootout gui/$(id -u)/com.jarvis.qwen-tts && rm ~/Library/LaunchAgents/com.jarvis.qwen-tts.plist
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
label=com.jarvis.qwen-tts
home_dir="$HOME/.jarvis/qwen-tts"
plist="$HOME/Library/LaunchAgents/$label.plist"
log="$HOME/.jarvis/logs/qwen-tts.log"
mkdir -p "$home_dir" "$(dirname "$plist")" "$(dirname "$log")"
for f in server.py run.sh setup.sh pyproject.toml uv.lock; do
  cp "$here/$f" "$home_dir/$f"
done
"$home_dir/setup.sh"
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$home_dir/run.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$log</string>
  <key>StandardErrorPath</key><string>$log</string>
</dict>
</plist>
PLIST
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
# bootout 은 기다리지 않고 돌아온다. 이전 서버가 다 내려가기 전에 bootstrap 하면 "5: Input/output error" 로 실패한다
for _ in $(seq 1 60); do
  launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1 || break
  sleep 0.5
done
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "registered $label from $home_dir (log: $log)"

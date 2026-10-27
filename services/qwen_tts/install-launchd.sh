#!/bin/sh
# 로그인할 때 합성 서버가 뜨고, 죽으면 다시 뜨게 launchd 에 등록한다. 다시 실행하면 같은 등록으로 맞춘다.
# 지우려면: launchctl bootout gui/$(id -u)/com.jarvis.qwen-tts && rm ~/Library/LaunchAgents/com.jarvis.qwen-tts.plist
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
label=com.jarvis.qwen-tts
plist="$HOME/Library/LaunchAgents/$label.plist"
log="$HOME/.jarvis/logs/qwen-tts.log"
mkdir -p "$(dirname "$plist")" "$(dirname "$log")"
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$here/run.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$log</string>
  <key>StandardErrorPath</key><string>$log</string>
</dict>
</plist>
PLIST
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "registered $label (log: $log)"

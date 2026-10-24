#!/bin/zsh
set -eu
cd "${0:A:h}"
mkdir -p bin
xcrun swiftc -target arm64-apple-macosx13.0 -parse-as-library -O -module-cache-path "${TMPDIR:-/tmp}/meeting-swift-cache" native/SystemAudio.swift -o bin/SystemAudio -framework ScreenCaptureKit -framework AVFoundation -framework CoreMedia
codesign --force --sign - --identifier local.bulgarian-meeting.system-audio bin/SystemAudio

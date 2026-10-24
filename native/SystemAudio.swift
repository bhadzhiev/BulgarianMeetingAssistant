import Foundation
import ScreenCaptureKit
import AVFoundation
import CoreMedia
import Darwin

// Only audio output is registered: no screen frames are written or retained.
// All mutable state and file IO are confined to queue after initialization.
final class AudioSink: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    let file: FileHandle
    var origin: Double
    var armed = false
    let queue = DispatchQueue(label: "meeting.system-audio")
    var pausedAt: Double? = nil
    var pausedTotal = 0.0
    var samplesWritten = 0
    var lastSync = ProcessInfo.processInfo.systemUptime

    init(path: String, origin: Double) throws {
        FileManager.default.createFile(atPath: path, contents: nil)
        file = try FileHandle(forWritingTo: URL(fileURLWithPath: path))
        self.origin = origin
    }

    func command(_ command: String) {
        let fields = command.split(separator: " ")
        let now = fields.count > 1 ? Double(fields[1]) ?? ProcessInfo.processInfo.systemUptime : ProcessInfo.processInfo.systemUptime
        if fields.first == "begin" { origin = now; armed = true }
        if fields.first == "pause", pausedAt == nil { pausedAt = now }
        if fields.first == "resume", let start = pausedAt {
            pausedTotal += now - start
            pausedAt = nil
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fputs("System capture stopped: \(error.localizedDescription)\n", stderr)
        exit(2)
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer buffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, buffer.isValid, armed, pausedAt == nil else { return }
        do {
            try buffer.withAudioBufferList { list, _ in
                guard let description = buffer.formatDescription?.audioStreamBasicDescription,
                      let format = AVAudioFormat(standardFormatWithSampleRate: description.mSampleRate, channels: description.mChannelsPerFrame),
                      let pcm = AVAudioPCMBuffer(pcmFormat: format, bufferListNoCopy: list.unsafePointer),
                      let floats = pcm.floatChannelData else { return }
                guard Int(format.sampleRate) == 48000 else {
                    throw NSError(domain: "Capture", code: 1, userInfo: [NSLocalizedDescriptionKey: "Unexpected system audio sample rate"])
                }
                let count = Int(pcm.frameLength)
                let presentation = CMSampleBufferGetPresentationTimeStamp(buffer).seconds
                let position = max(0, Int(((presentation - origin - pausedTotal) * 48000).rounded()))
                var gap = position - samplesWritten
                while gap > 0 {
                    let n = min(gap, 48000)
                    try file.write(contentsOf: Data(count: n * 2))
                    samplesWritten += n
                    gap -= n
                }
                let skip = max(0, samplesWritten - position)
                if skip >= count { return }
                var output = [Int16](repeating: 0, count: count - skip)
                for i in skip..<count {
                    var sample: Float = 0
                    for c in 0..<Int(format.channelCount) { sample += floats[c][i] }
                    sample /= Float(format.channelCount)
                    output[i - skip] = Int16(max(-32768, min(32767, (sample * 32767).rounded())))
                }
                try output.withUnsafeBytes { bytes in
                    try file.write(contentsOf: Data(bytes))
                }
                samplesWritten += output.count
                let now = ProcessInfo.processInfo.systemUptime
                if now - lastSync >= 1 {
                    try file.synchronize()
                    lastSync = now
                }
            }
        } catch {
            fputs("System audio write failed: \(error.localizedDescription)\n", stderr)
            exit(3)
        }
    }
}

@main
struct SystemAudio {
    static func main() async {
        guard CommandLine.arguments.count == 3, let origin = Double(CommandLine.arguments[2]) else {
            fputs("Usage: SystemAudio output.pcm monotonicOrigin\n", stderr)
            exit(1)
        }
        do {
            let sink = try AudioSink(path: CommandLine.arguments[1], origin: origin)
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard let display = content.displays.first else {
                throw NSError(domain: "Capture", code: 1, userInfo: [NSLocalizedDescriptionKey: "No display is available"])
            }
            let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
            let config = SCStreamConfiguration()
            config.capturesAudio = true
            config.excludesCurrentProcessAudio = true
            config.sampleRate = 48000
            config.channelCount = 1
            config.width = 2
            config.height = 2
            config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
            let stream = SCStream(filter: filter, configuration: config, delegate: sink)
            try stream.addStreamOutput(sink, type: .audio, sampleHandlerQueue: sink.queue)
            try await stream.startCapture()
            print("READY")
            fflush(stdout)
            await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
                DispatchQueue.global().async {
                    while let line = readLine() {
                        if line == "stop" { break }
                        sink.queue.sync { sink.command(line) }
                    }
                    continuation.resume()
                }
            }
            try await stream.stopCapture()
            try sink.queue.sync {
                try sink.file.synchronize()
                try sink.file.close()
            }
        } catch {
            fputs("\(error.localizedDescription)\n", stderr)
            exit(1)
        }
    }
}
